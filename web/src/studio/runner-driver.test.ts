import { describe, expect, it, vi } from "vitest";
import type { StateModel } from "../types";
import { executeEffect, type RunnerApi } from "./runner-driver";
import type { Effect, RunEvent } from "./runner";

const state = (changes: Partial<StateModel> = {}): StateModel => ({
  mode: "vertical", cols: 7, rows: 6, calibrated: true, selected: null,
  command: null, level: 0, build_state: "READY", locked_reason: null,
  camera: "LIVE", camera_age_ms: 10, last_result: null,
  last_result_reason: null, views: {}, geometry: {
    image_size: [640, 480], calibrated: true,
    grid: [{ col: 3, row: 2, polygon: [[300, 200], [340, 200], [340, 240], [300, 240]] }],
    selected: null, detections: [], paper: null,
  },
  ...changes,
});

function mockApi(): { api: RunnerApi; calls: string[] } {
  const calls: string[] = [];
  const api: RunnerApi = {
    setLevel: vi.fn(async value => { calls.push(`level:${value}`); return state({ level: value }); }),
    select: vi.fn(async (x, y, w, h) => {
      calls.push(`select:${x},${y},${w},${h}`);
      return state({ level: 1, selected: [3, 2], command: "B 3 2 1" });
    }),
    selectAxis: vi.fn(async (axis, value) => {
      calls.push(`axis:${axis}:${value}`);
      return state({ selected: axis === "col" ? [value, 0] : [0, value], command: `B ${axis === "col" ? value : 0} ${axis === "row" ? value : 0} 0` });
    }),
    build: vi.fn(async command => { calls.push(`build:${command}`); return state({ build_state: "RUNNING", command }); }),
    mode: vi.fn(async next => { calls.push(`mode:${next}`); return state({ mode: next }); }),
  };
  return { api, calls };
}

describe("runner effect driver with a mocked API", () => {
  it("sets the level, selects the exact polygon centre, then returns the rig command for verification", async () => {
    const { api, calls } = mockApi();
    const events: RunEvent[] = [];
    await executeEffect({ kind: "select", col: 3, row: 2, level: 1 }, {
      api, state: () => state(), dispatch: event => events.push(event), now: () => 50,
    });
    expect(calls).toEqual(["level:1", "select:320,220,640,480"]);
    expect(events).toEqual([{ type: "selected", command: "B 3 2 1", now: 50 }]);
  });

  it("uses the axis route for a real zero-axis target", async () => {
    const { api, calls } = mockApi();
    await executeEffect({ kind: "select", col: 4, row: 0, level: 0 }, {
      api, state: () => state(), dispatch: () => {}, now: () => 50,
    });
    expect(calls).toEqual(["axis:col:4"]);
  });

  it("compares verify effects without touching the API", async () => {
    const { api, calls } = mockApi();
    const events: RunEvent[] = [];
    await executeEffect({ kind: "verify", expect: "B 3 2 1", actual: "B 3 2 0" }, {
      api, state: () => state(), dispatch: event => events.push(event), now: () => 51,
    });
    expect(calls).toEqual([]);
    expect(events).toEqual([{ type: "verified", actual: "B 3 2 0", now: 51 }]);
  });

  it("posts one build and reports RUNNING without waiting for a terminal outcome", async () => {
    const { api, calls } = mockApi();
    const events: RunEvent[] = [];
    await executeEffect({ kind: "build", command: "B 3 2 1", dry: false }, {
      api, state: () => state(), dispatch: event => events.push(event), now: () => 52,
    });
    expect(calls).toEqual(["build:B 3 2 1"]);
    expect(events).toEqual([{ type: "build-running", now: 52 }]);
  });

  it("posts a mode only after the reducer has emitted it", async () => {
    const { api, calls } = mockApi();
    const events: RunEvent[] = [];
    await executeEffect({ kind: "mode", mode: "horizontal", command: "RR", dry: false }, {
      api, state: () => state(), dispatch: event => events.push(event), now: () => 53,
    });
    expect(calls).toEqual(["mode:horizontal"]);
    expect(events).toEqual([{ type: "mode-settled", now: 53 }]);
  });

  it("DRY RUN completes against fake transport with zero API calls", async () => {
    const { api, calls } = mockApi();
    const events: RunEvent[] = [];
    const delay = vi.fn(async () => {});
    const effects: Effect[] = [
      { kind: "select", col: 3, row: 2, level: 1, dry: true },
      { kind: "build", command: "B 3 2 1", dry: true },
      { kind: "mode", mode: "horizontal", command: "RR", dry: true },
    ];
    for (const effect of effects) {
      await executeEffect(effect, { api, state: () => state(), dispatch: event => events.push(event), now: () => 54, delay });
    }
    expect(calls).toEqual([]);
    expect(delay).toHaveBeenCalledTimes(2);
    expect(events).toEqual([
      { type: "selected", command: "B 3 2 1", now: 54 },
      { type: "build-running", now: 54 },
      { type: "build-settled", result: "placed", reason: null, now: 54 },
      { type: "mode-settled", now: 54 },
    ]);
  });

  it("refuses every real transport effect when the observed server state is RUNNING", async () => {
    const effects: Effect[] = [
      { kind: "select", col: 3, row: 2, level: 1 },
      { kind: "build", command: "B 3 2 1", dry: false },
      { kind: "mode", mode: "horizontal", command: "RR", dry: false },
    ];
    for (const effect of effects) {
      const { api, calls } = mockApi();
      await expect(executeEffect(effect, {
        api, state: () => state({ build_state: "RUNNING" }), dispatch: () => {}, now: () => 55,
      })).rejects.toThrow("build_state is RUNNING");
      expect(calls).toEqual([]);
    }
  });
});
