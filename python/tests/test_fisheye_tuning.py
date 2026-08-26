#!/usr/bin/env python3
"""Regression tests for Camera Studio's advanced manual lens tuning."""

import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera.camera_studio import FIELDS, Studio, parse_args  # noqa: E402
from vision.fisheye import (  # noqa: E402
    OUTSIDE_COORD,
    PROJECTIONS,
    LensProfile,
    _estimated_maps,
    _output_geometry,
    build_maps,
    source_focal_px,
)


def legacy_estimated_maps(profile, size, out_size, k_out):
    """The pre-advanced-tuning map, retained here as an identity oracle."""
    w, h = size
    ow, oh = out_size
    f_src = source_focal_px(profile, size)
    theta_max = math.radians(profile.lens_fov_deg) / 2.0
    cx = (w - 1) / 2.0 + profile.centre_dx
    cy = (h - 1) / 2.0 + profile.centre_dy
    fx, fy = float(k_out[0, 0]), float(k_out[1, 1])
    ocx, ocy = float(k_out[0, 2]), float(k_out[1, 2])
    x = (np.arange(ow, dtype=np.float32) - ocx) / fx
    y = (np.arange(oh, dtype=np.float32) - ocy) / fy
    x, y = np.meshgrid(x, y)
    r_rect = np.hypot(x, y)
    theta = np.arctan(r_rect)
    r_src = f_src * PROJECTIONS[profile.model](theta).astype(np.float32)
    if profile.k1 or profile.k2:
        t = (theta / theta_max).astype(np.float32)
        t2 = t * t
        r_src = r_src * (1.0 + profile.k1 * t2 + profile.k2 * t2 * t2)
    scale = np.divide(r_src, r_rect, out=np.zeros_like(r_rect), where=r_rect > 1e-9)
    map_x = cx + x * scale
    map_y = cy + y * scale
    outside = theta > theta_max
    map_x[outside] = OUTSIDE_COORD
    map_y[outside] = OUTSIDE_COORD
    return map_x.astype(np.float32), map_y.astype(np.float32)


class FisheyeTuningTests(unittest.TestCase):
    def studio(self):
        with patch.object(sys, "argv", ["camera_studio.py", "--fresh"]):
            return Studio(parse_args(), LensProfile())

    def test_identity_defaults_preserve_legacy_estimated_map(self):
        profile = LensProfile(k1=0.08, k2=-0.03, centre_dx=7, centre_dy=-4)
        size = (320, 240)
        out_size, _, _, k_out = _output_geometry(profile, size)
        actual = _estimated_maps(profile, size, out_size, k_out)
        expected = legacy_estimated_maps(profile, size, out_size, k_out)
        self.assertTrue(np.array_equal(actual[0], expected[0]))
        self.assertTrue(np.array_equal(actual[1], expected[1]))

    def test_every_advanced_parameter_changes_the_remap(self):
        size = (240, 180)
        baseline = build_maps(LensProfile(), size, mip=False)
        changes = {
            "k3": 0.15, "k4": -0.15,
            "focal_x_scale": 1.08, "focal_y_scale": 0.92,
            "skew": 0.08, "p1": 0.08, "p2": -0.08,
        }
        for name, value in changes.items():
            with self.subTest(name=name):
                tuned = LensProfile(**{name: value})
                maps = build_maps(tuned, size, mip=False)
                self.assertFalse(
                    np.array_equal(maps.map1, baseline.map1)
                    and np.array_equal(maps.map2, baseline.map2))

    def test_tuning_section_exposes_every_manual_parameter(self):
        tuning = {field.command for field in FIELDS if field.group == "TUNING"}
        # The group marker is only on the first field; collect until OUTPUT too.
        commands = [field.command for field in FIELDS]
        start, end = commands.index("k1"), commands.index("out")
        tuning |= set(commands[start:end])
        self.assertEqual(
            tuning,
            {"k1", "k2", "k3", "k4", "cx", "cy", "fxscale", "fyscale",
             "skew", "p1", "p2"},
        )

    def test_tune_reset_preserves_non_tuning_setup(self):
        studio = self.studio()
        studio.profile.lens_fov_deg = 151
        studio.profile.output_fov_deg = 111
        studio.profile.k1 = 0.2
        studio.profile.k4 = -0.1
        studio.profile.focal_x_scale = 1.1
        studio.profile.p2 = 0.04
        studio.crops = [(0.1, 0.1, 0.9, 0.9)]
        studio.colour.gamma = 1.2
        studio._cmd_tunereset([])
        self.assertEqual(studio.profile.lens_fov_deg, 151)
        self.assertEqual(studio.profile.output_fov_deg, 111)
        self.assertEqual(studio.profile.k1, 0)
        self.assertEqual(studio.profile.k4, 0)
        self.assertEqual(studio.profile.focal_x_scale, 1)
        self.assertEqual(studio.profile.p2, 0)
        self.assertEqual(studio.crops, [(0.1, 0.1, 0.9, 0.9)])
        self.assertEqual(studio.colour.gamma, 1.2)

    def test_tune_view_prepares_an_uncropped_comparison(self):
        studio = self.studio()
        studio.correct = False
        studio.show_grid = False
        studio.view = "raw"
        studio.crops = [(0.1, 0.1, 0.9, 0.9)]
        studio.zoom = 3
        studio._cmd_tuneview([])
        self.assertTrue(studio.correct)
        self.assertTrue(studio.show_grid)
        self.assertEqual(studio.view, "both")
        self.assertEqual(studio.crops, [])
        self.assertEqual(studio.zoom, 1)

    def test_advanced_commands_are_registered(self):
        studio = self.studio()
        for command in ("k3", "k4", "fxscale", "fyscale", "skew", "p1", "p2",
                        "tuneview", "tunereset", "straight"):
            with self.subTest(command=command):
                self.assertIn(command, studio.commands)

    def test_profile_round_trip_keeps_advanced_values(self):
        profile = LensProfile(k3=0.12, focal_y_scale=0.94, skew=0.01, p1=-0.02)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lens.json"
            profile.save(path)
            loaded = LensProfile.load(path)
        self.assertEqual(loaded.k3, 0.12)
        self.assertEqual(loaded.focal_y_scale, 0.94)
        self.assertEqual(loaded.skew, 0.01)
        self.assertEqual(loaded.p1, -0.02)


if __name__ == "__main__":
    unittest.main()
