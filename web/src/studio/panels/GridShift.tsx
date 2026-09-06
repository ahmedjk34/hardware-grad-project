/**
 * The running-bond course control.
 *
 * A level can carry a half-pitch offset on the mode's RUN AXIS (Y for vertical,
 * X for horizontal) so a block bridges the joint of the two beneath it —
 * centred, equal overlap each side. The increment is derived, not typed: half
 * the pitch, `3.8 cm` on both modes today. This panel only WRITES the model's
 * `bondShifts` map through `onSetBond`; every geometry decision — where the
 * shifted lattice lands, which cells it clips — is `coords.ts` / `validate.ts`.
 *
 * `[0,0]` never moves: the offset is skipped for `level <= 0` and the feeder is
 * drawn unshifted on both machines. Blocks a course pushes off the travel cap
 * are marked, never deleted — `orphanCount` surfaces them and the model's
 * `CLIPPED_BY_SHIFT` errors block RUN until they are moved.
 */
import { bondIncrementCm, runAxisOf, type BondShifts, type ModeName } from "../coords";

export interface GridShiftProps {
  mode: ModeName;
  /** The level being edited — the LevelScrubber's held level, or null. */
  level: number | null;
  bondShifts?: BondShifts;
  /** Highest level any block sits on, so the preset knows how far to alternate. */
  maxLevel?: number;
  /** Blocks the current bond has pushed off the travel cap. */
  orphanCount?: number;
  onSetBond: (level: number, offsetCm: [number, number] | null) => void;
}

const cm = (value: number) => `${value < 0 ? "−" : ""}${Math.abs(value).toFixed(1)}`;

export function GridShift({ mode, level, bondShifts, maxLevel = 0, orphanCount = 0, onSetBond }: GridShiftProps) {
  const axis = runAxisOf(mode);
  const increment = bondIncrementCm(mode);
  const axisIndex = axis === "x" ? 0 : 1;
  const editable = level !== null && level >= 1;
  const current = editable ? bondShifts?.[mode]?.[level] : undefined;
  const offset = current ? current[axisIndex] : 0;

  const set = (steps: -1 | 0 | 1) => {
    if (level === null || level < 1) return;
    if (steps === 0) { onSetBond(level, null); return; }
    const value = steps * increment;
    onSetBond(level, axis === "x" ? [value, 0] : [0, value]);
  };

  const runningBond = () => {
    for (let l = 1; l <= Math.max(maxLevel, level ?? 0); l++) {
      onSetBond(l, l % 2 === 1
        ? (axis === "x" ? [increment, 0] : [0, increment])
        : null);
    }
  };

  const bondedLevels = Object.keys(bondShifts?.[mode] ?? {})
    .map(Number).filter(l => l >= 1).sort((a, b) => a - b);

  return (
    <section className="studio-gridshift" aria-label="Running-bond course">
      <header className="studio-panel-header">
        <span>RUNNING BOND</span>
        <span className="studio-gridshift-axis">{axis.toUpperCase()} · {cm(increment)} cm</span>
      </header>

      <div className="studio-gridshift-body">
        {editable ? (
          <div className="studio-gridshift-stepper" role="group"
               aria-label={`Level ${level} course offset on ${axis.toUpperCase()}`}>
            <button type="button" onClick={() => set(-1)} disabled={offset <= -increment + 1e-6}
                    aria-label="Half pitch toward home">&minus;</button>
            <span className="studio-gridshift-value" aria-live="polite">
              {offset === 0 ? "flush" : `${cm(offset)} cm`}
            </span>
            <button type="button" onClick={() => set(0)} disabled={offset === 0}
                    aria-label="Clear this course offset">0</button>
            <button type="button" onClick={() => set(1)} disabled={offset >= increment - 1e-6}
                    aria-label="Half pitch away from home">+</button>
          </div>
        ) : (
          <p className="studio-gridshift-hint">
            Hold a level ≥ 1 on the scrubber to set its course. Level 0 is the base
            course and never shifts — nor does the <b>[0,0]</b> feeder.
          </p>
        )}

        <button type="button" className="studio-gridshift-preset" onClick={runningBond}
                disabled={Math.max(maxLevel, level ?? 0) < 1}>
          RUNNING BOND · alternate 1,3,5…
        </button>

        {bondedLevels.length > 0 && (
          <p className="studio-gridshift-summary">
            Courses: {bondedLevels.map(l => `L${l}`).join(", ")}
          </p>
        )}
        {orphanCount > 0 && (
          <p className="studio-gridshift-orphans" role="alert">
            {orphanCount} block{orphanCount === 1 ? "" : "s"} pushed off the travel cap by this
            course — move or remove {orphanCount === 1 ? "it" : "them"} before RUN.
          </p>
        )}
      </div>
    </section>
  );
}
