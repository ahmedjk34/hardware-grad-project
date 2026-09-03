# Feature ideas — the software around the rig

A catalogue of everything worth building on top of the gantry, sorted by what it
costs and what it buys. The rig itself already works: a block gets picked from
the feeder and placed at `B <col> <row> <level>`. Everything here is about
making that capability *legible, planned, verified and impressive*.

The headline item — the **3D Build Studio** — has its own full plan at
[plans/plan-4-3d-build-studio.md](../plans/plan-4-3d-build-studio.md).
Visual language for all of it is in [DESIGN.md](DESIGN.md).

---

## Tier 0 — already supported by the backend, absent from the UI

These cost hours, not days. Every endpoint listed exists and is tested; the
browser simply does not call it.

| # | Feature | What already exists |
| --- | --- | --- |
| 0.1 | **Rig serial log panel** — every line the Mega prints, terminal-styled, `@`-ack lines highlighted | `app.py` broadcasts `{"type":"log","line":…}` on `/api/events`; `web/src/ws.ts` discards it |
| 0.2 | **Overlay view toggles** — grid / detections / printed sheet / overlay | `POST /api/view`, mirrored in `state.views` |
| 0.3 | **Grid mode switch in the browser** — vertical ⇄ horizontal | `POST /api/mode`; needs a confirm step, it homes X/Y first |
| 0.4 | **Camera freshness meter** — `LIVE 42 ms` / `STALE` / `WAITING` | `state.camera`, `state.camera_age_ms` |
| 0.5 | **Direct level entry** instead of only `+`/`−` | `POST /api/level` accepts `{value}` |
| 0.6 | **Axis select** — pick a column and row numerically when the camera tap is imprecise or the gantry occludes the cell | `POST /api/select/axis` |
| 0.7 | **Keyboard control** — arrows nudge the cell, `+`/`−` level, `B` arms, `Enter` confirms, `Esc` deselects | pure client work over existing routes |

Do these first. They make the console look finished before a single new
backend line is written.

---

## Tier 1 — the flagship: design, plan, build, verify

### 1.1 The 3D Build Studio  ★ headline

A real 3D modelling environment in the browser. Dark space, orbit with the
mouse, the machine's own lattice on the floor, click to drop an actual 3D block,
stack on top of it, switch orientation and watch the lattice re-form live, shift
the grid live, save models to a library.

Under the hood every model is nothing but an ordered list of
`B <col> <row> <level>` commands separated by `R` / `RR` mode latches — which is
exactly why this is tractable: the hard part is a viewer, not a robot.

Full specification: [plans/plan-4-3d-build-studio.md](../plans/plan-4-3d-build-studio.md).

### 1.2 The live digital twin

The same 3D engine, read-only, sitting **next to the camera on the index page**.
As the rig places each block the twin fills in, the next target pulses, and the
remaining plan shows as ghosts. Real workspace and virtual workspace, side by
side, in step. This is the single most impressive thing a demo can show.

Part of Plan 4 (milestone M6) because it must share the engine.

### 1.3 Plan projection onto the live camera  ★ sleeper hit

You already have a homography from workspace cells to camera pixels
(`WorkspaceMap.target_polygon`, used by `web/geometry.py`). Feed the *planned*
model through it and draw the plan superimposed on the real video: the next
block glowing in the exact place it will physically land, and the rest of the
design faintly behind it. Near-AR, on hardware you already own, with maths that
is already written and tested.

### 1.4 Placement supervision  ★ now has a full plan

After each `PLACED`, compare the detections against the cell the model expected
to fill: `VERIFIED`, `NOT DETECTED`, `UNEXPECTED BLOCK AT [c,r]`. Run the same
check continuously while the rig is idle and it also catches a **human moving
or removing a block** — the board stops matching the plan, and the console says
which cell.

This closes the loop between the vision pipeline and the motion system, the most
defensible engineering claim in the project, and it reuses the existing lattice
labelling with no new detector and no extra frames.

Full specification: [plans/placement-supervision.md](../plans/placement-supervision.md).

### 1.5 Colour-aware planning and feeder prompts

Detections already carry a colour name. Let a model assign a colour per block,
then have the console tell the operator which block to load next:
**`FEED: RED`**, with the count remaining per colour. Turns a manual feeder into
a guided one without touching the hardware.

### 1.6 Build execution runner

Given a compiled model, step through it: current command, blocks placed / total,
elapsed and estimated remaining from measured cycle time, per-block confirm or
continuous run, and a clean resume point if a build is rejected. The safety
rules do not change — one command at a time, never queued.

---

## Tier 2 — credibility and polish

| # | Feature | Why it earns its place |
| --- | --- | --- |
| 2.1 | **Session timeline** — every build with timestamp, command, result, duration and a camera thumbnail at completion | Becomes the evidence section of the written report |
| 2.2 | **Time-lapse export** — save a JPEG on every `PLACED`, stitch to GIF/MP4 | Frames already flow through the pipeline; near-free, enormous demo value |
| 2.3 | **Telemetry strip** — builds today, placed/rejected/aborted counts, mean cycle time, camera FPS, socket round-trip | Makes the console feel instrumented rather than decorative |
| 2.4 | **Diagnostics page** — serial port, board FQBN, camera settings in force, calibration age, workspace-map presence, self-test | The page you open when a demo misbehaves in front of an examiner |
| 2.5 | **SIMULATION badge** — the console already runs `--mock` with no hardware; say so unmistakably on screen | Lets you rehearse and present with zero risk, honestly labelled |
| 2.6 | **Audio and haptic result cues** — distinct tones for placed / rejected / locked, `navigator.vibrate` on phones | The operator is looking at the rig, not the screen. This is real usability |
| 2.7 | **Calibration wizard** — stepped four-corner flow with progress, preview and a saved-calibration timestamp | Replaces a row of bare buttons with something an examiner can follow |
| 2.8 | **Control arbitration** — one operator "holds" the rig, others are view-only | Listed as *later* in Plan 3; cheap to fake convincingly, good safety story |
| 2.9 | **Run report export** — Markdown/PDF of a session: model, commands, results, timings, photos | Straight into the thesis appendix |
| 2.10 | **QR code on screen** to open the console on a phone | Two lines of code, always impresses |
| 2.11 | **Kiosk mode** — fullscreen, no chrome, for a tablet mounted at the rig | Makes the installation look like a product |
| 2.12 | **E-stop status surface** — the hardware interlock is deferred; display `E-STOP: NOT FITTED` honestly, and require the operator to hold the button for unattended runs | Honesty about a known gap reads as engineering maturity, not weakness |

---

## Deliberately not doing

- **Cancel / retry controls.** The firmware is deaf during a build and an
  aborted session has no software recovery. Any button implying otherwise is a
  lie about the machine.
- **Autonomous block-to-target decisions.** Out of scope for Plan 3 and Plan 4
  alike; the operator or a compiled plan chooses every target.
- **Cloud anything.** The Pi serves this over LAN with no guaranteed internet.
  No CDN assets, no remote APIs, no telemetry leaving the bench.
