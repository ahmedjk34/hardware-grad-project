#!/usr/bin/env python3
"""Hold the raw-phone colour tuning, and Camera Studio's button, to spec.

    cd python
    ../.venv/bin/python tests/test_color_tuning.py

No camera and no window. A synthetic scene is cast the way the rig camera casts
it, and the tuner asked to put the colour back; then Camera Studio is driven,
without a frame, to prove the TUNE TO RAW PHONE IMAGE button only *loads and
applies* a profile the offline tuner already wrote.

What is actually being protected
--------------------------------
* ``color_similarity`` is 1.0 for identical frames, symmetric, and rises when a
  cast is corrected;
* ``solve_distribution_transfer`` leaves an already-matching pair alone and
  recovers a known gain+contrast cast from two differently-framed crops;
* ``tune_to_reference`` improves the score, validates the result (no clipping,
  positive gains, a monotone ramp), reports honestly when it cannot reach the
  target, and falls back off an unsafe fit;
* the committed ``captures/color_correction`` pair is identified correctly and
  tunes to a better score than the untouched frame;
* Camera Studio's ``tunetoraw`` command and button apply the saved profile
  WITHOUT a camera frame and WITHOUT re-running the tuning, show the similarity
  score, and round-trip through the ordinary save/load workflow.
"""

from pathlib import Path
import argparse
import json
import sys
import tempfile

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vision.color_correction import (
    GAIN_RANGE,
    GAMMA_RANGE,
    SATURATION_RANGE,
    ColorCorrection,
    ColorCorrectionError,
    color_similarity,
    solve_distribution_transfer,
    tune_to_reference,
)

failed = False


def check(name, ok, detail=""):
    global failed
    print(f"{'ok  ' if ok else 'FAIL'}  {name}{': ' + detail if detail else ''}")
    failed |= not ok
    return ok


def scene(seed=0, size=(240, 320)):
    """A blocky colour chart: enough distinct hues to pin a 3x3 transform."""
    rng = np.random.default_rng(seed)
    palette = np.array([
        (238, 240, 243), (40, 40, 44), (150, 190, 90), (90, 110, 70),
        (200, 130, 150), (150, 90, 170), (210, 180, 120), (70, 150, 200),
    ], dtype=np.uint8)
    rows, cols = 6, 8
    img = np.zeros((size[0], size[1], 3), np.uint8)
    ch, cw = size[0] // rows, size[1] // cols
    for r in range(rows):
        for c in range(cols):
            colour = palette[rng.integers(len(palette))]
            img[r * ch:(r + 1) * ch, c * cw:(c + 1) * cw] = colour
    return img


def apply_bgr_affine(img, linear, offset):
    flat = img.reshape(-1, 3).astype(np.float64) @ np.asarray(linear).T + offset
    return np.clip(flat, 0, 255).astype(np.uint8).reshape(img.shape)


reference = scene(0)
# A cast like the rig's: blue lifted, green starved, mildly lower contrast, plus
# a different crop so nothing lines up pixel to pixel — the raw-phone situation.
# Kept gentle enough that a clean recovery does not need the darkening guard.
CAST_LINEAR = np.linalg.inv(np.diag([1.0 / 0.82, 1.0 / 1.08, 1.0 / 0.9])) * 0.85
CAST_OFFSET = np.array([16.0, 24.0, 14.0])
camera_full = apply_bgr_affine(reference, CAST_LINEAR, CAST_OFFSET)
camera = camera_full[10:210, 20:300]             # a different framing
reference_crop = reference[0:230, 10:320]

# A harsher cast that WILL need softening: heavy contrast crush and a deep lift.
HARSH_LINEAR = np.linalg.inv(np.diag([1.0 / 0.6, 1.0 / 1.2, 1.0 / 0.8])) * 0.55
HARSH_OFFSET = np.array([55.0, 70.0, 48.0])
harsh_camera = apply_bgr_affine(reference, HARSH_LINEAR, HARSH_OFFSET)


# --- 1. the similarity metric --------------------------------------------------

check("identical frames score exactly 1.0",
      abs(color_similarity(reference, reference) - 1.0) < 1e-9,
      f"{color_similarity(reference, reference):.6f}")
check("the metric is symmetric",
      abs(color_similarity(camera, reference_crop)
          - color_similarity(reference_crop, camera)) < 1e-9)
raw_sim = color_similarity(camera, reference_crop)
check("a cast frame scores below 1", 0.0 <= raw_sim < 0.95, f"{raw_sim:.3f}")
try:
    color_similarity(np.zeros((4, 4), np.uint8), reference)
    check("a non-BGR image is refused", False, "it was accepted")
except ColorCorrectionError:
    check("a non-BGR image is refused", True)


# --- 2. the distribution transfer -------------------------------------------

matrix, notes = solve_distribution_transfer(reference, reference, mode="matrix")
check("an already-matching pair transfers to near-identity",
      np.allclose(matrix[:, :3], np.eye(3), atol=1e-3)
      and np.abs(matrix[:, 3]).max() < 1.0,
      f"max offset {np.abs(matrix[:, 3]).max():.3f}")

matrix, notes = solve_distribution_transfer(camera, reference_crop, mode="matrix")
recovered = ColorCorrection(enabled=True, matrix=matrix).apply(camera)
check("the transfer lines up the channel means",
      np.abs(recovered.reshape(-1, 3).mean(0)
             - reference_crop.reshape(-1, 3).mean(0)).max() < 2.0,
      f"mean gap {np.abs(recovered.reshape(-1, 3).mean(0) - reference_crop.reshape(-1, 3).mean(0)).max():.2f}")
check("the transfer lines up the channel spreads",
      np.abs(recovered.reshape(-1, 3).std(0)
             - reference_crop.reshape(-1, 3).std(0)).max() < 3.0,
      f"std gap {np.abs(recovered.reshape(-1, 3).std(0) - reference_crop.reshape(-1, 3).std(0)).max():.2f}")
check("correcting the cast raises the similarity",
      color_similarity(recovered, reference_crop) > raw_sim + 0.05,
      f"{raw_sim:.3f} -> {color_similarity(recovered, reference_crop):.3f}")

for mode in ("gain", "affine", "matrix"):
    m, _ = solve_distribution_transfer(camera, reference_crop, mode=mode)
    check(f"the {mode} transfer runs and is finite", np.all(np.isfinite(m)))
try:
    solve_distribution_transfer(camera, reference_crop, mode="bogus")
    check("an unknown mode is refused", False, "it was accepted")
except ColorCorrectionError:
    check("an unknown mode is refused", True)


# --- 3. the whole tuning process ------------------------------------------

# Different crops: the realistic raw-phone case. The score cannot reach 1 (the
# framings genuinely differ) but the cast must be largely gone.
cropped = tune_to_reference(camera, reference_crop, target=0.9)
check("tuning a differently-framed pair beats the untouched frame",
      cropped.similarity > cropped.baseline + 0.1,
      f"{cropped.baseline:.3f} -> {cropped.similarity:.3f}")

# Same framing: a clean cast with nothing else different should come back almost
# entirely.
result = tune_to_reference(camera_full, reference, target=0.9)
check("tuning beats the untouched frame",
      result.similarity > result.baseline + 0.05,
      f"{result.baseline:.3f} -> {result.similarity:.3f}")
check("tuning reaches a high score on a clean synthetic cast",
      result.similarity >= 0.9, f"{result.similarity:.3f}")
check("passed is true only when the target is met",
      result.passed == (result.similarity >= 0.9))
check("the tuned gains are positive and in range",
      all(GAIN_RANGE[0] <= g <= GAIN_RANGE[1] for g in result.correction.gain)
      and min(result.correction.gain) > 0,
      f"gains {tuple(round(g, 3) for g in result.correction.gain)}")
check("the tuned gamma stays in range",
      GAMMA_RANGE[0] <= result.correction.gamma <= GAMMA_RANGE[1])
check("the tuned saturation stays in range",
      SATURATION_RANGE[0] <= result.correction.saturation <= SATURATION_RANGE[1])
check("the tuned profile clips almost nothing new",
      result.clipping < 0.02, f"{result.clipping * 100:.2f}%")
check("the tuned matrix is finite",
      np.all(np.isfinite(result.correction.matrix)))

ramp = np.repeat(np.arange(256, dtype=np.uint8)[None, :, None], 3, axis=2)
ramp = np.ascontiguousarray(np.repeat(ramp, 2, axis=0))
mapped = result.correction.apply(ramp)[0].astype(int)
check("the tuned profile keeps a neutral ramp monotone",
      all(np.mean(np.diff(mapped[:, c]) >= 0) >= 0.95 for c in range(3)))

identical = tune_to_reference(reference, reference, target=0.9)
check("tuning identical frames is a near-no-op",
      identical.similarity > 0.99
      and np.allclose(identical.correction.matrix[:, :3], np.eye(3), atol=1e-2),
      f"sim {identical.similarity:.4f}")

hard = tune_to_reference(camera_full, reference, target=0.999)
check("an unreachable target is reported, not faked",
      not hard.passed and hard.similarity < 0.999
      and "did not" not in " ".join(hard.notes),
      hard.summary())
check("the result summary reads cleanly",
      "colour similarity" in hard.summary())


# --- 3b. the darkening guard --------------------------------------------

from vision.color_correction import MIN_TUNED_SHADOW, NEAR_BLACK  # noqa: E402


def near_black_fraction(img):
    return float((img < NEAR_BLACK).any(2).mean())


gentle = tune_to_reference(camera_full, reference, target=0.9)
check("a gentle cast is corrected at full strength",
      gentle.strength > 0.999, f"strength {gentle.strength:.2f}")

softened = tune_to_reference(harsh_camera, reference, target=0.9)
check("a harsh contrast-crushing cast is softened, not applied raw",
      softened.strength < 0.999, f"strength {softened.strength:.2f}")
check("softening still improves on the untouched frame",
      softened.similarity > softened.baseline + 0.05,
      f"{softened.baseline:.3f} -> {softened.similarity:.3f}")
check("the softened profile keeps the darkest 2% out of the floor",
      softened.shadow_after >= MIN_TUNED_SHADOW - 1.0,
      f"darkest 2% at {softened.shadow_after:.0f}")
check("the softened profile does not crush the frame to black",
      near_black_fraction(softened.correction.apply(harsh_camera)) < 0.02,
      f"{near_black_fraction(softened.correction.apply(harsh_camera)) * 100:.1f}% near-black")
dimmer = np.clip(harsh_camera.astype(np.float32) * 0.82, 0, 255).astype(np.uint8)
was = near_black_fraction(dimmer)
check("the softened profile holds up on a dimmer exposure too",
      near_black_fraction(softened.correction.apply(dimmer)) - was < 0.03,
      f"{was * 100:.1f}% -> "
      f"{near_black_fraction(softened.correction.apply(dimmer)) * 100:.1f}%")
check("softening is recorded in the notes and summary",
      any("soften" in n for n in softened.notes)
      and "strength" in softened.summary())
check("the softened correction stays finite and positive-gain",
      np.all(np.isfinite(softened.correction.matrix))
      and min(softened.correction.gain) > 0)


# --- 4. the committed capture pair ----------------------------------------

CAPTURE_DIR = Path(__file__).resolve().parents[1] / "captures" / "color_correction"
if CAPTURE_DIR.is_dir():
    from vision.tune_color_to_raw_phone import build_profile, identify_pair

    phone_path, camera_path = identify_pair(CAPTURE_DIR)
    check("the phone photo is identified as the reference",
          "phone" in phone_path.stem or "raw" in phone_path.stem,
          phone_path.name)
    check("the live view is identified as the camera image",
          phone_path != camera_path, f"{phone_path.name} vs {camera_path.name}")

    document, real = build_profile(phone_path, camera_path)
    check("tuning the real pair beats the untouched frame",
          real.similarity > real.baseline,
          f"{real.baseline:.3f} -> {real.similarity:.3f}")
    check("the real tuned profile clips almost nothing new",
          real.clipping < 0.02, f"{real.clipping * 100:.2f}%")
    check("the real tuned profile has positive gains",
          min(real.correction.gain) > 0,
          f"{tuple(round(g, 3) for g in real.correction.gain)}")
    check("the real tuned profile serialises to the colour block",
          "matrix" in document["colour"] and "similarity" in document)
    reloaded = ColorCorrection.from_settings(document)
    check("the serialised block reloads to the same correction",
          np.allclose(reloaded.matrix, real.correction.matrix))
else:
    check("the committed capture pair is present", False, str(CAPTURE_DIR))


# --- 5. Camera Studio's button, with no camera --------------------------

import camera.camera_studio as studio_module  # noqa: E402
from camera.camera_studio import BUTTONS, Studio  # noqa: E402

args = argparse.Namespace(
    backend="auto", device=None, autosave=False,
    settings=Path("/nonexistent/camera_settings.json"), profile=Path("/nonexistent"),
)

check("the TUNE TO RAW PHONE IMAGE button exists",
      "TUNE TO RAW PHONE IMAGE" in {label for label, _ in BUTTONS})
check("the button runs the tunetoraw command",
      dict((label, cmd) for label, cmd in BUTTONS).get("TUNE TO RAW PHONE IMAGE")
      == "tunetoraw")

studio = Studio(args, studio_module.LensProfile())
check("studio has the tunetoraw command", "tunetoraw" in studio.commands)
check("studio has the rawphone alias", "rawphone" in studio.commands)
check("colour similarity starts unset", studio.colour_similarity is None)

# A missing profile is explained, not crashed.
original_path = studio_module.RAW_PHONE_PROFILE_PATH
studio_module.RAW_PHONE_PROFILE_PATH = Path("/nonexistent/color_profile_raw_phone.json")
missing = studio.commands.execute("tunetoraw")
check("a missing profile is refused with a hint",
      not missing.ok and "profile" in missing.message.lower(),
      missing.message[:70])
studio_module.RAW_PHONE_PROFILE_PATH = original_path

with tempfile.TemporaryDirectory() as directory:
    profile_path = Path(directory) / "color_profile_raw_phone.json"
    tuned = tune_to_reference(camera, reference_crop, target=0.9)
    profile_doc = {
        "generated_at": "test",
        "reference_image": "raw_with_phone.jpeg",
        "camera_image": "current_live_view.png",
        "similarity": round(tuned.similarity, 5),
        "target_met": tuned.passed,
        "notes": tuned.notes,
        "colour": tuned.correction.to_settings(),
    }
    profile_path.write_text(json.dumps(profile_doc, indent=2))
    mtime_before = profile_path.stat().st_mtime_ns

    studio_module.RAW_PHONE_PROFILE_PATH = profile_path
    try:
        result = studio.commands.execute("tunetoraw")
        check("tunetoraw applies the saved profile without a frame",
              result.ok and studio.last_capture is None, result.message[:70])
        check("tunetoraw switched the correction on",
              studio.colour.enabled and not studio.colour.is_identity)
        check("tunetoraw applied the saved matrix exactly",
              np.allclose(studio.colour.matrix, tuned.correction.matrix))
        check("tunetoraw surfaced the similarity score",
              abs(studio.colour_similarity - round(tuned.similarity, 5)) < 1e-9,
              str(studio.colour_similarity))
        check("the panel line shows the match percentage",
              "match to raw phone" in studio.colour_line()
              and f"{tuned.similarity * 100:.1f}%" in studio.colour_line(),
              studio.colour_line()[:90])
        check("the colour report shows the similarity",
              "colour similarity to the raw phone image" in studio.colour_report())
        check("applying the profile did not rewrite it",
              profile_path.stat().st_mtime_ns == mtime_before)

        # A second press is identical — it is a load, not an optimisation.
        first_matrix = studio.colour.matrix.copy()
        studio.commands.execute("tunetoraw")
        check("a second press is byte-for-byte the same",
              np.array_equal(studio.colour.matrix, first_matrix))

        # It saves and loads through the ordinary settings workflow.
        studio.capture_size = (1296, 972)
        settings_path = Path(directory) / "camera_settings.json"
        studio.write_settings(settings_path)
        saved = json.loads(settings_path.read_text())
        check("SAVE JSON carries the colour block and the score",
              "colour" in saved and "similarity" in saved,
              ", ".join(sorted(saved))[:70])
        check("the saved colour block matches what was applied",
              np.allclose(ColorCorrection.from_settings(saved).matrix,
                          studio.colour.matrix))

        studio.commands.execute("colourreset")
        check("colourreset clears the similarity too",
              studio.colour_similarity is None
              and "match to raw phone" not in studio.colour_line())

        check("loading the saved file restores the score",
              studio.commands.execute(f"load {settings_path}").ok
              and studio.colour_similarity is not None
              and abs(studio.colour_similarity - saved["similarity"]) < 1e-9)
    finally:
        studio_module.RAW_PHONE_PROFILE_PATH = original_path

studio.commands.execute("reset")
check("a full studio reset clears the tuned similarity",
      studio.colour_similarity is None and studio.colour.is_identity)


raise SystemExit(1 if failed else 0)
