#!/usr/bin/env python3
"""Where a block sits relative to its planned cell, from the detection's own box.

Pure interval arithmetic — no camera, no numpy, no rig. Supervision's
``DISPLACED`` localisation and the CORRECTION action's pick offset both want the
same thing: given a block's measured centre and footprint in the map's
``(u,v)*workspace_cm`` frame, **how far is it off the cell the plan put it on,
along which axis, and is the reading trustworthy enough to act on.**

Why this is separable
---------------------
The grid's footprints are axis-aligned and the deliberate gaps between them are
axis-aligned strips, so every question here is answered **one axis at a time**
with 1-D overlap — the same footing :func:`rig.workspace._slot_containing`
already uses. A block we are willing to touch is axis-aligned to within
``ANGLE_TOLERANCE_DEG`` (``P`` rotates the claw to the *mode* rotation, not the
block's), so modelling it as an axis-aligned interval of the nominal block
length loses nothing a correction could have used.

What replaces the centroid-in-polygon test
-----------------------------------------
The old ``DISPLACED`` question was "did the centroid pixel land in the gap
polygon" — a binary that carried no magnitude and no confidence. Here the block
is split along each axis into the part over its **planned footprint**, the part
over the **gap**, the part over the **neighbour footprint** it drifted toward,
and any part **beyond** that. A clean single-cell displacement puts everything
in the first three and ``beyond`` at zero; a non-zero ``beyond`` means the thing
reaches further than one displacement can explain — two blocks, a merged blob,
or a shift — and is not a correction.

Sign convention (AGENTS.md Rule 0 / 0a): every cm here is a magnitude from the
axis' home switch, ``+`` away from home. A displacement is ``observed −
planned``, so a block farther from home than its cell yields a positive
component — the exact frame :func:`rig.placement_check.correction_offset`
returns, so the two never need reconciling.
"""

from __future__ import annotations

from dataclasses import dataclass

Interval = tuple[float, float]


def overlap_1d(a: Interval, b: Interval) -> float:
    """Length of the intersection of two intervals, never negative."""
    lo = max(a[0], b[0])
    hi = min(a[1], b[1])
    return hi - lo if hi > lo else 0.0


def span(centre: float, length: float) -> Interval:
    """The interval a block of ``length`` centred at ``centre`` occupies."""
    half = length / 2.0
    return (centre - half, centre + half)


def _axis_deviation_deg(angle_deg: float) -> float:
    """How far ``angle_deg`` is from the nearest grid axis, in [0, 45].

    A duplicate of :func:`rig.placement_check.axis_deviation_deg` kept here so
    this module has no dependency on that one — the rectangle's four
    0/90/180/-90 orientations are equivalent, so the test is "near any multiple
    of 90 degrees", not "near zero".
    """
    return abs((angle_deg + 45.0) % 90.0 - 45.0)


@dataclass(frozen=True)
class AxisCoverage:
    """One axis of a block's placement, split against its planned cell.

    ``origin + gap + neighbour + beyond == block_len`` by construction. The
    first three are the anatomy of a single-cell displacement; ``beyond`` is the
    part of the block that overlaps neither its cell, the gap, nor the one
    neighbour it drifted toward — the signal that the reading is not a lone
    block one displacement off its site.
    """

    axis: str
    #: ``+1`` the block drifted away from home, ``-1`` toward it, ``0`` centred.
    direction: int
    #: Signed centre offset, ``observed − planned``. ``+`` away from home.
    displacement: float
    block_len: float
    origin: float
    gap: float
    neighbour: float
    beyond: float

    @property
    def accounted(self) -> float:
        """``origin + gap + neighbour`` — everything but :attr:`beyond`."""
        return self.origin + self.gap + self.neighbour

    @property
    def on_site_fraction(self) -> float:
        """Fraction of the block still over its planned footprint, in [0, 1]."""
        return self.origin / self.block_len if self.block_len else 0.0


def axis_coverage(*, observed_centre: float, planned_centre: float,
                  block_len: float, gap_len: float, pitch: float,
                  epsilon: float = 1e-6) -> AxisCoverage:
    """Split a block's extent on one axis against its planned cell.

    ``planned_centre`` is the map lattice centre of the cell the block belongs
    on, on this axis; ``observed_centre`` is where the detection's centre landed.
    ``block_len`` / ``gap_len`` / ``pitch`` are the mode's geometry for this
    axis (``pitch == block_len + gap_len``). Everything is cm, magnitude space.

    The neighbour and gap spans are taken on whichever side the block actually
    drifted, so a block nudged toward home is split the same way as one nudged
    away. A cell at the edge of the grid has no neighbour on one side; this
    function still computes the intervals — bounds are the caller's job.
    """
    d = observed_centre - planned_centre
    direction = 0 if abs(d) <= epsilon else (1 if d > 0 else -1)
    toward = direction or 1

    extent = span(observed_centre, block_len)
    origin_fp = span(planned_centre, block_len)
    neighbour_centre = planned_centre + toward * pitch
    neighbour_fp = span(neighbour_centre, block_len)

    inner_edge = planned_centre + toward * (block_len / 2.0)
    outer_edge = neighbour_centre - toward * (block_len / 2.0)
    gap_span = (min(inner_edge, outer_edge), max(inner_edge, outer_edge))

    origin = overlap_1d(extent, origin_fp)
    gap = overlap_1d(extent, gap_span)
    neighbour = overlap_1d(extent, neighbour_fp)
    beyond = max(0.0, block_len - origin - gap - neighbour)

    return AxisCoverage(axis="", direction=direction, displacement=d,
                        block_len=block_len, origin=origin, gap=gap,
                        neighbour=neighbour, beyond=beyond)


def displacement_cm(observed_centre_cm: tuple[float, float],
                    planned_centre_cm: tuple[float, float]) -> tuple[float, float]:
    """``observed − planned`` in map cm — the same vector as ``correction_offset``.

    Provided so supervision and the CORRECTION action name the displacement the
    same way. Magnitude space, ``+`` away from each home switch.
    """
    return (observed_centre_cm[0] - planned_centre_cm[0],
            observed_centre_cm[1] - planned_centre_cm[1])


def residual_cm(observed_centre_cm: tuple[float, float],
                planned_centre_cm: tuple[float, float]) -> float:
    """Straight-line cm from a block's observed centre to its planned cell centre.

    ``hypot`` of :func:`displacement_cm` — the single "how far off" number.
    Supervision publishes it for a MOVED / DISPLACED verdict as an ADVISORY
    field; it never gates a correction (that is
    :func:`consistency` + :func:`corridor_clear`).
    """
    dx, dy = displacement_cm(observed_centre_cm, planned_centre_cm)
    return (dx * dx + dy * dy) ** 0.5


def drift_axis(cov_x: AxisCoverage, cov_y: AxisCoverage) -> str:
    """Which axis carries the displacement — ``"x"`` or ``"y"``.

    A single-cell displacement is essentially 1-D: the block slid along one
    machine axis into the gap beside it. This names that axis so the caller
    checks the right neighbour's occupancy and descent corridor.
    """
    return "x" if abs(cov_x.displacement) >= abs(cov_y.displacement) else "y"


@dataclass(frozen=True)
class Consistency:
    """Whether a detection is a lone axis-aligned block, one displacement off.

    ``ok`` gates whether supervision may publish a *correctable* displacement.
    ``reason`` is always a sentence — the affirmative one for the log, the
    negative one for the operator, verbatim.
    """

    ok: bool
    reason: str
    #: The worst ``beyond`` across the two axes — cm of block that no single
    #: displacement explains. Zero for a clean read.
    beyond_cm: float
    #: How far the block is rotated off the grid, in degrees.
    angle_off_deg: float
    #: ``max`` absolute size disagreement against the nominal block, in cm.
    size_error_cm: float


def corridor_clear(cov: AxisCoverage, *, neighbour_occupied: bool,
                   gap_len: float, jaw_clearance_cm: float) -> tuple[bool, str]:
    """Is there room to lower a jaw between the block and the cell it drifted into.

    Only the **drift axis** matters — that is the direction the block has closed
    the gap on a neighbour. If that neighbour is empty there is nothing for the
    descending jaw to foul, at any displacement (`consistency` still caps how
    far the block may reach). If the neighbour is occupied, the still-open part
    of the gap, ``gap_len − cov.gap``, must be at least ``jaw_clearance_cm``;
    once the block's edge is inside that margin — or inside the neighbour
    footprint itself — the jaw shoves the neighbour instead of gripping.

    This is what the fixed ``1.2 cm`` ceiling was a blunt proxy for. It never
    checked whether the neighbour was actually there.
    """
    if not neighbour_occupied:
        return True, ""
    if cov.neighbour > 0:
        return (False, "the block overlaps an occupied neighbour cell — "
                       "clear it by hand")
    open_gap = gap_len - cov.gap
    if open_gap < jaw_clearance_cm:
        return (False, f"only {open_gap:.2f} cm of gap is open to an occupied "
                       f"neighbour — no room for the jaw; clear it by hand")
    return True, ""


def consistency(*, cov_x: AxisCoverage, cov_y: AxisCoverage,
                measured_size_cm: tuple[float, float],
                nominal_size_cm: tuple[float, float], angle_deg: float,
                size_tolerance_cm: float, angle_tolerance_deg: float) -> Consistency:
    """Is this one straight block, one displacement off its cell?

    Three ways it is not, each its own sentence:

    * **wrong size** — the detected rectangle is not a block. Two blocks read as
      one merged blob, a partial read is a fragment. ``measured_size_cm`` and
      ``nominal_size_cm`` are both ``(long, short)``.
    * **reaches past the neighbour** — a non-zero ``beyond`` on either axis: the
      block overlaps more than its cell, the gap and one neighbour, so "one
      block, one displacement" cannot be the whole story (a shift, or a second
      block).
    * **rotated** — more than ``angle_tolerance_deg`` off the nearest grid axis.
      Grid-aligned jaws cannot grip it; it is a hand-straighten, not a claw job.
    """
    long_err = abs(measured_size_cm[0] - nominal_size_cm[0])
    short_err = abs(measured_size_cm[1] - nominal_size_cm[1])
    size_error = max(long_err, short_err)
    beyond = max(cov_x.beyond, cov_y.beyond)
    angle_off = _axis_deviation_deg(angle_deg)

    if size_error > size_tolerance_cm:
        return Consistency(
            False,
            f"the detected shape is {measured_size_cm[0]:.1f}x"
            f"{measured_size_cm[1]:.1f} cm, not a {nominal_size_cm[0]:.1f}x"
            f"{nominal_size_cm[1]:.1f} cm block — two blocks, or a partial read",
            beyond, angle_off, size_error)
    if beyond > size_tolerance_cm:
        return Consistency(
            False,
            f"the block reaches {beyond:.2f} cm past its neighbour cell — more "
            f"than a single displacement can account for",
            beyond, angle_off, size_error)
    if angle_off > angle_tolerance_deg:
        return Consistency(
            False,
            f"the block is rotated {angle_off:.0f} deg off the grid; straighten "
            f"it by hand",
            beyond, angle_off, size_error)
    return Consistency(
        True,
        f"one axis-aligned block, {cov_x.displacement:+.2f} cm X / "
        f"{cov_y.displacement:+.2f} cm Y off its cell",
        beyond, angle_off, size_error)
