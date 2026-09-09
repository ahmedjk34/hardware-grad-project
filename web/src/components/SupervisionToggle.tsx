import * as api from "../api";
import { Icon } from "./Icon";
import type { StateModel } from "../types";

/**
 * The operator kill switch for placement supervision (D14). One button, the
 * same behaviour everywhere it appears: pressed = supervision on, one click
 * flips it, never disabled, talks to `/api/supervision/enabled`. Rendered in
 * the console's camera toolbar (next to DETECT) and in building mode's top
 * bar, so the operator can always find it whichever screen they are on.
 */
export function SupervisionToggle({ state, className = "toggle" }: {
  state: StateModel;
  className?: string;
}) {
  const on = state.supervision_enabled !== false;
  const faulted = !on && !!state.supervision_fault;
  return (
    <button
      type="button"
      className={`${className} sv-toggle${faulted ? " is-faulted" : ""}`}
      aria-pressed={on}
      aria-label={on ? "Turn placement supervision off" : "Turn placement supervision on"}
      title={faulted
        ? `Supervision stopped after an error: ${state.supervision_fault}. Click to restart it.`
        : on
          ? "Placement supervision is on — banner, runner board, activity log and twin overlay are live"
          : "Placement supervision is off — no board checks, no corrections"}
      onClick={() => void api.setSupervisionEnabled(!on)}
    >
      <Icon name="power" size={15} />
      supervisor
    </button>
  );
}
