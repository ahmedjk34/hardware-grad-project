/**
 * The three operator estimates that turn physical uncertainty into visible,
 * editable Studio policy. They are versioned because friction, claw width and
 * a practical stack height can only be settled on the real rig.
 */
export interface StudioSettings {
  supportRatio: number;
  clawMarginMm: number;
  levelCeiling: number;
}

export const SUPPORT_RATIO = 0.55;
export const CLAW_MARGIN_MM = 8;
export const LEVEL_CEILING = 6;
export const STUDIO_SETTINGS_KEY = "rig.studio.settings.v1";

export const DEFAULT_STUDIO_SETTINGS: StudioSettings = Object.freeze({
  supportRatio: SUPPORT_RATIO,
  clawMarginMm: CLAW_MARGIN_MM,
  levelCeiling: LEVEL_CEILING,
});

export interface SettingsStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

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
