import { describe, expect, it } from "vitest";
import {
  BLOCK_CYCLE_SECONDS, DEFAULT_STUDIO_SETTINGS, LATCH_HOMING_SECONDS,
  STUDIO_SETTINGS_KEY, loadStudioSettings, saveStudioSettings,
} from "./settings";

describe("versioned Studio validation settings", () => {
  it("ships the conservative visible defaults", () => {
    expect(DEFAULT_STUDIO_SETTINGS).toEqual({
      supportRatio: 0.55,
      clawMarginMm: 8,
      levelCeiling: 6,
      blockCycleSeconds: BLOCK_CYCLE_SECONDS,
      latchHomingSeconds: LATCH_HOMING_SECONDS,
    });
    expect([BLOCK_CYCLE_SECONDS, LATCH_HOMING_SECONDS]).toEqual([2.115, 16]);
  });

  it("persists under rig.studio.settings.v1", () => {
    const storage = new Map<string, string>();
    const adapter = {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => { storage.set(key, value); },
    };
    const settings = {
      supportRatio: 0.7, clawMarginMm: 12, levelCeiling: 4,
      blockCycleSeconds: 33, latchHomingSeconds: 9,
    };
    saveStudioSettings(settings, adapter);
    expect(STUDIO_SETTINGS_KEY).toBe("rig.studio.settings.v1");
    expect(loadStudioSettings(adapter)).toEqual(settings);
  });

  it("backfills the timing fields a pre-existing v1 blob never stored", () => {
    const blob = JSON.stringify({ supportRatio: 0.6, clawMarginMm: 10, levelCeiling: 5 });
    const adapter = { getItem: () => blob, setItem: () => {} };
    expect(loadStudioSettings(adapter)).toEqual({
      supportRatio: 0.6, clawMarginMm: 10, levelCeiling: 5,
      blockCycleSeconds: BLOCK_CYCLE_SECONDS, latchHomingSeconds: LATCH_HOMING_SECONDS,
    });
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
