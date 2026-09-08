# Browser → Pi → Mega communication pipeline

The production rig has one runtime serial device: the Arduino Mega running
`arduino/build_test_v1/build_test_v1.ino`. The Raspberry Pi owns that port for
the FastAPI service lifetime. The browser never writes serial directly.

```text
React console / Studio
        |
        | guarded HTTP requests + event stream
        v
FastAPI: BuildController + BuildJob + PickupCoordinator
        |
        | one operation lock, Mega USB serial at config serial.baud
        v
Arduino Mega: X/Y/Z, claw, rotation and placement
```

## One placement

1. The operator selects a normal build cell. `[0,0]` is the reserved physical
   pickup cell and cannot be selected as a target.
2. Camera freshness, selection, level, mode, occupancy, supervision and
   one-at-a-time guards run before the build can be armed.
3. The UI requires a second explicit action confirming that one block is
   physically staged at pickup.
4. `PickupCoordinator` acquires the pickup operation lock and the Pi sends
   `M <col> <row> <level>` to the Mega.
5. The Mega homes/approaches pickup and descends with the claw open. It emits
   `phase=await_manual_close` and waits. An early `/api/manual-close` request is
   rejected; only this firmware event enables the UI's `CLOSE CLAW` action.
6. The Pi sends the single `C`. The Mega grips, carries, rotates if required,
   places, releases and parks, reporting its normal phase stream and exactly
   one terminal result.
7. A terminal `placed` updates the placement ledger and clears selection. A
   refusal or unknown result after manual staging locks the session for human
   inspection because pickup/claw state may be unknown.

Mega motion is not interruptible. “Stop after this block” is a browser runner
policy and never claims to stop an in-flight placement.

## State and events

Hardware readiness depends on the Mega connection alone. Current cell phases
are `idle`, `manual_staging_confirmed`, `placing`,
`awaiting_manual_close`, `complete`, and `error`. The durable event stream
carries `serial`, `build_step`, and `build_result` events; camera/state
snapshots are coalesced.

## Configuration and flashing

`config/rig.json` owns `serial.port`, `serial.baud`, `board.fqbn`, and
`board.sketch`. Compile without uploading hardware:

```bash
./scripts/flash.sh compile
```

Use `./scripts/flash.sh` or `./scripts/flash.sh upload` only when an upload is
intended. The script never embeds a device path.

## Grid rules

Every in-range, reachable cell except `[0,0]` is an ordinary candidate build
cell. There is no configurable forbidden-cell list. Range, geometric fit,
travel, tool-offset, level, occupancy and correction checks remain in force.

