import { describe, expect, it } from "vitest";
import {
  DEFAULT_STUDIO_SETTINGS, STUDIO_SETTINGS_KEY, loadStudioSettings,
  saveStudioSettings,
} from "./settings";

describe("versioned Studio validation settings", () => {
  it("ships the conservative visible defaults", () => {
    expect(DEFAULT_STUDIO_SETTINGS).toEqual({
      supportRatio: 0.55,
      clawMarginMm: 8,
      levelCeiling: 6,
    });
  });

  it("persists under rig.studio.settings.v1", () => {
    const storage = new Map<string, string>();
    const adapter = {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => { storage.set(key, value); },
    };
    const settings = { supportRatio: 0.7, clawMarginMm: 12, levelCeiling: 4 };
    saveStudioSettings(settings, adapter);
    expect(STUDIO_SETTINGS_KEY).toBe("rig.studio.settings.v1");
    expect(loadStudioSettings(adapter)).toEqual(settings);
  });

  it("falls back safely when storage is unavailable or corrupt", () => {
    const broken = {
      getItem: () => "not json",
      setItem: () => { throw new Error("quota"); },
    };
    expect(loadStudioSettings(broken)).toEqual(DEFAULT_STUDIO_SETTINGS);
    expect(() => saveStudioSettings(DEFAULT_STUDIO_SETTINGS, broken)).not.toThrow();
  });
});
