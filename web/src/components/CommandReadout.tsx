import type { StateModel } from "../types";

/** The exact string that will be sent to the Mega. The well never collapses,
 *  so picking a cell cannot make the layout jump. */
export function CommandReadout({ state }: { state: StateModel }) {
  const command = state.command;
  return (
    <div className={`readout${command ? "" : " empty"}`}>
      <div className="command">{command ?? "— — —"}</div>
      <div className="decoded">
        {command && state.selected
          ? `column ${state.selected[0]} · row ${state.selected[1]} · level ${state.level}`
          : "no cell selected"}
      </div>
    </div>
  );
}
