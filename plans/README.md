# Plans

This directory used to hold every plan, worked through one at a time then
archived. It no longer does that.

Every plan that reached "built" has been retired: its content was folded into
the hard documentation for the subsystem it describes, and the plan file was
deleted so there is exactly one place — the code and its living doc — that
describes current behaviour. Genuine reference material that had been sitting
alongside those plans (grid geometry specs, the printed-sheet detector, the
ack protocol, calibration guides) was moved out to [../docs/](../docs/)
unchanged, since it was never a plan to begin with.

| What you're looking for | Where it lives now |
| --- | --- |
| The web operator console — architecture, current state | [docs/CONSOLE.md](../docs/CONSOLE.md) |
| The 3D Build Studio — architecture, current state, changelog | [docs/STUDIO.md](../docs/STUDIO.md) |
| Grid geometry, printed sheets, calibration routes | [docs/printed-grid-spec.md](../docs/printed-grid-spec.md), [docs/printed-color-grid.md](../docs/printed-color-grid.md), [docs/cluster-calibration-grid.md](../docs/cluster-calibration-grid.md), [docs/dual-orientation-grid.md](../docs/dual-orientation-grid.md), [docs/evidence-assisted-printed-grid-calibration.md](../docs/evidence-assisted-printed-grid-calibration.md) |
| The `@`-line serial protocol | [docs/ack-protocol.md](../docs/ack-protocol.md) |
| Lens/fisheye tuning, grid capture calibration | [docs/camera-fisheye-tuning-guide.md](../docs/camera-fisheye-tuning-guide.md), [docs/grid-capture-calibration-playbook.md](../docs/grid-capture-calibration-playbook.md) |
| Designed but not yet built (placement supervision, the Studio's "wow pass") | [docs/feature-ideas.md](../docs/feature-ideas.md) |

`archive/` is untouched: two already-superseded early drafts, kept for the
detail they hold that the docs above don't repeat (exact firmware strings,
GPIO pinout, the original cable/upload bring-up).

If a new plan starts here, the same rule applies when it lands: fold what got
built into the relevant doc under `docs/`, then delete the plan rather than
letting it sit as a second, drifting description of the same code.
