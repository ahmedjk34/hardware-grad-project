# The web operator console — living record

**What this document is.** The current, complete description of the browser
operator console as it actually exists in the repository: a React PWA talking
to a FastAPI service on the Pi, the browser successor to the desktop
click-to-build tool (`python/camera/rig_build_v1.py`, which still exists and
still works standalone). Update this file in the same commit as any change
that would surprise a reader of the code. If this file and the code disagree,
the code is right and this file is a bug.

Related: [docs/STUDIO.md](STUDIO.md) (the 3D Build Studio, which is layered on
top of this console and shares its store/components),
[docs/BLOCK-VISION.md](BLOCK-VISION.md) (the detection layers this console's
camera pipeline consumes), [AGENTS.md](../AGENTS.md) (the Pi/firmware
contract), [docs/ack-protocol.md](ack-protocol.md) (the serial protocol this
console's `/api/events` stream carries).

---

## 1. Status at a glance

**Built and tested.** All ten of the original build steps are implemented;
`npm test -- --run` is 492/492 green across 38 files (console + Studio
combined, they now share a test run); the relevant backend suites
(`pytest python/tests -k "web or link or mock_board or feeder or orchestrator"`)
are 62/62 green.

| Piece | State |
| --- | --- |
| `MockBoard` — protocol-level fake Mega | built — `python/rig/mock_board.py` |
| `MockCamera` — simulated workspace frame source | built — `python/vision/mock_camera.py`, two known test issues, see §6 |
| `ConsolePipeline` — headless capture+detect loop | built — `python/rig/console_pipeline.py` |
| FastAPI app, lifespan, state model | built — `python/web/app.py`, `state.py` |
| Command endpoints (select/level/mode/build/…) | built — `python/web/routes_command.py` |
| MJPEG stream + drawable geometry | built — `python/web/mjpeg.py`, `geometry.py` |
| React PWA shell, WebSocket state store | built — `web/src/App.tsx`, `store.ts`, `ws.ts` |
| SVG overlay, click/tap interaction | built — `web/src/components/GridOverlay.tsx`, `web/src/lib/workspace.ts` |
| Two-tap build confirm + terminal states | built — `BuildButton.tsx`, `BuildBanner.tsx`, `ResultToast.tsx` |
| Calibration in the browser | built — `python/web/routes_calibration.py`, `web/src/components/Calibrate.tsx` |

**Grown beyond the original ten steps, undocumented until now:**

- `python/web/events.py` — a durable, replayable `/api/events` history
  (`serial`, `feeder`, `build_step`, `build_result` event types with server-assigned
  ids), added to carry the ack-protocol `STEP` channel (see
  [ack-protocol.md](ack-protocol.md)).
- `python/web/progress.py` — the full build-progress state machine:
  idle → accepted → validating → running → parking → placed / rejected /
  aborted → locked.
- `routes_calibration.py` also exposes a `block/{start,step,undo,cancel,save}`
  sub-flow — placed-block self-calibration (AGENTS.md §3d-bis) driven from the
  browser, with `web/src/components/Calibrate.tsx` offering it as the first
  calibration choice. This is not in the original console design at all.
- The entire `web/src/studio/` tree (the 3D Build Studio, `docs/STUDIO.md`)
  now shares this console's store and components — `TwinPanel.tsx` and
  `RunnerPanel.tsx` on the index page, `routes/Studio.tsx` for the Studio
  route — rather than being a separate app.

---

## 2. The product

A single-page web app, installable to a phone home screen (PWA), served over
HTTPS from the Pi on the local network. Opening it shows:

- a **live camera view** of the rig's workspace (raw MJPEG), low latency, that
  never freezes the controls even if the camera stalls;
- an **SVG overlay** on that view: the machine's addressable grid, the cell
  under the cursor/finger, the currently selected cell, and any coloured
  blocks the vision code has detected;
- a **control panel**: active grid orientation (vertical / horizontal),
  whether the camera-to-rig mapping is calibrated, the selected cell and the
  exact firmware command it will send, a build-level stepper, and a **BUILD**
  button;
- a **status area**: connection state, the last build's result, a scrolling
  log of what the rig printed, and — when something has gone wrong — a
  prominent **SESSION LOCKED** banner.

**The core interaction**, unchanged from the desktop `rig_build_v1.py` this
replaced:

1. Operator taps a cell on the camera image. This **selects** it. Nothing
   moves.
2. The panel shows `B <col> <row> <level>` — the exact command.
3. Operator taps **BUILD**, then a second **CONFIRM** (two deliberate taps).
4. The server sends one correlated `FEED` to the Uno. Only its exact terminal
   staged success permits the selected `B` to be sent to the Mega. The camera
   keeps streaming throughout and every mutation stays disabled until the
   complete two-board operation settles.
5. Result: **PLACED** (green, selection clears), **REJECTED** (amber, bad
   input, nothing moved, selection kept), or **ABORTED** / timeout (red, the
   machine's physical state is unknown, session locks — a human inspects the
   rig and restarts the process; there is no software recovery, and the UI
   never offers a "retry" button).

**Explicitly not in scope:** a physical emergency-stop button or hardware
safety interlock; WebRTC or hardware video encoding; real user accounts (a
single shared secret is enough for a trusted LAN); multiple operators
coordinating simultaneously; anything autonomous (no auto-placement, no
block-detection-driven building — the operator or a compiled Studio program
chooses every target).

---

## 3. The eight facts that shape the design

1. **The Arduino goes deaf during a build.** `buildBlock()` in
   `arduino/build_test_v1/build_test_v1.ino` runs homing, Z travel and the
   servo inside one function and does not read serial while it runs. A build
   cannot be cancelled. A second command sent mid-build sits in a 64-byte
   buffer and arrives late, out of context. **One command at a time, never
   queued.**
2. **Opening the serial port reboots the board.** The board forgets
   everything on reset, including grid size and orientation, and comes back
   in `vertical` mode, un-homed. `Rig.connect()` repairs this (waits for
   `@0 READY`, re-pushes mode, re-pushes grid size). An *unexpected* reboot
   mid-session is a hard error (`RigReset`) — the claw may be holding a block.
3. **`ABORTED` and timeout lock the session.** The machine's physical state is
   unknown. `BuildController` sets `locked_reason` and refuses all further
   mutations until a human restarts the process.
4. **The safety model lives below the web layer, not in it.**
   `rig/build_controller.py`, `rig/build_job.py` and `rig/link.py` enforce:
   feeder cell `[0,0]` is never a build target, out-of-envelope cells are
   refused, only one build runs at a time, a stale camera blocks selection and
   build, an aborted build locks. The web backend reuses those modules
   unchanged and re-checks everything server-side — **the browser is never
   trusted.**
5. **There is exactly one owner of the camera and one owner of each serial
   port.** One process, one `Picamera2` object, one Mega `serial.Serial`, and
   one Uno `serial.Serial`. The FastAPI lifespan owns all three. No second
   script, reload worker, per-request connection, or board-to-board link.
6. **Calibration is optional for selection.** Without a saved
   `config/workspace_map.json`, the app still lets an operator select cells on
   an *approximate* grid computed from `config/rig.json` geometry — drawn
   amber, labelled `APPROXIMATION ONLY`. Calibration only refines the
   pixel-to-cell mapping; it is never required to place a block.
7. **There are two grids, latched by mode.** `vertical` (7 × 6 addressable,
   6 × 5 positive build cells) and `horizontal` (3 × 10 addressable, 2 × 9
   positive). `[0,0]` is the feeder in both. Switching mode changes what every coordinate means, so it
   clears any selection, and entering `horizontal` requires X/Y to be homed
   first. See AGENTS.md §3.
8. **The camera pipeline is heavy and already built.** Colour correction,
   fisheye undistortion, block detection, printed-grid detection all run
   before this console sees a frame — detection on background workers at a
   lower rate, the main loop using the last completed result. Nothing here
   reimplements any of it.

---

## 4. Architecture

```text
  ┌─────────────────────────────────────────────┐
  │  React PWA  (phone / tablet / desktop)       │
  │  - MJPEG <img> video layer                   │
  │  - SVG overlay layer (grid, hover, selection)│
  │  - WebSocket state store                     │
  │  - REST calls for every action                │
  └───────────────┬─────────────────────────────┘
                  │  HTTPS, trusted LAN, shared-secret cookie
                  ▼
  ┌─────────────────────────────────────────────┐
  │  FastAPI service on the Pi (uvicorn, 1 worker)│
  │                                               │
  │  lifespan owns ONE of each:                  │
  │   ├─ ConsolePipeline                         │
  │   │    ├─ LatestFramePump → camera source    │
  │   │    ├─ AnalysisWorker (block detection)   │
  │   │    └─ PaperGridTracker (printed grid)    │
  │   ├─ Feeder (Uno serial, or MockFeeder)       │
  │   ├─ Rig     (Mega serial, or MockBoard)      │
  │   ├─ CellOrchestrator → BuildController/Job   │
  │   └─ MJPEG encoder (encode-once, fan-out)     │
  │                                               │
  │  GET  /api/state         full snapshot        │
  │  WS   /api/events        durable replayable   │
  │                          state + serial + step │
  │  GET  /api/stream.mjpg   raw video            │
  │  POST /api/select|deselect|level|mode|view    │
  │  POST /api/build         (echoes command)     │
  │  POST /api/calibration/* (corners / sheet /   │
  │                            placed-block)      │
  └───────────────┬───────────────┬──────────────┘
                  ▼               ▼
           CSI camera       USB serial → Uno feeder
        (or MockCamera)     USB serial → Mega gantry
```

**Backend modules** (`python/`):

| Module / symbol | What it owns |
| --- | --- |
| `vision/camera_source.py` → `LatestFramePump`, `open_camera(backend, …)` | non-blocking capture; backends `"auto"`, `"picamera2"`, `"v4l2"`, `"mock"` |
| `vision/analysis_worker.py` → `AnalysisWorker` | async block detection off the main loop |
| `camera/gridded_camera_feed.py` → `PaperGridTracker` | async printed-grid detection |
| `rig/build_controller.py` → `BuildController` | selection, level, mode-cycle, the one safety gate every mutation goes through |
| `rig/build_job.py` → `BuildJob` | one-build-at-a-time worker thread |
| `rig/feeder.py` → `Feeder` | protocol-2 Uno client, READY identity validation, correlated terminal results |
| `rig/orchestrator.py` → `CellOrchestrator` | serializes the pickup resource: staged Uno success first, then Mega `B` |
| `rig/link.py` → `Rig`, `BuildResult` | the serial protocol client; `str(result)` ∈ `{"placed","rejected","aborted"}` |
| `rig/workspace.py` → `WorkspaceMap` | pixel ↔ cell math; `.cell_at()`, `.target_polygon()`, `.from_grid()`, `.save()` |
| `rig/mock_board.py` → `MockBoard` | protocol-level fake Mega, promoted from the old test-only `FakeSerial` |
| `rig/mock_feeder.py` → `MockFeeder` | protocol-2 fake Uno with failure/reset/disconnect/cancel controls |
| `vision/mock_camera.py` → `MockCamera` | renders blocks at real grid cells plus a printed-lattice stand-in, so detection is exercisable off the Pi |
| `rig/console_pipeline.py` → `ConsolePipeline`, `ProcessedFrame` | the headless capture+detect loop; owns exactly one camera, applies orientation then colour correction exactly once, does **not** own a serial `Rig` |
| `web/app.py` | FastAPI app factory, one-owner lifespan, `GET /api/state`, `WS /api/events` |
| `web/state.py` | Pydantic snapshot model |
| `web/routes_command.py` | select / select-axis / deselect / level / mode / view / build, all guarded through `BuildController` |
| `web/routes_calibration.py` | corner calibration, printed-sheet calibration, and the placed-block calibration sub-flow |
| `web/mjpeg.py` | one latest-JPEG slot shared across clients, no encoding while nobody is subscribed |
| `web/geometry.py` | cached grid polygons + current selection/detection geometry for `StateModel` |
| `web/events.py` | durable, replayable `/api/events` history (`serial`, `feeder`, `build_step`, `build_result`) |
| `web/progress.py` | the idle→accepted→validating→running→parking→placed/rejected/aborted→locked state machine |

**Frontend modules** (`web/src/`): `App.tsx`, `store.ts` (client state store),
`ws.ts` (reconnecting WebSocket with a `?after=` replay cursor), `api.ts` (REST
calls), `consoleStore.ts`; components `GridOverlay.tsx`, `BuildButton.tsx`,
`BuildBanner.tsx`, `ResultToast.tsx`, `Calibrate.tsx`, `CameraView.tsx`,
`ControlPanel.tsx`, `StatusBar.tsx`, `RigLog.tsx`, `ModeSwitch.tsx`,
`LevelStepper.tsx`, `LockedBanner.tsx`; `lib/workspace.ts` — the TypeScript
port of `WorkspaceMap.cell_at()` / `.target_polygon()` used for the local
hover highlight (the server's Python `cell_at()` stays authoritative for what
is actually selected — the browser is never trusted, per §3 fact 4).

---

## 5. Running it

```bash
cd python && ../.venv/bin/python -m web              # backend, real hardware
cd python && ../.venv/bin/python -m web --mock        # backend, no Pi/Arduino/camera needed
cd web && npm run dev                                 # frontend dev server, proxies /api to :8000
cd web && npm test -- --run                            # the gate; console + Studio, must be green
```

See [docs/server-guide.md](server-guide.md) for prerequisites, configuration
checks and day-to-day operation.

---

## 6. Known issues

- `python/tests/mock_camera_test.py` has two failures under load, both
  isolated to the mock camera, neither a console regression:
  - a freeze/pump race — one source frame can arrive after
    `MockCamera.freeze()` before the pump observes the freeze;
  - `test_warm_mock_blocks_are_detected_at_their_real_grid_cells` can report
    1 detection instead of `>=2` for two same-colour red blocks.
- The ack-protocol `STEP`/`RECV`/`SAFE`/`HELD` lines this console's
  `/api/events` stream depends on have been compile-checked and verified
  byte-for-byte on a host build, but **never flashed to real hardware** — see
  [ack-protocol.md](ack-protocol.md).
