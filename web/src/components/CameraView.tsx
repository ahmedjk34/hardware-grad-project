import { useState } from "react";
import * as api from "../api";
import { GridOverlay } from "./GridOverlay";
import { Icon } from "./Icon";
import type { CellGeometry, StateModel } from "../types";

const VIEWS: { key: string; icon: string; label: string }[] = [
  { key: "grid", icon: "grid", label: "grid" },
  { key: "detect", icon: "detect", label: "detect" },
  { key: "paper", icon: "sheet", label: "sheet" },
  { key: "overlay", icon: "overlay", label: "overlay" },
];

export function CameraView({ state, connected, onCalibrationPoint }: {
  state: StateModel;
  connected: boolean;
  onCalibrationPoint?: (point: [number, number], imageSize: [number, number]) => void;
}) {
  const [hover, setHover] = useState<CellGeometry | null>(null);
  const size = state.geometry?.image_size ?? ([1, 1] as [number, number]);
  const collecting = !!onCalibrationPoint;
  const selectable = collecting
    || (connected && state.build_state === "READY" && state.camera === "LIVE");

  const select = ([x, y]: [number, number]) => {
    if (onCalibrationPoint) onCalibrationPoint([x, y], size);
    else if (connected && state.build_state === "READY") void api.select(x, y, size[0], size[1]);
  };

  const shown = hover ?? state.geometry?.selected ?? null;
  const stageState = !connected ? "offline" : state.camera === "STALE" ? "stale" : "";

  return (
    <>
      {/* Display-only toggles: the server allows these while the rig is moving,
          so they are deliberately never disabled. */}
      <div className="stage-toolbar" role="group" aria-label="Overlay views">
        {VIEWS.map(item => {
          const active = state.views[item.key] !== false;
          return (
            <button
              key={item.key}
              type="button"
              className="toggle"
              aria-pressed={active}
              aria-label={`Toggle ${item.label} overlay`}
              onClick={() => void api.view({ [item.key]: !active })}
            >
              <Icon name={item.icon} size={15} />
              {item.label}
            </button>
          );
        })}
        <span className="spacer" />
        {collecting && (
          <span className="chip is-motion"><Icon name="ruler" size={13} />Collecting corners</span>
        )}
        <span className="chip is-idle">
          <Icon name="grid" size={13} />
          <span className="value">{state.cols}×{state.rows}</span>
        </span>
      </div>

      <div className="stage-area">
        <main
          className={`stage ${stageState}`}
          aria-label="Camera stage"
          style={{ ["--ar" as string]: `${size[0]} / ${size[1]}` }}
        >
          <div className="stage-frame">
            <img src="/api/stream.mjpg" alt="Live rig camera" />
            <GridOverlay state={state} onSelect={select} onHover={setHover} selectable={selectable} />
          </div>

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

          <div className="hud">
            <span className="label">Cell</span>
            <span className="cell">{shown ? `${shown.col},${shown.row}` : "—,—"}</span>
            <span className="label">Level</span>
            <span className="cell">{state.level}</span>
          </div>
        </main>
      </div>
    </>
  );
}
