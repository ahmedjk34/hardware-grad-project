import { useEffect, useState } from "react";
import type { StateModel } from "../types";

export function BuildBanner({ state, connected }: { state: StateModel; connected: boolean }) {
  const running = state.build_state === "RUNNING";
  const [started, setStarted] = useState(() => Date.now());
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!running) return;
    setStarted(Date.now());
    setElapsed(0);
  }, [running]);

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [running, started]);

  if (state.build_state === "LOCKED") return (
    <section className="banner locked" role="alert">
      <strong>SESSION LOCKED</strong>
      <span className="detail">
        {state.locked_reason}. A human must inspect the rig and restart the service.
      </span>
    </section>
  );

  if (running) return (
    <section className="banner running" role="status">
      {!connected ? (
        <>
          <strong>DISCONNECTED</strong>
          <span className="detail">a build may still be in progress; do not touch the rig.</span>
        </>
      ) : (
        <>
          <strong>RIG MOVING</strong>
          <span className="detail">The rig is moving and cannot be interrupted</span>
          <span className="elapsed">{elapsed}s</span>
        </>
      )}
    </section>
  );

  return null;
}
