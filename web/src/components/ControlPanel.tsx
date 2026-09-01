import * as api from "../api";
import type { StateModel } from "../types";
import { BuildButton } from "./BuildButton";
import { CommandReadout } from "./CommandReadout";
import { LevelStepper } from "./LevelStepper";

export function ControlPanel({ state, connected, onBuild: _onBuild, primaryElsewhere = false }: {
  state: StateModel;
  connected: boolean;
  onBuild: () => void;
  /** True on phones, where the readout, stepper and BUILD live in the action sheet. */
  primaryElsewhere?: boolean;
}) {
  const mutable = connected && state.build_state === "READY";
  return (
    <aside className="panel controls" aria-label="Rig controls">
      <header>
        <h2>Target</h2>
        <span className={`chip ${state.calibrated ? "is-ready" : "is-motion"}`}>
          {state.calibrated ? "Calibrated" : "Approximate"}
        </span>
      </header>
      {!primaryElsewhere && (
        <>
          <CommandReadout state={state} />
          <LevelStepper level={state.level} disabled={!mutable} />
        </>
      )}
      <button type="button" className="btn" disabled={!mutable} onClick={() => void api.deselect()}>Deselect</button>
      {!primaryElsewhere && <BuildButton state={state} connected={connected} />}
    </aside>
  );
}
