#!/usr/bin/env python3
"""Tune the software colour correction against a trusted phone photograph.

    cd python
    ../.venv/bin/python vision/tune_color_to_raw_phone.py

What it does
------------
Reads the two images in ``captures/color_correction/`` — a RAW-ish photo of the
scene taken with a phone, and a frame grabbed straight from the rig's live view —
works out which is which, and runs :func:`vision.color_correction.tune_to_reference`
to solve a full :class:`~vision.color_correction.ColorCorrection` that carries the
live view onto the phone's colours: gains, offsets, cross-channel mixing, then
gamma and saturation by pattern search.

The result is written to ``config/color_profile_raw_phone.json`` in the same
``colour`` block Camera Studio and ``camera_feed.py`` already read, plus the
similarity score and the validation notes. Camera Studio's
``TUNE TO RAW PHONE IMAGE`` button loads *that file* and applies it — it never
re-runs this.

Identifying the two images
--------------------------
By filename first (``phone``/``raw`` vs ``live``/``view``/``camera``); failing
that, by sharpness — the phone shot has far more high-frequency detail than a
rig frame that has been through the fisheye remap and is slightly soft.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vision.color_correction import ColorCorrection, tune_to_reference

CAPTURE_DIR = Path(__file__).resolve().parents[1] / "captures" / "color_correction"
PROFILE_PATH = Path(__file__).resolve().parents[1] / "config" / "color_profile_raw_phone.json"

_PHONE_HINTS = ("phone", "raw", "reference", "ref", "truth")
_CAMERA_HINTS = ("live", "view", "camera", "rig", "feed", "current")
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")


def _sharpness(image: np.ndarray) -> float:
    """Variance of the Laplacian — higher means more fine detail, i.e. the phone."""
    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    scale = 512.0 / max(grey.shape)
    if scale < 1.0:
        grey = cv2.resize(grey, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(grey, cv2.CV_64F).var())


def identify_pair(directory: Path = CAPTURE_DIR):
    """Return ``(phone_path, camera_path)`` for the two images in *directory*."""
    files = sorted(p for p in directory.iterdir()
                   if p.suffix.lower() in _IMAGE_SUFFIXES)
    if len(files) < 2:
        raise SystemExit(f"need two images in {directory}, found {len(files)}")
    if len(files) > 2:
        raise SystemExit(
            f"expected exactly two images in {directory}, found "
            f"{', '.join(f.name for f in files)}")

    def hint(path, words):
        return any(word in path.stem.lower() for word in words)

    a, b = files
    if hint(a, _PHONE_HINTS) and not hint(b, _PHONE_HINTS):
        return a, b
    if hint(b, _PHONE_HINTS) and not hint(a, _PHONE_HINTS):
        return b, a
    if hint(a, _CAMERA_HINTS) and not hint(b, _CAMERA_HINTS):
        return b, a
    if hint(b, _CAMERA_HINTS) and not hint(a, _CAMERA_HINTS):
        return a, b

    # No usable filename hint: the phone photo is the sharper of the two.
    sharp_a = _sharpness(cv2.imread(str(a)))
    sharp_b = _sharpness(cv2.imread(str(b)))
    return (a, b) if sharp_a >= sharp_b else (b, a)


def build_profile(phone_path: Path, camera_path: Path, *, target: float = 0.95):
    phone = cv2.imread(str(phone_path))
    camera = cv2.imread(str(camera_path))
    if phone is None or camera is None:
        raise SystemExit(f"could not read {phone_path} / {camera_path}")

    result = tune_to_reference(camera, phone, target=target)
    correction = result.correction
    correction.source = f"tuned to {phone_path.name}"

    document = {
        "_about": ("Written by vision/tune_color_to_raw_phone.py. The 'colour' "
                   "block is the same one config/camera_settings.json carries; "
                   "Camera Studio's TUNE TO RAW PHONE IMAGE button loads this "
                   "file and applies it without re-tuning."),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "reference_image": phone_path.name,
        "camera_image": camera_path.name,
        "similarity": round(result.similarity, 5),
        "baseline_similarity": round(result.baseline, 5),
        "target": target,
        "target_met": result.passed,
        "iterations": result.iterations,
        "new_clipping_fraction": round(result.clipping, 6),
        "notes": result.notes,
        "colour": correction.to_settings(),
    }
    return document, result


def main() -> int:
    phone_path, camera_path = identify_pair()
    print(f"phone / reference : {phone_path.name}")
    print(f"camera live view  : {camera_path.name}")

    document, result = build_profile(phone_path, camera_path)

    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(document, indent=2) + "\n")

    print()
    print(result.summary())
    print(ColorCorrection.from_settings(document).describe())
    for note in result.notes:
        print(f"  note: {note}")
    print()
    print(f"wrote {PROFILE_PATH}")
    if not result.passed:
        print("target not reached — this is the best safe result; see the notes. "
              "The live view is soft and framed differently from the phone shot, "
              "which caps the achievable score.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
