import { useEffect, useState } from "react";
import { CameraChip } from "./CameraChip";
import type { StateModel } from "../types";

function clock(seconds: number) {
  const parts = [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60];
  return parts.map(part => String(part).padStart(2, "0")).join(":");
}

export function StatusBar({ state, connected }: { state: StateModel; connected: boolean }) {
  const [started] = useState(() => Date.now());
  const [uptime, setUptime] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setUptime(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [started]);

  return (
    <header className="status-rail" aria-label="Rig status">
      <span className="rig-name">Rig console</span>
      <span className="chip">
        {state.mode}
        <span className="value">{state.cols}×{state.rows}</span>
      </span>
      <span className={`chip ${state.calibrated ? "is-ready" : "is-motion"}`}>
        <span className="glyph" aria-hidden="true">{state.calibrated ? "●" : "▲"}</span>
        {state.calibrated ? "Calibrated" : "Approximation only"}
      </span>
      <CameraChip state={state} />
      <span className={`chip ${connected ? "is-ready" : "is-danger"}`}>
        <span className="glyph" aria-hidden="true">{connected ? "●" : "■"}</span>
        Socket
        <span className="value">{connected ? "up" : "down"}</span>
      </span>
      <span className="chip">
        Level<span className="value">{state.level}</span>
      </span>
      <span className="chip">
        Uptime<span className="value">{clock(uptime)}</span>
      </span>
    </header>
  );
}
