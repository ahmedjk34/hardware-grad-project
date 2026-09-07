import { useEffect, useState } from "react";
import type { StateModel, Supervision, SupervisionVerdict } from "../types";

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
  NO_MAP: "▲",
};

function cell([col, row]: [number, number]) { return `[${col},${row}]`; }
function list(cells: [number, number][]) { return cells.map(cell).join(" "); }

/** §6.9: name the cell in the first four words, say what the operator should
 *  DO, and never say "error" for something the machine may have got right.
 *  The banner is the authoritative text — the overlay alone is not enough. */
function sentence(supervision: Supervision): string {
  const cells = supervision.cells as [number, number][];
  const first = cells.length ? cell(cells[0]) : "";
  switch (supervision.verdict as SupervisionVerdict) {
    case "REMOVED":
      return cells.length > 1
        ? `${list(cells)} are gone — blocks the plan placed are no longer on the board. Put them back, or dismiss to continue without them.`
        : `${first} — a block the plan placed is gone. Put it back, or dismiss to continue without it.`;
    case "NOT_DETECTED":
      return `${first} — the block just placed was not seen. The run is paused.`;
    case "MOVED":
      return `${cell(cells[0])} → ${cell(cells[1] ?? cells[0])} — the board no longer matches the plan at two cells. The run is paused.`;
    case "DISPLACED":
      return `${first} — a block was knocked off its cell and is sitting in a gap, not on a site. Straighten it, or dismiss to continue. The run is paused.`;
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
  if (supervision.state === "BUSY") return supervision.reason ?? "NOT WATCHING";
  return "WATCHING";
}

/** The CORRECTION control (docs/features/correction-action.md). It is shown ONLY
 *  when the server says `correctable` — vertical mode, level 0, the block
 *  axis-aligned, no taller neighbour, the destination clear, and (DISPLACED) the
 *  displacement in the 0.5-1.2 cm band. It is a two-step confirm: a correction
 *  drives the claw into a finished structure, so it never fires on one click,
 *  and the copy never reads as "the machine already fixed this". */
function CorrectionControl({ supervision, onCorrect }: {
  supervision: Supervision;
  onCorrect: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  // Reset the confirm state whenever the verdict/cell changes underneath us.
  const key = `${supervision.verdict}:${(supervision.correction_cell ?? []).join(",")}`;
  useEffect(() => setConfirming(false), [key]);

  const cell = supervision.correction_cell;
  const where = cell ? `column ${cell[0]} row ${cell[1]}` : "its planned cell";

  if (!confirming) {
    return (
      <button type="button" className="sv-correct" onClick={() => setConfirming(true)}
              aria-label={`Return the block to ${where} — the claw will pick it up and set it down`}>
        RETURN BLOCK TO CELL
      </button>
    );
  }
  return (
    <span className="sv-correct-confirm" role="group"
          aria-label="Confirm returning the block">
      <span className="sv-correct-warn">
        The claw will pick the block up from where it is and set it on{" "}
        {cell ? `[${cell[0]},${cell[1]}]` : "its cell"}. Watch the rig. Runs once.
      </span>
      <button type="button" className="sv-correct-go"
              onClick={() => { setConfirming(false); onCorrect(); }}>
        RUN
      </button>
      <button type="button" className="sv-correct-cancel"
              onClick={() => setConfirming(false)}>
        CANCEL
      </button>
    </span>
  );
}

export function SupervisionBanner({ state, onAcknowledge, onCorrect }: {
  state: StateModel;
  onAcknowledge: () => void;
  onCorrect?: () => void;
}) {
  const supervision = state.supervision;
  if (!supervision) return null;

  // VERIFIED gets NO banner, deliberately. A 40-block build would produce 40
  // green bars, and a console that celebrates every success trains the
  // operator to ignore it — and then the one amber bar that matters is ignored
  // too. The good case lives in the log row and one brief cell pulse.
  const verdict = supervision.verdict;
  const loud = verdict !== null && verdict !== "VERIFIED" && !supervision.acknowledged;

  if (!loud) {
    // NO_MAP is genuinely degraded and takes amber. Everything else here is
    // --text-dim / --text-faint and says only what it is doing.
    const dim = supervision.state === "NO_MEMORY" || supervision.state === "BUSY"
      || supervision.state === "QUIET" || supervision.state === "WARMING";
    if (!dim && supervision.state !== "NO_MAP") return null;
    return (
      <p className={`sv-status${supervision.state === "NO_MEMORY" ? " sv-faint" : ""}`}
         role="status" aria-live="polite">
        <span aria-hidden="true">{SHAPE[supervision.state]}</span>{" "}
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

  return (
    <section
      className={`banner supervision sv-${supervision.severity}`}
      role={red ? "alert" : "status"}
      aria-live={red ? "assertive" : "polite"}
    >
      <span className="sv-chip">
        <span aria-hidden="true">{SHAPE[verdict!]}</span> {verdict!.replace("_", " ")}
      </span>
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
          DISPLACED, and only when the SERVER says it is safe — otherwise the
          reason is shown so the operator knows why there is no button. The
          browser never derives `correctable`; the route re-checks server-side. */}
      {(verdict === "MOVED" || verdict === "DISPLACED") && (
        supervision.correctable
          ? <CorrectionControl supervision={supervision} onCorrect={onCorrect ?? (() => {})} />
          : supervision.correction_reason
            ? <span className="sv-correct-why">Cannot return it by claw: {supervision.correction_reason}</span>
            : null
      )}
      {/* Dismiss: a real button, ≥ 44 × 44, named for the CELL rather than
          "dismiss". It sits AFTER the correction control in tab order —
          dismissing is always safe, acting is not. */}
      <button type="button" className="sv-ack" aria-label={label} onClick={onAcknowledge}>
        {red ? "ACKNOWLEDGE" : "DISMISS"}
      </button>
    </section>
  );
}
