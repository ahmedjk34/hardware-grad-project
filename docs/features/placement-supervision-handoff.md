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
| what the feature does, and every decision behind it | [placement-supervision.md](placement-supervision.md) |
| what was measured, what changed, and why — **20 findings and 7 decisions** | [placement-supervision-progress.md](placement-supervision-progress.md) |
| the camera's role, and the status board | [../CAMERA.md](../CAMERA.md) |
| the raw Gate 0 traces | [../measurements/](../measurements/) |

## What is actually left

- **A bench session.** Nothing here has been watched on hardware — there is no
  camera on the development desktop. That is M2's last open item.
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
