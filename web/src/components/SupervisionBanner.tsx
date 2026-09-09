import type { StateModel, Supervision, SupervisionVerdict } from "../types";
import { CorrectionControl } from "./CorrectionControl";

/** DESIGN.md §4's shape vocabulary, extended by two. Never colour alone: every
 *  state carries a WORD and a SHAPE, because video sits behind half of these
 *  and glare eats saturation. */
const SHAPE: Record<string, string> = {
  VERIFIED: "●",       // ● seen
  NOT_DETECTED: "▲",   // ▲ attention
  REMOVED: "▲",
  MOVED: "▲",
  DISPLACED: "▲",
  FOREIGN: "■",        // ■ stop
  DISAGREES: "■",
  WARMING: "◐",        // ◐ settling
  BUSY: "○",           // ○ idle
  QUIET: "○",
  NO_MEMORY: "○",
  NO_VISION: "○",      // ○ not a fault of the board — the camera pipeline
  NO_MAP: "▲",
};
const icon = (key: string | null) => (key && SHAPE[key]) || "▲";

function cell([col, row]: [number, number]) { return `[${col},${row}]`; }
function list(cells: [number, number][]) { return cells.map(cell).join(" "); }

/** §6.9: name the cell in the first four words, say what the operator should
 *  DO, and never say "error" for something the machine may have got right.
 *  The banner is the authoritative text — the overlay alone is not enough.
 *
 *  When the server has judged a claw pick safe (`correctable`), the wording
 *  points at the RETURN BLOCK TO CELL control rather than implying the only fix
 *  is by hand. */
function sentence(supervision: Supervision): string {
  const cells = supervision.cells as [number, number][];
  const first = cells.length ? cell(cells[0]) : "";
  const canClaw = supervision.correctable === true;
  switch (supervision.verdict as SupervisionVerdict) {
    case "REMOVED":
      return cells.length > 1
        ? `${list(cells)} are gone — blocks the plan placed are no longer on the board. Put them back, or dismiss to continue without them.`
        : `${first} — a block the plan placed is gone. Put it back, or dismiss to continue without it.`;
    case "NOT_DETECTED":
      return `${first} — the block just placed was not seen. The run is paused.`;
    case "MOVED":
      return canClaw
        ? `${cell(cells[0])} → ${cell(cells[1] ?? cells[0])} — a block is on the wrong cell. Return it with the claw, straighten it by hand, or dismiss. The run is paused.`
        : `${cell(cells[0])} → ${cell(cells[1] ?? cells[0])} — the board no longer matches the plan at two cells. Straighten it by hand, or dismiss. The run is paused.`;
    case "DISPLACED":
      return canClaw
        ? `${first} — a block was knocked off its cell into a gap. Return it with the claw, straighten it by hand, or dismiss. The run is paused.`
        : `${first} — a block was knocked off its cell and is sitting in a gap, not on a site. Straighten it by hand, or dismiss to continue. The run is paused.`;
    case "FOREIGN":
      return cells.length
        ? `${list(cells)} — something is on a cell the plan did not fill. Clear it, then acknowledge.`
        : "A block is on the board and not on any cell. Clear it, then acknowledge.";
    case "DISAGREES":
      return `Too much changed at once to name a cause — ${supervision.cells.length} cells differ. Expected and observed are below.`;
    default:
      return "";
  }
}

/** What supervision says when it is NOT judging. None of these is a fault, and
 *  three of them take no state colour at all: BUSY is the normal condition for
 *  the whole of a build, and an amber console during every build would spend
 *  the reserved palette on nothing. Not looking is not finding something wrong. */
function statusLine(supervision: Supervision): string {
  if (supervision.state === "NO_MEMORY")
    return "NO MEMORY — the board is only tracked from the first build after a restart.";
  if (supervision.state === "NO_MAP")
    return "NO MAP — calibrate to enable board checks.";
  if (supervision.state === "WARMING") return "SETTLING — gathering evidence.";
  if (supervision.state === "NO_VISION")
    return supervision.reason
      ?? "NO VISION — the detector could not read this frame. The board is not being checked.";
  if (supervision.state === "BUSY") return supervision.reason ?? "NOT WATCHING";
  return "WATCHING";
}

export function SupervisionBanner({ state, onAcknowledge, onCorrect, quiet = false }: {
  state: StateModel;
  onAcknowledge: () => void;
  onCorrect?: () => void;
  /** `#/build` sets this: suppress the calm "WATCHING" / "SETTLING" / "NO
   *  MEMORY" strip so the spare screen is not carrying chrome. A real verdict
   *  and the genuinely-degraded `NO MAP` still show. */
  quiet?: boolean;
}) {
  const supervision = state.supervision;
  if (!supervision) return null;

  // The operator (or a crash) switched supervision off: every surface it feeds
  // goes quiet. A crash leaves one dim line so the toolbar toggle is not the
  // only sign; a deliberate OFF says nothing at all.
  if (state.supervision_enabled === false) {
    if (!state.supervision_fault) return null;
    return (
      <p className="sv-status sv-faint" role="status" aria-live="polite">
        <span aria-hidden="true">○</span>{" "}
        SUPERVISOR OFF — stopped after an error: {state.supervision_fault}.{" "}
        Re-enable from the camera toolbar.
      </p>
    );
  }

  // VERIFIED gets NO banner, deliberately. A 40-block build would produce 40
  // green bars, and a console that celebrates every success trains the
  // operator to ignore it — and then the one amber bar that matters is ignored
  // too. The good case lives in the log row and one brief cell pulse.
  const verdict = supervision.verdict;
  const loud = verdict !== null && verdict !== "VERIFIED" && !supervision.acknowledged;

  if (!loud) {
    if (quiet && supervision.state !== "NO_MAP") return null;
    // NO_MAP is genuinely degraded and takes amber. Everything else here is
    // --text-dim / --text-faint and says only what it is doing.
    const dim = supervision.state === "NO_MEMORY" || supervision.state === "BUSY"
      || supervision.state === "QUIET" || supervision.state === "WARMING"
      || supervision.state === "NO_VISION";
    if (!dim && supervision.state !== "NO_MAP") return null;
    return (
      <p className={`sv-status${supervision.state === "NO_MEMORY" ? " sv-faint" : ""}`}
         role="status" aria-live="polite">
        <span aria-hidden="true">{icon(supervision.state)}</span>{" "}
        {statusLine(supervision)}
        {supervision.unjudged.length > 0 && (
          <span className="sv-limits">
            {" "}UNCHECKED {supervision.unjudged.length} cells above the detection ceiling
          </span>
        )}
      </p>
    );
  }

  const red = supervision.severity === "red";
  const cells = supervision.cells as [number, number][];
  const label = cells.length
    ? `Acknowledge ${verdict} at ${cells.map(([col, row]) => `column ${col} row ${row}`).join(", ")}`
    : `Acknowledge ${verdict}`;
  const showCorrection = verdict === "MOVED" || verdict === "DISPLACED";

  return (
    <section
      className={`banner supervision sv-${supervision.severity}`}
      role={red ? "alert" : "status"}
      aria-live={red ? "assertive" : "polite"}
    >
      <span className="sv-chip">
        <span aria-hidden="true">{icon(verdict)}</span> {verdict!.replace("_", " ")}
      </span>

      <div className="sv-body">
        <span className="sv-sentence">{sentence(supervision)}</span>
        {verdict === "DISAGREES" && (
          <span className="sv-sets">
            expected {list(supervision.expected as [number, number][]) || "none"}
            {" · "}
            observed {list(supervision.observed as [number, number][]) || "none"}
          </span>
        )}
        {supervision.unjudged.length > 0 && (
          <span className="sv-limits">
            UNCHECKED {supervision.unjudged.length} cells above the detection ceiling
          </span>
        )}
        {/* CORRECTION (docs/features/correction-action.md). Only for MOVED /
            DISPLACED, and only when the SERVER says the pick is safe — otherwise
            the reason is shown so the operator knows why there is no button. The
            browser never derives `correctable`; the route re-checks server-side. */}
        {showCorrection && (
          supervision.correctable
            ? <CorrectionControl supervision={supervision}
                                 onCorrect={onCorrect ?? (() => {})} />
            : supervision.correction_reason
              ? <span className="sv-correct-why">
                  Cannot return it by claw: {supervision.correction_reason}
                </span>
              : null
        )}
      </div>

      {/* Dismiss: a real button, ≥ 44 × 44, named for the CELL rather than
          "dismiss". It is last in the markup — dismissing is always safe, so it
          never sits ahead of the correction control in tab order. */}
      <button type="button" className="sv-ack" aria-label={label} onClick={onAcknowledge}>
        {red ? "ACKNOWLEDGE" : "DISMISS"}
      </button>
    </section>
  );
}
