import { useEffect, useState } from "react";
import * as api from "../api";
import { Icon } from "./Icon";
import type { StateModel } from "../types";

const CONFIRM_MS = 3000;
const TICK_MS = 100;

export function BuildButton({ state, connected, onBuild, onManualClose }: {
  state: StateModel;
  connected: boolean;
  /** Runner STEP mode reuses this exact two-tap affordance, but owns the effect. */
  onBuild?: (command: string) => void;
  /** Called only after the firmware reports the claw is down and open. */
  onManualClose?: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [remaining, setRemaining] = useState(CONFIRM_MS);
  const allowed = connected && state.gantry_connected && state.selected !== null && state.camera === "LIVE"
    && state.build_state === "READY" && !!state.command;

  const submit = () => {
    if (!state.command) return;
    if (onBuild) onBuild(state.command);
    else void api.build(state.command);
    setConfirming(false);
  };

  useEffect(() => {
    if (!confirming) return;
    setRemaining(CONFIRM_MS);
    const deadline = Date.now() + CONFIRM_MS;
    const tick = window.setInterval(() => setRemaining(Math.max(0, deadline - Date.now())), TICK_MS);
    const timer = window.setTimeout(() => setConfirming(false), CONFIRM_MS);
    return () => { clearInterval(tick); clearTimeout(timer); };
  }, [confirming]);

  useEffect(() => { if (!allowed) setConfirming(false); }, [allowed]);

  if (state.cell_phase === "awaiting_manual_close") return (
    <div className="build-block manual-close-block" role="status" aria-live="polite">
      <p className="manual-staging-note">Claw is down and open. Align the block, then close it when ready.</p>
      <button type="button" className="btn btn-build armed"
              onClick={() => onManualClose ? onManualClose() : void api.closeManualPick()}>
        CLOSE CLAW
      </button>
    </div>
  );

  if (confirming) return (
    <div className="build-block">
      <p className="manual-staging-note" role="note">
        Place one block in the pickup area before continuing.
      </p>
      <button type="button" className="btn btn-build armed"
              aria-label={`CONFIRM ${state.command}`}
              disabled={!allowed} onClick={submit}>
        CONFIRM BLOCK STAGED · {state.command}
        <span
          className="arm-drain"
          aria-hidden="true"
          style={{ transform: `scaleX(${remaining / CONFIRM_MS})` }}
        />
      </button>
      <p className="reason" aria-hidden="true">
        <Icon name="clock" size={14} />
        Arm expires in {Math.ceil(remaining / 1000)}s — tap again to move the rig
      </p>
    </div>
  );

  const reason = !connected ? "Disconnected"
    : !state.gantry_connected ? "Mega gantry is disconnected"
    : state.build_state !== "READY" ? "Rig is unavailable"
    : !state.selected ? "Select a cell first"
    : state.camera !== "LIVE" ? "Camera is not live"
    : "";

  return (
    <div className="build-block">
      <button type="button" className="btn btn-build" title={reason} disabled={!allowed} onClick={() => setConfirming(true)}>
        BUILD
      </button>
      {reason
        ? <p className="reason"><Icon name="lock" size={14} />{reason}</p>
        : <p className="reason"><Icon name="power" size={14} />Confirm the block is staged at pickup · ~40s uninterruptible</p>}
    </div>
  );
}
