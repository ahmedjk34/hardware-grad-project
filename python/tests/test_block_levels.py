#!/usr/bin/env python3
"""Checks for vision/block_levels.py, the level-aware detector.

Run from python/:  ../.venv/bin/python tests/test_block_levels.py

Most frames here are synthesised through the *same projection the module claims
to invert*, so the level of every block and the camera height above them are
known exactly rather than eyeballed. That is the only way to test this: a real
capture cannot tell you the true camera height, and eyeballing a level from a
photograph is precisely the judgement the module exists to replace.

The renderer is deliberately written from the forward geometry (project a
prism's eight corners, paint the silhouette dark and the top face bright) and
never from the module's own equations, so a sign error in
``_ground_projection`` or ``_side_ratio`` cannot cancel itself out.

The committed captures are then used for what they can genuinely prove: that
the surface split is bimodal on real wood under real light, that a single-layer
board is not hallucinated into a tower, and that the multi-level capture comes
back with a physically plausible camera height.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vision.block_levels import (                                   # noqa: E402
    MAX_LEVEL_SNAP,
    MIN_HEIGHT_CONFIDENCE,
    LevelMetrics,
    detect_leveled_blocks,
    detect_top_layer,
    estimate_camera_height,
    height_map,
    split_surfaces,
    suppress_side_faces,
)


BLOCK_HEIGHT_CM = 1.5      # arduino/build_test_v1: BLOCK_HEIGHT_CM
BLOCK_LONG_CM = 6.0        # config/rig.json: grid.modes.*.block_x_cm
BLOCK_SHORT_CM = 2.2       # config/rig.json: grid.modes.*.block_y_cm

failures = []


def check(name, condition, detail=""):
    mark = "ok  " if condition else "FAIL"
    print(f"  {mark}  {name}" + (f"   [{detail}]" if detail else ""))
    if not condition:
        failures.append(name)


def expect_error(name, fn, needle=""):
    try:
        fn()
    except Exception as error:                        # noqa: BLE001
        check(name, needle in str(error), f"{type(error).__name__}: {error}")
        return
    check(name, False, "no error raised")


# ---------------------------------------------------------------------------
# A synthetic overhead camera
# ---------------------------------------------------------------------------


class Scene:
    """An overhead pinhole above a table, rendering blocks as solid prisms.

    Straight forward geometry: a point ``(X, Y)`` centimetres from the optical
    axis at height ``z`` images at ``axis + focal*(X, Y)/(H - z)``. Every block
    is drawn as the convex hull of its projected corners (that is exactly the
    silhouette a solid prism casts) filled in the shaded side colour, then its
    four top corners filled in the bright top colour on top of it.

    **A raised block is drawn as a column from the table up to its top face**,
    not as a slab floating at its own level. That is not a shortcut, it is the
    physics: the rig cannot place a block in mid-air, so a level-1 block always
    has something under it and the side the camera sees runs all the way down to
    the table. A first draft rendered raised blocks floating, which gave every
    one of them a side band exactly one block tall -- so every level read back as
    level 0 and the module looked broken when it was the fixture that was.

    This is also what the module's ruler actually measures: the height of a top
    face above the *ground*, not above whatever is immediately beneath it. A
    horizontal seam between two stacked blocks is bridged by the ray walker's
    gap tolerance, so an aligned two-block stack reads 3.0 cm and not 1.5.

    Nothing here consults block_levels. If the module's algebra disagrees with
    this renderer, the module is wrong.
    """

    def __init__(self, camera_height_cm=42.0, focal_px=None, size=(640, 480)):
        self.camera_height_cm = float(camera_height_cm)
        # Focal length scales with height by default, so every scene frames the
        # same build area. That is what a real rig would do -- move the camera
        # back and you fit a longer lens -- and it keeps the test about camera
        # height rather than about how big the blocks happen to look. Note it
        # does NOT rescue a distant camera: the side band shrinks as h/H whether
        # or not the framing is held constant, which is the geometry half of
        # block_levels.minimum_measurable_radius_px.
        self.focal_px = float(focal_px if focal_px is not None
                              else 520.0 * self.camera_height_cm / 42.0)
        self.size = size
        self.axis = np.array([(size[0] - 1) / 2.0, (size[1] - 1) / 2.0])
        # Warm on pale, matching the real captures: the top face must clear the
        # detector's red-minus-blue thresholds and the side must sit clearly
        # darker while staying warm enough for the relaxed union mask.
        #
        # The background must FAIL that test, and "pale" is not enough to
        # guarantee it -- a first draft used (196, 188, 205), whose red-minus-
        # blue of 9 clears the default threshold of 8. The whole frame then
        # segmented as one warm blob and every synthetic check failed at once
        # while the real captures passed. Keep the wall cool: B above R.
        self.background = (208, 200, 196)      # B=208 R=196, red-minus-blue -12
        self.top_color = (150, 196, 232)       # red-minus-blue +82
        self.side_color = (86, 118, 150)       # red-minus-blue +64, much darker

    def project(self, x_cm, y_cm, z_cm):
        denominator = max(self.camera_height_cm - z_cm, 1e-6)
        return self.axis + self.focal_px * np.array(
            [x_cm, y_cm]) / denominator

    def render(self, blocks, noise=0):
        """``blocks`` are ``(x_cm, y_cm, level, vertical)`` tuples."""
        frame = np.full((self.size[1], self.size[0], 3),
                        self.background, dtype=np.uint8)
        # Far blocks first, so a nearer block correctly occludes what is behind
        # it. "Far" here means small image radius, since an overhead camera
        # occludes outward.
        order = sorted(blocks, key=lambda b: math.hypot(b[0], b[1]))
        for x_cm, y_cm, level, vertical in order:
            half_x = (BLOCK_SHORT_CM if vertical else BLOCK_LONG_CM) / 2.0
            half_y = (BLOCK_LONG_CM if vertical else BLOCK_SHORT_CM) / 2.0
            top = level * BLOCK_HEIGHT_CM + BLOCK_HEIGHT_CM
            corners = [(x_cm + sx * half_x, y_cm + sy * half_y)
                       for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
            top_face = np.array([self.project(cx, cy, top)
                                 for cx, cy in corners])
            # Down to the table, not down to this block's own base: see the
            # class docstring for why a floating slab is the wrong fixture.
            bottom_face = np.array([self.project(cx, cy, 0.0)
                                    for cx, cy in corners])
            silhouette = cv2.convexHull(
                np.vstack([top_face, bottom_face]).astype(np.float32))
            cv2.fillConvexPoly(frame, silhouette.round().astype(np.int32),
                               self.side_color, cv2.LINE_AA)
            cv2.fillConvexPoly(frame, top_face.round().astype(np.int32),
                               self.top_color, cv2.LINE_AA)
        if noise:
            rng = np.random.default_rng(7)
            frame = np.clip(frame.astype(np.int16) +
                            rng.integers(-noise, noise + 1, frame.shape),
                            0, 255).astype(np.uint8)
        return frame

    def truth_top_face_cm(self, level):
        return (level + 1) * BLOCK_HEIGHT_CM


def nearest(blocks, point, limit=40.0):
    """The detected block whose image centre is closest to ``point``."""
    best, best_distance = None, limit
    for block in blocks:
        distance = math.hypot(block.detection.center[0] - point[0],
                              block.detection.center[1] - point[1])
        if distance < best_distance:
            best, best_distance = block, distance
    return best


# ---------------------------------------------------------------------------

print("\nthe height equation, against a renderer that never saw it")

scene = Scene(camera_height_cm=42.0)
# A ring of single blocks at level 0 and a matching ring at level 1. Radius is
# what makes a side face visible at all, so both rings sit well off the axis.
layout = []
for index, angle in enumerate(np.linspace(0, 2 * math.pi, 8, endpoint=False)):
    radius = 9.0 + 2.0 * (index % 2)
    level = index % 2
    layout.append((radius * math.cos(angle), radius * math.sin(angle),
                   level, index % 3 == 0))
frame = scene.render(layout)

metrics = LevelMetrics()
blocks = detect_leveled_blocks(frame, block_height_cm=BLOCK_HEIGHT_CM,
                               camera_height_cm=scene.camera_height_cm,
                               metrics=metrics)
check("every synthetic block is found", len(blocks) >= len(layout),
      f"{len(blocks)} for {len(layout)} placed")
check("the surface split is bimodal on synthetic wood", metrics.split_ok,
      f"separability {metrics.separability:.2f}")

correct = 0
compared = 0
for x_cm, y_cm, level, _vertical in layout:
    truth = scene.project(x_cm, y_cm, scene.truth_top_face_cm(level))
    found = nearest(blocks, truth)
    if found is None or found.level is None:
        continue
    compared += 1
    correct += int(found.level == level)
check("a known camera height recovers the known level",
      compared >= 6 and correct >= compared - 1,
      f"{correct}/{compared} levels exact")

# Not "the heights are accurate" -- the module documents a 4-9% low bias from
# the anti-aliased band edges. What must hold is that no measurement lands in no
# man's land between two levels, because that is what would make a level
# assignment a coin flip rather than a reading.
heights = [b.height_cm for b in blocks if b.height_cm is not None]
worst = max((abs(h / BLOCK_HEIGHT_CM - round(h / BLOCK_HEIGHT_CM))
             for h in heights), default=None)
check("no measured height lands between two levels",
      worst is not None and worst <= MAX_LEVEL_SNAP,
      f"worst {worst:.2f} blocks from a lattice step, snap limit {MAX_LEVEL_SNAP}"
      if worst is not None else "none measured")


print("\nparallax correction puts a raised block back on its footprint")

# One block at level 3, far off axis, is where an uncorrected report is most
# wrong. The ground projection must beat the raw image centre by a wide margin.
tower = Scene(camera_height_cm=42.0)
tower_frame = tower.render([(x, y, 3, False) for x, y in [(11.0, 6.0)]] +
                           [(-11.0, -6.0, 0, False), (11.0, -6.0, 0, True),
                            (-11.0, 6.0, 1, True), (0.0, 11.0, 1, False),
                            (0.0, -11.0, 0, False), (13.0, 0.0, 2, True)])
raised = detect_leveled_blocks(tower_frame, block_height_cm=BLOCK_HEIGHT_CM,
                               camera_height_cm=tower.camera_height_cm)
truth_ground = tower.project(11.0, 6.0, 0.0)
truth_image = tower.project(11.0, 6.0, tower.truth_top_face_cm(3))
found = nearest(raised, truth_image, limit=60.0)
check("the level-3 block is detected", found is not None)
if found is not None:
    raw_error = math.hypot(found.detection.center[0] - truth_ground[0],
                           found.detection.center[1] - truth_ground[1])
    fixed_error = math.hypot(found.ground_center[0] - truth_ground[0],
                             found.ground_center[1] - truth_ground[1])
    check("the uncorrected image centre really is far from the footprint",
          raw_error > 15.0, f"{raw_error:.1f} px")
    check("the ground projection lands on the footprint",
          fixed_error < raw_error * 0.35,
          f"{fixed_error:.1f} px corrected vs {raw_error:.1f} px raw")


print("\nstacking: only the top block survives")

stack = Scene(camera_height_cm=42.0)
# A horizontal block lying across a vertical one, twice, plus a lone block.
# This is the shape the question is actually about, and it is the shape the rig
# builds: the crossing pair share only their middle, so BOTH remain visible and
# layer 1 returns two overlapping rectangles. The ordering logic has to pick.
#
# Two arrangements were tried first and are worth not repeating. Two blocks of
# the same orientation offset along their long axis fuse into one 123 px
# rectangle -- layer 1 sees a single long block and there is nothing to order.
# And a level-1 block sitting exactly on a level-0 one hides it completely; no
# overhead camera can report what it cannot see, so asserting otherwise would be
# asserting a physical impossibility.
CROSSES = [(-9.0, 5.0, 0, True), (-9.0, 5.0, 1, False),
           (9.0, -6.0, 0, True), (9.0, -6.0, 1, False),
           (11.0, 7.0, 0, True)]
stack_frame = stack.render(CROSSES)
stacked = detect_leveled_blocks(stack_frame, block_height_cm=BLOCK_HEIGHT_CM,
                                camera_height_cm=stack.camera_height_cm)
tops = [b for b in stacked if b.on_top]
check("a crossing pair collapses to one reported block",
      len(tops) < len(stacked), f"{len(tops)} tops of {len(stacked)} detected")


def by_orientation(blocks, point, vertical):
    """Pick the detection matching a placed block's orientation and position.

    The two blocks of a cross share a centre, so position alone cannot tell them
    apart -- only the long axis can. Layer 1 reports a block long in Y near
    +/-90 degrees and one long in X near 0.
    """
    want = 90.0 if vertical else 0.0
    scored = []
    for block in blocks:
        angle = abs(block.detection.angle)
        bearing = min(abs(angle - want), abs(180.0 - angle - want))
        distance = math.hypot(block.detection.center[0] - point[0],
                              block.detection.center[1] - point[1])
        scored.append((bearing + 0.3 * distance, block))
    return min(scored, key=lambda item: item[0])[1]


upper_correct = 0
lower_correct = 0
for x_cm, y_cm, level, vertical in CROSSES[:4]:
    placed = by_orientation(stacked,
                            stack.project(x_cm, y_cm,
                                          stack.truth_top_face_cm(level)),
                            vertical)
    if level == 1:
        upper_correct += int(placed.level == 1 and placed.on_top)
    else:
        lower_correct += int(placed.level == 0 and not placed.on_top)
check("the block lying across the top is the one reported",
      upper_correct == 2, f"{upper_correct}/2 crossing blocks kept")
check("the block underneath is found, levelled, and then suppressed",
      lower_correct == 2, f"{lower_correct}/2 lower blocks suppressed")
check("the lone block is not suppressed by anything",
      by_orientation(stacked,
                     stack.project(11.0, 7.0, stack.truth_top_face_cm(0)),
                     True).on_top)
check("every suppressed block names what covers it",
      all(b.covered_by is not None for b in stacked if not b.on_top))
check("nothing is its own cover",
      all(b.covered_by != index
          for index, b in enumerate(stacked) if not b.on_top))
covered_levels = [(stacked[b.covered_by].height_ratio, b.height_ratio)
                  for b in stacked
                  if not b.on_top and b.height_ratio is not None
                  and stacked[b.covered_by].height_ratio is not None]
check("the surviving block is the higher one of every pair",
      all(top >= under - 1e-9 for top, under in covered_levels),
      f"{len(covered_levels)} measured pairs")

check("detect_top_layer returns exactly the surviving blocks",
      len(detect_top_layer(stack_frame, block_height_cm=BLOCK_HEIGHT_CM,
                           camera_height_cm=stack.camera_height_cm)) == len(tops))

summary = height_map(stacked, block_height_cm=BLOCK_HEIGHT_CM)
check("the height map has one entry per stack", len(summary) == len(tops))
check("height map entries carry a footprint, not an image centre",
      all(len(entry["center"]) == 2 for entry in summary))


print("\nself-calibration bootstraps the camera height it was rendered at")

# Eight blocks on a radius-13 ring: far enough apart that they do not occlude
# one another, which a tighter ring does. A packed ring was tried first and
# scattered the measurements badly enough to break the fit -- worth knowing,
# since a real board is packed, and it is part of why the module's docstring
# calls this a bootstrap rather than a calibration.
for truth_height in (32.0, 42.0, 60.0):
    rig = Scene(camera_height_cm=truth_height)
    mixed = []
    for index, angle in enumerate(np.linspace(0, 2 * math.pi, 8,
                                              endpoint=False)):
        mixed.append((13.0 * math.cos(angle), 13.0 * math.sin(angle),
                      index % 3, index % 2 == 0))
    report = LevelMetrics()
    detect_leveled_blocks(rig.render(mixed), block_height_cm=BLOCK_HEIGHT_CM,
                          self_calibrate=True, metrics=report)
    recovered = report.camera_height_cm
    error = None if recovered is None else abs(recovered - truth_height) / truth_height
    # 15%, not 5%. The band is a few pixels wide and its edges are anti-aliased,
    # so the fit runs low; the module's docstring explains why that bias largely
    # cancels when the same fit is used to convert back to a height.
    check(f"camera height bootstrapped at {truth_height:.0f} cm",
          error is not None and error < 0.15,
          f"got {recovered:.1f} cm" if recovered else "declined to fit")


print("\nthe height fit's two traps")

# The alias: any H that fits with levels k also fits with 2k at 2H. The fit must
# take the smaller, or every block silently doubles its level.
exact = [BLOCK_HEIGHT_CM / 40.0, 2 * BLOCK_HEIGHT_CM / 40.0,
         BLOCK_HEIGHT_CM / 40.0, 3 * BLOCK_HEIGHT_CM / 40.0,
         2 * BLOCK_HEIGHT_CM / 40.0, BLOCK_HEIGHT_CM / 40.0]
height, residual, confidence = estimate_camera_height(exact, BLOCK_HEIGHT_CM)
check("a clean ladder recovers its own height",
      height is not None and abs(height - 40.0) < 1.5, f"{height:.2f} cm")
check("the alias is resolved downward, not doubled",
      height is not None and height < 60.0, f"{height:.2f} cm")
check("a clean ladder is maximally confident", confidence > 0.9,
      f"residual {residual:.3f}, confidence {confidence:.2f}")

# One wild outlier must not move the answer. This is the real capture's failure
# mode and the reason the score is a median rather than a mean.
polluted = exact + [0.0031]
height_out, _residual_out, _confidence_out = estimate_camera_height(
    polluted, BLOCK_HEIGHT_CM)
check("one bad ray does not move the fit",
      height_out is not None and abs(height_out - 40.0) < 2.5,
      f"{height_out:.2f} cm with an outlier vs {height:.2f} without")

check("too few samples decline rather than guess",
      estimate_camera_height([0.04, 0.08], BLOCK_HEIGHT_CM)[0] is None)

# A characterisation test for a KNOWN WEAKNESS, not a feature. The confidence
# score cannot tell structureless input from a real ladder: seven uniformly
# random ratios still fit some camera height at confidence 0.85, because with H
# free to be anything, almost any set of ratios can be pushed near integers.
# Measured: 0 of 200 random sets scored below the gate.
#
# This is the whole reason self_calibrate defaults off, and the reason the
# module docstring says to measure the camera height rather than fit it. If a
# future change makes the score actually discriminate, this check will fail --
# that is a good failure, and the fix is to invert it, not to delete it.
noise_confidence = estimate_camera_height(
    [0.0131, 0.0217, 0.0409, 0.0533, 0.0701], BLOCK_HEIGHT_CM)[2]
check("confidence does NOT detect structureless input (known weakness)",
      noise_confidence >= MIN_HEIGHT_CONFIDENCE,
      f"noise scored {noise_confidence:.2f} against a {MIN_HEIGHT_CONFIDENCE} gate")


print("\nblock thickness is firmware-owned and must be supplied")

flat = np.full((240, 320, 3), 200, np.uint8)
expect_error("detect_leveled_blocks refuses a missing block height",
             lambda: detect_leveled_blocks(flat, block_height_cm=None),
             "block_height_cm")
expect_error("detect_leveled_blocks refuses a nonsense block height",
             lambda: detect_leveled_blocks(flat, block_height_cm=0.0),
             "block_height_cm")
expect_error("estimate_camera_height refuses a missing block height",
             lambda: estimate_camera_height([0.04], None), "block_height_cm")
expect_error("height_map refuses a missing block height",
             lambda: height_map([], block_height_cm=None), "block_height_cm")


print("\nthe split degrades instead of inventing a level")

# A flat, evenly lit frame has one luminance mode. Otsu still returns a
# threshold; the separability gate is what stops it being believed.
even = np.full((240, 320, 3), 0, np.uint8)
even[:, :] = (150, 196, 232)
masks = split_surfaces(even)
check("an unimodal frame refuses to split", not masks.split_ok,
      f"separability {masks.separability:.2f}")
check("a refused split calls everything a top face", not masks.side.any())
check("a refused split leaves the frame untouched",
      suppress_side_faces(even, masks) is even)

blocks_even = detect_leveled_blocks(even, block_height_cm=BLOCK_HEIGHT_CM)
check("a refused split still returns without a level",
      all(b.level is None for b in blocks_even))


print("\nthe committed captures")

CAPTURES = Path(__file__).resolve().parents[1] / "captures"
paths = sorted(CAPTURES.glob("*corrected*.png"))
check("there are captures to check", bool(paths), f"{len(paths)} found")

for path in paths:
    capture = cv2.imread(str(path))
    if capture is None:
        continue
    label = path.name[:16]
    report = LevelMetrics()
    found = detect_leveled_blocks(capture, block_height_cm=BLOCK_HEIGHT_CM,
                                  metrics=report)
    check(f"{label}: real wood splits bimodally", report.split_ok,
          f"separability {report.separability:.2f}")
    check(f"{label}: a camera height is either plausible or declined",
          report.camera_height_cm is None or
          20.0 <= report.camera_height_cm <= 120.0,
          f"{report.camera_height_cm}")
    check(f"{label}: no block is reported above what was built",
          all(b.level is None or 0 <= b.level <= 6 for b in found))
    check(f"{label}: every block is on top or covered, never both",
          all((b.covered_by is None) == b.on_top for b in found))

# The multi-level capture is the one with something to prove. What it can prove
# is the ORDERING -- that stacked blocks are found and the covered ones dropped.
# It cannot prove a level number, because nobody measured the camera height when
# it was taken, so nothing here asserts one.
multi = [p for p in paths if "20260905-123235" in p.name]
if multi:
    capture = cv2.imread(str(multi[0]))
    report = LevelMetrics()
    found = detect_leveled_blocks(capture, block_height_cm=BLOCK_HEIGHT_CM,
                                  metrics=report)
    check("the multi-level capture measures most of its blocks",
          report.measured >= len(found) * 0.6,
          f"{report.measured} of {len(found)}")
    check("it suppresses blocks that something sits on",
          report.suppressed > 0, f"{report.suppressed} covered")
    check("suppression finds more blocks than raw layer 1 did",
          len(found) >= 12, f"{len(found)} detected")
    check("ordering needs no camera height",
          all(b.level is None for b in found) and
          any(not b.on_top for b in found),
          "levels declined, stacks still resolved")

# The 29-block reference board is FLAT, and this is the regression that matters
# most: a flat board must not be reported as a tower. With self_calibrate on it
# is -- eleven blocks on level 0, one on level 1, three on level 2 -- which is
# exactly why that switch defaults off and why this check pins the default.
board = [p for p in paths if "20260903-122957" in p.name]
if board:
    capture = cv2.imread(str(board[0]))
    report = LevelMetrics()
    found = detect_leveled_blocks(capture, block_height_cm=BLOCK_HEIGHT_CM,
                                  metrics=report)
    check("the flat board reports no stacking",
          report.suppressed == 0, f"{report.suppressed} suppressed")
    check("the flat board names no levels by default",
          all(b.level is None for b in found) and not report.self_calibrated)
    check("every block on the flat board is reported as a top",
          all(b.on_top for b in found), f"{len(found)} blocks")


print()
if failures:
    print(f"{len(failures)} failing check(s): {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")
