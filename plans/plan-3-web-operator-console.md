# Plan 3 — Web operator console

**One-line goal.** Turn `python/camera/rig_build_v1.py` — the desktop
click-to-build camera app — into a browser app: a React PWA that runs on a phone
or tablet, talking to a FastAPI service on the Raspberry Pi. Same capability as
today (look at the rig through the camera, click a grid cell, confirm, a block is
placed there), but the operator is holding a phone instead of sitting at the Pi's
keyboard, and every safety rule is enforced on the server.

This document is written to be executed by someone (or something) that has **not**
read the rest of the repo. It over-explains on purpose. Read *The final goal* and
*Mental model* first; they are the context every step assumes.

---

## Contents

1. The final goal
2. Mental model — the eight facts that shape everything
3. What already exists (do not rebuild these)
4. Decisions locked for this plan
5. Architecture
6. The development rule: tests first
7. The steps
   - Step 1 — Ship the fake board (`MockBoard`)
   - Step 2 — Mock camera with a simulated workspace
   - Step 3 — Extract the headless pipeline
   - Step 4 — FastAPI skeleton, lifespan, state model
   - Step 5 — Command endpoints, all guarded on the server
   - Step 6 — Raw MJPEG stream + drawing geometry in the state
   - Step 7 — React PWA shell
   - Step 8 — Overlay + interaction layer (TypeScript port of the cell math)
   - Step 9 — Two-step build + every terminal state in the UI
   - Step 10 — Calibration in the browser
8. Wiring and deployment notes
9. Later, not now
10. Order of work

---

## 1. The final goal

**The product.** A single-page web app, installable to a phone home screen
(PWA), served over HTTPS from the Pi on the local network. When you open it you
see:

- a **live camera view** of the rig's workspace, low latency, that never freezes
  the controls even if the camera stalls;
- an **overlay** on that view showing the machine's addressable grid, the cell
  the cursor/finger is over, the currently selected cell, and any coloured
  blocks the vision code has detected;
- a **control panel**: which grid orientation is active (vertical / horizontal),
  whether the camera-to-rig mapping is calibrated, the selected cell and the
  exact firmware command it will send, a build-level stepper, and a big **BUILD**
  button;
- a **status area**: connection state, the last build's result, a scrolling log
  of what the rig printed, and — when something went wrong — a prominent
  **SESSION LOCKED** banner.

**The core interaction (unchanged from `rig_build_v1.py`):**

1. Operator taps a cell on the camera image. This **selects** it. Nothing moves.
2. The panel shows `B <col> <row> <level>` — the exact command.
3. Operator taps **BUILD**, then a second **CONFIRM** (two deliberate actions).
4. The server sends the command to the Arduino, which performs a ~40-second
   pick-and-place. The camera keeps streaming the whole time; every control is
   disabled until the rig reports back.
5. Result: **PLACED** (green, selection clears), **REJECTED** (amber, bad input,
   nothing moved, selection kept), or **ABORTED / timeout** (red, the machine
   state is unknown, session locks, a human must go look and restart the
   service).

**What "done" means for this plan.** All ten steps complete. You can run the
whole thing on a development machine with **no Pi and no Arduino** using
`--mock`, drive every one of those outcomes, and see the UI respond correctly.
On the Pi, with the real camera and board, the same app places a real block.
There is a strong automated test suite (pytest for the backend, Vitest for the
frontend) and it was written test-first.

**Explicitly NOT in this plan:** the physical emergency-stop button and any
hardware safety interlock (deferred by an explicit decision — see *Later*);
WebRTC or hardware video encoding; real user accounts (a single shared secret is
enough for a trusted LAN); multiple operators coordinating; anything autonomous
(no auto-placement, no block-detection-driven building).

---

## 2. Mental model — the eight facts that shape everything

A weaker model will get this wrong unless it internalises these first. Every step
below assumes them.

1. **The Arduino goes deaf during a build.** `buildBlock()` in
   `arduino/build_test_v1/build_test_v1.ino` runs homing, Z travel and the servo
   inside one function and does not read serial while it runs. You cannot cancel
   a build. A second command sent during a build sits in a 64-byte buffer and
   arrives late and out of context. **One command at a time, never queue.**

2. **Opening the serial port reboots the board.** Normal USB behaviour. The
   board forgets everything on reset — including its grid size and which
   orientation it is in — and comes back in `vertical` mode, un-homed. The
   `Rig.connect()` handshake repairs this (waits for `@0 READY`, re-pushes mode,
   re-pushes grid size). An *unexpected* reboot mid-session is a hard error
   (`RigReset`): the board has forgotten its state and the claw may be holding a
   block.

3. **`ABORTED` and timeout lock the session.** They mean the machine's physical
   state is unknown. `BuildController` sets `locked_reason` and refuses all
   further mutations. There is **no software recovery** — a human inspects the
   rig and restarts the process. The UI must never offer a "retry" button.

4. **The safety model already exists and it is not in the UI.**
   `rig/build_controller.py`, `rig/build_job.py` and `rig/link.py` enforce:
   feeder cell `[0,0]` is never a target, out-of-envelope cells are refused,
   only one build runs at a time, a stale camera blocks selection and build, an
   aborted build locks. `rig_build_v1.py` adds only a call to
   `reject_mutation_if_unsafe()` before each mutation. **The web backend reuses
   those three modules unchanged and re-checks everything server-side. The
   browser is never trusted.**

5. **There must be exactly one owner of the camera and one owner of the serial
   port.** One process, one `Picamera2` object, one `serial.Serial`. This is why
   the FastAPI service runs with a single worker and holds both as a singleton.
   No second script, no reload worker, no per-request connection.

6. **Calibration is optional for selection.** `config/workspace_map.json` does
   not exist in this checkout. Without it, `rig_build_v1.py` still lets you
   select cells on an *approximate* grid computed from `config/rig.json`
   geometry — it just draws it amber and labels it `APPROXIMATION ONLY`. The web
   app keeps that behaviour: it works uncalibrated, and calibration refines the
   pixel-to-cell mapping.

7. **There are two grids, latched by mode.** `vertical` (blocks standing,
   6 columns × 5 rows of real build cells) and `horizontal` (blocks lying down,
   2 columns × 10 rows). Coordinate `[0,0]` is the feeder in both. Switching
   mode changes what every coordinate means, so it clears any selection.
   Entering `horizontal` requires X/Y to be homed first. See `AGENTS.md` §3.

8. **The camera has heavy per-frame processing already built.** Colour
   correction, fisheye undistortion, block detection, printed-grid detection.
   Detection runs on background workers at a lower rate; the main loop uses the
   last completed result. Do not re-implement any of this — reuse the pipeline.

---

## 3. What already exists (do not rebuild these)

| Capability | Module / symbol | Key API |
| --- | --- | --- |
| Non-blocking capture thread | `vision/camera_source.py` → `LatestFramePump` | `.start()`, `.snapshot() → FrameSnapshot(frame, captured_at, sequence, error)`, `.stop() → bool` |
| Frame source interface | same file → `V4L2Source`, `Picamera2Source` | `.read() → (ok, bgr_frame)`, `.size`, `.name`, `.apply(settings)`, `.release()` |
| Backend selector | same file → `open_camera(backend, size, device, controls)` | backends `"auto"`, `"picamera2"`, `"v4l2"` — **you will add `"mock"`** |
| Async block detection | `vision/analysis_worker.py` → `AnalysisWorker(detect_blocks, max_hz=10)` | `.submit(frame, seq, generation, color_threshold=, min_area=)`, `.snapshot() → AnalysisSnapshot` |
| Async printed-grid detection | `camera/gridded_camera_feed.py` → `PaperGridTracker` | `.submit(frame, seq, gen)`, `.poll(gen)`, `.calibration`, `.status()` |
| Build safety state | `rig/build_controller.py` → `BuildController(rig, level=0)` | `.select(cell)`, `.clear_selection()`, `.adjust_level(±1)`, `.cycle_mode(home_before_horizontal=True)`, `.command`, `.selected`, `.level`, `.locked`, `.locked_reason` |
| One-build-at-a-time worker | `rig/build_job.py` → `BuildJob(controller, timeout)` | `.start()`, `.running`, `.poll() → BuildOutcome(result, error, locked) | None` |
| Serial link | `rig/link.py` → `Rig(cfg, on_line=, on_error=, mode=)` | `.connect(home_before_configure=)`, `.build(col,row,level) → BuildResult`, `.home(full=)`, `.set_mode(m)`, `.goto(c,r)`, `.close()`, `.grid`, `.port_name` |
| Build outcome | `rig/link.py` → `BuildResult` | `str(r)` ∈ {`"placed"`,`"rejected"`,`"aborted"`}; `.reason`; `.needs_a_human` |
| Pixel ↔ cell math | `rig/workspace.py` → `WorkspaceMap` | `.cell_at(point, image_size) → (col,row)|None`, `.target_polygon(col,row,image_size)`, `.from_grid(grid, corners, image_size, projection)`, `.save(path)` |
| Approximate / saved map loaders | `camera/gridded_camera_feed.py` | `approximate_workspace(grid, image_size, projection)`, `load_workspace(path, grid, projection) → (map|None, rejection|None)`, `projection_metadata(profile, capture, enabled, roi)` |
| Grid drawing + drawable geometry | same file | `draw_machine_grid(frame, workspace, hover, calibrated)`, `_grid_geometry(workspace, image_size)` (private — a starting point for the JSON geometry payload) |
| Camera settings + frame prep | `camera/camera_feed.py` | `load_settings`, `capture_settings`, `profile_from_settings`, `sensor_from_settings`, `colour_from_settings`, `frame_orientation(frame, capture)`, `framing_roi(data)`, `crop_resize`, `draw_block_overlay`, `block_hover_text` |
| Fisheye correction | `vision/fisheye.py` | `build_maps(profile, size, interp, mip=, roi=)`, `undistort(frame, maps)` |
| Protocol-accurate fake board | `tests/test_link.py` → `FakeSerial` | **test-only today; Step 1 promotes it** |
| The reference UI (read it) | `camera/rig_build_v1.py` | the loop in `main()`, `reject_mutation_if_unsafe()`, `on_mouse()`, `handle_key()`, `status_lines()` |

**Environment rules (`AGENTS.md`, "Environment rules that will bite you"):**
On the Pi, `numpy` and OpenCV come from `apt`; everything else goes in the venv.
New pure-Python deps (`fastapi`, `uvicorn`, `httpx`, `pytest`, `pytest-asyncio`)
are fine — but verify none pull a compiled extension before adding them to
`requirements*.txt`. Use `.venv/bin/python`, never a bare `python3`, in anything
that runs on the Pi.

---

## 4. Decisions locked for this plan

| Decision | Choice | Consequence |
| --- | --- | --- |
| Backend test framework | **Adopt `pytest`** (`+ httpx + pytest-asyncio`) for all new code | The existing plain-assert scripts (`tests/test_*.py`, run directly) stay as they are. New tests are `pytest`-style and live alongside them. Add a `pytest.ini`/`pyproject` `[tool.pytest.ini_options]` with `testpaths` scoped so it does **not** try to collect the plain-assert files. |
| Frontend tests | **Vitest + React Testing Library**, unit + component only | No Playwright / browser e2e in this plan. |
| Overlays | **Drawn in the browser** as SVG from JSON geometry | The MJPEG stream is raw video. `WorkspaceMap.cell_at` / `.target_polygon` get ported to TypeScript for the hover/selected highlight. The **server's Python `cell_at` stays authoritative** for what is actually selected. |
| `--mock` camera | **Simulated workspace** — rendered blocks at grid cells + the printed-grid pattern | Block detection and calibration are exercisable off the Pi, not just "pipeline runs". |

---

## 5. Architecture

```text
  ┌─────────────────────────────────────────────┐
  │  React PWA  (phone / tablet / desktop)       │
  │  - MJPEG <img> video layer                   │
  │  - SVG overlay layer (grid, hover, selection)│
  │  - WebSocket state store                     │
  │  - REST calls for every action              │
  └───────────────┬─────────────────────────────┘
                  │  HTTPS, trusted LAN, shared-secret cookie
                  ▼
  ┌─────────────────────────────────────────────┐
  │  FastAPI service on the Pi (uvicorn, 1 worker)│
  │                                              │
  │  lifespan owns ONE of each:                  │
  │   ├─ ConsolePipeline  (Step 3)               │
  │   │    ├─ LatestFramePump → camera source    │
  │   │    ├─ AnalysisWorker (block detection)   │
  │   │    └─ PaperGridTracker (printed grid)    │
  │   ├─ Rig  (real serial, or MockBoard)        │
  │   ├─ BuildController + BuildJob              │
  │   └─ MJPEG encoder (encode-once, fan-out)    │
  │                                              │
  │  GET  /api/state         full snapshot       │
  │  WS   /api/events        state + log push    │
  │  GET  /api/stream.mjpg   raw video           │
  │  POST /api/select|deselect|level|mode|view   │
  │  POST /api/build         (echoes command)    │
  │  POST /api/calibration/* (corners / sheet)   │
  └───────────────┬───────────────┬─────────────┘
                  ▼               ▼
           CSI camera       USB serial → Arduino Mega → motors
        (or MockCamera)     (or MockBoard)
```

Proposed new files (names are suggestions; keep them consistent):

```text
python/rig/mock_board.py         # Step 1  — promoted FakeSerial
python/vision/mock_camera.py     # Step 2  — simulated-workspace frame source
python/rig/console_pipeline.py   # Step 3  — headless capture+detect loop
python/web/__init__.py
python/web/app.py                # Step 4  — FastAPI app + lifespan
python/web/state.py              # Step 4  — Pydantic state models + snapshot builder
python/web/routes_command.py     # Step 5  — select/level/mode/build/...
python/web/mjpeg.py              # Step 6  — shared-latest-JPEG encoder + streamer
python/web/geometry.py           # Step 6  — build the JSON drawing geometry
python/tests/mock_board_test.py          # Step 1
python/tests/mock_camera_test.py         # Step 2
python/tests/console_pipeline_test.py    # Step 3
python/tests/web_state_test.py           # Step 4
python/tests/web_command_test.py         # Step 5
python/tests/web_stream_test.py          # Step 6
web/                             # Step 7+ — Vite React app
  src/lib/workspace.ts           # Step 8  — TS port of the cell math
  src/lib/workspace.fixtures.json# Step 8  — golden table from Python
```

---

## 6. The development rule: tests first

For **every** step: write the test file, run it, watch it fail for the right
reason, then write the implementation until it passes, then clean up. The test
and its implementation are committed together, test first in the diff. If a step
has both backend and frontend parts, each part follows this rule independently.

"Tests first" is not "tests eventually". If you find yourself writing
implementation with no failing test pointing at it, stop and write the test.

---

## 7. The steps

Each step below has the same shape: **Goal · Files · How (hints) · Tests to
write first · Gotchas · Done when.**

---

### Step 1 — Ship the fake board (`MockBoard`)

**Goal.** A supported, importable fake Arduino that speaks the real firmware
serial protocol, so the whole backend can run with no hardware. Today this logic
exists only inside `tests/test_link.py` as `FakeSerial`.

**Files.**
- New: `python/rig/mock_board.py`
- New test: `python/tests/mock_board_test.py`
- Edit: `python/rig/link.py` — add a transport injection point
- Edit: `python/tests/test_link.py` — import `FakeSerial` from the new module
  instead of defining it (keep the test passing)

**How.**

1. **Read `tests/test_link.py` lines ~34–260 first.** `FakeSerial` there already
   implements: a boot banner (`@0 BOOT`, `@0 READY grid=...`), a `write()` that
   parses the command, scripted replies per command, `@n OK/SAFE/HELD/ERR` ack
   lines in the right positions, and a way to make a build take a realistic
   number of seconds. Move that class almost verbatim into `mock_board.py`.

2. **Give it a small, explicit control surface** for tests and `--mock`:
   ```python
   class MockBoard:
       def __init__(self, *, grid="6x5", mode="vertical", build_seconds=0.5):
           ...
       def fail_next_build(self, kind="ABORTED", reason="simulated abort"):
           """Make the next B return ABORTED / HELD instead of OK."""
       def drop_next_ack(self):
           """Emit prose only, no @-line — exercises link.py's prose fallback."""
       def reboot(self):
           """Emit an unexpected @0 BOOT — exercises RigReset handling."""
       # pyserial-shaped surface the reader thread uses:
       def read(self, n=1): ...
       def readline(self): ...
       def write(self, data): ...
       def close(self): ...
       @property
       def is_open(self): ...
   ```
   Keep timing controllable: `build_seconds` small by default so tests are fast;
   the web `--mock` mode can pass something like `2.0` to feel real.

3. **Add the injection point to `Rig`.** `rig/link.py` currently hard-codes
   `serial.Serial(candidate, self.baud, timeout=0.2)` inside `connect()`. Add a
   parameter:
   ```python
   def __init__(self, cfg=None, on_line=None, on_error=None, mode=None,
                serial_factory=None):
       self._serial_factory = serial_factory or (lambda port, baud, timeout: serial.Serial(port, baud, timeout=timeout))
   ```
   and call `self._serial_factory(candidate, self.baud, 0.2)` in `connect()`.
   For `--mock`, pass `serial_factory=lambda *a, **k: MockBoard(...)`. This is
   cleaner than the test's `link.serial.Serial = ...` monkeypatch; keep the
   monkeypatch working too so `test_link.py` is untouched beyond the import.

4. **Protocol reference:** `plans/ack-protocol.md` lists every `@` kind
   (`OK`, `ERR`, `SAFE`, `HELD`, `BOOT`, `READY`) and the prose each sits beside.
   `SAFE` (nothing moved) and `HELD` (claw may still hold a block) are **not**
   interchangeable — `MockBoard` must be able to produce each.

**Tests to write first (`mock_board_test.py`, pytest):**
- `Rig(serial_factory=mock).connect()` returns, and the log shows `@0 READY`.
- After connect, `rig.grid.cols/rows` match what `config/rig.json` says (connect
  re-pushes `S`).
- `rig.build(3, 5, 0)` returns a `BuildResult` with `str(result) == "placed"`.
- `mock.fail_next_build("ABORTED"); rig.build(...)` → `str(result) == "aborted"`
  and `result.needs_a_human` is true.
- `mock.drop_next_ack(); rig.build(...)` still returns `"placed"` via the prose
  fallback, and `rig.prose_fallbacks` incremented.
- `mock.reboot()` during an idle period → the next command raises `RigReset`.
- `rig.build(0, 0, 0)` raises `ValueError` (feeder is never a target — this is
  `Rig.build`'s own guard, verify the mock doesn't mask it).
- A second `rig.build(...)` called while one is "in flight" raises `RigBusy`
  (drive this with two threads, or a `build_seconds` long enough to overlap).

**Gotchas.**
- `Rig` is deliberately not thread-safe; the `RigBusy` path is a lock, not a
  queue. Don't "fix" that.
- The reader runs on a daemon thread. Tests must `rig.close()` in a finally / a
  fixture teardown or threads leak between tests.
- Keep `MockBoard.readline()` returning `b""` on timeout (like pyserial) rather
  than blocking forever — the reader loop expects to wake up regularly.

**Done when.** `pytest python/tests/mock_board_test.py` passes, `python
python/tests/test_link.py` still prints all-pass, and a REPL can do
`Rig(serial_factory=lambda *a,**k: MockBoard()).connect()` →
`.build(3,5,0)` → `"placed"` with no hardware.

---

### Step 2 — Mock camera with a simulated workspace

**Goal.** A frame source with the same interface as `V4L2Source` that renders a
believable top-down view of the rig: coloured block rectangles sitting in grid
cells, the printed calibration-grid pattern, and a frame counter, so that block
detection *and* calibration can be developed off the Pi.

**Files.**
- New: `python/vision/mock_camera.py`
- New test: `python/tests/mock_camera_test.py`
- Edit: `python/vision/camera_source.py` → `open_camera()` — add `"mock"` backend

**How.**

1. **Match the interface exactly** (see `V4L2Source`): `read() -> (True, frame)`
   where `frame` is `HxWx3` BGR `uint8`; attributes `.size` (w, h) and `.name`;
   methods `.apply(settings) -> ([], [])` (a no-op is fine) and `.release()`.
   Default size `DEFAULT_SIZE = (1296, 972)` from `camera_source.py`.

2. **Render with plain OpenCV/NumPy.** Each `read()`:
   - start from a mid-grey canvas (`np.full((h, w, 3), 90, np.uint8)`);
   - draw the workspace as a lighter quad (optionally with a slight perspective
     so the homography calibration has something non-trivial to solve);
   - draw configured blocks as filled rotated rectangles in strong colours
     (`detect_blocks` keys on red-minus-blue, so use saturated reds/greens/blues
     — check `vision/block_detector.py` for the exact threshold, default
     `--color-threshold 8`);
   - optionally stamp a frame counter + timestamp in a corner;
   - return a copy so consumers can't mutate the canvas.

3. **Constructor knobs** for tests:
   ```python
   MockCamera(size=DEFAULT_SIZE, *, blocks=((3, 5, "red"), (2, 2, "green")),
              draw_printed_grid=True, perspective=0.0, fps_cap=30)
   def set_blocks(self, blocks): ...
   def freeze(self):  """Stop advancing the frame counter / timestamp — for stale-frame tests."""
   def resume(self): ...
   ```
   To place a block *at a grid cell*, reuse the real geometry: build a
   `MachineGrid.from_config(load_rig_config(), mode=...)` and a
   `WorkspaceMap` (approximate is fine) and call `.target_polygon(col, row,
   size)` to get the pixel quad to fill. That guarantees the mock blocks line up
   with where the overlay will draw the grid.

4. **The printed grid.** Full fidelity is not required for v1 — a regular
   lattice of alternating coloured bars in roughly the right place is enough for
   `PaperGridTracker` / `paper_workspace_map` to lock on. If it proves fiddly,
   ship Step 2 with blocks only and note the printed-grid mock as a follow-up
   inside Step 10.

5. **Wire the backend:** in `open_camera()`, before the `"auto"/"picamera2"`
   branch, add
   `if backend == "mock": from vision.mock_camera import MockCamera; return MockCamera(size)`.

**Tests to write first (`mock_camera_test.py`, pytest):**
- `open_camera("mock")` returns something with `.read()`, `.size`, `.name`,
  `.release()`.
- Pushed through `LatestFramePump`: `snapshot().sequence` increases across two
  reads spaced by a short sleep.
- After `.freeze()`, `snapshot().sequence` stops increasing and
  `snapshot().age_s()` grows past `STALE_FRAME_AFTER_S`.
- `detect_blocks(frame, color_threshold=8, min_area=500)` returns at least the
  number of blocks configured, and their centres are within a tolerance of the
  `target_polygon` centres for those cells.
- (If printed grid included) `analyze_paper_grid(frame, spec)` returns a
  calibration candidate rather than an error.

**Gotchas.**
- BGR, not RGB. OpenCV order. Blue and red swapped is the classic bug.
- `LatestFramePump` never calls `source.release()`; the pipeline owner does,
  after `pump.stop()` returns `True`. Mirror that in tests.
- Don't sleep in `read()` to simulate fps — let the pump call as fast as it
  likes; if you must cap, cap cheaply and never block longer than ~30 ms.

**Done when.** The existing processing chain (colour correction → `build_maps` /
`undistort` → `detect_blocks` → `PaperGridTracker`) runs end-to-end on
`open_camera("mock")` frames on a machine with no camera, and finds the planted
blocks.

---

### Step 3 — Extract the headless pipeline

**Goal.** One class that owns the capture + detection loop from
`rig_build_v1.py:main()` and exposes "the latest fully-processed frame plus
everything needed to describe it", with no Tk, no `cv2.imshow`, no `argparse`,
no key handling.

**Files.**
- New: `python/rig/console_pipeline.py`
- New test: `python/tests/console_pipeline_test.py`
- `rig_build_v1.py` — ideally refactor it to consume the new class; at minimum,
  do not break it.

**How.**

1. **Study `rig_build_v1.py:main()` lines ~221–320 (setup) and ~657–707 (the
   per-frame body).** The processing sequence per new frame is:
   ```python
   frame = colour.apply(frame_orientation(snapshot.frame, capture))
   if maps is None or frame.shape[1::-1] != input_size:
       maps = build_maps(profile, frame.shape[1::-1], interpolation, mip=mip, roi=roi)
       input_size = frame.shape[1::-1]
       map_generation += 1
   view = undistort(frame, maps) if enabled else crop_resize(frame, roi, maps.out_size, interpolation)
   image_size = view.shape[1::-1]
   workspace = saved_workspace or approximate_workspace(grid, image_size, projection)
   analysis.submit(view, snapshot.sequence, map_generation, color_threshold=..., min_area=...)
   paper.submit(view, snapshot.sequence, map_generation)
   ```
   Lift this into a method. Keep `map_generation` — the analysis workers use it
   to discard results computed against a stale remap table.

2. **Shape of the class:**
   ```python
   class ConsolePipeline:
       def __init__(self, *, camera_backend="auto", settings_path=SETTINGS_PATH,
                    rig_config_path=CONFIG_PATH, workspace_map_path=WORKSPACE_MAP_PATH,
                    mode=None, analysis_hz=10.0, paper_hz=PAPER_GRID_HZ): ...
       def start(self): ...            # opens camera, starts pump + workers
       def stop(self): ...             # reverse order; pump.stop() before camera.release()
       def process_once(self) -> "ProcessedFrame | None":
           """Pull the newest frame, run the per-frame sequence, return the result
           (or None if no new frame since last call)."""
       def set_workspace(self, wsmap):     # after a successful calibration
       def set_grid_mode(self, mode, grid): # after BuildController.cycle_mode
   ```
   ```python
   @dataclass(frozen=True)
   class ProcessedFrame:
       view: np.ndarray          # corrected BGR, writeable=False
       sequence: int
       captured_at: float
       image_size: tuple[int, int]
       stale: bool               # age_s >= STALE_FRAME_AFTER_S
       detections: tuple         # last completed block detections
       workspace: WorkspaceMap
       calibrated: bool
       paper_status: str
       grid_mode: str
   ```

3. **Ownership / threading.** `ConsolePipeline` owns the `LatestFramePump`, the
   `AnalysisWorker`, the `PaperGridTracker`. It does **not** own the `Rig` — the
   FastAPI lifespan owns both side by side. `process_once()` is called from a
   single driver (a background task in Step 4); it is not required to be
   thread-safe against itself.

4. **Config loading** mirrors `rig_build_v1.py:232–253`: `load_settings`,
   `load_rig_config`, `MachineGrid.from_config`, `capture_settings`,
   `profile_from_settings`, `sensor_from_settings`, `colour_from_settings`,
   `framing_roi`, `projection_metadata`. Copy that block; don't reinvent it.

**Tests to write first (`console_pipeline_test.py`, pytest):**
- With `camera_backend="mock"`: `start()`, call `process_once()` in a short
  loop, assert you get `ProcessedFrame`s with a strictly increasing `sequence`.
- `process_once()` returns `None` when called twice with no new frame in
  between.
- Freeze the mock camera → within `STALE_FRAME_AFTER_S` the `ProcessedFrame`
  has `stale is True`.
- `detections` becomes non-empty within ~1 s (detection is async; poll).
- `calibrated is False` when no `workspace_map.json` exists; after
  `set_workspace(a_saved_map)` it flips to `True`.
- `stop()` returns cleanly and a second `stop()` is a no-op.

**Gotchas.**
- `view.flags.writeable = False` in `rig_build_v1.py` is deliberate — the
  analysis workers hold a reference. Keep it.
- Colour correction MUST be applied exactly once, right after
  `frame_orientation`, per `AGENTS.md` §3e. Don't add a second application
  anywhere downstream.
- Stop order: `analysis.stop()`, `paper.stop()`, then `pump.stop()`, and only
  `camera.release()` if `pump.stop()` returned `True` (a wedged CSI read makes
  release unsafe — see `LatestFramePump` docstring).

**Done when.** One object exposes "latest processed frame + geometry" driven by
`process_once()`, tests pass against the mock camera, and `rig_build_v1.py`
still runs (whether or not you refactored it to use the class).

---

### Step 4 — FastAPI skeleton, lifespan, state model

**Goal.** A running FastAPI service that, on startup, brings up exactly one
`ConsolePipeline` and one `Rig` (real or `MockBoard`), and exposes the current
state as JSON over `GET /api/state` and as a push stream over `WS /api/events`.

**Files.**
- New: `python/web/__init__.py`, `python/web/app.py`, `python/web/state.py`
- New test: `python/tests/web_state_test.py`
- Edit: `requirements.txt` / `requirements-dev.txt` (see *Wiring notes*)

**How.**

1. **Lifespan owns the singletons.** Use FastAPI's lifespan context:
   ```python
   @asynccontextmanager
   async def lifespan(app):
       mock = os.environ.get("RIG_MOCK") == "1" or app.state.args.mock
       pipeline = ConsolePipeline(camera_backend="mock" if mock else "auto", ...)
       rig = Rig(serial_factory=(lambda *a, **k: MockBoard(build_seconds=2.0)) if mock else None,
                 on_line=lambda l: app.state.log.append(l), mode=app.state.args.mode)
       pipeline.start()
       rig.connect(home_before_configure=(rig.grid.mode == "horizontal"))
       controller = BuildController(rig, level=0)
       job = BuildJob(controller, timeout=300.0)
       driver = asyncio.create_task(_drive_pipeline(app, pipeline))  # calls process_once in a loop
       app.state.pipeline, app.state.rig, app.state.controller, app.state.job = ...
       try:
           yield
       finally:
           driver.cancel(); ...
           job.join(); pipeline.stop(); rig.close()
   ```
   `--mock` comes from a CLI arg or `RIG_MOCK=1`. Provide a `python -m web`
   entrypoint or a small `run.py` that calls `uvicorn.run(app, workers=1)`.

2. **The driver task.** A plain `async` loop that does
   `frame = pipeline.process_once()` then `await asyncio.sleep(0)` / a small
   delay, storing the newest `ProcessedFrame` on `app.state`. `process_once` is
   sync CPU work — if it turns out to block the loop noticeably, move it to
   `await asyncio.to_thread(pipeline.process_once)`. Cap the effective rate
   ~15–20 Hz.

3. **State model (`web/state.py`).** Pydantic models. One builder function
   `build_state(app) -> StateModel` that reads `controller`, `job`, the latest
   `ProcessedFrame`, and `rig`:
   ```python
   class StateModel(BaseModel):
       mode: str                     # "vertical" | "horizontal"
       cols: int
       rows: int
       calibrated: bool
       selected: tuple[int, int] | None
       command: str | None           # controller.command
       level: int
       build_state: Literal["READY", "RUNNING", "LOCKED"]
       locked_reason: str | None
       camera: Literal["LIVE", "STALE", "WAITING"]
       camera_age_ms: int | None
       last_result: Literal["placed", "rejected", "aborted"] | None
       last_result_reason: str | None
       # geometry added in Step 6
   ```
   `build_state`: `"RUNNING"` if `job.running`, else `"LOCKED"` if
   `controller.locked`, else `"READY"` (mirrors `rig_build_v1.py:628`).

4. **`GET /api/state`** → `build_state(app)`.

5. **`WS /api/events`.** On connect, send the full state. Then push the full
   state whenever it changes and push log lines as they arrive. Simplest
   correct approach: an `asyncio.Event` "something changed" that the driver
   loop and the command handlers `.set()`, plus a monotonic revision counter;
   the socket task waits on it and re-sends `build_state`. Also send a
   `{"type": "heartbeat"}` every ~10 s so a dead socket is detected. Keep
   messages small — **never send frames over the socket.**

**Tests to write first (`web_state_test.py`, pytest + httpx ASGITransport):**
- App starts under `RIG_MOCK=1` with no hardware and `GET /api/state` returns
  200 with the documented fields and sane defaults (`build_state == "READY"`,
  `calibrated == False`, `selected is None`).
- `camera` transitions `WAITING` → `LIVE` shortly after startup.
- A WebSocket client receives an initial state message, then receives an updated
  message after a state change is triggered (e.g. a direct
  `app.state.controller.select((3, 5))` in the test, then signal change).
- Heartbeats arrive on the socket.
- Shutdown (exit the lifespan / `TestClient` context) does not hang and closes
  the mock rig.

**Gotchas.**
- **One worker only.** Never `uvicorn --workers N`, never `--reload` in
  production — each worker is a separate process and they'd fight for the port
  and camera. `--reload` is acceptable *only* on a dev machine in `--mock`.
- `httpx.ASGITransport` + `LifespanManager` (from `asgi-lifespan`, or FastAPI's
  `TestClient` which runs lifespan) so the pipeline/rig actually start in tests.
- Don't do blocking `rig.connect()` inside the event loop without
  `to_thread` if it's slow — with `MockBoard` it's fast, with real hardware it
  waits out the boot banner. `await asyncio.to_thread(rig.connect, ...)`.

**Done when.** `RIG_MOCK=1 uvicorn web.app:app` (one worker) serves
`/api/state`, and a WebSocket client sees state change messages while a build
runs.

---

### Step 5 — Command endpoints, all guarded on the server

**Goal.** Every action `rig_build_v1.py` supports, as a REST endpoint that
re-checks safety server-side and returns the new state. The browser cannot
bypass a single guard.

**Files.**
- New: `python/web/routes_command.py`
- New test: `python/tests/web_command_test.py`

**How.**

1. **Port `reject_mutation_if_unsafe()`** (`rig_build_v1.py:420`) into a
   dependency / helper:
   ```python
   def require_mutable(app):
       if app.state.job.running:
           raise HTTPException(409, "build in progress; wait for its result")
       if app.state.controller.locked:
           raise HTTPException(409, app.state.controller.locked_reason)
   ```
   Also port the **stale-camera** guard: selection and build are refused unless
   the latest `ProcessedFrame` is fresh (`not stale`).

2. **Endpoints** (all return the new `StateModel`; all call `require_mutable`
   unless noted):

   | Method + path | Body | Maps to |
   | --- | --- | --- |
   | `POST /api/select` | `{x, y, img_w, img_h}` | scale `(x,y)` from display size to feed `image_size`, `workspace.cell_at(pt, image_size)`; `None` → 400 "outside the grid or in a gap"; else `controller.select(cell)` |
   | `POST /api/select/axis` | `{axis: "col"|"row", value: int}` | `controller.select((value, 0))` or `((0, value))` — the `x`/`y` keyboard picks in `rig_build_v1.py:536` |
   | `POST /api/deselect` | — | `controller.clear_selection()` |
   | `POST /api/level` | `{delta}` or `{value}` | `controller.adjust_level(delta)` / `set_level(value)` |
   | `POST /api/mode` | `{mode}` | `controller.cycle_mode(home_before_horizontal=True)` (or a `set_mode`); then `pipeline.set_grid_mode(...)`, reload the workspace map for that mode. Clears selection. |
   | `POST /api/view` | `{grid?, detect?, paper?, overlay?}` | **no** `require_mutable` — these are display-only toggles. Store on `app.state`. |
   | `POST /api/build` | `{confirm: true, command: "B 3 5 0"}` | 400 unless `command == controller.command`; then `app.state.job.start()`. 409 if already running/locked. |
   | `POST /api/calibration/*` | see Step 10 | four-corner + printed-sheet |

3. **After `job.start()`**, the driver loop keeps producing frames and the state
   flips to `RUNNING`. When `job.poll()` returns a `BuildOutcome`, translate it
   like `rig_build_v1.py:outcome_message()` / `result_message()` and update
   `last_result` / `locked_reason`, then signal the WebSocket. Do the `poll()`
   in the driver loop, not in a request handler.

4. **Coordinate scaling.** The browser sends the pixel it clicked *and* the
   size of the image element it clicked on. The server scales to the pipeline's
   `image_size` before calling `cell_at`. Do not assume they're equal.

**Tests to write first (`web_command_test.py`, pytest):** a table of
`(precondition, request) → (status, effect)`. At minimum:
- select a valid cell → 200, `state.selected == [3,5]`, `state.command == "B 3 5 0"`.
- select the feeder `[0,0]` → 400, selection unchanged.
- select outside the envelope → 400.
- select with a **frozen** (stale) mock camera → 409 / refused.
- `POST /api/build` without a matching `command` → 400, no build starts.
- `POST /api/build` with the right command → 200, `state.build_state == "RUNNING"`;
  after ~`build_seconds`, `state.last_result == "placed"` and `selected` clears.
- with `MockBoard.fail_next_build("ABORTED")`: build → eventually
  `build_state == "LOCKED"`, `locked_reason` set, and every subsequent mutation
  returns 409.
- `REJECTED` path (mock returns rejected): `last_result == "rejected"`,
  selection **kept**, not locked.
- any mutation while `build_state == "RUNNING"` → 409.
- `POST /api/mode` → selection cleared, `state.mode` flipped, `cols/rows`
  changed.
- level down at 0 stays at 0 (`adjust_level` clamps).

**Gotchas.**
- `controller.build()` blocks for the whole build. It must only ever be called
  from `BuildJob`'s worker thread (which is what `job.start()` does), **never**
  from a request handler or the event loop.
- `cycle_mode(home_before_horizontal=True)` may physically home X/Y (real rig)
  or just latch (mock). It raises `RigError` if homing fails — catch and return
  409 with the reason.
- Reload the workspace map after a mode change: vertical and horizontal have
  **separate** calibrations in `workspace_map.json` (`load_workspace` handles
  the lookup by `grid.mode`).

**Done when.** Every guard in `rig_build_v1.py`'s `reject_mutation_if_unsafe`,
`on_mouse` (click during build / locked / calibrating) and `handle_key` (build,
mode, level, deselect, axis pick) has a corresponding passing server-side test.

---

### Step 6 — Raw MJPEG stream + drawing geometry in the state

**Goal.** A live video endpoint that costs one JPEG encode per processed frame
no matter how many clients watch, and never back-pressures the pipeline. Plus:
the state payload carries the geometry the browser needs to draw the grid,
selection and detections as SVG.

**Files.**
- New: `python/web/mjpeg.py`, `python/web/geometry.py`
- New test: `python/tests/web_stream_test.py`
- Edit: `web/state.py` — add a `geometry` field

**How — the stream.**

1. **Encode once, in the driver loop.** After `process_once()` yields a new
   `ProcessedFrame`, if there is ≥1 stream subscriber, encode:
   ```python
   ok, buf = cv2.imencode(".jpg", frame.view, [cv2.IMWRITE_JPEG_QUALITY, 75])
   latest_jpeg = (frame.sequence, buf.tobytes())
   jpeg_ready.set(); jpeg_ready.clear()
   ```
   Store `latest_jpeg` on `app.state`. **Skip the encode entirely when the
   subscriber count is 0** (ref-count in the streaming endpoint's
   enter/exit).

2. **`GET /api/stream.mjpg`** is an async generator response,
   `media_type="multipart/x-mixed-replace; boundary=frame"`. Each client loop:
   `await jpeg_ready.wait()` → yield the boundary + headers + `latest_jpeg`
   bytes. A slow client that misses a `set()` just picks up the next frame — it
   never blocks the producer, and frames are dropped, never buffered.

3. **Raw frame only.** Do **not** call `draw_machine_grid` /
   `draw_block_overlay` here. Overlays are the browser's job in this plan.

4. **Rate cap.** The driver loop already runs ~15–20 Hz; the stream inherits
   that. Optionally throttle per-client to a max fps if a client asks.

**How — the geometry payload (`web/geometry.py`).**

5. Build a JSON-serialisable structure from the current `WorkspaceMap` +
   `ProcessedFrame`:
   ```python
   {
     "image_size": [w, h],
     "calibrated": bool,
     "grid": [                       # every addressable cell
       {"col": c, "row": r,
        "polygon": [[x,y],[x,y],[x,y],[x,y]]}   # workspace.target_polygon(c, r, size)
     ],
     "selected": {"col": c, "row": r, "polygon": [...]} | null,
     "detections": [
       {"color": "red", "center": [x,y], "box": [[x,y]*4]}
     ],
     "paper": { ... } | null         # printed-grid quad(s), optional for v1
   }
   ```
   `_grid_geometry(workspace, image_size)` in `gridded_camera_feed.py` already
   computes most of this for the desktop overlay — read it and reuse its logic
   rather than starting from scratch. Iterate cells with
   `grid.max_col` / `grid.max_row`.

6. Put `geometry` in the `StateModel` (or a sibling `GET /api/geometry` if the
   state message gets too big — but one payload is simpler for the client).
   Recompute it when: a new frame changes `image_size`, the selection changes,
   the mode changes, or calibration changes. Not every frame if nothing moved.

**Tests to write first (`web_stream_test.py`, pytest):**
- `GET /api/stream.mjpg` yields at least 3 well-formed multipart JPEG parts
  within a couple of seconds (parse the boundary, check the JPEG magic
  `\xff\xd8`).
- With **zero** clients connected, an encode counter on `app.state` does not
  advance; it starts advancing once a client connects. (Prove the "skip encode
  when nobody's watching" optimisation.)
- The `geometry.grid` polygons for a known set of corners match
  `WorkspaceMap.target_polygon` computed directly in the test (same map, same
  size).
- `geometry.selected` is `null` with no selection and becomes the right polygon
  after `POST /api/select`.
- `detections` in the geometry reflects the planted mock blocks.

**Gotchas.**
- `cv2.imencode` returns `(bool, ndarray)`; call `.tobytes()`.
- Multipart MJPEG needs `\r\n` line endings and a `Content-Length` per part for
  picky clients; browsers are lenient but tests parsing the stream are not.
- Backpressure: use a single shared "latest" slot + an event, **not** a
  `Queue` per client with `maxsize>1`. Any per-client buffer that can grow is a
  latency bug waiting to happen.
- If `process_once` is offloaded with `to_thread`, the encode should happen in
  that same thread (CPU-bound), then hop back to set the asyncio event
  (`loop.call_soon_threadsafe`).

**Done when.** A bare `<img src="/api/stream.mjpg">` in a browser shows live
mock video, `/api/state` carries `geometry` sufficient to draw the overlay, and
the encode-skip test proves zero cost with no viewers.

---

### Step 7 — React PWA shell

**Goal.** The app scaffold: layout, WebSocket state store, the MJPEG `<img>` as
the video layer, an empty SVG layer above it, connection handling, and the
control panel wired to the REST endpoints — but overlay drawing and the full
build flow come in Steps 8–9.

**Files.** New `web/` project: Vite + React + TypeScript + `vite-plugin-pwa`.
- `web/src/store.ts` — state store (Zustand or `useReducer` + context; keep it
  small and typed to `StateModel`)
- `web/src/api.ts` — typed fetch wrappers for every endpoint
- `web/src/ws.ts` — WebSocket client with auto-reconnect
- `web/src/components/CameraView.tsx`, `ControlPanel.tsx`, `StatusBar.tsx`,
  `LockedBanner.tsx`
- `web/src/*.test.tsx` — Vitest + React Testing Library

**How.**

1. **Layout** (from the sketch): camera view fills the main area; a right-hand
   control rail (stacks below the video on narrow screens); a status/log strip
   along the bottom. Use CSS grid/flex, relative units, `max-width: 100%` on the
   video so the page never scrolls sideways.

2. **State store** holds the last `StateModel` from the socket plus a
   `connected: boolean`. All rendering is a pure function of that. The
   `ws.ts` client: connect, on message `JSON.parse` and dispatch, on close set
   `connected=false` and retry with backoff, on open set `connected=true`.

3. **Video layer.** `<img src="/api/stream.mjpg">` inside a positioned
   container; an `<svg>` absolutely positioned on top at the same size with a
   `viewBox` matching `geometry.image_size` (so overlay coordinates are just
   image pixels). When `connected` is false, grey the video (CSS filter) and
   overlay a "DISCONNECTED" message.

4. **Control panel** renders from state: mode badge, `CALIBRATED` /
   `APPROXIMATION ONLY` badge, selected cell + `command` string, level stepper
   (`POST /api/level`), view toggles (`POST /api/view`), a **BUILD** button
   (wired fully in Step 9 — for now just disabled/enabled logic), a **Deselect**
   button.

5. **BUILD enabled** iff `selected != null && camera === "LIVE" &&
   build_state === "READY"`. Disabled with a reason tooltip otherwise.

6. **PWA config**: `vite-plugin-pwa` with `registerType: 'prompt'`,
   `workbox.globPatterns` limited to the **app shell** (JS/CSS/HTML/icons).
   **Do not** add runtime caching for `/api/*` or the stream — stale rig state
   or a cached camera frame is dangerous. A manifest with name, icons,
   `display: standalone`.

**Tests to write first (Vitest + RTL):**
- store reducer: applying a `StateModel` message updates the store; a `close`
  event sets `connected=false`.
- `<ControlPanel>` given `{selected:null}` → BUILD disabled; given
  `{selected:[3,5], camera:"LIVE", build_state:"READY"}` → BUILD enabled.
- given `{build_state:"LOCKED", locked_reason:"..."}` → `<LockedBanner>` renders
  the reason and BUILD is disabled.
- given `connected:false` → controls disabled, "DISCONNECTED" shown.
- level `+`/`-` buttons call `api.level` with the right delta (mock the fetch).

**Gotchas.**
- Some browsers cap concurrent `multipart/x-mixed-replace` connections — keep
  exactly one `<img>` stream per page.
- The MJPEG `<img>` keeps loading forever; that's expected, don't treat it as an
  error. Detect camera health from `state.camera`, not from the `<img>`.
- Keep the SVG `viewBox` locked to `image_size`; let CSS scale the whole
  container. Then Step 8's math never has to think about display scale for
  *drawing* (only for translating a click back — see Step 8).

**Done when.** `npm run dev` in `web/`, pointed at a `--mock` backend, shows the
live mock video and a control panel that reflects real state over the socket.

---

### Step 8 — Overlay + interaction layer (TypeScript port of the cell math)

**Goal.** Draw the grid, the hovered cell, the selected cell and detected blocks
as SVG over the video, and turn a click into a `POST /api/select`. A TypeScript
port of the projection math gives instant local feedback; the server stays
authoritative.

**Files.**
- `web/src/lib/workspace.ts` — port of the relevant `WorkspaceMap` methods
- `web/src/lib/workspace.fixtures.json` — golden cases generated from Python
- `web/src/components/GridOverlay.tsx`
- `web/src/lib/workspace.test.ts` (Vitest)
- New Python helper script: `python/tools/dump_workspace_fixtures.py` (generates
  the golden file — run once, commit the JSON)

**How.**

1. **Port only what the browser needs** from `rig/workspace.py`:
   - the 3×3 homography solve (`_homography`) and `_project`;
   - `normalized_at(point, image_size)` and `cell_at(point, image_size)`;
   - `pixel_at(u, v, image_size)` and `target_polygon(col, row, image_size)` for
     drawing.
   The physical-grid (`MachineGrid`) branch of `cell_at` handles the gaps
   between blocks. If porting the full `MachineGrid` lattice math is too much
   for v1, port the **approximate** path (uniform `cols × rows` split) and rely
   on the **server** to reject clicks that land in a gap (it already runs the
   real `cell_at`). Document that the browser highlight is approximate and the
   server's answer wins.

2. **Golden fixtures.** `dump_workspace_fixtures.py` builds a `WorkspaceMap`
   (both an approximate one and, if available, a saved one) and dumps a table:
   input `(x, y, image_size)` → output `cell` or `null`, plus a set of
   `target_polygon` results. The Vitest test loads the JSON and asserts the TS
   port matches every row. This is how you know the two implementations agree.

3. **`GridOverlay.tsx`** renders, from `state.geometry`:
   - every cell polygon as a faint `<polygon>` (amber stroke when
     `!calibrated`);
   - the cell currently under the pointer, computed locally with `cell_at` for
     zero-latency hover, highlighted;
   - `geometry.selected.polygon` as a bold `<polygon>`;
   - each detection's box + centre dot, colour-coded.

4. **Click handling.** On `pointerdown` on the SVG: get the pointer position in
   SVG user units (use `getScreenCTM().inverse()` or the `viewBox` ratio) — that
   is already in image-pixel space. `POST /api/select {x, y, img_w:
   image_size[0], img_h: image_size[1]}`. Optimistically highlight the local
   `cell_at` result; correct it when the next state message arrives.

5. **Touch.** `pointer` events cover mouse + touch. Make cells comfortably
   tappable; a tap is a select, not a hover.

**Tests to write first (Vitest):**
- `workspace.test.ts`: for every row in `workspace.fixtures.json`, TS `cell_at`
  equals the Python result; TS `target_polygon` matches within 1e-6.
- clicking outside all cell polygons → local `cell_at` returns `null`, no
  optimistic highlight.
- `<GridOverlay>` renders N `<polygon>` elements for an N-cell grid; renders the
  selected polygon with the "selected" class when `geometry.selected` is set.
- amber styling when `geometry.calibrated === false`.

**Gotchas.**
- The homography solve needs a small linear solver. Either hand-roll Gaussian
  elimination for the 8×8 system (it's fixed-size) or vendor a tiny function;
  do **not** pull in a big matrix library for this.
- Corner order matters: `CORNER_NAMES` order (`holder home`, `far-X/home-Y`,
  `far-X/far-Y`, `home-X/far-Y`). The fixture generator and the TS port must use
  the same order the Python does.
- Keep drawing in image-pixel units inside a `viewBox`; never bake display
  scale into the geometry. Only the *click translation* touches screen
  coordinates, and `getScreenCTM()` handles that for you.

**Done when.** Hovering shows the cell under the pointer, tapping selects it, the
SVG grid lines up with the mock blocks in the video, and the TS/Python
`cell_at` agreement test passes on the full fixture table.

---

### Step 9 — Two-step build + every terminal state in the UI

**Goal.** The confirmed build flow and correct, unmistakable UI for RUNNING,
PLACED, REJECTED and ABORTED/timeout.

**Files.** `web/src/components/BuildButton.tsx`, `BuildBanner.tsx`,
`ResultToast.tsx`; extend the store; Vitest tests.

**How.**

1. **Two-step.** BUILD → the button becomes **CONFIRM `B 3 5 0`** for ~3 s (show
   a countdown/ring). A second tap sends `POST /api/build {confirm: true,
   command: <the exact string from state.command>}`. Timeout or tap-away
   reverts to BUILD. This mirrors `rig_build_v1.py`'s "click selects, `b`/Enter
   confirms" rule — a single action must never start motion.

2. **RUNNING.** When `state.build_state === "RUNNING"`: a full-width banner
   "The rig is moving and cannot be interrupted", an elapsed timer, **every**
   control disabled (level, mode, select, calibrate, deselect, build). The video
   keeps streaming. There is deliberately no cancel/stop control — the Arduino
   is deaf; a stop button would be a lie.

3. **Terminal states**, from `state.last_result` / `state.build_state` when it
   leaves RUNNING:
   - `placed` → green toast "PLACED — select the next cell"; selection is
     already cleared server-side.
   - `rejected` → amber toast with `last_result_reason`; selection is kept;
     controls re-enable.
   - `aborted` or the socket reports `LOCKED` → red **SESSION LOCKED** banner
     with `locked_reason` and the sentence "A human must inspect the rig and
     restart the service." No retry control exists. Everything stays disabled.

4. **Disconnect during a build.** If the socket drops while `RUNNING`, show
   "DISCONNECTED — a build may still be in progress; do not touch the rig." On
   reconnect, re-sync from `GET /api/state`; the build either completed
   (show the result) or is still `RUNNING`.

**Tests to write first (Vitest):**
- BUILD → CONFIRM state → `api.build` called with `{confirm:true, command}`
  matching `state.command`; auto-revert after the timeout with no call.
- `state.build_state === "RUNNING"` → `<BuildBanner>` shown, all control
  buttons `disabled`.
- transition to `last_result === "placed"` → green toast, controls enabled,
  no selection.
- `last_result === "rejected"` → amber toast, selection still shown.
- `build_state === "LOCKED"` → red banner with reason, everything disabled,
  no retry button in the tree.

**Gotchas.**
- Trust `state.command` for the confirm payload — don't rebuild the string in
  the client from `selected` + `level`, or a race can send a stale command and
  the server will (correctly) 400 it.
- `REJECTED` must **not** clear the selection (matches `BuildController`:
  `PLACED` clears, a safe rejection may retain).
- Re-enable controls only on an explicit non-locked terminal state, never on a
  timeout guess.

**Done when.** Against `--mock` you can: select → confirm → PLACED; force a
REJECTED (`MockBoard` returns rejected) and see amber + kept selection; force an
ABORTED and see the red locked banner with no way forward but restarting.

---

### Step 10 — Calibration in the browser

**Goal.** Both calibration routes from `rig_build_v1.py`, in the web UI:
four clicked corners, and the printed-colour-sheet detection. Both write the
same `config/workspace_map.json` and both are refused during a build or on a
stale camera (the server already enforces that).

**Files.** `python/web/routes_calibration.py`; `web/src/components/Calibrate.tsx`;
tests both sides.

**How — backend.**

1. Endpoints (all `require_mutable` + fresh-camera):
   - `POST /api/calibration/start` → server enters "collecting corners", clears
     selection, returns the ordered `CORNER_NAMES` and which one is next.
   - `POST /api/calibration/corner {x, y, img_w, img_h}` → append a corner
     (scale to `image_size` first); returns count + next name.
   - `POST /api/calibration/undo` → pop the last corner.
   - `POST /api/calibration/cancel` → discard, keep the previous map.
   - `POST /api/calibration/save` → with 4 corners,
     `WorkspaceMap.from_grid(grid, corners, image_size, projection)` then
     `.save(path)`; on success `pipeline.set_workspace(new_map)` and
     `calibrated` flips. Validation errors (`ValueError` — degenerate /
     non-convex corners) → 400 with the message.
   - `POST /api/calibration/paper {selection?}` → `paper_workspace_map(view,
     spec, grid, projection, convention, window_index)` then `.save(path)`;
     surface `ColorGridError` as 400.
   This is the logic in `rig_build_v1.py:708–755` — port it, keep the guards.

**How — frontend.**

2. "Calibrate" button → enters corner mode: the SVG layer shows the current
   `CORNER_NAMES[next]` prompt and a marker at each placed corner; tap the video
   to place; Undo / Cancel / Save buttons. On Save, the badge flips to
   `CALIBRATED`.
3. "Calibrate from sheet" → shows detector status from `state` (reuse
   `PaperGridTracker.status()` text), prev/next candidate buttons
   (`{selection}`), Save.
4. Both entry points disabled while `build_state !== "READY"`.

**Tests to write first.**
- pytest: `POST /api/calibration/{start,corner×4,save}` with a temp
  `workspace_map.json` path writes a valid file and flips `state.calibrated`;
  degenerate corners → 400; any calibration call during `RUNNING` → 409; on a
  frozen camera → refused.
- pytest: after save, `GET /api/state` shows `calibrated: true` and the
  `geometry.grid` polygons change (calibrated map ≠ approximate map).
- Vitest: the corner-collection component advances the prompt through the four
  `CORNER_NAMES`, Undo steps back, Save calls `api.calibration.save` only at 4
  corners.

**Gotchas.**
- `WorkspaceMap.save` writes per-mode entries — a vertical calibration and a
  horizontal one coexist in one file. Don't overwrite the other mode's entry.
- Point the tests at a temp path (`tmp_path` fixture); never let the suite write
  the repo's real `config/workspace_map.json`.
- A lens/orientation/crop/grid change invalidates a saved map — out of scope
  here, but don't add code that silently reuses a stale map across such a
  change; `load_workspace` already returns a rejection reason for that.

**Done when.** Off the Pi, against the simulated printed grid, the sheet route
runs and flips the badge; and the four-corner route writes a map that visibly
tightens the overlay against the mock blocks.

---

## 8. Wiring and deployment notes

- **`uvicorn` with exactly one worker, always.** One process owns
  `/dev/ttyACM*` and the camera. `--reload` only ever on a dev box in `--mock`.
- **Entry point.** A `python -m web` or `web/run.py` that parses `--mock` /
  `--mode` / `--host` / `--port` and calls `uvicorn.run(app, host, port,
  workers=1)`. `RIG_MOCK=1` env var as an alternative to `--mock`.
- **`systemd` unit on the Pi** runs the real service (no `--mock`), after the
  camera and the board are known good. Restart policy `on-failure`; note that a
  restart does **not** clear a locked build — a human still has to have looked
  at the rig.
- **HTTPS.** A PWA only installs off `localhost` over HTTPS. Use a self-signed
  cert trusted on the LAN devices, or `caddy` as a local reverse proxy with its
  internal CA. A single shared secret in an HTTP-only, `SameSite=Strict` session
  cookie gates every endpoint and the WebSocket. No public port-forwarding.
  This is a trusted-LAN console, not an identity system.
- **Dependencies.** Add `fastapi`, `uvicorn[standard]` to `requirements.txt`
  (pure Python — safe in the Pi venv). Add `pytest`, `pytest-asyncio`, `httpx`,
  `asgi-lifespan` to `requirements-dev.txt`. Before committing any of them, run
  the `AGENTS.md` check: `pip show <pkg> | grep Requires` and look for compiled
  `.so` files — nothing here should need them, but verify.
- **`pytest` collection.** Configure `testpaths`/`python_files` so pytest runs
  only the new `*_test.py` files and does not try to import-and-run the existing
  plain-assert `tests/test_*.py` scripts (those are executed directly, not
  collected). Keep both green.

---

## 9. Later, not now

- **The physical emergency stop and hardware safety interlock.** Deferred by
  explicit decision for this plan. It is a precondition for any *unattended*
  remote build: the Arduino is deaf during a `B`, so no browser action can stop
  one in progress. Revisit before letting anyone build without watching the rig.
- **WebRTC / hardware-encoded H.264**, if MJPEG bandwidth becomes a problem with
  several simultaneous clients.
- **Server-side overlay rendering** as a fallback path for very weak client
  devices.
- **Real authentication** — accounts, roles, audit — instead of one shared
  secret.
- **Playwright end-to-end tests** driving the real PWA against a `--mock`
  backend.
- **Multi-operator control arbitration** (who currently "holds" the rig).
- **Full-fidelity printed-grid rendering** in the mock camera, if Step 2 shipped
  with a simplified pattern.

---

## 10. Order of work

- **Steps 1 → 2 → 3 are entirely off-Pi** and unblock everything else. Do them
  first, in order. After Step 3 you can process mock frames into
  `ProcessedFrame`s with no hardware.
- **Steps 4 → 5 → 6** build the backend on top of Step 3. After Step 5 the whole
  safety model is reachable and tested over HTTP.
- **Steps 7 → 8 → 9 → 10** build the frontend. Step 7 can start in parallel once
  Step 4 exists (it only needs `/api/state` + the socket); Step 8 needs Step 6's
  geometry; Step 9 needs Step 5's build endpoint.
- **Only final acceptance needs the Pi, the camera and the rig together:** run
  the real service (no `--mock`), calibrate against the real printed sheet, and
  place a real block from a phone on the LAN.

Every step is done test-first. A step is not finished until its "Done when" is
demonstrably true and its tests pass.
