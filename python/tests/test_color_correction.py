#!/usr/bin/env python3
"""Hold the software colour correction, and Camera Studio's COLOUR section, to spec.

    cd python
    ../.venv/bin/python tests/test_color_correction.py

No camera and no window. A synthetic printed sheet is rendered, a known colour
cast applied to a copy of it, and the calibration asked to recover the cast —
which is the one thing that can be checked exactly, because the answer is known
before the fit runs.

What is actually being protected
--------------------------------
* an identity correction costs nothing and changes nothing;
* the gain fit recovers a known per-channel cast to within a level;
* the equivalent sensor gains come from the transform's effect, not from the
  matrix diagonal — those disagree wildly once offsets are involved, and the
  diagonal reading was wrong by a factor of 1.8 on real rig data;
* ``implausibilities()`` flags the fits that score well and look terrible, in
  the order they actually looked terrible;
* the settings block survives a round trip, and a file without one still loads;
* every command in Camera Studio's COLOUR section exists and runs.
"""

from pathlib import Path
import json
import sys
import tempfile

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vision.color_correction import (
    CHANNELS,
    FIT_MODES,
    ColorCorrection,
    ColorCorrectionError,
    IDENTITY,
    equivalent_sensor_gains,
    neutral_matrix,
    pair_samples,
    solve_matrix,
)
from vision.color_grid import ColorGridSpec, sample_ink_colors

failed = False


def check(name, ok, detail=""):
    global failed
    print(f"{'ok  ' if ok else 'FAIL'}  {name}{': ' + detail if detail else ''}")
    failed |= not ok
    return ok


def render_sheet(spec, cols=12, rows=7, px_per_cm=14.0, margin_cm=1.6):
    """A printed sheet, big enough for the colour sampler to find its materials."""
    width = round((cols * spec.pitch_x_cm - spec.gap_x_cm + 2 * margin_cm) * px_per_cm)
    height = round((rows * spec.pitch_y_cm - spec.gap_y_cm + 2 * margin_cm) * px_per_cm)
    sheet = np.full((height, width, 3), (238, 240, 243), np.uint8)
    for row in range(rows):
        for col in range(cols):
            x0 = (margin_cm + col * spec.pitch_x_cm) * px_per_cm
            y0 = (margin_cm + row * spec.pitch_y_cm) * px_per_cm
            colour = (150, 190, 90) if (col + row) % 2 == 0 else (190, 140, 200)
            cv2.rectangle(sheet, (round(x0), round(y0)),
                          (round(x0 + spec.block_x_cm * px_per_cm) - 1,
                           round(y0 + spec.block_y_cm * px_per_cm) - 1),
                          colour, -1)
    return sheet


def cast(image, gains):
    """Push a frame's channels around the way a bad camera white balance does."""
    return np.clip(image.astype(np.float32) * np.float32(gains), 0, 255).astype(np.uint8)


spec = ColorGridSpec()
reference = render_sheet(spec)
# BGR, and every gain <= 1 on purpose: the rig's cast starves green, and a
# synthetic cast that *boosts* a channel would clip near-white paper to 255 and
# destroy the very ratio the fit is meant to recover. Clipping is a real camera
# failure, but it is not what this test is about.
CAST = (0.85, 0.62, 0.98)
camera = cast(reference, CAST)


# --- 1. the transform itself ------------------------------------------------

identity = ColorCorrection()
frame = np.full((8, 8, 3), 100, np.uint8)
check("a disabled correction returns the very same frame",
      identity.apply(frame) is frame)
identity.enabled = True
check("an enabled identity still returns the same frame",
      identity.apply(frame) is frame)
check("an identity reports itself as one", identity.is_identity)

doubled = ColorCorrection(enabled=True,
                          matrix=np.hstack([np.diag([2.0, 1.0, 0.5]),
                                            np.zeros((3, 1))]))
out = doubled.apply(np.full((4, 4, 3), 100, np.uint8))
check("a diagonal gain scales each channel", tuple(out[0, 0]) == (200, 100, 50),
      str(tuple(int(v) for v in out[0, 0])))
saturating = ColorCorrection(enabled=True,
                             matrix=np.hstack([np.diag([4.0, 1.0, 1.0]),
                                               np.zeros((3, 1))]))
out = saturating.apply(np.full((4, 4, 3), 100, np.uint8))
check("gains clip rather than wrap", int(out[0, 0][0]) == 255,
      str(int(out[0, 0][0])))

# The LUT fast path and the general matrix path have to agree, or a correction
# would change the moment someone added a cross-channel term and removed it.
diagonal = np.hstack([np.diag([1.3, 0.9, 1.1]), np.array([[5.0], [-3.0], [2.0]])])
noise = np.random.default_rng(0).integers(0, 256, (32, 32, 3), dtype=np.uint8)
lut_path = ColorCorrection(enabled=True, matrix=diagonal).apply(noise)
nudged = diagonal.copy()
nudged[0, 1] = 1e-9         # enough to leave the diagonal fast path, not to matter
matrix_path = ColorCorrection(enabled=True, matrix=nudged).apply(noise)
check("the LUT and matrix paths agree",
      int(np.abs(lut_path.astype(int) - matrix_path.astype(int)).max()) <= 1,
      f"max difference {int(np.abs(lut_path.astype(int) - matrix_path.astype(int)).max())}")

clamped = ColorCorrection()
check("gain is clamped, not rejected", clamped.set_gain(0, 1e6) < 1e5)
check("gamma is clamped, not rejected", clamped.set_gamma(-4) > 0)


# --- 2. recovering a known cast ---------------------------------------------

reference_samples = sample_ink_colors(reference)
camera_samples = sample_ink_colors(camera)
check("the sampler finds all three materials in the reference",
      set(reference_samples.names) == {"green", "magenta", "paper"},
      reference_samples.describe()[:80])
check("the ink samples are tight",
      max(reference_samples.spread.values()) < 12.0,
      f"worst spread {max(reference_samples.spread.values()):.1f}")

camera_colors, reference_colors, names = pair_samples(camera_samples,
                                                      reference_samples)
check("pairing matches by ink identity", set(names) == {"green", "magenta", "paper"})

matrix, residual, notes = solve_matrix(camera_colors, reference_colors, mode="gain")
recovered = tuple(round(float(matrix[i, i]), 3) for i in range(3))
expected = tuple(round(1.0 / g, 3) for g in CAST)
check("the gain fit recovers the known cast",
      all(abs(a - b) < 0.05 for a, b in zip(recovered, expected)),
      f"got {recovered}, cast implies {expected}")
check("recovering a known cast leaves no warnings", not notes, "; ".join(notes))

corrected = ColorCorrection(enabled=True, matrix=matrix).apply(camera)
after = sample_ink_colors(corrected)
worst = max(
    float(np.abs(np.array(after.colors[name]) - np.array(reference_samples.colors[name])).max())
    for name in names)
check("the corrected frame matches the reference", worst < 6.0,
      f"worst channel difference {worst:.1f} levels")


# --- 3. the sensor-gain equivalence, which read the wrong thing before -------

white = camera_samples.colors["paper"]
red, blue = equivalent_sensor_gains(matrix, white)
check("equivalent sensor gains undo the cast's own ratios",
      abs(red - (CAST[1] / CAST[2])) < 0.06
      and abs(blue - (CAST[1] / CAST[0])) < 0.06,
      f"red {red:.3f} (want {CAST[1] / CAST[2]:.3f}), "
      f"blue {blue:.3f} (want {CAST[1] / CAST[0]:.3f})")

# The regression, taken from the real rig fit: a diagonal of B2.29 G1.44 R2.22
# paired with offsets of -207/-8/-188. Reading the diagonal says red and blue
# need boosting by ~1.55 relative to green; reading the transform's actual
# effect says they need cutting to ~0.86. The second one is right, and getting
# this backwards would have had someone type a gain that doubles the cast.
tricky = np.hstack([np.diag([2.292, 1.441, 2.220]),
                    np.array([[-207.07], [-7.53], [-188.15]])])
rig_white = (191.0, 159.0, 181.0)
effective_red, effective_blue = equivalent_sensor_gains(tricky, rig_white)
naive_red = tricky[2, 2] / tricky[1, 1]
check("sensor gains read the transform's effect, not the matrix diagonal",
      effective_red < 1.0 and effective_blue < 1.0 and naive_red > 1.4,
      f"effective red {effective_red:.3f} blue {effective_blue:.3f}; "
      f"the diagonal alone would have said {naive_red:.3f}")


# --- 4. the guard that ranks the fits ---------------------------------------

check("a plain gain fit is plausible",
      not ColorCorrection(matrix=matrix).implausibilities())
negative = ColorCorrection(matrix=np.hstack([np.diag([-0.97, 1.5, 3.2]),
                                             np.zeros((3, 1))]))
check("a negative gain is flagged",
      any("negative gain" in note for note in negative.implausibilities()),
      "; ".join(negative.implausibilities())[:70])
offset_heavy = ColorCorrection(matrix=np.hstack([np.diag([2.3, 1.4, 2.2]),
                                                 np.array([[-207.0], [-7.0], [-188.0]])]))
check("a runaway offset is flagged",
      any("offset reaches" in note for note in offset_heavy.implausibilities()),
      "; ".join(offset_heavy.implausibilities())[:70])
mixed = ColorCorrection(matrix=np.hstack([np.array([[1.0, 2.9, 0.0],
                                                    [0.0, 1.5, 0.0],
                                                    [0.0, 0.0, 3.2]]),
                                          np.zeros((3, 1))]))
check("heavy cross-channel mixing is flagged",
      any("mixing" in note for note in mixed.implausibilities()),
      "; ".join(mixed.implausibilities())[:70])
before = mixed.mix
mixed.drop_mix()
check("dropping the mix leaves a diagonal correction",
      mixed.is_diagonal and before > 0, f"removed {before:.2f}")

for mode in FIT_MODES:
    try:
        _, _, mode_notes = solve_matrix(camera_colors, reference_colors, mode=mode)
        check(f"the {mode} fit runs on three colours", True,
              f"{len(mode_notes)} warning(s)")
    except ColorCorrectionError as exc:
        check(f"the {mode} fit runs on three colours", False, str(exc)[:60])

try:
    solve_matrix(camera_colors[:1], reference_colors[:1], mode="matrix")
    check("a full matrix from one colour is refused", False, "it was accepted")
except ColorCorrectionError as exc:
    check("a full matrix from one colour is refused", True, str(exc)[:60])


# --- 5. white balance with no reference photograph --------------------------

neutral = ColorCorrection(enabled=True,
                          matrix=neutral_matrix(camera_samples.colors["paper"]))
paper_after = sample_ink_colors(neutral.apply(camera)).colors["paper"]
check("paper-only white balance makes the paper neutral",
      float(np.abs(np.array(paper_after) - np.mean(paper_after)).max()) < 6.0,
      f"paper lands at {tuple(round(v) for v in paper_after)}")
try:
    neutral_matrix((0.0, 0.0, 0.0))
    check("a black white-reference is refused", False, "it was accepted")
except ColorCorrectionError as exc:
    check("a black white-reference is refused", True, str(exc)[:50])


# --- 6. persistence ---------------------------------------------------------

original = ColorCorrection(enabled=True, matrix=matrix, gamma=1.3,
                           saturation=0.85, source="test")
restored = ColorCorrection.from_settings({"colour": original.to_settings()})
check("a correction survives a settings round trip",
      np.allclose(original.matrix, restored.matrix)
      and restored.enabled and abs(restored.gamma - 1.3) < 1e-6
      and abs(restored.saturation - 0.85) < 1e-6
      and restored.source == "test")
check("settings with no colour block load as a disabled identity",
      ColorCorrection.from_settings({"capture": {}}).is_identity
      and not ColorCorrection.from_settings({"capture": {}}).enabled)
check("a gain/offset-only block still loads",
      abs(ColorCorrection.from_settings(
          {"colour": {"gain": [1.5, 1.0, 0.5], "offset": [0, 0, 0]}}
      ).gain[0] - 1.5) < 1e-9)
check("the settings block is JSON-serialisable",
      isinstance(json.dumps(original.to_settings()), str))


# --- 7. Camera Studio's COLOUR section, without a camera --------------------

import argparse  # noqa: E402

from camera.camera_studio import BUTTONS, FIELDS, Studio  # noqa: E402
from vision.commands import CommandError  # noqa: E402
from vision.fisheye import LensProfile  # noqa: E402

args = argparse.Namespace(
    backend="auto", device=None, autosave=False,
    settings=Path("/nonexistent/camera_settings.json"), profile=Path("/nonexistent"),
)
studio = Studio(args, LensProfile())

for name in ("colour", "wb", "colourcal", "colourmode", "gamma", "csat",
             "nomix", "colourinfo", "colourreset",
             *(f"{c[0]}gain" for c in CHANNELS), *(f"{c[0]}off" for c in CHANNELS)):
    check(f"studio has the {name!r} command", name in studio.commands)

check("the panel has a COLOUR group",
      any(field.group == "COLOUR" for field in FIELDS))
check("the colour buttons are present",
      {"WHITE BAL", "COLOUR CAL", "COLOUR RESET"} <= {label for label, _ in BUTTONS})

check("colour starts off and identity",
      not studio.colour.enabled and studio.colour.is_identity)
check("rgain is reachable as a command",
      studio.commands.execute("rgain 1.25").ok
      and abs(studio.colour.gain[2] - 1.25) < 1e-9)
check("gains step relatively too",
      studio.commands.execute("rgain +0.25").ok
      and abs(studio.colour.gain[2] - 1.5) < 1e-9)
check("colour on/off toggles",
      studio.commands.execute("colour on").ok and studio.colour.enabled)

# wb and colourcal need a frame; they must say so rather than crash.
result = studio.commands.execute("wb")
check("wb without a frame explains itself",
      not result.ok and "frame" in result.message, result.message[:50])

studio.last_capture = camera
result = studio.commands.execute("wb")
check("wb from a live sheet succeeds", result.ok, result.message[:70])
check("wb switched the correction on", studio.colour.enabled)

with tempfile.TemporaryDirectory() as directory:
    reference_path = Path(directory) / "reference.png"
    cv2.imwrite(str(reference_path), reference)
    result = studio.commands.execute(f"colourcal {reference_path} gain")
    check("colourcal against a reference photo succeeds", result.ok,
          result.message[:80])
    recovered = studio.colour.gain
    check("colourcal recovered the cast",
          all(abs(a - 1.0 / b) < 0.06 for a, b in zip(recovered, CAST)),
          f"{tuple(round(v, 3) for v in recovered)} vs {expected}")

    result = studio.commands.execute(f"colourcal {reference_path} matrix")
    check("colourcal accepts an explicit fit mode", result.ok, result.message[:60])
    check("nomix returns a matrix fit to a diagonal one",
          studio.commands.execute("nomix").ok and studio.colour.is_diagonal)

    result = studio.commands.execute("colourcal /nonexistent/nope.png")
    check("a missing reference image is refused",
          not result.ok and "reference" in result.message, result.message[:50])

    # The saved file has to carry it, or none of this reaches the runtime feed.
    studio.capture_size = (1296, 972)
    settings_path = Path(directory) / "camera_settings.json"
    studio.write_settings(settings_path)
    saved = json.loads(settings_path.read_text())
    check("the settings file carries the colour block", "colour" in saved,
          ", ".join(sorted(saved))[:60])
    reloaded = ColorCorrection.from_settings(saved)
    check("the saved block reloads to the same correction",
          np.allclose(reloaded.matrix, studio.colour.matrix))

    studio.commands.execute("colourreset")
    check("colourreset returns to a disabled identity",
          studio.colour.is_identity and not studio.colour.enabled)
    check("loading the file brings the correction back",
          studio.commands.execute(f"load {settings_path}").ok
          and np.allclose(ColorCorrection.from_settings(saved).matrix,
                          studio.colour.matrix))

studio.commands.execute("reset")
check("a full studio reset clears the colour correction too",
      studio.colour.is_identity and not studio.colour.enabled)

raise SystemExit(1 if failed else 0)
