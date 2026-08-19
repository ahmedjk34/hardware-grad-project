#!/usr/bin/env python3
"""Fisheye -> rectilinear correction for the OV5647 160-degree lens.

READ THIS FIRST: nothing here is measured
-----------------------------------------
Until a checkerboard/ChArUco calibration is run, the lens is described by exactly
two estimates:

  1. the vendor's "160 degrees" FOV number, assumed to be the *diagonal* FOV;
  2. an assumed ideal projection curve (equidistant by default).

On top of that we assume the principal point is the exact image centre and that
decentring (tangential) distortion is zero. Both are certainly a little wrong.
That is enough to make straight edges look substantially straight, and nowhere
near enough to measure with. Treat the output as visually straightened, not
metrically correct.

How the correction works
------------------------
A fisheye lens maps an incoming ray at angle theta from the optical axis to an
image radius r = f * proj(theta). A normal (rectilinear) lens instead maps it to
r = f * tan(theta) — and tan() is precisely the projection under which straight
lines in the world stay straight in the image. So "undistorting" means
re-projecting: for every pixel of the desired rectilinear output we work out
which incoming ray it represents, then which fisheye pixel that ray landed on.

That produces a fixed lookup table, so the per-frame cost is only a cv2.remap.
Rebuild the table (build_maps) whenever a parameter or the input size changes.

Why the corrected image looks softer than the raw one
-----------------------------------------------------
The re-projection is *never* 1:1 in scale, and that is where the sharpness goes.
tan(theta) grows much faster than theta, so a ray near the edge of the output
frame is stretched far more than one near the centre. At the default 160-degree
lens / 120-degree output / scale 1.0 the corners are stretched about 3.2x
radially: each output pixel there is manufactured by interpolating between
source pixels that are a third of a pixel apart. No interpolator can invent that
detail — it was never captured.

`sampling_stats()` reports this as "source pixels per output pixel". Below 1.0
means the output is being upscaled (soft); above 1.0 means it is being
downscaled (which aliases unless mip levels are used — see build_maps).

The one real cure is to feed the correction more source pixels than the output
needs: capture at the sensor's full 2592x1944 and render a 1296x972 output, and
the corner stretch halves because the source detail doubles. Everything else —
interpolation kernel, mip filtering — is a second-order polish on top of that.

Which knob to turn
------------------
The quoted FOV dominates the *geometry* — being 10 degrees off bends edges far
more than picking the wrong projection curve does. So tune `lens_fov_deg` first
(the tools bind it to `[` and `]`), and only then try `model`.

For *sharpness* the order is: capture resolution, then output_scale / output_fov
(they set how hard the stretch is), then the interpolation kernel.

After calibration
-----------------
Drop real `camera_matrix` / `dist_coeffs` / `calibration_size` into the profile
JSON and build_maps switches to the OpenCV fisheye model automatically. The
output geometry is computed the same way in both branches, so nothing
downstream changes.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import cv2
import numpy as np

# python/config/lens_profile.json
PROFILE_PATH = Path(__file__).resolve().parent.parent / "config" / "lens_profile.json"

# r(theta) / f for the standard ideal fisheye projections, ordered from the one
# that stretches the edges most to the one that compresses them most. A real
# cheap M12 fisheye normally sits between equidistant and equisolid; the exact
# curve is a second-order effect next to getting the FOV right.
PROJECTIONS = {
    "stereographic": lambda t: 2.0 * np.tan(t / 2.0),
    "equidistant": lambda t: t,
    "equisolid": lambda t: 2.0 * np.sin(t / 2.0),
    "orthographic": lambda t: np.sin(t),
}
MODEL_NAMES = list(PROJECTIONS)

# Resampling kernels, cheapest first. Linear is what the Pi can afford at high
# frame rates; cubic is visibly crisper wherever the output is being upscaled,
# which for this lens is most of the frame. lanczos4 is another small step up
# and roughly twice the cost of cubic.
INTERPOLATIONS = {
    "linear": cv2.INTER_LINEAR,
    "cubic": cv2.INTER_CUBIC,
    "lanczos4": cv2.INTER_LANCZOS4,
}
DEFAULT_INTERPOLATION = "cubic"

# A rectilinear rendering grows without bound as the output FOV approaches 180
# degrees (tan(90) is infinite), so the output FOV has to stop short of it.
MAX_OUTPUT_FOV_DEG = 170.0

# Where to send output pixels that have no source pixel at all. Must be far
# enough outside the image that even an 8-tap lanczos kernel picks up only the
# constant border colour — a coordinate of -1 would still blend with row 0.
OUTSIDE_COORD = -1000.0

# Mip levels beyond this are pointless here (a 3-level pyramid already covers an
# 8x downscale) and each one costs another remap per frame.
MAX_MIP_LEVELS = 3

# Below this much downscaling (2^0.5 = 1.41x), mip filtering costs more than the
# aliasing it removes, so undistort() stays a single remap.
MIP_THRESHOLD_LOD = 0.5


@dataclass
class LensProfile:
    """Every parameter the correction needs. Defaults = estimated OV5647 160deg."""

    # --- source lens description (estimated) ---
    lens_fov_deg: float = 160.0
    fov_reference: str = "diagonal"   # is lens_fov_deg the "diagonal" or "horizontal" FOV?
    model: str = "equidistant"        # one of MODEL_NAMES

    # --- desired output rendering ---
    output_fov_deg: float = 120.0     # how much of the source cone to re-project
    output_scale: float = 1.0         # output size relative to input; >1 preserves centre detail

    source: str = "estimated"         # flips to "calibrated" once real data lands

    # --- filled in ONLY by a real cv2.fisheye calibration ---
    camera_matrix: list | None = None
    dist_coeffs: list | None = None
    calibration_size: list | None = None  # [w, h] the calibration images were shot at

    @property
    def calibrated(self) -> bool:
        """True once real calibration data is present; drives the UI warning."""
        return self.camera_matrix is not None and self.dist_coeffs is not None

    def clamp(self) -> None:
        """Force every field into a range that produces a valid remap table.

        Called after any edit (CLI, keypress, JSON load) so the interactive keys
        can be held down without ever generating a degenerate projection.
        """
        self.lens_fov_deg = float(min(max(self.lens_fov_deg, 20.0), 220.0))
        # Can't render more of the world than the lens actually sees, and can't
        # reach 180 degrees rectilinear.
        self.output_fov_deg = float(
            min(max(self.output_fov_deg, 10.0), MAX_OUTPUT_FOV_DEG, self.lens_fov_deg)
        )
        self.output_scale = float(min(max(self.output_scale, 0.1), 4.0))
        if self.model not in PROJECTIONS:
            self.model = "equidistant"
        if self.fov_reference not in ("diagonal", "horizontal"):
            self.fov_reference = "diagonal"

    @classmethod
    def load(cls, path: Path = PROFILE_PATH) -> "LensProfile":
        """Load a profile, or return defaults if the file doesn't exist yet."""
        if not path.exists():
            return cls()
        data = json.loads(path.read_text())
        # Ignore unknown keys so a profile written by a future version (e.g. one
        # carrying extra calibration metadata) still loads here.
        known = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        profile = cls(**known)
        profile.clamp()
        return profile

    def save(self, path: Path = PROFILE_PATH) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n")
        return path


@dataclass
class UndistortMaps:
    """A built lookup table plus the geometry it encodes.

    `levels` holds one fixed-point remap table per mip level: level 0 samples the
    frame as captured, level i samples it after i rounds of cv2.pyrDown. Most
    configurations only ever need level 0, in which case `blend_weights` is empty
    and undistort() is a single remap.
    """

    levels: list[tuple[np.ndarray, np.ndarray]]   # [(map1, map2)] per mip level
    out_size: tuple[int, int]      # (w, h) of the corrected image
    source_focal_px: float         # estimated focal length of the fisheye, pixels
    output_focal_px: float         # focal length of the virtual pinhole camera
    output_camera_matrix: np.ndarray  # K of that pinhole camera; needed by later stages
    sampling: np.ndarray           # source px per output px, MOST-shrunk direction
    detail: np.ndarray             # source px per output px, MOST-stretched direction
    interpolation: int = cv2.INTER_CUBIC
    blend_weights: list[tuple[np.ndarray, np.ndarray]] = field(default_factory=list)

    @property
    def map1(self) -> np.ndarray:
        """Level-0 table, for callers that only want the plain remap."""
        return self.levels[0][0]

    @property
    def map2(self) -> np.ndarray:
        return self.levels[0][1]


def _reference_radius(w: int, h: int, reference: str) -> float:
    """Image radius (px) that the quoted FOV's half-angle corresponds to.

    A "160 degree" spec means the ray at 80 degrees off-axis lands at the edge of
    the image — but which edge depends on whether the number is the diagonal or
    the horizontal FOV, hence this switch.
    """
    return 0.5 * math.hypot(w, h) if reference == "diagonal" else 0.5 * w


def source_focal_px(profile: LensProfile, size: tuple[int, int]) -> float:
    """Focal length in pixels implied by the quoted FOV and projection model.

    Inverts r = f * proj(theta) at the image edge, where theta is known (half the
    quoted FOV) and r is known (the reference radius). ESTIMATED, not measured.
    """
    w, h = size
    theta_max = math.radians(profile.lens_fov_deg) / 2.0
    r_at_theta_max = float(PROJECTIONS[profile.model](np.array(theta_max)))
    return _reference_radius(w, h, profile.fov_reference) / r_at_theta_max


def _output_geometry(profile: LensProfile, size: tuple[int, int]):
    """Size and intrinsics of the virtual pinhole camera we re-project onto.

    Shared by both the estimated and calibrated branches so that switching to
    real calibration data does not shift the output framing.
    """
    w, h = size
    ow = max(2, int(round(w * profile.output_scale)))
    oh = max(2, int(round(h * profile.output_scale)))

    # Rectilinear: r = f * tan(theta), so f follows from the output FOV we want.
    theta_out = math.radians(profile.output_fov_deg) / 2.0
    f_out = _reference_radius(ow, oh, profile.fov_reference) / math.tan(theta_out)

    k_out = np.array(
        [[f_out, 0.0, (ow - 1) / 2.0],
         [0.0, f_out, (oh - 1) / 2.0],
         [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    return (ow, oh), f_out, k_out


def build_maps(
    profile: LensProfile,
    size: tuple[int, int],
    interpolation: str = DEFAULT_INTERPOLATION,
    mip: bool = True,
) -> UndistortMaps:
    """Precompute the remap tables for one input resolution.

    Costs roughly 50 ms (more with mip levels), so call it on startup and on
    every parameter change — never per frame.

    `mip` enables pyramid filtering wherever the correction *shrinks* the image,
    which happens as soon as the capture resolution exceeds the output
    resolution. Without it those regions are point-sampled and alias; with it
    they cost one extra remap per level per frame. Levels are only built where
    the geometry actually needs them, so leaving this on is free for
    configurations that never downscale.
    """
    profile.clamp()
    (ow, oh), f_out, k_out = _output_geometry(profile, size)

    if profile.calibrated:
        map_x, map_y = _calibrated_maps(profile, size, (ow, oh), k_out)
        f_src = float(np.array(profile.camera_matrix, dtype=np.float64)[0, 0])
    else:
        map_x, map_y = _estimated_maps(profile, size, (ow, oh), f_out)
        f_src = source_focal_px(profile, size)

    sampling, detail = _sampling_density(map_x, map_y)
    levels, weights = _build_levels(map_x, map_y, sampling, mip)

    return UndistortMaps(
        levels=levels,
        out_size=(ow, oh),
        source_focal_px=f_src,
        output_focal_px=f_out,
        output_camera_matrix=k_out,
        sampling=sampling,
        detail=detail,
        interpolation=INTERPOLATIONS.get(interpolation, cv2.INTER_CUBIC),
        blend_weights=weights,
    )


def _estimated_maps(profile, size, out_size, f_out):
    """Build the table from the FOV estimate — the uncalibrated path.

    Works backwards, as remapping requires: for each OUTPUT pixel, find the
    SOURCE pixel it should be filled from. Returns float32 maps; the fixed-point
    conversion happens later, once per mip level.
    """
    w, h = size
    ow, oh = out_size
    f_src = source_focal_px(profile, size)
    theta_max = math.radians(profile.lens_fov_deg) / 2.0
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0      # assumed principal point
    ocx, ocy = (ow - 1) / 2.0, (oh - 1) / 2.0

    # 1. Turn each output pixel into a normalised pinhole ray direction.
    x = (np.arange(ow, dtype=np.float32) - ocx) / f_out
    y = (np.arange(oh, dtype=np.float32) - ocy) / f_out
    x, y = np.meshgrid(x, y)

    # 2. Recover that ray's angle from the optical axis. For a pinhole camera
    #    the normalised radius is exactly tan(theta).
    r_rect = np.hypot(x, y)
    theta = np.arctan(r_rect)

    # 3. Ask the fisheye model where a ray at that angle actually landed.
    r_src = f_src * PROJECTIONS[profile.model](theta).astype(np.float32)

    # 4. Rescale the ray direction to that radius. r_src/r_rect has a finite
    #    limit on the optical axis, but is 0/0 numerically — guard that pixel.
    scale = np.divide(r_src, r_rect, out=np.zeros_like(r_rect), where=r_rect > 1e-9)
    map_x = cx + x * scale
    map_y = cy + y * scale

    # 5. Rays beyond the lens' real cone have no source pixel at all. Send them
    #    well off-image so remap fills them with the border colour (black)
    #    instead of smearing edge pixels outward.
    outside = theta > theta_max
    map_x[outside] = OUTSIDE_COORD
    map_y[outside] = OUTSIDE_COORD

    return map_x.astype(np.float32), map_y.astype(np.float32)


def _calibrated_maps(profile, size, out_size, k_out):
    """Build the table from real cv2.fisheye calibration data — the future path.

    Handles the common case of calibrating at full sensor resolution but running
    the preview at a lower one, by rescaling the intrinsics accordingly.
    """
    w, h = size
    k = np.array(profile.camera_matrix, dtype=np.float64).reshape(3, 3)
    d = np.array(profile.dist_coeffs, dtype=np.float64).reshape(4, 1)

    cal_w, cal_h = profile.calibration_size or (w, h)
    if (cal_w, cal_h) != (w, h):
        # Focal length and principal point scale with resolution; the distortion
        # coefficients are normalised and so do not.
        sx, sy = w / float(cal_w), h / float(cal_h)
        k = k.copy()
        k[0, 0] *= sx
        k[0, 2] *= sx
        k[1, 1] *= sy
        k[1, 2] *= sy

    # CV_32FC1 rather than the fixed-point form: the sampling-density analysis
    # and the mip tables both need the maps as real coordinates first.
    return cv2.fisheye.initUndistortRectifyMap(
        k, d, np.eye(3), k_out, out_size, cv2.CV_32FC1
    )


def _sampling_density(map_x: np.ndarray, map_y: np.ndarray):
    """How many source pixels each output pixel consumes, along both extremes.

    The (output -> source) mapping is locally an affine transform whose Jacobian
    has two singular values: the largest is how many source pixels are crammed
    into one output pixel in the most-SHRUNK direction, the smallest is the same
    number in the most-STRETCHED direction. Both matter, for opposite reasons:

        sampling (max)  > 1 -> the correction is shrinking here, so point
                               sampling would alias and the pixel wants a mip
                               level. This is what drives _build_levels.
        detail (min)    < 1 -> the correction is magnifying here; detail is
                               being interpolated and no kernel can bring it
                               back. This is what makes the corners look soft.

    Computed numerically from the maps, so it works for the estimated and the
    calibrated branch alike. Pixels that map outside the source have no
    meaningful density and are reported as 1.0, so they neither trigger mip
    levels nor skew the statistics.
    """
    # np.gradient returns d/drow then d/dcol.
    dxdr, dxdc = np.gradient(map_x)
    dydr, dydc = np.gradient(map_y)

    # Singular values of [[dxdc, dxdr], [dydc, dydr]], in closed form.
    e = dxdc * dxdc + dydc * dydc
    g = dxdr * dxdr + dydr * dydr
    f = dxdc * dxdr + dydc * dydr
    half = (e + g) * 0.5
    disc = np.sqrt(np.maximum(((e - g) * 0.5) ** 2 + f * f, 0.0))
    sampling = np.sqrt(np.maximum(half + disc, 0.0)).astype(np.float32)
    detail = np.sqrt(np.maximum(half - disc, 0.0)).astype(np.float32)

    # The step from a real coordinate to the OUTSIDE_COORD sentinel is a huge
    # fake gradient. Blank it, and its immediate neighbours, back to 1.0.
    invalid = (map_x <= OUTSIDE_COORD / 2.0).astype(np.uint8)
    invalid = cv2.dilate(invalid, np.ones((3, 3), np.uint8)) > 0
    sampling[invalid] = 1.0
    detail[invalid] = 1.0

    np.clip(sampling, 1.0 / 64.0, 64.0, out=sampling)
    np.clip(detail, 1.0 / 64.0, 64.0, out=detail)
    return sampling, detail


def _build_levels(map_x, map_y, sampling, mip):
    """Convert the float maps into one fixed-point table per needed mip level.

    Level i samples the frame after i rounds of halving with an INTER_AREA box
    filter, where output pixel x is the average of source pixels 2x and 2x+1 —
    i.e. centred on source coordinate 2x + 0.5. Inverting that gives the
    coordinate transform below. The blend weight for level i is the fractional
    part of the per-pixel level-of-detail, which makes the composite trilinear.

    Weights are stored pre-split as (1 - w, w) because cv2.blendLinear wants
    both, and it is an order of magnitude faster than the equivalent numpy.
    """
    # Fixed-point maps remap measurably faster than float32 ones on the Pi's CPU.
    levels = [cv2.convertMaps(map_x, map_y, cv2.CV_16SC2)]
    if not mip:
        return levels, []

    lod = np.log2(sampling)
    top = float(lod.max())
    if top < MIP_THRESHOLD_LOD:
        return levels, []

    n = min(int(math.ceil(top)), MAX_MIP_LEVELS)
    weights = []
    for i in range(1, n + 1):
        f = 1.0 / (1 << i)
        lx = (map_x + 0.5) * f - 0.5
        ly = (map_y + 0.5) * f - 0.5
        levels.append(cv2.convertMaps(lx.astype(np.float32), ly.astype(np.float32),
                                      cv2.CV_16SC2))
        # Weight of level i *over* the composite of levels 0..i-1.
        w = np.clip(lod - (i - 1), 0.0, 1.0).astype(np.float32)
        weights.append((np.ascontiguousarray(1.0 - w), np.ascontiguousarray(w)))
    return levels, weights


def sampling_stats(maps: "UndistortMaps") -> dict:
    """Human-readable summary of how hard the correction is resampling.

    All figures are source pixels per output pixel: 1.0 is a clean 1:1 transfer,
    0.5 means every output pixel is interpolated from half a source pixel (i.e.
    2x empty magnification), 2.0 means two source pixels are being averaged into
    one. `centre` and `edge` sample the most and least favourable places.

    Used by the tools' HUD so the sharpness cost of a parameter change is
    visible while making it.
    """
    d = maps.detail
    h, w = d.shape
    return {
        "centre": float(d[h // 2, w // 2]),
        "edge": float(np.percentile(d, 1.0)),
        "worst_upscale": float(d.min()),
        "worst_downscale": float(maps.sampling.max()),
        "upscaled_fraction": float((d < 0.95).mean()),
        "mip_levels": len(maps.levels),
    }


def undistort(frame: np.ndarray, maps: UndistortMaps) -> np.ndarray:
    """Apply a prebuilt table. This is the only part that runs per frame.

    With no mip levels this is a single cv2.remap. With them it is one remap per
    level plus a per-pixel blend — the price of not aliasing the parts of the
    image that the correction shrinks.
    """
    out = cv2.remap(
        frame,
        maps.levels[0][0],
        maps.levels[0][1],
        interpolation=maps.interpolation,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )
    if not maps.blend_weights:
        return out

    src = frame
    for (m1, m2), (w_lo, w_hi) in zip(maps.levels[1:], maps.blend_weights):
        src = cv2.resize(src, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        layer = cv2.remap(
            src, m1, m2,
            interpolation=maps.interpolation,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0),
        )
        out = cv2.blendLinear(out, layer, w_lo, w_hi)
    return out
