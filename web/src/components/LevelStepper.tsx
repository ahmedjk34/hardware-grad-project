import { useEffect, useState } from "react";
import * as api from "../api";

/** Stepping to level 6 with `+` is tedious, so the value is directly editable.
 *  Negative levels are refused here as well as by the controller. */
export function LevelStepper({ level, disabled }: { level: number; disabled: boolean }) {
  const [draft, setDraft] = useState(String(level));
  useEffect(() => setDraft(String(level)), [level]);

  const commit = () => {
    const parsed = Number.parseInt(draft, 10);
    if (!Number.isFinite(parsed) || parsed < 0) return setDraft(String(level));
    if (parsed !== level) void api.setLevel(parsed);
  };

  return (
    <div className="stepper-block">
      <span className="label" id="level-label">Level</span>
      <div className="stepper">
        <button type="button" className="btn" aria-label="Level -" disabled={disabled} onClick={() => void api.level(-1)}>−</button>
        <input
          aria-labelledby="level-label"
          inputMode="numeric"
          type="number"
          min={0}
          value={draft}
          disabled={disabled}
          onChange={event => setDraft(event.target.value)}
          onBlur={commit}
          onKeyDown={event => { if (event.key === "Enter") commit(); }}
        />
        <button type="button" className="btn" aria-label="Level +" disabled={disabled} onClick={() => void api.level(1)}>+</button>
      </div>
    </div>
  );
}
