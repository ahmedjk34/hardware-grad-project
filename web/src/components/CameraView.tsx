import { useState } from "react";
import * as api from "../api";
import { GridOverlay } from "./GridOverlay";
import type { CellGeometry, StateModel } from "../types";

const VIEWS: { key: string; glyph: string; label: string }[] = [
  { key: "grid", glyph: "⌗", label: "grid" },
  { key: "detect", glyph: "◎", label: "detect" },
  { key: "paper", glyph: "▦", label: "sheet" },
  { key: "overlay", glyph: "◐", label: "overlay" },
];

export function CameraView({ state, connected, onCalibrationPoint }: {
  state: StateModel;
  connected: boolean;
  onCalibrationPoint?: (point: [number, number], imageSize: [number, number]) => void;
}) {
  const [hover, setHover] = useState<CellGeometry | null>(null);
  const size = state.geometry?.image_size ?? ([1, 1] as [number, number]);
  const selectable = !onCalibrationPoint && connected && state.build_state === "READY" && state.camera === "LIVE";

  const select = ([x, y]: [number, number]) => {
    if (onCalibrationPoint) onCalibrationPoint([x, y], size);
    else if (connected && state.build_state === "READY") void api.select(x, y, size[0], size[1]);
  };

  const shown = hover ?? state.geometry?.selected ?? null;
  const stageState = !connected ? "offline" : state.camera === "STALE" ? "stale" : "";

  return (
    <main className={`stage ${stageState}`} aria-label="Camera stage">
      {/* The frame keeps the camera's aspect ratio so the SVG can never drift
          from the video, and is capped by viewport height so a portrait frame
          cannot push the log and rail off the bottom of a desktop screen. */}
      <div
        className="stage-frame"
        style={{
          aspectRatio: `${size[0]} / ${size[1]}`,
          maxWidth: `calc((100dvh - 14rem) * ${size[0] / size[1]})`,
        }}
      >
        <img src="/api/stream.mjpg" alt="Live rig camera" />
        <GridOverlay
          state={state}
          onSelect={select}
          onHover={setHover}
          selectable={selectable || !!onCalibrationPoint}
        />
        {state.camera === "WAITING" && (
          <div className="stage-plate waiting">
            <span className="scanline" aria-hidden="true" />
            WAITING FOR FIRST FRAME
            <span className="sub">The pipeline has not delivered a frame yet.</span>
          </div>
        )}
        {!connected && (
          <div className="stage-plate offline">
            DISCONNECTED
            <span className="sub">
              {state.build_state === "RUNNING"
                ? "A build may still be in progress; do not touch the rig."
                : "Reconnecting to the rig service…"}
            </span>
          </div>
        )}
      </div>

      <div className="hud">
        <span className="label">Cell</span>
        <span className="cell">
          {shown ? `[${shown.col},${shown.row}] · L${state.level}` : `— · L${state.level}`}
        </span>
      </div>

      <div className="view-chips" role="group" aria-label="Overlay views">
        {VIEWS.map(item => {
          const active = state.views[item.key] !== false;
          return (
            <button
              key={item.key}
              type="button"
              className="chip"
              aria-pressed={active}
              aria-label={`Toggle ${item.label} overlay`}
              onClick={() => void api.view({ [item.key]: !active })}
            >
              <span className="glyph" aria-hidden="true">{item.glyph}</span>
              {item.label}
            </button>
          );
        })}
      </div>
    </main>
  );
}
