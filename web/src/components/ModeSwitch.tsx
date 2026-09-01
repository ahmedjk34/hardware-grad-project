import { useState } from "react";
import * as api from "../api";
import { Icon } from "./Icon";
import type { StateModel } from "../types";

const MODES: ("vertical" | "horizontal")[] = ["vertical", "horizontal"];

/** Changing mode homes the X and Y axes — physical motion, never a silent toggle. */
export function ModeSwitch({ state, disabled }: { state: StateModel; disabled: boolean }) {
  const [pending, setPending] = useState<"vertical" | "horizontal" | null>(null);

  return (
    <section className="panel">
      <header><h2><Icon name="axes" size={13} />Grid mode</h2></header>

      <div className="segmented" role="group" aria-label="Grid mode">
        {MODES.map(mode => (
          <button
            key={mode}
            type="button"
            className="btn"
            aria-pressed={state.mode === mode}
            disabled={disabled || state.mode === mode}
            onClick={() => setPending(mode)}
          >
            {mode}
          </button>
        ))}
      </div>

      {pending && (
        <>
          <p className="confirm-note" role="status">
            <Icon name="stale" size={15} />
            <span>
              Switching to {pending.toUpperCase()} homes the X and Y axes and clears your
              selection. The rig will move.
            </span>
          </p>
          <div className="row">
            <button
              type="button"
              className="btn"
              disabled={disabled}
              onClick={() => { void api.mode(pending); setPending(null); }}
            >Home and switch</button>
            <button type="button" className="btn btn-ghost" disabled={disabled} onClick={() => setPending(null)}>
              Keep {state.mode}
            </button>
          </div>
        </>
      )}
    </section>
  );
}
