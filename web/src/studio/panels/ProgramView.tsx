/**
 * The compiled program as a serial log — the register this whole console speaks
 * in. Every line is the literal `op.text` the runner will send; latches are set
 * apart as a full-width rule because a mode latch homes the whole machine, and
 * a chip on its own would understate that. This component only draws: the
 * ordering, the latch state machine and the estimate are all `compile.ts`.
 */
import { useState } from "react";
import type { KeyboardEvent } from "react";
import { estimateLabel, type Op, type Stats } from "../compile";

export interface ProgramViewProps {
  program: Op[];
  valid: boolean;
  stats: Stats;
  selectedId?: string | null;
  onSelect?: (blockId: string) => void;
}

const lineNumber = (index: number) => String(index).padStart(2, "0");

export function ProgramView({ program, valid, stats, selectedId, onSelect }: ProgramViewProps) {
  const [copied, setCopied] = useState(false);

  const serialText = program.map(op => op.text).join("\n");
  const copy = () => {
    void navigator.clipboard?.writeText?.(serialText);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  };

  let built = 0;
  const rows = program.map((op, index) => {
    if (op.op === "mode") {
      return (
        <div key={`latch-${index}`} className="studio-program-latch" role="separator"
             aria-label={`latch ${op.text} — ${op.cost}`}>
          <span className="studio-program-chip">{op.text}</span>
          <span className="studio-program-rule" aria-hidden="true" />
          <span className="studio-program-cost">{op.cost}</span>
        </div>
      );
    }
    built += 1;
    const selected = selectedId != null && selectedId === op.id;
    const select = () => onSelect?.(op.id);
    const keyDown = (event: KeyboardEvent<HTMLDivElement>) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(); }
    };
    return (
      <div key={op.id} className="studio-program-line" role="button" tabIndex={0}
           aria-pressed={selected} aria-label={`line ${built}: ${op.text} — block ${op.id}`}
           onClick={select} onKeyDown={keyDown}>
        <span className="studio-program-num">{lineNumber(built)}</span>
        <span className="studio-program-text">{op.text}</span>
        <span className="studio-program-block">{op.id}</span>
      </div>
    );
  });

  return (
    <section className="studio-program" aria-label="Compiled program">
      <header className="studio-panel-header studio-program-head">
        {valid ? (
          <span className="studio-program-estimate">{estimateLabel(stats)}</span>
        ) : (
          <span className="studio-program-invalid">MODEL HAS ERRORS</span>
        )}
        <button type="button" className="studio-program-copy" onClick={copy}
                disabled={program.length === 0}>
          {copied ? "COPIED" : "COPY"}
        </button>
      </header>
      {program.length === 0 ? (
        <p className="studio-program-empty">
          {valid ? "NOTHING TO BUILD" : "FIX THE ERRORS ABOVE — NO PROGRAM IS EMITTED"}
        </p>
      ) : (
        <div className="studio-program-body">{rows}</div>
      )}
    </section>
  );
}
