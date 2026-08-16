#!/usr/bin/env python3
"""Fisheye -> rectilinear undistortion for the OV5647 160-degree lens.

IMPORTANT: nothing in here is measured. Until a checkerboard/ChArUco calibration
is run, the lens is described by two estimates only:

  1. the vendor's FOV number (160 degrees, assumed to be the *diagonal* FOV),
  2. an assumed ideal projection curve (equidistant by default).

The principal point is assumed to be the exact image centre and decentring
(tangential) distortion is assumed to be zero. That is enough to make straight
edges look substantially straight, and nowhere near enough to measure with.
Treat the output as visually straightened, not metrically correct.

Once a real calibration exists, drop `camera_matrix` / `dist_coeffs` /
`calibration_size` into the profile JSON and `build_maps` switches to the
OpenCV fisheye model automatically; the output geometry stays identical.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np

PROFILE_PATH = Path(__file__).resolve().parent.parent / "config" / "lens_profile.json"

# r(theta) / f for the usual ideal fisheye projections, in rough order of how
# aggressively they compress the edges. A real cheap M12 fisheye normally sits
# somewhere between equidistant and equisolid.
PROJECTIONS = {
    "stereographic": lambda t: 2.0 * np.tan(t / 2.0),
    "equidistant": lambda t: t,
    "equisolid": lambda t: 2.0 * np.sin(t / 2.0),
    "orthographic": lambda t: np.sin(t),
}
MODEL_NAMES = list(PROJECTIONS)

MAX_OUTPUT_FOV_DEG = 170.0  # a rectilinear render approaches infinite size at 180


@dataclass
class LensProfile:
    """Everything the undistorter needs. Defaults are the estimated OV5647 160deg lens."""

    lens_fov_deg: float = 160.0
    fov_reference: str = "diagonal"  # "diagonal" or "horizontal"
    model: str = "equidistant"
    output_fov_deg: float = 120.0
    output_scale: float = 1.0
    source: str = "estimated"  # becomes "calibrated" once a real calibration lands

    # Populated only by a real checkerboard/ChArUco calibration (cv2.fisheye).
    camera_matrix: list | None = None
    dist_coeffs: list | None = None
    calibration_size: list | None = None

    @property
    def calibrated(self) -> bool:
        return self.camera_matrix is not None and self.dist_coeffs is not None

    def clamp(self) -> None:
        self.lens_fov_deg = float(min(max(self.lens_fov_deg, 20.0), 220.0))
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
        if not path.exists():
            return cls()
        data = json.loads(path.read_text())
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
    map1: np.ndarray
    map2: np.ndarray
    out_size: tuple[int, int]  # (w, h)
    source_focal_px: float
    output_focal_px: float
    output_camera_matrix: np.ndarray


def _reference_radius(w: int, h: int, reference: str) -> float:
    """Image radius (px) that the quoted FOV half-angle corresponds to."""
    return 0.5 * math.hypot(w, h) if reference == "diagonal" else 0.5 * w


def source_focal_px(profile: LensProfile, size: tuple[int, int]) -> float:
    """Estimated focal length in pixels implied by the quoted FOV + projection model."""
    w, h = size
    theta_max = math.radians(profile.lens_fov_deg) / 2.0
    r_at_theta_max = float(PROJECTIONS[profile.model](np.array(theta_max)))
    return _reference_radius(w, h, profile.fov_reference) / r_at_theta_max


def _output_geometry(profile: LensProfile, size: tuple[int, int]):
    w, h = size
    ow = max(2, int(round(w * profile.output_scale)))
    oh = max(2, int(round(h * profile.output_scale)))
    theta_out = math.radians(profile.output_fov_deg) / 2.0
    f_out = _reference_radius(ow, oh, profile.fov_reference) / math.tan(theta_out)
    k_out = np.array(
        [[f_out, 0.0, (ow - 1) / 2.0], [0.0, f_out, (oh - 1) / 2.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    return (ow, oh), f_out, k_out


def build_maps(profile: LensProfile, size: tuple[int, int]) -> UndistortMaps:
    """Precompute the remap tables for one input resolution. Call on every param change."""
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
    """Inverse map: for each rectilinear output pixel, where does it live in the fisheye?"""
    w, h = size
    ow, oh = out_size
    f_src = source_focal_px(profile, size)
    theta_max = math.radians(profile.lens_fov_deg) / 2.0
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    ocx, ocy = (ow - 1) / 2.0, (oh - 1) / 2.0

    # Normalised pinhole ray for every output pixel.
    x = (np.arange(ow, dtype=np.float32) - ocx) / f_out
    y = (np.arange(oh, dtype=np.float32) - ocy) / f_out
    x, y = np.meshgrid(x, y)

    r_rect = np.hypot(x, y)
    theta = np.arctan(r_rect)
    r_src = f_src * PROJECTIONS[profile.model](theta).astype(np.float32)

    # r_src / r_rect scales the ray direction into fisheye image radius; the
    # limit at the optical axis is finite, so just guard the 0/0 pixel.
    scale = np.divide(r_src, r_rect, out=np.zeros_like(r_rect), where=r_rect > 1e-9)
    map_x = cx + x * scale
    map_y = cy + y * scale

    # Rays outside the lens' real cone have no source pixel -> force border fill.
    outside = theta > theta_max
    map_x[outside] = -1.0
    map_y[outside] = -1.0

    # Fixed-point maps are noticeably faster to remap on the Pi's CPU.
    return cv2.convertMaps(map_x, map_y, cv2.CV_16SC2)


def _calibrated_maps(profile, size, out_size, k_out):
    """Real cv2.fisheye calibration path, rescaled if it was shot at another resolution."""
    w, h = size
    k = np.array(profile.camera_matrix, dtype=np.float64).reshape(3, 3)
    d = np.array(profile.dist_coeffs, dtype=np.float64).reshape(4, 1)

    cal_w, cal_h = profile.calibration_size or (w, h)
    if (cal_w, cal_h) != (w, h):
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
    return cv2.remap(
        frame,
        maps.map1,
        maps.map2,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )
