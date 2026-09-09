"""The camera's ONE job at the feeder cell: is a block staged there right now?

This is deliberately **not** part of placement supervision. :mod:`rig.supervisor`
strips every detection near :data:`~rig.supervisor.FEEDER_CELL` before a verdict
is formed — a hand-fed block is the feeder, never ``FOREIGN``. This module is the
other half: a single-purpose, fail-closed read of whether the operator has put a
block on the feeder, so an autonomous RUN can close the claw without a human tap
(``docs/features/placement-supervision-handoff.md`` / AGENTS.md §2a).

It answers **presence only** — never alignment. ``feeder_has_block`` returning
``True`` means "something block-shaped is within
:data:`~rig.supervisor.FEEDER_RADIUS_CM` of the feeder centre", nothing more; a
corner-fed or skewed block still reads present. Every uncertainty — no map, no
vision, a stale frame, a frame that cannot be projected — returns
``(False, why)``, so a caller that acts on ``True`` alone can only ever close the
claw on evidence, never on the absence of it.
"""

from __future__ import annotations

import math

from rig.supervisor import FEEDER_RADIUS_CM, _feeder_centre_cm, point_cm


def feeder_has_block(frame) -> tuple[bool, str]:
    """``(present, reason)`` for the current pipeline frame. Fails CLOSED.

    ``frame`` is a :class:`rig.console_pipeline.ProcessedFrame` (or ``None``).
    The reason is always a short human sentence: an operator seeing
    "camera frame is stale" versus "no block detected at the feeder" does
    different things about it.
    """
    if frame is None:
        return False, "no camera frame yet"
    if not bool(getattr(frame, "calibrated", False)):
        return False, "no calibrated workspace map — the feeder cannot be located"
    if not bool(getattr(frame, "analysis_ok", True)):
        return False, "vision is not returning a usable reading"
    if bool(getattr(frame, "stale", False)):
        return False, "camera frame is stale"

    workspace = getattr(frame, "workspace", None)
    feeder = _feeder_centre_cm(workspace)
    if feeder is None:
        return False, "workspace map carries no physical grid"
    # The physical feeder is the machine home corner (the VERTICAL grid's
    # [0,0]) in BOTH modes — in horizontal mode it is NOT horizontal [0,0],
    # which sits +1.9 cm out. `_feeder_centre_cm` returns the right point.
    fx, fy = feeder

    image_size = getattr(frame, "image_size", None)
    nearest: float | None = None
    for detection in getattr(frame, "detections", ()) or ():
        centre = getattr(detection, "center", None)
        if centre is None:
            continue
        cm = point_cm(workspace, centre, image_size)
        if cm is None:
            continue
        distance = math.hypot(cm[0] - fx, cm[1] - fy)
        if nearest is None or distance < nearest:
            nearest = distance

    if nearest is not None and nearest <= FEEDER_RADIUS_CM:
        return True, f"block staged {nearest:.1f} cm from the feeder centre"
    return False, "no block detected at the feeder"
