/**
 * The running-bond course control — the grid-shift window.
 *
 * A course (a level) can carry a half-pitch offset on the mode's RUN AXIS
 * (Y for vertical, X for horizontal) so a block bridges the joint of the two
 * beneath it — centred, equal overlap each side. The increment is derived, not
 * typed: half the pitch, `3.8 cm` on both modes today.
 *
 * This panel only WRITES the model's `bondShifts` map through `onSetBond`;
 * every geometry decision — where the shifted lattice lands, which cells it
 * clips — is `coords.ts` / `validate.ts`. `[0,0]` never moves: the offset is
 * skipped for `level <= 0` and the feeder is drawn unshifted on both machines.
 * Blocks a course pushes off the travel cap are marked, never deleted —
 * `orphanCount` surfaces them and `CLIPPED_BY_SHIFT` blocks RUN until they move.
 */
import { useEffect, useState } from "react";
import { bondIncrementCm, runAxisOf, type BondShifts, type ModeName } from "../coords";

export interface GridShiftProps {
  mode: ModeName;
  /** A level held on the LevelScrubber, if any — the panel follows it. */
  level?: number | null;
  bondShifts?: BondShifts;
  /** Highest level any block sits on, so the preset knows how far to alternate. */
  maxLevel?: number;
  /** Upper bound for the course selector. */
  ceiling?: number;
  /** Blocks the current bond has pushed off the travel cap. */
  orphanCount?: number;
  onSetBond: (level: number, offsetCm: [number, number] | null) => void;
}

const cm = (value: number) => `${value < 0 ? "−" : ""}${Math.abs(value).toFixed(1)}`;
const clamp = (value: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, value));

export function GridShift({
  mode, level, bondShifts, maxLevel = 0, ceiling = 17, orphanCount = 0, onSetBond,
}: GridShiftProps) {
  const axis = runAxisOf(mode);
  const increment = bondIncrementCm(mode);
  const axisIndex = axis === "x" ? 0 : 1;
  const topCourse = clamp(Math.max(maxLevel, 4), 1, ceiling);

  // The course being edited. Defaults to 1, follows a held level when there is
  // one, but is otherwise steered by this panel's own ◀ ▶ — it does not need a
  // level held on the scrubber to work.
  const [course, setCourse] = useState(1);
  useEffect(() => {
    if (level != null && level >= 1) setCourse(clamp(level, 1, ceiling));
  }, [level, ceiling]);
  const editLevel = clamp(course, 1, ceiling);

  const offset = (bondShifts?.[mode]?.[editLevel] ?? [0, 0])[axisIndex];
  const at = (l: number) => (bondShifts?.[mode]?.[l] ?? [0, 0])[axisIndex] !== 0;

  const set = (steps: -1 | 0 | 1) => {
    if (steps === 0) { onSetBond(editLevel, null); return; }
    const value = steps * increment;
    onSetBond(editLevel, axis === "x" ? [value, 0] : [0, value]);
  };

  const runningBond = () => {
    for (let l = 1; l <= clamp(Math.max(maxLevel, editLevel, 2), 1, ceiling); l++) {
      onSetBond(l, l % 2 === 1
        ? (axis === "x" ? [increment, 0] : [0, increment])
        : null);
    }
  };
  const clearAll = () => {
    for (const l of Object.keys(bondShifts?.[mode] ?? {})) onSetBond(Number(l), null);
  };

  const bondedLevels = Object.keys(bondShifts?.[mode] ?? {})
    .map(Number).filter(l => l >= 1).sort((a, b) => a - b);

  return (
    <section className="studio-gridshift" aria-label="Grid shift — running-bond course">
      <header className="studio-panel-header">
        <span>GRID SHIFT</span>
        <span className="studio-gridshift-axis">{axis.toUpperCase()} · {cm(increment)} cm / course</span>
      </header>

      <div className="studio-gridshift-body">
        <button type="button" className="studio-gridshift-preset" onClick={runningBond}>
          RUNNING BOND · offset courses 1, 3, 5…
        </button>

        <div className="studio-gridshift-course">
          <span className="studio-gridshift-courselabel">course</span>
          <button type="button" onClick={() => setCourse(clamp(editLevel - 1, 1, ceiling))}
                  disabled={editLevel <= 1} aria-label="Previous course">◀</button>
          <span className="studio-gridshift-coursenum" aria-live="polite">
            {editLevel}{at(editLevel) ? " ·offset" : ""}
          </span>
          <button type="button" onClick={() => setCourse(clamp(editLevel + 1, 1, ceiling))}
                  disabled={editLevel >= ceiling} aria-label="Next course">▶</button>
        </div>

        <div className="studio-gridshift-stepper" role="group"
             aria-label={`Course ${editLevel} offset on ${axis.toUpperCase()}`}>
          <button type="button" onClick={() => set(-1)} disabled={offset <= -increment + 1e-6}
                  aria-label="Half pitch toward home">−</button>
          <span className="studio-gridshift-value">
            {offset === 0 ? "flush" : `${cm(offset)} cm`}
          </span>
          <button type="button" onClick={() => set(0)} disabled={offset === 0}
                  aria-label="Clear this course offset">flush</button>
          <button type="button" onClick={() => set(1)} disabled={offset >= increment - 1e-6}
                  aria-label="Half pitch away from home">+</button>
        </div>

        {bondedLevels.length > 0 && (
          <p className="studio-gridshift-summary">
            Offset courses: {bondedLevels.map(l => `L${l}`).join(", ")}
            {" · "}
            <button type="button" className="studio-gridshift-clear" onClick={clearAll}>clear all</button>
          </p>
        )}
        {orphanCount > 0 && (
          <p className="studio-gridshift-orphans" role="alert">
            {orphanCount} block{orphanCount === 1 ? "" : "s"} pushed off the travel cap by a
            course — move or remove {orphanCount === 1 ? "it" : "them"} before RUN.
          </p>
        )}
        <p className="studio-gridshift-hint">
          Course 0 is the base and never shifts, nor does the <b>[0,0]</b> feeder.
          The lattice previews the course you hold on the level scrubber.
        </p>
      </div>
    </section>
  );
}
