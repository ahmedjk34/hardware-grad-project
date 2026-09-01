import { useEffect, useState } from "react";
import * as api from "../api";
import { Icon } from "./Icon";
import type { StateModel } from "../types";

const CONFIRM_MS = 3000;
const TICK_MS = 100;

export function BuildButton({ state, connected }: { state: StateModel; connected: boolean }) {
  const [confirming, setConfirming] = useState(false);
  const [remaining, setRemaining] = useState(CONFIRM_MS);
  const allowed = connected && state.selected !== null && state.camera === "LIVE"
    && state.build_state === "READY" && !!state.command;

  useEffect(() => {
    if (!confirming) return;
    setRemaining(CONFIRM_MS);
    const deadline = Date.now() + CONFIRM_MS;
    const tick = window.setInterval(() => setRemaining(Math.max(0, deadline - Date.now())), TICK_MS);
    const timer = window.setTimeout(() => setConfirming(false), CONFIRM_MS);
    return () => { clearInterval(tick); clearTimeout(timer); };
  }, [confirming]);

  useEffect(() => { if (!allowed) setConfirming(false); }, [allowed]);

  if (confirming) return (
    <div className="build-block">
      <button
        type="button"
        className="btn btn-build armed"
        onClick={() => {
          if (state.command) void api.build(state.command);
          setConfirming(false);
        }}
      >
        CONFIRM {state.command}
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
        : <p className="reason"><Icon name="power" size={14} />Two taps to run · ~40s uninterruptible</p>}
    </div>
  );
}
