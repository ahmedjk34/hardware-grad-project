# Rig operator console — server guide

This guide runs the browser console in the `hardware-grad-project` checkout.
The service owns exactly one camera and one Arduino serial connection, so run
one backend process only. Do not start multiple Uvicorn workers or launch a
second camera/serial client while the service is running.

## 1. Prerequisites

You need:

- Python 3 and the repository virtual environment at `.venv/`.
- Node.js and npm for the browser app.
- For mock operation: no hardware.
- For real operation: a configured camera, a powered Arduino Mega, and the
  flashed sketch selected by `config/rig.json`.

On a desktop, create the environment once with:

```bash
cd /home/ahmedjk34/Desktop/Work_Dev/Miscellaneous/hardware-grad-project
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements-dev.txt
```

The Raspberry Pi should use its distro-provided NumPy/OpenCV/Picamera2 and the
venv for the remaining Python packages. Do not pip-install `numpy` or
`opencv-python` into the Pi venv; see [AGENTS.md](../AGENTS.md).

Install the browser dependencies once:

```bash
cd web
npm install
```

## 2. Check configuration

Before starting, inspect `config/rig.json`:

- `serial.port`, `serial.baud`, and `board.*` identify the Arduino.
- `grid.active_mode` selects the vertical or horizontal layout.
- `workspace.width_cm` and `workspace.height_cm` are the holder travel
  envelope; they are not the observed build footprint.

Camera settings are read from
`python/config/camera_settings.json`. A saved
`config/workspace_map.json` is generated calibration data and is ignored by
Git. Delete that local file only when you intentionally want to recalibrate.

If the sketch or any shared geometry/baud value changes, update both firmware
and Python-side partners as described in [AGENTS.md](../AGENTS.md), then run the
grid/config tests before connecting hardware.

## 3. Run a complete mock console (recommended first)

Use two terminals from the repository root.

Terminal A — backend:

```bash
PYTHONPATH=python .venv/bin/python -m web --mock --host 127.0.0.1 --port 8000
```

Terminal B — browser app:

```bash
cd web
npm run dev -- --host 127.0.0.1
```

Open the URL Vite prints, normally `http://127.0.0.1:5173/`. The Vite proxy
forwards `/api/*` and `/api/events` to the backend on port 8000. Mock mode
provides a simulated camera and board; it does not move hardware.

The mock workflow is:

1. Wait for the camera badge to become `LIVE`.
2. Tap a grid cell. The server returns the authoritative selection and `B`
   command.
3. Tap `BUILD`, then tap the displayed `CONFIRM B ...` button.
4. Watch the RUNNING banner and terminal result.
5. Use **Calibrate** for four-corner calibration if you want to exercise the
   generated map path. The current mock artwork is not a full-fidelity printed
   calibration sheet; test the printed-sheet route with a real sheet/camera.

## 4. Run with the real rig

First flash and bench-check the live sketch using the repository's configured
port and board:

```bash
scripts/flash.sh
```

Then start only the backend on the Pi (or the machine physically connected to
the rig):

```bash
cd /home/ahmedjk34/hardware-grad-project
PYTHONPATH=python .venv/bin/python -m web --host 0.0.0.0 --port 8000
```

Do not pass `--mock`. The default camera backend is `auto`, and the backend
opens the configured serial port during startup. If startup cannot home/connect
cleanly, stop and inspect the camera, USB cable, board reset, and the values in
`config/rig.json`; do not work around it by starting another process.

From a phone or tablet on the trusted LAN, open `http://<raspberry-pi-ip>:8000/`
if you have copied/built `web/dist/` on the Pi. The FastAPI process serves that
bundle and the `/api/*` routes from the same origin. The backend itself is HTTP
unless you place it behind an HTTPS reverse proxy; do not expose port 8000
directly to the public Internet.

## 5. Build and serve the PWA

Create the production app bundle with:

```bash
cd web
npm test
npm run build
```

For a no-separate-frontend-server deployment, build on the Pi (or copy the
resulting `web/dist/` directory to the Pi) and then start the backend from the
repository root:

```bash
cd /home/ahmedjk34/hardware-grad-project/web
npm install
npm test
npm run build
cd /home/ahmedjk34/hardware-grad-project
PYTHONPATH=python .venv/bin/python -m web --host 0.0.0.0 --port 8000
```

Open `http://<raspberry-pi-ip>:8000/` on the phone. There is exactly one server
process: FastAPI serves `web/dist/`, REST, the WebSocket, and MJPEG stream.
Node/npm is needed to build the bundle, not to keep the live UI running.

The generated `web/dist/` directory is a deployment artefact and is ignored by
Git. Serve it from a static web server or local HTTPS reverse proxy, forwarding
these paths to the single backend process:

| Browser path | Backend route |
| --- | --- |
| `/api/state` | REST state snapshot |
| `/api/events` | WebSocket event stream (state, build phases, serial, results) |
| `/api/stream.mjpg` | shared MJPEG camera stream |
| `/api/select`, `/api/build`, `/api/level`, etc. | guarded commands |
| `/api/calibration/*` | guarded calibration routes |

The frontend must not cache `/api/*`, `/api/events`, or the MJPEG stream. Only
the app shell may be precached; stale rig state or camera imagery is unsafe.

### The `/api/events` protocol

Every frame carries `type`, a monotonic `event_id` and an `at` timestamp in
epoch milliseconds. There are five fact types plus one envelope:

| `type` | Carries |
| --- | --- |
| `state` | the whole `StateModel` snapshot, under `state` |
| `build_step` | one firmware build phase: `command_seq`, `step`, `total`, `phase`, `label`, `action`, `status`, `eta_ms` |
| `build_result` | one settled build: `command_seq`, `result`, `reason`, `locked`, `locked_reason`, `from_prose` |
| `serial` | one raw line the rig printed, under `line`, with `stream` (`rig` / `error`) |
| `heartbeat` | nothing but its id — proof the socket is alive |
| `replay` | the envelope a reconnect's missed events arrive in: `events`, plus `gap` |

**Priority.** `serial`, `build_step` and `build_result` are DURABLE: delivered
exactly once each, in order, and kept in a bounded server-side replay buffer.
`state` is COALESCED: each client holds only the newest pending snapshot,
because a snapshot describes *now* and an older one has no value once a newer
one exists. Durable events are always sent first, so a backlog of camera
geometry can never delay a build phase.

**Rate.** A state snapshot goes out immediately whenever something semantic
changes — a selection, a phase, a result. A snapshot whose only change is
camera geometry is throttled to `geometry_hz` (default 5) rather than the
driver's 20 Hz.

**Reconnecting.** Open with `?after=<the newest durable event_id you applied>`
and the server replays everything after it, in one `replay` envelope. If that
id predates the buffer, `gap` is true and the client says so rather than
pretending its log is continuous. Deduplicate with `>` on the id — **never by
comparing text**, because two identical serial lines are two real lines, and
**never** by assuming `previous + 1`, because coalesced snapshots and
heartbeats consume ids without being replayable.

**What the build fields mean.** `build_phase_status` walks `idle → accepted →
validating → running → parking → placed | rejected | aborted | locked`.
`parking` is still a RUNNING command: the block is down and the rig is tidying
up. `build_release_confirmed` is phase 11's `status=done` — the jaws opened —
and is **not** a placement. Nothing says `placed` before the terminal `@n OK`
arrives as a `build_result`.

**`eta_ms`** is the firmware's own prediction of how long a phase will take,
present on the Z moves only and `null` everywhere else. The board computes it
(exact step count x its Z step period) because the constants it needs are
firmware-owned and the Pi may not keep copies. It is a FLOOR — the real move can
only take longer — so a client may animate from it but must never treat its
expiry as the phase having finished.

The firmware reports PHASES, not motor positions. There is no continuous
position telemetry, so no client may claim to know where the arm is between
phases. The one animation driven by a clock is the placement descent, and it is
clamped short of the cell so that only the real release event can land the
block.

## 6. Safety rules while operating

- A build always requires selection followed by a second confirmation tap.
- During `RUNNING`, the server rejects mutations and the UI offers no cancel or
  retry control; the Arduino is busy and may not be listening.
- A rejected build is safe and keeps the selection.
- A placed build clears the selection.
- An aborted build, timeout, reset, or cable-loss/unknown outcome locks the
  session. Stop touching the controls, inspect the physical rig, and restart
  the service only after a human has verified its state.
- Calibration, selection, and build commands are server-guarded for freshness,
  build state, and lock state. Never rely on a disabled browser button as the
  safety mechanism.

## 7. Troubleshooting

**The page says `DISCONNECTED`.** Confirm the backend is listening on port
8000, the browser is using the correct host, and the reverse proxy forwards the
WebSocket upgrade for `/api/events`. In development, keep the backend on 8000
and use the Vite dev server so its proxy remains active.

**Camera stays `WAITING` or becomes `STALE`.** Check the camera connection and
`python/config/camera_settings.json`; on a desktop use `--mock` because the
Pi CSI camera is not available there. A stale frame is intentionally refused
for selection and calibration.

**The Arduino does not connect.** Verify `serial.port`, `serial.baud`, and the
board/sketch in `config/rig.json`; check that no other process owns the port.
The USB port reset returns firmware to its compiled vertical mode, after which
the service performs its configured handshake.

**The overlay is amber.** No valid saved workspace map exists for the active
mode. Approximate-grid operation is supported; use four-corner or printed-sheet
calibration when you need a measured camera mapping.

**The session is locked.** This is deliberate. Inspect the claw, holder,
block, and gantry before restarting the service. There is no browser reset,
cancel, or retry path for an unknown machine state.

## 8. Verification commands

From the repository root:

```bash
PYTHONPATH=python .venv/bin/python -m pytest
cd web && npm test && npm run build
```

The Python suite currently has one documented Step 2 race in
`mock_camera_test.py`: an in-flight frame may arrive immediately after
`MockCamera.freeze()`. Do not hide that failure as part of server/frontend
changes.
