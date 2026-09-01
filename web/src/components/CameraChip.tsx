import { Icon } from "./Icon";
import type { StateModel } from "../types";

const ICON = { LIVE: "live", STALE: "stale", WAITING: "waiting" } as const;
const TONE = { LIVE: "is-ready", STALE: "is-motion", WAITING: "is-idle" } as const;

/** Camera freshness with the frame age, so a stalling pipeline is visible
 *  before the server starts refusing selections. */
export function CameraChip({ state }: { state: StateModel }) {
  return (
    <span className={`chip ${TONE[state.camera]}`}>
      <Icon name={ICON[state.camera]} size={13} />
      {state.camera}
      {state.camera_age_ms !== null && (
        <span className="value">{state.camera_age_ms.toLocaleString()}ms</span>
      )}
    </span>
  );
}
