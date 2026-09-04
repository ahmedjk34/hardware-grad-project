# The communication pipeline — browser to both boards and back

This is the one end-to-end description of how a placement request travels from
an operator action to two Arduinos and back to the screen. It ties together the
segment-level docs rather than repeating them:

- Uno wire protocol, every message type, feed state machine, timing →
  **[feeder-controller.md](feeder-controller.md)**
- Mega `@seq STEP` build-phase protocol and its prose fallback →
  **[ack-protocol.md](ack-protocol.md)**
- Deep audit of the Pi ↔ Mega link (framing, ACK correlation, failure modes) →
  **[mega-pi-communication-audit.md](mega-pi-communication-audit.md)**
- How the console is built and its `/api/*` surface → **[CONSOLE.md](CONSOLE.md)**
- The Studio runner that drives multi-block runs → **[STUDIO.md](STUDIO.md)** §5.14
- How to run and operate the service → **[server-guide.md](server-guide.md)**

---

## 1. Topology

Three controllers, one brain. The Raspberry Pi 5 is the only master; the two
Arduinos never exchange a byte with each other.

```text
                       ┌──────────────────────────────────────────┐
   browser / Studio     │            Raspberry Pi 5                │
   (untrusted mirror)   │  one FastAPI process, one uvicorn worker │
        │  HTTPS/WS      │                                          │
        ▼               │   web.app lifespan owns, exactly once:    │
  /api/* + /api/events ─┼─▶ ConsolePipeline ── CSI camera           │
                        │   Feeder ───────────── USB serial A ──────┼──▶ Arduino Uno   (belt_v1)
                        │   Rig ───────────────── USB serial B ─────┼──▶ Arduino MEGA  (build_test_v1)
                        │   CellOrchestrator ── serializes A then B │
                        │   BuildController + BuildJob ── outer gate│
                        └──────────────────────────────────────────┘
```

| Role | Board | Firmware | Owns |
| --- | --- | --- | --- |
| Feeder | Arduino Uno | `arduino/belt_v1/belt_v1.ino` | hopper container, belt, alignment arm, two HC-SR04 — the path from hopper to the fixed pickup point `[0,0]` |
| Gantry | Arduino MEGA 2560 | `arduino/build_test_v1/build_test_v1.ino` | X/Y/Z motion, claw servo, rotation stepper — pick from `[0,0]`, place at any cell |
| Brain | Raspberry Pi 5 | `python/web` + `python/rig` | camera, all orchestration, every safety rule, the web server |

---

## 2. The two USB serial connections

They are independent links. Different ports, different clients, different
protocols, opened and closed separately by the same FastAPI lifespan.

| | Feeder link (A) | Gantry link (B) |
| --- | --- | --- |
| Python client | `python/rig/feeder.py` → `Feeder` | `python/rig/link.py` → `Rig` |
| Config keys | `config/rig.json` → `feeder.port` / `.baud` / `.firmware` / `.protocol` / `.fqbn` / `.sketch` | `config/rig.json` → `serial.port` / `.baud`, `board.*` |
| Baud | 9600 8N1 | 9600 8N1 |
| Identity check on connect | `@0 READY firmware=belt_v1 protocol=2 board=uno` must match `feeder.*` exactly, or the port is closed and startup fails | `@0 READY ... board=` must not be `mega`-mismatched; Mega banner/READY handshake |
| Reader | one daemon thread, `readline()` loop, parsed lines pushed to a queue | one daemon thread, same shape |
| Log tag | `[UNO/FEEDER …]` in `logs/serial.log` and the `/api/events` `serial` stream | `[MEGA/GANTRY …]` |
| Mock (`--mock`) | `rig/mock_feeder.py` → `MockFeeder` | `rig/mock_board.py` → `MockBoard` |

**Port configuration is deliberate and manual.** `feeder.port` ships empty
(`""`). Real-rig startup raises with setup instructions until you put the Uno's
stable path there:

```bash
ls -l /dev/serial/by-id/          # on the Pi
# put the Uno's full by-id path in feeder.port, the Mega's in serial.port
```

`app.py` additionally refuses to start if `feeder.port` and `serial.port` name
the same device. Never distinguish the boards by `/dev/ttyACM0` / `ttyACM1`
enumeration order.

---

## 3. The guard stack

Every production placement passes through five layers, outermost first. Each one
can refuse; none can be skipped by the browser.

| Layer | File | Refuses when |
| --- | --- | --- |
| HTTP route | `web/routes_command.py` `build()` | not `confirm=true`; command string ≠ the server's own `controller.command`; stale camera; `job.running`; session `LOCKED`; **either board not `connected`** |
| Build worker | `rig/build_job.py` `BuildJob` | a build is already on the worker thread (one at a time, off the event loop) |
| Safety state | `rig/build_controller.py` `BuildController` | `locked`; no cell selected. Holds selection/level/mode; converts any exception below into a session lock |
| Two-board handoff | `rig/orchestrator.py` `CellOrchestrator` | its own `locked_reason` is set; another `place_block` already owns the pickup lock |
| Serial clients | `Feeder` / `Rig` | overlapping transaction (`FeederBusy` / `Rig._inflight`); not connected; identity wrong |

`BuildController.build()` calls `orchestrator.place_block()` in production
(injected by the lifespan). A direct `rig.build()` path still exists for
calibration/commissioning, where a human is responsible for staging a block.

---

## 4. The FEED → BUILD sequence

One placement is **one indivisible Pi-owned operation**: stage exactly one block
on the Uno, then — only on its exact terminal success — place it with the Mega.

```text
Pi (CellOrchestrator.place_block)          Uno (belt_v1)              MEGA (build_test_v1)
  phase=feeding
  Feeder.feed(timeout=45s) ───── FEED <id> ──▶
                              ◀── @id RECV cmd=FEED
                              ◀── @id ACK cmd=FEED accepted=1
                              ◀── @id STATE state=closing … moving_to_stage … verifying_stage
                              ◀── @id EVENT phase=…            (progress telemetry only)
                              ◀── @id OK state=block_ready result=staged      ← the ONLY success
  phase=ready_for_pick
  phase=placing
  Rig.build(col,row,level) ───────────────────────────────── B <col> <row> <level> ──▶
                                                          ◀── @seq RECV cmd=B …
                                                          ◀── @seq STEP step=n/14 phase=… status=begin
                                                          ◀── @seq OK col=… row=… level=…            ← PLACED
  phase=complete → BuildResult(PLACED)
```

Hard rules (enforced in `orchestrator.py` and `feeder.py`):

- **Only** a terminal `@id OK state=block_ready result=staged` whose `id` matches
  the request authorizes `B`. `ACK` / `STATE` / `SENSOR` / `EVENT` are progress,
  never success. A terminal with the wrong `id` is ignored.
- A malformed success (`result=` anything else) is treated as **failure**, not
  permission.
- On any Uno error / timeout / disconnect / reset before `OK`: **no `B` is
  sent**, the orchestrator locks, `BuildResult` is `ABORTED`.
- After `B` is sent, a non-`PLACED` Mega result (`SAFE`/`REJECTED`, `HELD`,
  timeout, disconnect) also **locks** — a block was already staged, so feeding
  another would double-load the pickup point. This is why a Mega `REJECTED`,
  which is "safe" for a bare gantry, is `aborted` + `LOCKED` inside a cell
  operation.
- One `FEED` at a time; the next `FEED` never starts until the prior `B`
  returns terminal `PLACED`.

### Stop / cancel semantics

| When the operator stops | What happens |
| --- | --- |
| `cell_phase` is `feeding` or `staging` | `POST /api/stop` → `orchestrator.cancel()` → `Feeder.stop()` sends Uno `STOP`; the feed waiter observes `@id ERROR … reason=cancelled`; session locks for inspection |
| `cell_phase` is `placing` (Mega moving) | stop is **stop-after-current only**. The Mega does not read serial inside `buildBlock()`. The in-flight block finishes; no next `FEED`/`B` is issued |

There is no software emergency stop for Mega motion. See
[mega-pi-communication-audit.md](mega-pi-communication-audit.md) §12.

---

## 5. Result and lock behavior

`CellOrchestrator` returns a `rig.link.BuildResult`; `str(result)` ∈
`{"placed", "rejected", "aborted"}`. `BuildController` maps that to session
state.

| Outcome | `last_result` | `build_state` | Selection | Recovery |
| --- | --- | --- | --- | --- |
| Uno staged + Mega `OK` | `placed` | `READY` | cleared | continue |
| Uno error / timeout / reset / disconnect / malformed OK (before `B`) | `aborted` | `LOCKED` | kept | inspect pickup area, **restart the service** |
| Uno OK, then Mega `SAFE`/`REJECTED` | `aborted` | `LOCKED` | kept | a block is staged — inspect, then restart |
| Uno OK, then Mega `HELD` / timeout / cable loss | `aborted` | `LOCKED` | kept | machine state unknown — inspect, restart |
| Operator `STOP` during feed | `aborted` (`reason` contains `cancelled`) | `LOCKED` | kept | inspect, restart |

`LOCKED` is intentionally sticky: a new service process is the required recovery.
Nothing is auto-retried, because a retried `FEED` or `B` risks a double-load or
duplicate placement.

---

## 6. What the browser sees

The browser is a mirror. It sends `POST /api/build {confirm, command}` and
`POST /api/stop`, and it renders whatever `/api/state` + `/api/events` report.

New/relevant `StateModel` fields (`python/web/state.py`):

| Field | Meaning |
| --- | --- |
| `gantry_connected`, `feeder_connected` | per-board link state; shown as the **Gantry** / **Feeder** chips in `StatusBar` |
| `hardware_ready` | `gantry_connected and feeder_connected`; **BUILD is disabled unless true** |
| `cell_phase` | `idle → feeding → staging → ready_for_pick → placing → complete / error` — drives the `BuildBanner` copy |
| `feeder_transaction_id` | the active Uno request id |
| `feeder_state` | the Uno's last authoritative `STATE` (`closing`, `moving_to_stage`, …) |
| `feeder_error` | last Uno error string, if any |

`/api/events` fact types (`python/web/events.py`, all durable except `state`):

| `type` | Carries |
| --- | --- |
| `feeder` | one parsed Uno line: `request_id`, `message_type`, `fields` |
| `serial` | one board-labelled raw line, `stream` ∈ `rig` / `feeder` / `error` |
| `build_step` | one Mega build phase (`step`, `total`, `phase`, `status`, `eta_ms`, …) |
| `build_result` | one settled placement (`result`, `locked`, `locked_reason`, …) |
| `state` | the whole `StateModel` snapshot (coalesced) |
| `heartbeat` / `replay` | liveness id / reconnect envelope |

Ordering guarantee: for one placement, the matching `feeder` `OK` event is
delivered before any `build_step` and before the `build_result`.

---

## 7. How the two entry points use the sequence

**Click-to-build** (`web/src/components/BuildButton.tsx`, console): operator taps
a camera cell → server computes `B c r l` → operator taps **BUILD** then
**CONFIRM** → `POST /api/build` → the guard stack above runs one
`CellOrchestrator.place_block`. `PLACED` clears the selection; anything else
locks. BUILD is greyed unless `hardware_ready`.

**Studio runner** (`web/src/studio/runner.ts` + `RunnerPanel.tsx`): compiles a
model to an ordered program of `mode` / `select` / `build` effects and dispatches
**one guarded `/api/build` at a time**, waiting for the durable `build_result`
before the next. Each `build` effect is the same full FEED→BUILD operation
server-side. The panel's next-block colour line is a *preview only* — it never
implies a second feed is running, because the orchestrator will not start the
next `FEED` until the current `B` is terminal. "STOP AFTER THIS BLOCK" becomes
"CANCEL FEED" (calling `POST /api/stop`) while `cell_phase` is `feeding`/
`staging`.

---

## 8. Configure, run, and test both boards

**Configure** — `config/rig.json`:

```jsonc
"serial": { "port": "/dev/serial/by-id/…-Mega…", "baud": 9600 },
"feeder": { "port": "/dev/serial/by-id/…-Uno…", "baud": 9600,
            "firmware": "belt_v1", "protocol": 2,
            "fqbn": "arduino:avr:uno", "sketch": "arduino/belt_v1" }
```

**Flash** (`scripts/flash.sh`, reads both roles from that file):

```bash
./scripts/flash.sh boards            # what's on USB
./scripts/flash.sh gantry upload     # Mega
./scripts/flash.sh feeder compile    # Uno syntax check
./scripts/flash.sh feeder upload     # Uno
./scripts/flash.sh all compile       # both syntax checks
```

**Bench-check the Uno** without the server (`python/feeder_console.py`, same
`Feeder` client the server uses):

```bash
.venv/bin/python python/feeder_console.py status
.venv/bin/python python/feeder_console.py feed     # one block, expect final OK
```

Full step-by-step in [feeder-controller.md](feeder-controller.md) §Commissioning.

**Automated tests** (no hardware):

```bash
PYTHONPATH=python .venv/bin/python -m pytest \
  python/tests -k "web or link or mock_board or feeder or orchestrator"
cd web && npm test -- --run
```

- `python/tests/feeder_test.py` — Uno protocol parse, `READY` identity,
  id correlation, reset/cancel, malformed-success rejection.
- `python/tests/orchestrator_test.py` — the pickup invariant: every block is
  `FEED` terminal `OK` then Mega `B`; any feed failure never calls the Mega;
  a post-staging Mega non-success locks.
- `python/tests/web_command_test.py`, `web_events_test.py` — the full path
  through FastAPI with `MockFeeder` + `MockBoard`.

**Run for real** (`docs/server-guide.md`): one backend process, no `--mock`; it
opens and validates **both** ports before accepting traffic. If either fails,
stop and fix `config/rig.json` — do not start a second process.

---

## 9. Known limits

- The Mega `@seq STEP`/ACK firmware is compile-verified but, per
  [ack-protocol.md](ack-protocol.md), **has not been flashed**; `link.py` still
  has a loud prose fallback. The Uno protocol-2 firmware is likewise
  syntax-checked only — physical commissioning is still required.
- No hardwired emergency stop, watchdog, or Mega mid-motion interrupt exists.
- The Mega does not correlate `B` to a Pi-supplied id (it uses its own
  counter); the Uno does correlate to the Pi's `FEED <id>`.
