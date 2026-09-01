import type { StateModel } from "../types";

const GLYPH = { LIVE: "●", STALE: "▲", WAITING: "◌" } as const;
const TONE = { LIVE: "is-ready", STALE: "is-motion", WAITING: "is-idle" } as const;

/** Camera freshness, with the frame age so a slow pipeline is visible. */
export function CameraChip({ state }: { state: StateModel }) {
  return (
    <span className={`chip ${TONE[state.camera]}`}>
      <span className="glyph" aria-hidden="true">{GLYPH[state.camera]}</span>
      {state.camera}
      {state.camera_age_ms !== null && (
        <span className="value">{state.camera_age_ms.toLocaleString()}ms</span>
      )}
    </span>
  );
}
