import { useEffect, useState } from "react";
import * as api from "../api";
import { Icon } from "./Icon";
import type { StateModel } from "../types";
import type { FeedMode } from "../api";

const CONFIRM_MS = 3000;
const TICK_MS = 100;

export function BuildButton({ state, connected, onBuild }: {
  state: StateModel;
  connected: boolean;
  /** Runner STEP mode reuses this exact two-tap affordance, but owns the effect. */
  onBuild?: (command: string, feedMode: FeedMode) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [remaining, setRemaining] = useState(CONFIRM_MS);
  const automaticAllowed = connected && state.hardware_ready;
  const manualAllowed = connected && state.gantry_connected;
  const allowed = (automaticAllowed || manualAllowed) && state.selected !== null && state.camera === "LIVE"
    && state.build_state === "READY" && !!state.command;

  const submit = (feedMode: FeedMode) => {
    if (!state.command) return;
    if (onBuild) onBuild(state.command, feedMode);
    else if (feedMode === "manual") void api.build(state.command, "manual");
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

  if (confirming) return (
    <div className="build-block">
      <p className="manual-feed-note" role="note">
        For manual feed, place one block in the pickup area before continuing.
      </p>
      <button type="button" className="btn btn-build armed"
              aria-label={`CONFIRM ${state.command}`}
              disabled={!automaticAllowed} onClick={() => submit("automatic")}>
        CONFIRM {state.command} · USE FEEDER
        <span
          className="arm-drain"
          aria-hidden="true"
          style={{ transform: `scaleX(${remaining / CONFIRM_MS})` }}
        />
      </button>
      <button type="button" className="btn btn-manual-feed"
              disabled={!manualAllowed} onClick={() => submit("manual")}>
        FEED MANUALLY
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
        : <p className="reason"><Icon name="power" size={14} />Confirm, then choose feeder or manual pickup · ~40s uninterruptible</p>}
    </div>
  );
}
