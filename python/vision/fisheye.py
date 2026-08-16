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

Which knob to turn
------------------
The quoted FOV dominates the result — being 10 degrees off bends edges far more
than picking the wrong projection curve does. So tune `lens_fov_deg` first
(the tools bind it to `[` and `]`), and only then try `model`.

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
from dataclasses import asdict, dataclass
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

# A rectilinear rendering grows without bound as the output FOV approaches 180
# degrees (tan(90) is infinite), so the output FOV has to stop short of it.
MAX_OUTPUT_FOV_DEG = 170.0


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
        self.output_scale = float(min(max(self.output_scale, 0.25), 4.0))
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
    """A built lookup table plus the geometry it encodes."""

    map1: np.ndarray               # fixed-point remap tables (CV_16SC2)
    map2: np.ndarray
    out_size: tuple[int, int]      # (w, h) of the corrected image
    source_focal_px: float         # estimated focal length of the fisheye, pixels
    output_focal_px: float         # focal length of the virtual pinhole camera
    output_camera_matrix: np.ndarray  # K of that pinhole camera; needed by later stages


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


def build_maps(profile: LensProfile, size: tuple[int, int]) -> UndistortMaps:
    """Precompute the remap tables for one input resolution.

    Costs roughly 50 ms, so call it on startup and on every parameter change —
    never per frame.
    """
    profile.clamp()
    (ow, oh), f_out, k_out = _output_geometry(profile, size)

    if profile.calibrated:
        map1, map2 = _calibrated_maps(profile, size, (ow, oh), k_out)
        f_src = float(np.array(profile.camera_matrix, dtype=np.float64)[0, 0])
    else:
        map1, map2 = _estimated_maps(profile, size, (ow, oh), f_out)
        f_src = source_focal_px(profile, size)

    return UndistortMaps(map1, map2, (ow, oh), f_src, f_out, k_out)


def _estimated_maps(profile, size, out_size, f_out):
    """Build the table from the FOV estimate — the uncalibrated path.

    Works backwards, as remapping requires: for each OUTPUT pixel, find the
    SOURCE pixel it should be filled from.
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
    #    off-image so remap fills them with the border colour (black) instead of
    #    smearing edge pixels outward.
    outside = theta > theta_max
    map_x[outside] = -1.0
    map_y[outside] = -1.0

    # Fixed-point maps remap measurably faster than float32 ones on the Pi's CPU.
    return cv2.convertMaps(map_x, map_y, cv2.CV_16SC2)


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

    return cv2.fisheye.initUndistortRectifyMap(
        k, d, np.eye(3), k_out, out_size, cv2.CV_16SC2
    )


def undistort(frame: np.ndarray, maps: UndistortMaps) -> np.ndarray:
    """Apply a prebuilt table. This is the only part that runs per frame."""
    return cv2.remap(
        frame,
        maps.map1,
        maps.map2,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )
