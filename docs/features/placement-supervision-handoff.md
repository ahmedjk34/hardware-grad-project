# Handoff prompt — placement supervision — **COMPLETE, do not run**

This was a prompt to be copied into a fresh agent session. **The work it
describes is done**, so its "state of play" is now wrong in every line: it says
M2 is unwired and M3a/M3b are not started, and all three have landed.

It is kept as a stub rather than deleted so that a link to it does not rot, and
because the repo's rule is that a second, drifting description of built code is
worse than none.

**Go here instead:**

| For | Read |
| --- | --- |
| what the feature does, and every decision behind it | [placement-supervision.md](placement-supervision.md) — §2c is the 2026-09-07 geometry layer |
| what was measured, what changed, and why — **25 findings and 7 decisions** | [placement-supervision-progress.md](placement-supervision-progress.md) — §2b is the 2026-09-07 pass |
| the detector, its `include_rejected` intake and `own_size` | [../BLOCK-VISION.md](../BLOCK-VISION.md) §2 |
| the CORRECTION gate (no more `1.2 cm` ceiling) | [correction-action.md](correction-action.md) |
| the camera's role, and the status board | [../CAMERA.md](../CAMERA.md) |
| the raw Gate 0 traces | [../measurements/](../measurements/) |

## What is actually left

- **A bench session.** Nothing here has been watched on hardware — there is no
  camera on the development desktop. That is M2's last open item, and the
  2026-09-07 camera-path changes add to it.
- **The off-lattice shape gate** (F24) and **`PLACEMENT_DRIFT`** (F25) —
  proposed, not built.
- **Stage 15 Stage B** — `SIZE_TOLERANCE_CM`, `JAW_CLEARANCE_CM`,
  `PAIRING_BEYOND_CM` are provisional constants awaiting bench measurement.
- **Gate 0b** — the per-cell change threshold that would let the per-build check
  confirm a placement at level 1 or 2 instead of reporting `unconfirmed`
  (finding F17).
- **M4** — bounded automatic repair. Deliberately off: *a machine that re-places
  a block a human just deliberately removed is infuriating*, and there is still
  no way to tell the two apart.
- **M5** — lifting the level-3 detection ceiling, via
  [camera-parallax-and-levels.md](camera-parallax-and-levels.md).
- **F10 / P5** — `test_grid.py`'s `zGoPickup()` check, a firmware/AGENTS.md
  paired value. Out of this feature's scope, and the user's own change.
