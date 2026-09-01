/**
 * The operator estimates that turn physical uncertainty into visible, editable
 * Studio policy. They are versioned because friction, claw width, a practical
 * stack height and the rig's real cycle time can only be settled on the machine.
 *
 * The two timing values feed the compiler's `ESTIMATES — NOT MEASUREMENTS`
 * duration: a build is ~40 s of motion and a mode latch homes X and Y. M7
 * measures the real mean against `--mock`; when it does, the constant moves and
 * the STUDIO.md changelog records that it came from a measurement.
 */
export interface StudioSettings {
  supportRatio: number;
  clawMarginMm: number;
  levelCeiling: number;
  blockCycleSeconds: number;
  latchHomingSeconds: number;
}

export const SUPPORT_RATIO = 0.55;
export const CLAW_MARGIN_MM = 8;
export const LEVEL_CEILING = 6;
/** rig/link.py: "A build is ~40 s of motion." Not yet measured against --mock. */
export const BLOCK_CYCLE_SECONDS = 40;
/** A latch homes X and Y — a whole-machine seek. A guess until M7 times it. */
export const LATCH_HOMING_SECONDS = 16;
export const STUDIO_SETTINGS_KEY = "rig.studio.settings.v1";

export const DEFAULT_STUDIO_SETTINGS: StudioSettings = Object.freeze({
  supportRatio: SUPPORT_RATIO,
  clawMarginMm: CLAW_MARGIN_MM,
  levelCeiling: LEVEL_CEILING,
  blockCycleSeconds: BLOCK_CYCLE_SECONDS,
  latchHomingSeconds: LATCH_HOMING_SECONDS,
});

export interface SettingsStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
/** A stored blob written before a field existed keeps working: missing or
 *  invalid positive numbers fall back to the shipped default, they do not
 *  discard the whole settings object. */
const positive = (value: unknown, fallback: number): number =>
  finite(value) && value > 0 ? value : fallback;

function parsedSettings(value: unknown): StudioSettings | null {
  if (!value || typeof value !== "object") return null;
  const settings = value as Partial<StudioSettings>;
  if (!finite(settings.supportRatio) || settings.supportRatio < 0 || settings.supportRatio > 1
      || !finite(settings.clawMarginMm) || settings.clawMarginMm < 0
      || !finite(settings.levelCeiling) || settings.levelCeiling < 0) return null;
  return {
    supportRatio: settings.supportRatio,
    clawMarginMm: settings.clawMarginMm,
    levelCeiling: Math.floor(settings.levelCeiling),
    blockCycleSeconds: positive(settings.blockCycleSeconds, BLOCK_CYCLE_SECONDS),
    latchHomingSeconds: positive(settings.latchHomingSeconds, LATCH_HOMING_SECONDS),
  };
}

export function loadStudioSettings(
  storage: SettingsStorage | undefined = typeof localStorage === "undefined" ? undefined : localStorage,
): StudioSettings {
  try {
    if (!storage) return { ...DEFAULT_STUDIO_SETTINGS };
    const raw = storage.getItem(STUDIO_SETTINGS_KEY);
    if (raw === null) return { ...DEFAULT_STUDIO_SETTINGS };
    return parsedSettings(JSON.parse(raw)) ?? { ...DEFAULT_STUDIO_SETTINGS };
  } catch {
    return { ...DEFAULT_STUDIO_SETTINGS };
  }
}

export function saveStudioSettings(
  settings: StudioSettings,
  storage: SettingsStorage | undefined = typeof localStorage === "undefined" ? undefined : localStorage,
): void {
  try {
    storage?.setItem(STUDIO_SETTINGS_KEY, JSON.stringify(settings));
  } catch {
    // A private window or a full quota must not make the editor unusable.
  }
}
