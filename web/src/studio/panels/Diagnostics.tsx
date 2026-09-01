/**
 * Structured validator output rendered as machine-readable operator feedback.
 * This component groups and dispatches; every fact and fix comes from the pure
 * validator so the panel cannot disagree with the ghost or compiler.
 */
import type { KeyboardEvent, MouseEvent } from "react";
import type { Diagnostic, DiagnosticFix, DiagnosticSeverity } from "../validate";

export interface DiagnosticsProps {
  diagnostics: Diagnostic[];
  onHover?: (blockId: string | null) => void;
  onSelect?: (blockId: string) => void;
  onFix?: (fix: DiagnosticFix) => void;
}

const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? "" : "S"}`;

function DiagnosticRow({ diagnostic, onHover, onSelect, onFix }: {
  diagnostic: Diagnostic;
  onHover?: DiagnosticsProps["onHover"];
  onSelect?: DiagnosticsProps["onSelect"];
  onFix?: DiagnosticsProps["onFix"];
}) {
  const select = () => diagnostic.blockId && onSelect?.(diagnostic.blockId);
  const keyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if ((event.key === "Enter" || event.key === " ") && diagnostic.blockId) {
      event.preventDefault();
      select();
    }
  };
  const applyFix = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    if (diagnostic.fix) onFix?.(diagnostic.fix);
  };
  return (
    <div className="studio-diagnostic-row" role={diagnostic.blockId ? "button" : undefined}
         tabIndex={diagnostic.blockId ? 0 : undefined}
         onClick={select} onKeyDown={keyDown}
         onMouseEnter={() => onHover?.(diagnostic.blockId ?? null)}
         onMouseLeave={() => onHover?.(null)}>
      <span className={`studio-severity studio-severity-${diagnostic.severity}`} aria-hidden="true" />
      <span className="studio-diagnostic-id">{diagnostic.blockId ?? "RIG"}</span>
      <span className="studio-diagnostic-message">{diagnostic.message}</span>
      {diagnostic.fix ? (
        <button type="button" className="studio-diagnostic-fix" onClick={applyFix}>
          {diagnostic.fix.label}
        </button>
      ) : null}
    </div>
  );
}

function Group({ severity, diagnostics, ...handlers }: {
  severity: DiagnosticSeverity;
  diagnostics: Diagnostic[];
} & Omit<DiagnosticsProps, "diagnostics">) {
  if (diagnostics.length === 0) return null;
  return (
    <section className="studio-diagnostic-group" aria-label={`${severity} diagnostics`}>
      {diagnostics.map((diagnostic, index) => (
        <DiagnosticRow key={`${diagnostic.code}:${diagnostic.blockId ?? "rig"}:${index}`}
                       diagnostic={diagnostic} {...handlers} />
      ))}
    </section>
  );
}

export function Diagnostics({ diagnostics, onHover, onSelect, onFix }: DiagnosticsProps) {
  const errors = diagnostics.filter(item => item.severity === "error");
  const warnings = diagnostics.filter(item => item.severity === "warning");
  return (
    <aside className="studio-diagnostics" aria-label="Diagnostics" aria-live="polite">
      <header className="studio-panel-header">
        {diagnostics.length === 0 ? (
          <span className="studio-diagnostics-clean">NO PROBLEMS</span>
        ) : (
          <>
            <span className="studio-error-count">
              <b>{errors.length}</b><span className="studio-count-word"> {plural(errors.length, "ERROR").replace(/^\d+\s/, "")}</span>
            </span>
            <span aria-hidden="true"> · </span>
            <span className="studio-warning-count">
              <b>{warnings.length}</b><span className="studio-count-word"> {plural(warnings.length, "WARNING").replace(/^\d+\s/, "")}</span>
            </span>
          </>
        )}
      </header>
      <Group severity="error" diagnostics={errors} onHover={onHover} onSelect={onSelect} onFix={onFix} />
      <Group severity="warning" diagnostics={warnings} onHover={onHover} onSelect={onSelect} onFix={onFix} />
    </aside>
  );
}
