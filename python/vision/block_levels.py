#!/usr/bin/env python3
"""Level-aware block detection: which blocks are on top, and how high they sit.

Why this exists, next to ``block_detector.py``
-----------------------------------------------
:func:`block_detector.detect_blocks` has no concept of height. It segments warm
material, fits rectangles, and returns a flat list. On a single-layer board that
is exactly right. On a *stack* it fails three ways at once:

1. **Segmentation.** A block's bright top face and its shaded vertical side are
   both warm, so they land in one colour blob. The side faces of a tower are the
   glue that welds neighbouring blocks into a single component with no
   concavity, which is precisely the input ``_split_touching`` cannot cut and
   ``_decompose_compound`` has to guess at.
2. **Position.** Everything is projected through one homography of the *ground*
   plane. A raised block images further from the optical axis than its true
   footprint, so it is reported in the wrong cell — silently, and worse the
   further it sits from frame centre. Per ``AGENTS.md`` that is the exact input
   that gets a calibration knob turned the wrong way.
3. **Ordering.** Nothing says which of two overlapping rectangles is the one on
   top, which is the only one a build rig can actually pick or place onto.

This module fixes all three from software alone — no second camera, no depth
sensor, no extra lighting.

The cue: the visible side face is a ruler
------------------------------------------
The rig's camera is wide and close, so a raised block shows a *sliver of its
vertical side*. That sliver is both the segmentation fix (remove it and stacked
blocks stop being connected) and the height measurement. One cue, two problems.

The geometry, for an overhead pinhole at height ``H`` above the ground:

* a ground point at radius ``R`` images at image radius ``r = f·R/H``;
* the top face of a block whose top surface is at height ``h`` images at
  ``r_top = f·R/(H − h)``, which is *further from the axis* than its own base;
* the visible side runs between the two, so its projected length is
  ``s = r_top − r_base = r_top · h/H``.

**Which side is visible is the opposite of most people's first guess, this
author's included.** Because the top face images further out than the base, the
exposed band lies *between* them -- on the side facing the optical axis. An
overhead camera looks down and outward at an off-axis block, so what it sees
past the top face is the block's near side, the one pointing back at the axis.
The equation is indifferent to this; a ray cast the wrong way is not, and walks
straight off the block into the background measuring nothing.

Rearranged, that is the whole module::

    h = H · s / r_top                       (1)  height of a top face
    p_ground = axis + (p_top − axis)·(H−h)/H  (2)  its true footprint

Two things about (1) are worth saying out loud, because they are what make this
practical rather than a calibration project:

* **Neither focal length nor pixels-per-centimetre appears.** They cancel. The
  only extrinsic needed is ``H``.
* **``s/r_top`` is a ratio, so it is scale-free.** It can be measured at the
  bounded working resolution and used directly against a full-resolution
  detection with no conversion. That is why :func:`_side_ratio` never sees a
  scale factor.

A known bias, and why it mostly cancels
----------------------------------------
The band is a handful of pixels wide, and both of its edges are anti-aliased, so
a measured ``s`` runs low: against the synthetic renderer the recovered camera
height comes back about 4-5% under truth at native resolution and 7-9% under at
the 384 px working width.

That bias is *multiplicative*, and self-calibration absorbs it. If every ``s``
is short by a factor β then every ``q`` is too, and :func:`estimate_camera_height`
returns ``H/β`` -- so ``h = H_est·q_measured`` recovers the true height and the
level rounds correctly anyway. The reported ``camera_height_cm`` is therefore
the less trustworthy of the two outputs, and a caller wanting the real camera
height should measure it rather than read it back from here. Passing a
*correctly measured* ``camera_height_cm`` in trades this cancellation for a
small level bias, which the rounding still absorbs at every level tested.

Two outputs, and they are NOT equally trustworthy
--------------------------------------------------
Read this before believing a number out of this module.

**Which block is on top of which — solid.** This needs only the *relative*
ordering of two side-face measurements in the same stack, never their absolute
size, so it needs no camera height and no calibration at all. It is what
``on_top`` / ``covered_by`` / :func:`detect_top_layer` report, and it works on
the committed multi-level capture.

**Which numbered level a block is on — not validated on real frames.** This
needs an absolute ``H``, and the measurements are not yet clean enough to
recover one from a photograph. The evidence, from the committed captures: on the
29-block reference board, which is *entirely flat*, the measured ratios scatter
with a coefficient of variation of 0.54 — higher than the genuinely multi-level
capture's 0.37. Fitting a height to that scatter puts eleven blocks on level 0,
one on level 1 and three on level 2, on a board where every block is on the
table. Synthetic scenes with exact ground truth do not show this (CV 0.07 when
flat, 0.43 across three levels), so the gap is real-world noise -- touching
blocks occluding each other's side faces, and the grooves between them reading
as side faces -- not an error in the algebra.

Hence ``self_calibrate`` defaults **False**. Without a camera height the module
still measures ``height_ratio``, still orders stacks, and still reports which
block is on top; it simply declines to name a level or to move a footprint.
Pass a *measured* ``camera_height_cm`` to unlock ``level``, ``height_cm`` and
the parallax correction, and see :func:`estimate_camera_height` -- runnable on
its own -- for a rough starting value to sanity-check a tape measure against.

``H`` bootstraps itself — but measure it if you can
-----------------------------------------------------
``h`` is not free to be anything: a block at level ``L`` has its top face at
exactly ``(L+1)`` block heights. So across the blocks in one frame the measured
ratios ``q_i = s_i/r_top_i`` must satisfy ``H·q_i ≈ k_i·t`` for integers
``k_i ≥ 1`` and known block thickness ``t``. That is a one-dimensional
quantisation fit, and :func:`estimate_camera_height` solves it by search, so a
frame with five or more measurable blocks can recover its own camera height.

**Treat that number as a bootstrap, not a calibration.** It was measured over
400 randomised synthetic scenes and it is not trustworthy enough to be the
production path: at 10% measurement noise roughly one fit in six lands more than
25% from truth, and the reported confidence barely predicts which — tightening
the gate from 0.60 to 0.85 throws away four fifths of the fits and still lets
15% of grossly wrong ones through. Worse, a wrong ``H`` does not look wrong: the
alias doubles every level at once, so the levels stay integers and the residual
stays small. **Pass ``camera_height_cm`` once you have measured it**, and treat
levels from a self-calibrated frame (``LevelMetrics.self_calibrated``) as
provisional. The self-calibration exists so a fresh rig gets a usable first
answer, and so a measured value can be sanity-checked against it.

Two things make the fit as good as it is. The **alias**: if ``H`` fits with
levels ``k_i``, then ``2H`` fits with ``2k_i`` always, so a larger ``H`` is
never penalised by the residual and the search takes the smallest one within
tolerance. And the **ground pin**: the rig builds upward from a table, so the
shallowest block in view is almost always resting on it, which fixes the scale
outright.

Where it cannot work, and what covers those cases
--------------------------------------------------
* **At the optical axis** no side face is visible on any block, at any height —
  ``s`` is zero and (1) is undefined. This is not a tuning problem, it is the
  projection. Covered by completeness ordering: the block on top is the only one
  whose rectangle is *whole*, because anything under it is notched by it.
* **Inside a plateau** of same-level blocks, interior blocks hide each other's
  sides. Covered by :func:`_share_plateaus`: top faces that touch in the mask
  with no side face between them are coplanar by construction, so a measured
  member lends its height to its unmeasured neighbours.
* **Fully buried** — a block hidden under a same-orientation block is not
  recoverable from one overhead view at all, and no amount of software changes
  that. It is the planner's job to know it is there; this module's job is to
  disagree with the planner loudly enough to notice when it is not.

Block thickness is NOT defined here
------------------------------------
``BLOCK_HEIGHT_CM`` is firmware-owned — ``tests/test_link.py`` states the Pi is
forbidden a copy of it, so this module refuses to keep one. Every entry point
that needs it takes ``block_height_cm`` as an explicit argument and raises if it
is missing. Callers must pass the value that matches the flashed sketch.

Layering
--------
This is layer 1.5: it consumes ``block_detector`` (layer 1) and is consumed by
``block_outline`` (layer 2). It borrows ``block_detector._warm_mask`` rather
than restating the colour rule, for the same reason layer 2 borrows layer 3's
``_deduplicate`` — two copies of a threshold is a threshold that drifts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math

import cv2
import numpy as np

from vision.block_detector import (
    MAX_PROCESSING_WIDTH,
    BlockDetection,
    DetectionMetrics,
    _warm_mask,
    detect_blocks,
)
from vision.color_grid import flatten_illumination, white_balance


# --- Surface split -------------------------------------------------------

# Otsu always returns a threshold, even for a single-humped histogram. This is
# its separability (between-class over total variance): below it, "bright" and
# "dark" are not two populations and splitting would shred whole blocks into
# fragments. The module falls back to no-split rather than trusting it.
MIN_SEPARABILITY = 0.28

# Side faces are the same material as the top, seen at a glancing angle, so they
# are darker AND less saturated -- their red-minus-blue response can fall under
# the threshold that finds top faces. The union mask is therefore built with
# relaxed colour thresholds, and the split then separates the two by luminance.
SIDE_COLOR_RELAXATION = 0.45

# Minimum half-thickness, in working-resolution pixels, for a dark band to be
# treated as a REAL side face rather than a shading rim on a top face.
#
# This one number is the difference between the split helping and hurting, and
# it was measured rather than guessed. Neutralising every dark pixel ate ~4 px
# off each block's short side on the multi-level capture, dropping its aspect
# ratio to 3.24 against a true 6.0/2.2 = 2.73 and collapsing 10 detections to 6.
# Requiring a band to be at least this thick before it is suppressed leaves thin
# rims alone. Measured over the committed captures:
#
#   capture              raw layer 1        guarded suppression
#   165930 (3 blocks)    3, aspect 2.72     3, aspect 2.74
#   122957 (29 board)    32, aspect 3.13    28, aspect 3.05
#   123235 (multi-level) 10, aspect 2.29    14, aspect 2.50
#
# So: neutral on a flat scene, a clear win where blocks are stacked, and
# slightly lossy on the dense single-layer board -- which is the one case where
# levels do not matter anyway. Values from 1.01 to 1.3 give identical results on
# all three; 1.6 starts giving ground back.
SIDE_MIN_HALF_THICKNESS_PX = 1.2

_SPLIT_OPEN = np.ones((3, 3), np.uint8)


# --- Side-face ray marching ----------------------------------------------

# Samples along each outward-facing box edge. Nine is enough to survive a
# neighbouring block occluding part of the side face and cheap enough that a
# full board costs a few milliseconds.
RAYS_PER_EDGE = 9

# An edge counts as outward-facing when its normal agrees this well with the
# radial direction. At 0.25 a block sitting near the axis still offers its two
# best edges; tightening this loses blocks in the middle of the frame.
MIN_EDGE_ALIGNMENT = 0.25

# Mask pinholes are common along a shaded face. A ray survives this many missing
# pixels in a row; the next one ends it.
RAY_GAP_TOLERANCE = 2

# A ray must find side pixels within this many steps of the box edge, or the
# face is occluded/absent at that sample and the ray is discarded rather than
# scored zero -- zeros would drag the median toward "level 0" on a tall block
# whose side is half hidden by its neighbour.
RAY_START_WINDOW = 3

# Fraction of cast rays that must find a side face before the height is trusted.
MIN_RAY_SUPPORT = 0.34

# Blocks closer than this to the optical axis (as a fraction of the frame's half
# diagonal) have no usable side face. Not a tuning knob -- it is where the
# projection stops producing one.
MIN_AXIS_RADIUS_FRACTION = 0.06


# --- Height fit ----------------------------------------------------------

# Five, not three. The score is a median, and a median of five tolerates two
# bad measurements; a median of three tolerates one and a median of four is
# already an average of the middle pair. Measured consequence on the committed
# captures: the 29-block single-layer board offers only four measurable side
# faces -- all of them marginal, since every block on it is at level 0 -- and
# from those four the search happily returns 173 cm. Refusing to answer there is
# correct twice over: the number is noise, and a flat board has no levels to
# report anyway.
MIN_HEIGHT_SAMPLES = 5

# A self-calibrated height below this confidence is discarded rather than used.
# A wrong H is worse than no H: it silently moves every reported footprint,
# which is the AGENTS.md failure where a bad placement report gets a calibration
# knob turned the wrong way. With no H the module still orders stacks by
# completeness and simply declines to name levels.
MIN_HEIGHT_CONFIDENCE = 0.60

CAMERA_HEIGHT_BOUNDS_CM = (18.0, 220.0)
HEIGHT_SEARCH_STEPS = 900
# A candidate camera height is "as good as the best" within this much residual.
# The smallest such candidate wins, which is what breaks the H/2H alias.
HEIGHT_ALIAS_TOLERANCE = 0.04
MAX_PLAUSIBLE_LEVEL = 12

# How far a measured top-face height may sit from an exact multiple of the block
# thickness and still be called that level, in units of one block.
MAX_LEVEL_SNAP = 0.42


# --- Completeness and stacking -------------------------------------------

COMPLETE_RECTANGULARITY = 0.80
COMPLETE_SOLIDITY = 0.84

# Two ground footprints belong to one stack when the smaller is this covered by
# the larger. Deliberately generous: a stacked pair is rarely aligned to the
# pixel, and splitting one stack into two is the failure that produces a phantom
# extra block in the report.
STACK_OVERLAP = 0.32


@dataclass
class SurfaceMasks:
    """The warm region of one frame, split into top faces and side faces."""

    top: np.ndarray
    side: np.ndarray
    solid_side: np.ndarray
    warm: np.ndarray
    scale: float
    separability: float
    split_ok: bool

    @property
    def size(self) -> tuple[int, int]:
        return self.top.shape[1], self.top.shape[0]


@dataclass
class LeveledBlock:
    """One detected top face, with whatever height evidence was recoverable."""

    detection: BlockDetection
    ground_center: tuple[float, float]
    ground_box: np.ndarray
    height_ratio: float | None = None
    height_cm: float | None = None
    level: int | None = None
    level_error: float | None = None
    support: float = 0.0
    inherited: bool = False
    complete: bool = True
    on_top: bool = True
    covered_by: int | None = None
    stack: int = -1

    @property
    def measured(self) -> bool:
        return self.height_ratio is not None


@dataclass
class LevelMetrics:
    detection: DetectionMetrics = field(default_factory=DetectionMetrics)
    separability: float = 0.0
    split_ok: bool = False
    detections: int = 0
    measured: int = 0
    inherited: int = 0
    stacks: int = 0
    suppressed: int = 0
    camera_height_cm: float | None = None
    height_residual: float | None = None
    height_confidence: float = 0.0
    self_calibrated: bool = False


# ---------------------------------------------------------------------------
# Surface split
# ---------------------------------------------------------------------------


def _otsu(values: np.ndarray) -> tuple[float, float]:
    """Otsu threshold over a 1-D sample, plus its separability.

    ``cv2.threshold`` gives the threshold but not how believable it is. The
    separability (between-class variance over total variance) is what tells a
    genuinely bimodal face/side histogram apart from one evenly lit surface, and
    it is the only thing standing between this module and cutting whole blocks
    in half on a flatly lit scene.
    """
    if values.size < 32:
        return 0.0, 0.0
    threshold, _ = cv2.threshold(values.reshape(-1, 1), 0, 255,
                                 cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    total_variance = float(values.var())
    if total_variance <= 1e-6:
        return float(threshold), 0.0
    dark = values[values < threshold]
    bright = values[values >= threshold]
    if dark.size == 0 or bright.size == 0:
        return float(threshold), 0.0
    weight = dark.size / values.size
    between = weight * (1.0 - weight) * (float(bright.mean()) -
                                         float(dark.mean())) ** 2
    return float(threshold), float(min(1.0, between / total_variance))


def split_surfaces(frame: np.ndarray, *, color_threshold: int = 8,
                   red_green_threshold: int = 3,
                   balance: bool = False, flatten: bool = False,
                   max_processing_width: int = MAX_PROCESSING_WIDTH,
                   ) -> SurfaceMasks:
    """Split the warm material in ``frame`` into bright tops and shaded sides.

    ``flatten`` matters more here than it does in the detector. A 168-degree
    lens rectified to 120 leaves a strong brightness gradient across the frame,
    and a single global luminance threshold under that gradient calls one corner
    "side" and the opposite corner "top". Callers that can afford it should turn
    it on; :func:`detect_leveled_blocks` does by default.

    Returns masks at the bounded working resolution, with the ``scale`` needed
    to map full-resolution coordinates into them. Nothing downstream converts
    *out* of that space: the height cue is a ratio and cancels the scale.
    """
    if frame is None or frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("split_surfaces expects a BGR colour image")

    height, width = frame.shape[:2]
    if width > max_processing_width:
        scale = max_processing_width / width
        work = cv2.resize(frame, (max_processing_width,
                                  max(1, round(height * scale))),
                          interpolation=cv2.INTER_AREA)
    else:
        scale = 1.0
        work = frame

    corrected = work
    if balance:
        corrected = white_balance(corrected)
    if flatten:
        corrected = flatten_illumination(corrected)

    # Two masks, not one. The tight one is what the detector itself would call a
    # block; the relaxed one also admits the shaded sides, which sit lower in
    # red-minus-blue precisely because they are shaded.
    warm = _warm_mask(corrected, color_threshold, red_green_threshold)
    union = _warm_mask(
        corrected,
        max(1, int(round(color_threshold * SIDE_COLOR_RELAXATION))),
        max(0, int(round(red_green_threshold * SIDE_COLOR_RELAXATION))),
    )
    union = cv2.bitwise_or(union, warm)

    luminance = cv2.cvtColor(corrected, cv2.COLOR_BGR2LAB)[:, :, 0]
    samples = luminance[union > 0]
    threshold, separability = _otsu(samples)
    split_ok = bool(samples.size >= 64 and separability >= MIN_SEPARABILITY)

    if not split_ok:
        # Degrade to the detector's own behaviour rather than inventing a split.
        # Everything warm is treated as a top face and the height stage will
        # find no side pixels, which downstream reads as "unmeasured" and falls
        # through to completeness ordering. That is a worse answer, not a wrong
        # one.
        empty = np.zeros_like(warm)
        return SurfaceMasks(top=warm.copy(), side=empty, solid_side=empty.copy(),
                            warm=union, scale=scale,
                            separability=separability, split_ok=False)

    bright = cv2.compare(luminance, threshold, cv2.CMP_GE)
    top = cv2.bitwise_and(union, bright)
    side = cv2.bitwise_and(union, cv2.bitwise_not(bright))

    # A top face is a large connected surface; a side face is a thin band. Open
    # only the top mask, so the opening cannot eat a genuinely thin side sliver
    # -- which is exactly the signal being measured.
    top = cv2.morphologyEx(top, cv2.MORPH_OPEN, _SPLIT_OPEN)
    side = cv2.bitwise_and(side, cv2.bitwise_not(top))

    # Two side masks, for two different jobs, and they must not be confused:
    #
    # * ``side`` keeps every dark pixel, and is what the ruler measures. A level
    #   0 block, or one near the optical axis, shows a genuinely thin sliver;
    #   cleaning that away would bias every such block's height upward.
    # * ``solid_side`` keeps only bands thick enough to be a real vertical face,
    #   and is the only thing allowed to be neutralised out of the frame. This
    #   is what stops suppression eating the top faces it is supposed to isolate.
    distance = cv2.distanceTransform(side, cv2.DIST_L2, 3)
    solid = np.uint8(distance >= SIDE_MIN_HALF_THICKNESS_PX) * 255
    solid = cv2.dilate(solid, _SPLIT_OPEN)
    solid = cv2.bitwise_and(solid, side)
    return SurfaceMasks(top=top, side=side, solid_side=solid, warm=union,
                        scale=scale, separability=separability, split_ok=True)


def suppress_side_faces(frame: np.ndarray, masks: SurfaceMasks) -> np.ndarray:
    """Return ``frame`` with side-face pixels neutralised to grey.

    Grey, not black: setting a pixel to its own luminance makes red-minus-blue
    and red-minus-green exactly zero, so it fails any positive colour threshold
    the detector might be run with, while leaving local contrast intact for the
    Canny support inside ``_decompose_compound``. Blacking it out would forge a
    hard edge that the rectangle scorer would happily fit a block against.

    This is what lets the whole module reuse layer 1 unmodified: the detector
    still gets a BGR frame and still applies its own thresholds, it just no
    longer sees the sides that were welding stacked blocks together.

    Only ``masks.solid_side`` is neutralised, never ``masks.side``. See
    :data:`SIDE_MIN_HALF_THICKNESS_PX` for the measurements behind that.
    """
    if not masks.split_ok or not masks.solid_side.any():
        return frame

    side = masks.solid_side
    if side.shape[:2] != frame.shape[:2]:
        side = cv2.resize(side, (frame.shape[1], frame.shape[0]),
                          interpolation=cv2.INTER_NEAREST)

    out = frame.copy()
    grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    out[side > 0] = np.repeat(grey[side > 0, None], 3, axis=1)
    return out


# ---------------------------------------------------------------------------
# The side-face ruler
# ---------------------------------------------------------------------------


def _inward_samples(box: np.ndarray, centre: np.ndarray,
                    inward: np.ndarray) -> np.ndarray:
    """Sample points along the box edges that face *towards* the optical axis.

    Inward, not outward, and this is the one direction in the module that is
    easy to get backwards -- the first draft got it backwards, and the synthetic
    renderer is what caught it.

    The intuition that says "the far side is visible" is the wrong intuition.
    An overhead camera looks down and *outward* at a block sitting away from its
    axis, so what it sees past the top face is the side facing back towards the
    axis. In projection terms: the top face is nearer the lens, so it images at
    a LARGER radius than the base, and the silhouette therefore extends inward
    from the top face down to the base. The exposed band lives between them, on
    the axis side.

    The height equation is unaffected -- ``s = r_top·h/H`` holds for the inner
    edge exactly as it does for the outer -- but a ray cast the other way walks
    straight off the block into the background and measures nothing.
    """
    points = []
    for index in range(4):
        a = box[index].astype(np.float64)
        b = box[(index + 1) % 4].astype(np.float64)
        edge = b - a
        length = float(np.hypot(*edge))
        if length < 1e-6:
            continue
        normal = np.array((edge[1], -edge[0])) / length
        midpoint = (a + b) * 0.5
        if float(np.dot(normal, midpoint - centre)) < 0:
            normal = -normal
        if float(np.dot(normal, inward)) < MIN_EDGE_ALIGNMENT:
            continue
        # Trim the ends: box corners are where two faces meet and the mask is
        # least reliable there.
        for step in np.linspace(0.16, 0.84, RAYS_PER_EDGE):
            points.append(a + edge * step)
    return np.asarray(points, dtype=np.float64)


def _walk_ray(on_top: np.ndarray, on_side: np.ndarray) -> tuple[int, int]:
    """Split one inward ray into its top-face run and its side-face run.

    Returns ``(top_end, side_length)``: the step index at which the top face
    stops -- which is the ``r_top`` of equation (1), located rather than assumed
    -- and how far the side face then continues.

    Locating the transition instead of starting at the detection's box edge is
    not a refinement, it is the difference between working and not. The box
    comes from layer 1, and whether it hugs the top face or spans top *and* side
    depends on whether suppression fired, which in turn depends on how thick the
    side band happened to be. Starting a ray at the box edge therefore begins
    *past* the side face exactly when the side face is thin -- which is to say,
    on every level-0 block and everything near the optical axis. Walking out
    from inside the top face and watching for the transition is indifferent to
    where the box landed.
    """
    length = on_top.shape[0]
    if not on_top[:RAY_START_WINDOW].any():
        return -1, 0        # the ray did not start on a top face at all

    index = 0
    gap = 0
    top_end = 0
    while index < length:
        if on_top[index]:
            gap = 0
            top_end = index + 1
        else:
            gap += 1
            if gap > RAY_GAP_TOLERANCE:
                break
        index += 1

    # The side face must begin where the top face ended, give or take the same
    # gap tolerance -- a band that starts later belongs to a different block.
    side_length = 0
    gap = 0
    started = False
    for step in range(top_end, length):
        if on_side[step]:
            started = True
            gap = 0
            side_length = step - top_end + 1
        elif started or step - top_end >= RAY_GAP_TOLERANCE:
            gap += 1
            if gap > RAY_GAP_TOLERANCE:
                break
    return top_end, side_length


def _side_ratio(box: np.ndarray, axis: np.ndarray, top: np.ndarray,
                side: np.ndarray, max_run: int,
                inset: float) -> tuple[float | None, float]:
    """Measure ``s/r_top`` for one top face by marching rays outward.

    Returns the scale-free height ratio of equation (1) and the fraction of rays
    that found a side face. Rays start ``inset`` pixels *inside* the inward-
    facing edges so they begin on the top face whatever layer 1's box enclosed,
    then march towards the optical axis, each finding its own top/side boundary.
    See :func:`_inward_samples` for why the direction is inward.

    The radius is taken per ray at that boundary rather than once at the block
    centre: on a 6 cm block the near and far ends sit at visibly different
    radii, and collapsing them first biases the height.

    The median over rays, not the mean -- a neighbour occluding half a side face
    should cost precision, not correctness.
    """
    centre = box.mean(axis=0)
    offset = centre - axis
    radius = float(np.hypot(*offset))
    if radius < 1e-6:
        return None, 0.0
    inward = -offset / radius

    samples = _inward_samples(box, centre, inward)
    if samples.size == 0:
        return None, 0.0
    # Step back along the ray, which pushes the start into the block's interior.
    samples = samples - inward[None, :] * inset

    steps = np.arange(0, max_run + 1, dtype=np.float64)
    # (rays, steps, 2) walk towards the axis along the shared radial direction.
    walk = samples[:, None, :] + inward[None, None, :] * steps[None, :, None]
    xs = np.clip(np.round(walk[:, :, 0]).astype(np.int32), 0, side.shape[1] - 1)
    ys = np.clip(np.round(walk[:, :, 1]).astype(np.int32), 0, side.shape[0] - 1)
    on_top = top[ys, xs] > 0
    on_side = side[ys, xs] > 0

    ratios = []
    for index in range(samples.shape[0]):
        top_end, side_length = _walk_ray(on_top[index], on_side[index])
        if top_end < 0 or side_length <= 0:
            continue
        boundary = samples[index] + inward * top_end
        boundary_radius = float(np.hypot(*(boundary - axis)))
        if boundary_radius < 1e-6:
            continue
        ratios.append(side_length / boundary_radius)

    support = len(ratios) / samples.shape[0]
    if not ratios or support < MIN_RAY_SUPPORT:
        return None, support
    return float(np.median(ratios)), support


def minimum_measurable_radius_px(camera_height_cm: float, block_height_cm: float,
                                 *, min_side_px: float = 2.5) -> float:
    """How far off-axis a block must sit before its side face can be measured.

    Rearranging ``s = r·h/H``: a side band of at least ``min_side_px`` needs
    ``r ≥ min_side_px·H/h``. Inside that radius the module measures nothing and
    falls back to completeness ordering, by projection rather than by choice.

    This is the module's operating envelope and it is worth checking against a
    real feed before trusting a level. Measured on the synthetic renderer at the
    working resolution, a camera framing the same build area from 32 cm and from
    42 cm both resolve levels comfortably; the band shrinks as ``h/H``, so a
    camera far enough away eventually cannot see a level at all no matter how
    many megapixels it has. Raising ``max_processing_width`` buys back the
    quantisation half of the problem but not the geometry half.
    """
    if block_height_cm is None or block_height_cm <= 0:
        raise ValueError("block_height_cm must be a positive length in cm")
    if camera_height_cm <= 0:
        raise ValueError("camera_height_cm must be a positive length in cm")
    return float(min_side_px) * float(camera_height_cm) / float(block_height_cm)


def estimate_camera_height(ratios, block_height_cm: float, *,
                           bounds: tuple[float, float] = CAMERA_HEIGHT_BOUNDS_CM,
                           steps: int = HEIGHT_SEARCH_STEPS,
                           ) -> tuple[float | None, float, float]:
    """Recover the camera height that makes every measured face a whole level.

    Each measurement gives ``h_i = H·q_i``, and physics constrains ``h_i`` to be
    ``k_i`` block thicknesses with ``k_i`` a positive integer. One unknown, many
    constraints: search ``H`` and score how close ``H·q_i/t`` lands to an
    integer. This is the same move ``block_grid.choose_lattice_model`` makes --
    fit the model the geometry allows rather than the one the data suggests.

    Returns ``(camera_height_cm, residual, confidence)``.

    Two traps, both of which cost a wrong answer on the first real capture this
    was run against, and both of which are handled here:

    **The alias.** If ``H`` explains the data with levels ``k_i`` then ``2H``
    explains it with ``2k_i``, exactly as well, for any data at all. Residual
    alone cannot choose between them, so the search takes the *smallest* height
    scoring within :data:`HEIGHT_ALIAS_TOLERANCE` of the best.

    **One bad ray ruins a mean.** The score is the **median** squared miss, not
    the mean. On the multi-level capture, five measured blocks included one
    whose side face was half occluded by its neighbour; under a root-mean-square
    score that single outlier dragged the fit to 115 cm (residual 0.22, levels
    0.81/2.73/3.12/3.16/5.68 -- not integers at all), while the median score
    recovers 39 cm with residual 0.07 and levels 0.28/0.93/1.06/1.07/1.93. The
    outlier is then rejected on its own by :data:`MAX_LEVEL_SNAP` instead of
    corrupting everything else. 39 cm is the physically right neighbourhood:
    ``rig.json`` puts the workspace at 38 cm and the frame at 35 cm.
    """
    if block_height_cm is None or block_height_cm <= 0:
        raise ValueError("block_height_cm must be a positive length in cm")
    values = np.asarray([r for r in ratios if r is not None and r > 0],
                        dtype=np.float64)
    if values.size < MIN_HEIGHT_SAMPLES:
        return None, float("inf"), 0.0

    low, high = bounds
    candidates = np.linspace(low, high, steps)
    # levels[c, i] = how many block thicknesses candidate c implies for block i.
    levels = np.outer(candidates, values) / block_height_cm
    nearest = np.clip(np.round(levels), 1.0, MAX_PLAUSIBLE_LEVEL)
    residuals = np.sqrt(np.median((levels - nearest) ** 2, axis=1))

    # Pin the scale with physics: the rig builds upward from the table, so the
    # shallowest block in view is almost always sitting ON the table, and its
    # top face is therefore exactly one block up. Requiring that collapses the
    # alias directly rather than hoping the residual will. Measured over 400
    # randomised scenes at 10% measurement noise, it roughly halves the rate of
    # grossly wrong fits (18/60 to 9/60 in the worst case tried).
    #
    # A soft constraint, not a hard one: a view cropped to the upper courses of
    # a tall build legitimately has nothing at level 0, so if no candidate can
    # satisfy it the search falls back to the residual alone.
    grounded = np.round(levels.min(axis=1)) == 1.0
    allowed = np.nonzero(grounded)[0]
    if allowed.size == 0:
        allowed = np.arange(candidates.size)

    best = float(residuals[allowed].min())
    acceptable = allowed[residuals[allowed] <= best + HEIGHT_ALIAS_TOLERANCE]
    chosen = int(acceptable[0]) if acceptable.size else int(residuals.argmin())
    height = float(candidates[chosen])
    residual = float(residuals[chosen])
    # Residual is in units of one block: 0 is a perfect stack, 0.5 is noise.
    confidence = float(np.clip(1.0 - residual / 0.5, 0.0, 1.0))
    return height, residual, confidence


# ---------------------------------------------------------------------------
# Plateaus, footprints and stacking
# ---------------------------------------------------------------------------


def _share_plateaus(blocks: list[LeveledBlock], masks: SurfaceMasks) -> int:
    """Lend a measured height to coplanar neighbours that could not measure one.

    Two top faces that are connected in the top-face mask have no side face
    between them, and a side face is the only thing that can separate two
    different heights. So they are coplanar by construction, and a block buried
    in the middle of a plateau -- which can never see its own side -- inherits
    from whichever member of its plateau could.
    """
    if not masks.split_ok:
        return 0
    count, labels = cv2.connectedComponents(masks.top)
    if count <= 1:
        return 0

    height, width = labels.shape
    groups: dict[int, list[int]] = {}
    for index, block in enumerate(blocks):
        cx, cy = block.detection.center
        x = int(round(cx * masks.scale))
        y = int(round(cy * masks.scale))
        if not (0 <= x < width and 0 <= y < height):
            continue
        label = int(labels[y, x])
        if label == 0:
            continue
        groups.setdefault(label, []).append(index)

    inherited = 0
    for members in groups.values():
        measured = [blocks[i].height_ratio for i in members
                    if blocks[i].height_ratio is not None]
        if not measured:
            continue
        shared = float(np.median(measured))
        for index in members:
            if blocks[index].height_ratio is None:
                blocks[index].height_ratio = shared
                blocks[index].inherited = True
                inherited += 1
    return inherited


def _ground_projection(box: np.ndarray, axis: np.ndarray, camera_height: float,
                       face_height: float) -> np.ndarray:
    """Equation (2): pull a raised top face back onto the ground plane.

    A block is a prism, so its top face outline and its footprint are the same
    shape in plan view -- shrinking the top face radially about the optical axis
    by ``(H−h)/H`` lands it exactly on the footprint the machine placed.
    """
    if camera_height <= 0:
        return box.astype(np.float64)
    factor = max(0.05, (camera_height - face_height) / camera_height)
    return axis + (box.astype(np.float64) - axis) * factor


def _overlap(a: np.ndarray, b: np.ndarray) -> float:
    area_a = abs(cv2.contourArea(a.astype(np.float32)))
    area_b = abs(cv2.contourArea(b.astype(np.float32)))
    smaller = min(area_a, area_b)
    if smaller <= 0:
        return 0.0
    intersection, _ = cv2.intersectConvexConvex(a.astype(np.float32),
                                                b.astype(np.float32))
    return float(intersection / smaller)


def _completeness(block: LeveledBlock) -> float:
    detection = block.detection
    return float(detection.rectangularity * detection.solidity)


def _resolve_stacks(blocks: list[LeveledBlock]) -> tuple[int, int]:
    """Group footprints into stacks and elect the block on top of each.

    Height decides when it is known. When it is not -- near the optical axis, or
    on a frame whose luminance never split -- completeness decides instead: the
    block on top is whole, and every block under it is notched by the one above.
    That fallback is the reason this stage never simply returns "unknown".
    """
    count = len(blocks)
    parent = list(range(count))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for i in range(count):
        for j in range(i + 1, count):
            if _overlap(blocks[i].ground_box, blocks[j].ground_box) >= STACK_OVERLAP:
                parent[find(i)] = find(j)

    stacks: dict[int, list[int]] = {}
    for index in range(count):
        stacks.setdefault(find(index), []).append(index)

    suppressed = 0
    for stack_id, (_root, members) in enumerate(sorted(stacks.items())):
        for index in members:
            blocks[index].stack = stack_id
        if len(members) == 1:
            continue
        # Prefer a measured height; fall back to the more complete rectangle,
        # then to the larger one. Ties on all three are a genuine coin flip.
        def rank(index: int):
            block = blocks[index]
            return (
                block.height_ratio is not None,
                block.height_ratio or 0.0,
                _completeness(block),
                block.detection.area,
            )

        winner = max(members, key=rank)
        for index in members:
            if index == winner:
                continue
            blocks[index].on_top = False
            blocks[index].covered_by = winner
            suppressed += 1
    return len(stacks), suppressed


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def detect_leveled_blocks(frame: np.ndarray, *, block_height_cm: float,
                          camera_height_cm: float | None = None,
                          axis: tuple[float, float] | None = None,
                          color_threshold: int = 8,
                          red_green_threshold: int = 3,
                          min_area: int = 500,
                          max_area: int | None = None,
                          max_processing_width: int = MAX_PROCESSING_WIDTH,
                          self_calibrate: bool = False,
                          balance: bool = False, flatten: bool = True,
                          suppress_sides: bool = True,
                          expected_size: tuple[float, float] | None = None,
                          metrics: LevelMetrics | None = None,
                          ) -> list[LeveledBlock]:
    """Detect blocks, estimate each one's level, and mark which are on top.

    ``block_height_cm`` is required and has no default on purpose: it is the
    firmware's ``BLOCK_HEIGHT_CM`` and the Pi is not allowed a second copy of
    it. Pass the value from the sketch that is actually flashed.

    ``camera_height_cm`` is what unlocks levels. Without it the function still
    measures every side face and still decides which block is on top -- that
    only needs relative sizes -- but leaves ``level``, ``height_cm`` and the
    ground projection alone. ``self_calibrate=True`` fits one from the frame
    instead; it defaults off because on real captures that fit invents levels on
    a flat board. See "Two outputs" in the module docstring.

    ``axis`` is the optical axis in full-resolution pixels, defaulting to the
    image centre. That default is correct for a fisheye-rectified frame, because
    ``fisheye.build_maps`` renders the output about the source principal point.
    A cropped or digitally zoomed feed moves it and must say so.

    ``flatten`` defaults ON here, unlike everywhere else in the codebase. The
    luminance split is a global threshold and a wide lens leaves a brightness
    gradient across the frame large enough to swamp the top/side difference; the
    detector's own segmentation has no such sensitivity. Turning it off is
    supported and will mostly cost separability.

    ``suppress_sides`` hides thick side faces from layer 1 so a stack stops
    reading as one connected blob. Default ON here because this function exists
    for stacked scenes; turn it OFF on a dense single-layer board, where it
    costs a block or two and buys nothing. See
    :data:`SIDE_MIN_HALF_THICKNESS_PX` for the numbers.
    """
    if block_height_cm is None or block_height_cm <= 0:
        raise ValueError(
            "block_height_cm is required (firmware BLOCK_HEIGHT_CM); the Pi "
            "keeps no copy of it, so the caller must supply it")

    report = metrics if metrics is not None else LevelMetrics()

    masks = split_surfaces(
        frame, color_threshold=color_threshold,
        red_green_threshold=red_green_threshold, balance=balance,
        flatten=flatten, max_processing_width=max_processing_width)
    report.separability = masks.separability
    report.split_ok = masks.split_ok

    # Layer 1, unmodified, on a frame whose side faces no longer read as warm.
    segmented = suppress_side_faces(frame, masks) if suppress_sides else frame
    detections = detect_blocks(
        segmented,
        color_threshold=color_threshold,
        red_green_threshold=red_green_threshold, min_area=min_area,
        max_area=max_area, max_processing_width=max_processing_width,
        metrics=report.detection, balance=balance, flatten=flatten,
        expected_size=expected_size)
    report.detections = len(detections)
    if not detections:
        return []

    full_h, full_w = frame.shape[:2]
    if axis is None:
        axis_full = np.array(((full_w - 1) / 2.0, (full_h - 1) / 2.0))
    else:
        axis_full = np.asarray(axis, dtype=np.float64)
    axis_work = axis_full * masks.scale

    half_diagonal = math.hypot(masks.top.shape[1], masks.top.shape[0]) * 0.5
    min_radius = half_diagonal * MIN_AXIS_RADIUS_FRACTION
    max_run = max(8, int(round(min(masks.top.shape[:2]) * 0.22)))

    blocks: list[LeveledBlock] = []
    for detection in detections:
        block = LeveledBlock(
            detection=detection,
            ground_center=detection.center,
            ground_box=detection.box.astype(np.float64),
            complete=(detection.rectangularity >= COMPLETE_RECTANGULARITY and
                      detection.solidity >= COMPLETE_SOLIDITY),
        )
        if masks.split_ok:
            box_work = detection.box.astype(np.float64) * masks.scale
            centre_work = box_work.mean(axis=0)
            if float(np.hypot(*(centre_work - axis_work))) >= min_radius:
                short_side = min(detection.width, detection.height) * masks.scale
                ratio, support = _side_ratio(
                    box_work, axis_work, masks.top, masks.side, max_run,
                    max(2.0, short_side * 0.30))
                block.height_ratio = ratio
                block.support = support
        blocks.append(block)

    report.inherited = _share_plateaus(blocks, masks)
    report.measured = sum(1 for block in blocks if block.measured)

    height = camera_height_cm
    if height is None and self_calibrate:
        height, residual, confidence = estimate_camera_height(
            [block.height_ratio for block in blocks], block_height_cm)
        report.height_residual = None if height is None else residual
        report.height_confidence = confidence
        if height is not None and confidence < MIN_HEIGHT_CONFIDENCE:
            height = None
        report.self_calibrated = height is not None
    elif height is not None:
        report.height_confidence = 1.0
    report.camera_height_cm = height

    if height is not None:
        for block in blocks:
            if block.height_ratio is None:
                continue
            face_height = height * block.height_ratio
            exact = face_height / block_height_cm
            level = int(round(exact)) - 1
            block.height_cm = face_height
            block.level_error = abs(exact - round(exact))
            if 0 <= level <= MAX_PLAUSIBLE_LEVEL and block.level_error <= MAX_LEVEL_SNAP:
                block.level = level
            block.ground_box = _ground_projection(
                block.detection.box, axis_full, height, face_height)
            block.ground_center = tuple(block.ground_box.mean(axis=0))

    report.stacks, report.suppressed = _resolve_stacks(blocks)
    return blocks


def detect_top_layer(frame: np.ndarray, *, block_height_cm: float,
                     **kwargs) -> list[BlockDetection]:
    """Detect only the blocks nothing is resting on.

    A thin wrapper over :func:`detect_leveled_blocks` returning plain
    ``BlockDetection`` values, so it is a drop-in for a caller that already
    consumes layer 1 and only wants the stack tops.

    Note that the returned detections keep their **image** geometry, not the
    ground projection -- an overlay must draw where the block appears, not where
    its footprint is. Callers that want the footprint (any caller naming a grid
    cell) must use :func:`detect_leveled_blocks` and read ``ground_center``.
    """
    blocks = detect_leveled_blocks(frame, block_height_cm=block_height_cm,
                                   **kwargs)
    return [block.detection for block in blocks if block.on_top]


def height_map(blocks, *, block_height_cm: float) -> list[dict]:
    """Summarise a detection as one entry per stack: footprint and level.

    This is the shape worth handing to the Twin. A per-cell height is something
    one overhead camera can genuinely measure; a block-by-block inventory of the
    buried layers is not, because a block hidden under a same-orientation block
    reflects no light to this camera at all. Comparing this against the planner
    catches a dropped or shifted block without ever needing to see the one
    underneath.
    """
    if block_height_cm is None or block_height_cm <= 0:
        raise ValueError("block_height_cm must be a positive length in cm")
    stacks: dict[int, LeveledBlock] = {}
    for block in blocks:
        if not block.on_top:
            continue
        stacks[block.stack] = block
    result = []
    for stack_id in sorted(stacks):
        block = stacks[stack_id]
        result.append({
            "stack": stack_id,
            "center": block.ground_center,
            "level": block.level,
            "height_cm": block.height_cm,
            "levels": None if block.level is None else block.level + 1,
            "angle": block.detection.angle,
            "measured": block.measured,
            "inherited": block.inherited,
            "support": block.support,
        })
    return result
