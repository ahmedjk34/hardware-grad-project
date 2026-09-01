/**
 * Physical estimates stay visible because hiding them would make guesses about
 * friction, claw width and practical height look like measured machine facts.
 */
import type { StudioSettings } from "../settings";

export function Settings({ value, onChange }: {
  value: StudioSettings;
  onChange: (settings: StudioSettings) => void;
}) {
  const number = (key: keyof StudioSettings, raw: string) => {
    const parsed = Number(raw);
    if (!Number.isFinite(parsed)) return;
    onChange({ ...value, [key]: key === "levelCeiling" ? Math.max(0, Math.floor(parsed)) : Math.max(0, parsed) });
  };
  return (
    <section className="studio-settings" aria-labelledby="studio-settings-title">
      <h2 id="studio-settings-title">ESTIMATES — NOT MEASUREMENTS</h2>

      <label className="studio-setting" htmlFor="studio-support-ratio">
        <span className="studio-setting-name">SUPPORT RATIO</span>
        <input id="studio-support-ratio" aria-label="Support ratio" type="number"
               min="0" max="1" step="0.01" value={value.supportRatio}
               onChange={event => number("supportRatio", event.target.value)} />
        <span className="studio-setting-copy">How much of a block's underside must rest on something. A guess about friction and the claw's release. Nobody has measured this rig. At least 70% contact bypasses the centre check.</span>
      </label>

      <label className="studio-setting" htmlFor="studio-claw-margin">
        <span className="studio-setting-name">CLAW CLEARANCE</span>
        <span className="studio-setting-value">
          <input id="studio-claw-margin" aria-label="Claw clearance in millimetres" type="number"
                 min="0" step="1" value={value.clawMarginMm}
                 onChange={event => number("clawMarginMm", event.target.value)} /> mm
        </span>
        <span className="studio-setting-copy">How much room the claw needs beside a block on the way down. A guess about the claw's width. Measure the claw and change this.</span>
      </label>

      <label className="studio-setting" htmlFor="studio-level-ceiling">
        <span className="studio-setting-name">LEVEL CEILING</span>
        <input id="studio-level-ceiling" aria-label="Level ceiling" type="number"
               min="0" max="17" step="1" value={value.levelCeiling}
               onChange={event => number("levelCeiling", event.target.value)} />
        <span className="studio-setting-copy">How high you are allowed to build. An operator limit, not a physical one — the Z travel would allow about 17.</span>
      </label>

      <label className="studio-setting" htmlFor="studio-block-cycle">
        <span className="studio-setting-name">BLOCK CYCLE</span>
        <span className="studio-setting-value">
          <input id="studio-block-cycle" aria-label="Block cycle in seconds" type="number"
                 min="0.001" step="0.001" value={value.blockCycleSeconds}
                 onChange={event => number("blockCycleSeconds", event.target.value)} /> s
        </span>
        <span className="studio-setting-copy">Seconds per block, measured across five mock builds: 2.115 s mean. This times rehearsal transport, not the physical arm; replace it after a hardware run.</span>
      </label>

      <label className="studio-setting" htmlFor="studio-latch-homing">
        <span className="studio-setting-name">LATCH HOMING</span>
        <span className="studio-setting-value">
          <input id="studio-latch-homing" aria-label="Latch homing in seconds" type="number"
                 min="0" step="1" value={value.latchHomingSeconds}
                 onChange={event => number("latchHomingSeconds", event.target.value)} /> s
        </span>
        <span className="studio-setting-copy">Seconds the estimate adds per mode latch, which homes X and Y. A guess until M7 measures it.</span>
      </label>
    </section>
  );
}
