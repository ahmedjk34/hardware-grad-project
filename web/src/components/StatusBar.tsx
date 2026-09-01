import { useEffect, useState } from "react";
import { CameraChip } from "./CameraChip";
import { Icon } from "./Icon";
import type { StateModel } from "../types";

function clock(seconds: number) {
  return [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60]
    .map(part => String(part).padStart(2, "0"))
    .join(":");
}

export function StatusBar({ state, connected }: { state: StateModel; connected: boolean }) {
  const [started] = useState(() => Date.now());
  const [uptime, setUptime] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(() => setUptime(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [started]);

  return (
    <header className="appbar" aria-label="Rig status">
      <span className="brand"><Icon name="target" size={16} />Rig console</span>

      <span className="chip">
        <Icon name="layers" size={13} />
        {state.mode}
        <span className="value">{state.cols}×{state.rows}</span>
      </span>

      <span className={`chip ${state.calibrated ? "is-ready" : "is-motion"}`}>
        <Icon name={state.calibrated ? "check" : "stale"} size={13} />
        {state.calibrated ? "Calibrated" : "Approximate"}
      </span>

      <CameraChip state={state} />

      <span className={`chip ${connected ? "is-ready" : "is-danger"}`}>
        <Icon name={connected ? "link" : "unlink"} size={13} />
        Socket
      </span>

      <span className="spacer" />

      <span className="chip">Level<span className="value">{state.level}</span></span>
      <span className="chip"><Icon name="clock" size={13} /><span className="value">{clock(uptime)}</span></span>
    </header>
  );
}
