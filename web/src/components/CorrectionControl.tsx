import { useEffect, useState } from "react";
import type { Supervision } from "../types";

/** The CORRECTION control (docs/features/correction-action.md), shared by the
 *  console banner and the building-mode detector panel.
 *
 *  It is shown ONLY when the server says `correctable` — vertical mode, level 0,
 *  the block axis-aligned, no taller neighbour, the destination clear, and for
 *  DISPLACED the displacement in the 0.5-1.2 cm band. It is a two-step confirm:
 *  a correction drives the claw into a finished structure, so it never fires on
 *  one click, and the copy never reads as "the machine already fixed this". The
 *  browser derives nothing — `POST /api/supervision/correct` re-checks safety
 *  server-side (DESIGN.md §8). */
export function CorrectionControl({ supervision, onCorrect, className = "" }: {
  supervision: Supervision;
  onCorrect: () => void;
  className?: string;
}) {
  const [confirming, setConfirming] = useState(false);
  // Reset the confirm state whenever the verdict/cell changes underneath us.
  const key = `${supervision.verdict}:${(supervision.correction_cell ?? []).join(",")}`;
  useEffect(() => setConfirming(false), [key]);

  const cell = supervision.correction_cell;
  const where = cell ? `column ${cell[0]} row ${cell[1]}` : "its planned cell";

  if (!confirming) {
    return (
      <button type="button" className={`sv-correct ${className}`.trim()}
              onClick={() => setConfirming(true)}
              aria-label={`Return the block to ${where} — the claw will pick it up and set it down`}>
        RETURN BLOCK TO CELL
      </button>
    );
  }
  return (
    <span className={`sv-correct-confirm ${className}`.trim()} role="group"
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

/** `POST /api/supervision/correct`. The one place the request shape lives, so
 *  the console and building mode cannot drift. Fire-and-forget: the outcome
 *  comes back through the state snapshot (`last_correction`, and the re-checked
 *  verdict), not this promise. */
export function requestCorrection(): void {
  void fetch("/api/supervision/correct", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm: true }),
  });
}
