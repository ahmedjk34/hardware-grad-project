/**
 * GRID SHIFT — a single incrementer, a live grid preview, and Apply.
 *
 * Pick a course (a level ≥ 1), step its offset on the mode's run axis
 * (Y for vertical, X for horizontal) by the half-pitch increment — `3.8 cm`
 * on both modes today, derived from the lattice, not typed — and watch the
 * grid move in the viewport. Apply commits it to the model's `bondShifts`;
 * nothing is written until then.
 *
 * `[0,0]` and course 0 never shift. A course that pushes a block off the
 * travel cap is flagged (`orphanCount`); the block is marked, never deleted,
 * and `CLIPPED_BY_SHIFT` blocks RUN until it moves.
 */
import { useEffect, useState } from "react";
import { BOND_MODE, bondIncrementCm, runAxisOf, type BondShifts, type ModeName } from "../coords";

export interface GridShiftProps {
  mode: ModeName;
  /** A level held on the LevelScrubber, if any — the panel follows it. */
  level?: number | null;
  bondShifts?: BondShifts;
  maxLevel?: number;
  ceiling?: number;
  orphanCount?: number;
  /** Called as the incrementer turns, so the viewport lattice moves live.
   *  `cm === null` means "nothing pending, show the committed grid". */
  onPreview?: (level: number, cm: number | null) => void;
  /** Apply: commit this course's offset (or clear it with `null`). */
  onSetBond: (level: number, offsetCm: [number, number] | null) => void;
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
const cm = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)} cm`;

export function GridShift(props: GridShiftProps) {
  // Running-bond courses are a HORIZONTAL-grid feature. In the vertical grid the
  // panel is inert and says so — nothing here can shift that lattice. The real
  // control is split out so the mode branch does not sit above its hooks.
  if (props.mode !== BOND_MODE) {
    return (
      <section className="studio-gridshift" aria-label="Grid shift">
        <header className="studio-panel-header">
          <span>GRID SHIFT</span>
          <span className="studio-gridshift-axis">horizontal only</span>
        </header>
        <div className="studio-gridshift-body">
          <p className="studio-gridshift-summary">
            Running-bond courses apply to the <b>horizontal</b> grid. Latch it
            (<b>RR</b>) to shift a course.
          </p>
        </div>
      </section>
    );
  }
  return <GridShiftControl {...props} />;
}

function GridShiftControl({
  mode, level, bondShifts, maxLevel = 0, ceiling = 17, orphanCount = 0, onPreview, onSetBond,
}: GridShiftProps) {
  const axis = runAxisOf(mode);
  const step = bondIncrementCm(mode);
  const axisIndex = axis === "x" ? 0 : 1;

  const [course, setCourse] = useState(1);
  const committed = (bondShifts?.[mode]?.[clamp(course, 1, ceiling)] ?? [0, 0])[axisIndex];
  const [pending, setPending] = useState(committed);

  // Follow a held level, and re-seed the incrementer whenever the course or
  // the committed value under it changes.
  useEffect(() => {
    if (level != null && level >= 1) setCourse(clamp(level, 1, ceiling));
  }, [level, ceiling]);
  useEffect(() => { setPending(committed); }, [course, committed]);

  const dirty = Math.abs(pending - committed) > 1e-6;

  // Drive the live preview: the pending offset while it differs, else nothing.
  useEffect(() => {
    onPreview?.(clamp(course, 1, ceiling), dirty ? pending : null);
    return () => onPreview?.(clamp(course, 1, ceiling), null);
  }, [course, ceiling, pending, dirty, onPreview]);

  const nudge = (dir: -1 | 1) => setPending(p => clamp(p + dir * step, -step, step));
  const vec = (v: number): [number, number] => (axis === "x" ? [v, 0] : [0, v]);

  const apply = () => onSetBond(clamp(course, 1, ceiling), pending === 0 ? null : vec(pending));
  const reset = () => setPending(committed);

  const runningBond = () => {
    for (let l = 1; l <= clamp(Math.max(maxLevel, course, 2), 1, ceiling); l++) {
      onSetBond(l, l % 2 === 1 ? vec(step) : null);
    }
  };
  const bonded = Object.keys(bondShifts?.[mode] ?? {}).map(Number)
    .filter(l => l >= 1).sort((a, b) => a - b);

  return (
    <section className="studio-gridshift" aria-label="Grid shift">
      <header className="studio-panel-header">
        <span>GRID SHIFT</span>
        <span className="studio-gridshift-axis">{axis.toUpperCase()} axis</span>
      </header>

      <div className="studio-gridshift-body">
        <div className="studio-gridshift-course">
          <span className="studio-gridshift-courselabel">course</span>
          <button type="button" onClick={() => setCourse(c => clamp(c - 1, 1, ceiling))}
                  disabled={clamp(course, 1, ceiling) <= 1} aria-label="Previous course">◀</button>
          <span className="studio-gridshift-coursenum" aria-live="polite">{clamp(course, 1, ceiling)}</span>
          <button type="button" onClick={() => setCourse(c => clamp(c + 1, 1, ceiling))}
                  disabled={clamp(course, 1, ceiling) >= ceiling} aria-label="Next course">▶</button>
        </div>

        <div className="studio-gridshift-inc" role="group" aria-label={`Course offset on the ${axis.toUpperCase()} axis`}>
          <button type="button" onClick={() => nudge(-1)} disabled={pending <= -step + 1e-6}
                  aria-label={`Decrease by ${step.toFixed(1)} cm`}>−{step.toFixed(1)}</button>
          <span className="studio-gridshift-amount" aria-live="polite">{cm(pending)}</span>
          <button type="button" onClick={() => nudge(1)} disabled={pending >= step - 1e-6}
                  aria-label={`Increase by ${step.toFixed(1)} cm`}>+{step.toFixed(1)}</button>
        </div>

        <div className="studio-gridshift-actions">
          <button type="button" className="studio-gridshift-apply" onClick={apply} disabled={!dirty}>
            APPLY
          </button>
          <button type="button" className="studio-gridshift-reset" onClick={reset} disabled={!dirty}>
            reset
          </button>
        </div>

        {orphanCount > 0 && (
          <p className="studio-gridshift-orphans" role="alert">
            {orphanCount} block{orphanCount === 1 ? "" : "s"} pushed off the travel cap — move
            {orphanCount === 1 ? " it" : " them"} before RUN.
          </p>
        )}

        <p className="studio-gridshift-summary">
          {bonded.length > 0 ? <>offset courses: {bonded.map(l => `L${l}`).join(", ")} · </> : null}
          <button type="button" className="studio-gridshift-clear" onClick={runningBond}>
            running bond (1,3,5…)
          </button>
        </p>
      </div>
    </section>
  );
}
