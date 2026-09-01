import { describe, expect, it } from "vitest";
import type { Op } from "./compile";
import {
  initialRun,
  feederPrompt,
  runTiming,
  programRows,
  step,
  type Effect,
  type RunEvent,
  type RunState,
} from "./runner";

const build = (id: string, col: number, row: number, level: number): Op => ({
  op: "build", id, col, row, level, text: `B ${col} ${row} ${level}`,
});
const mode = (next: "vertical" | "horizontal"): Op => ({
  op: "mode", mode: next, cost: "homes X and Y", text: next === "vertical" ? "R" : "RR",
});

function dispatch(state: RunState, event: RunEvent) {
  return step(state, event);
}

function start(program: Op[], style: "step" | "run" | "dry" = "run") {
  return dispatch(initialRun(), {
    type: "start", program, style, modelName: "Test model", colours: { a: "red", b: "blue" }, now: 100,
  });
}

describe("runner reducer", () => {
  it("runs the happy path select → verify → build → settle, one op at a time", () => {
    let turn = start([build("a", 3, 2, 1), build("b", 4, 2, 1)]);
    expect(turn.state.phase).toBe("arming");
    expect(turn.effects).toEqual([{ kind: "select", col: 3, row: 2, level: 1 }]);

    turn = dispatch(turn.state, { type: "selected", command: "B 3 2 1", now: 110 });
    expect(turn.state.phase).toBe("verifying");
    expect(turn.effects).toEqual([{ kind: "verify", expect: "B 3 2 1", actual: "B 3 2 1" }]);

    turn = dispatch(turn.state, { type: "verified", actual: "B 3 2 1", now: 111 });
    expect(turn.state.phase).toBe("building");
    expect(turn.state.inFlight).toBe(true);
    expect(turn.effects).toEqual([{ kind: "build", command: "B 3 2 1", dry: false }]);

    turn = dispatch(turn.state, { type: "build-running", now: 112 });
    expect(turn.effects).toEqual([]);
    turn = dispatch(turn.state, { type: "build-settled", result: "placed", reason: null, now: 712 });
    expect(turn.state.cursor).toBe(1);
    expect(turn.state.inFlight).toBe(false);
    expect(turn.effects).toEqual([{ kind: "select", col: 4, row: 2, level: 1 }]);
  });

  it("stops on a command mismatch and shows both strings verbatim", () => {
    let turn = start([build("a", 3, 2, 1)]);
    turn = dispatch(turn.state, { type: "selected", command: "B 3 2 0", now: 110 });
    turn = dispatch(turn.state, { type: "verified", actual: "B 3 2 0", now: 111 });
    expect(turn.state.phase).toBe("stopped-mismatch");
    expect(turn.state.mismatch).toEqual({ program: "B 3 2 1", rig: "B 3 2 0" });
    expect(turn.effects).toEqual([]);
  });

  it("pauses a rejection at the same op and can continue or end", () => {
    let turn = start([build("a", 3, 2, 1)]);
    turn = dispatch(turn.state, { type: "selected", command: "B 3 2 1", now: 110 });
    turn = dispatch(turn.state, { type: "verified", actual: "B 3 2 1", now: 111 });
    turn = dispatch(turn.state, { type: "build-settled", result: "rejected", reason: "target refused", now: 711 });
    expect(turn.state.phase).toBe("rejected");
    expect(turn.state.cursor).toBe(0);
    expect(turn.state.readOnly).toBe(false);

    const resumed = dispatch(turn.state, { type: "continue", now: 800 });
    expect(resumed.state.cursor).toBe(0);
    expect(resumed.effects).toEqual([{ kind: "select", col: 3, row: 2, level: 1 }]);

    const ended = dispatch(turn.state, { type: "end", now: 801 });
    expect(ended.state.phase).toBe("done");
    expect(ended.effects).toEqual([]);
  });

  it("locks read-only at the reached step after an abort", () => {
    let turn = start([build("a", 3, 2, 1), build("b", 4, 2, 1)]);
    turn = dispatch(turn.state, { type: "selected", command: "B 3 2 1", now: 110 });
    turn = dispatch(turn.state, { type: "verified", actual: "B 3 2 1", now: 111 });
    turn = dispatch(turn.state, { type: "build-settled", result: "aborted", reason: "claw unknown", now: 711 });
    expect(turn.state.phase).toBe("locked");
    expect(turn.state.readOnly).toBe(true);
    expect(turn.state.cursor).toBe(0);
    expect(turn.state.failure).toBe("claw unknown");
    expect(turn.effects).toEqual([]);
  });

  it("warns before every mode op, then calls mode only after confirmation", () => {
    let turn = start([mode("horizontal"), build("a", 1, 2, 0)]);
    expect(turn.state.phase).toBe("awaiting-confirm");
    expect(turn.effects).toEqual([{
      kind: "warn", text: "Switching to HORIZONTAL homes X and Y. The rig will move without a B.",
    }]);

    turn = dispatch(turn.state, { type: "confirm", now: 110 });
    expect(turn.state.phase).toBe("building");
    expect(turn.effects).toEqual([{ kind: "mode", mode: "horizontal", command: "RR", dry: false }]);
    turn = dispatch(turn.state, { type: "mode-settled", now: 710 });
    expect(turn.state.cursor).toBe(1);
    expect(turn.effects).toEqual([{ kind: "select", col: 1, row: 2, level: 0 }]);
  });

  it("STEP waits for the shared build confirmation after verification", () => {
    let turn = start([build("a", 3, 2, 1)], "step");
    turn = dispatch(turn.state, { type: "selected", command: "B 3 2 1", now: 110 });
    turn = dispatch(turn.state, { type: "verified", actual: "B 3 2 1", now: 111 });
    expect(turn.state.phase).toBe("awaiting-confirm");
    expect(turn.effects).toEqual([]);
    turn = dispatch(turn.state, { type: "confirm", now: 120 });
    expect(turn.effects).toEqual([{ kind: "build", command: "B 3 2 1", dry: false }]);
  });

  it("DRY RUN uses the same reducer but marks every transport effect dry", () => {
    let turn = start([mode("horizontal"), build("a", 1, 2, 0)], "dry");
    turn = dispatch(turn.state, { type: "confirm", now: 110 });
    expect(turn.effects).toEqual([{ kind: "mode", mode: "horizontal", command: "RR", dry: true }]);
    turn = dispatch(turn.state, { type: "mode-settled", now: 710 });
    expect(turn.effects).toEqual([{ kind: "select", col: 1, row: 2, level: 0, dry: true }]);
  });

  it("stop-after-this-block never interrupts the in-flight block", () => {
    let turn = start([build("a", 3, 2, 1), build("b", 4, 2, 1)]);
    turn = dispatch(turn.state, { type: "selected", command: "B 3 2 1", now: 110 });
    turn = dispatch(turn.state, { type: "verified", actual: "B 3 2 1", now: 111 });
    turn = dispatch(turn.state, { type: "stop-after", now: 120 });
    expect(turn.state.phase).toBe("building");
    expect(turn.state.stopAfterCurrent).toBe(true);
    expect(turn.effects).toEqual([]);
    turn = dispatch(turn.state, { type: "build-settled", result: "placed", reason: null, now: 711 });
    expect(turn.state.phase).toBe("paused");
    expect(turn.state.cursor).toBe(1);
    expect(turn.effects).toEqual([]);
  });

  it("pauses immediately when the socket drops and emits no next command", () => {
    const turn = start([build("a", 3, 2, 1)]);
    const dropped = dispatch(turn.state, { type: "socket", connected: false, now: 105 });
    expect(dropped.state.phase).toBe("paused");
    expect(dropped.state.pauseReason).toBe("stale");
    expect(dropped.effects).toEqual([]);

    const heardAgain = dispatch(dropped.state, { type: "socket", connected: true, now: 205 });
    const resumed = dispatch(heardAgain.state, { type: "continue", now: 206 });
    expect(resumed.effects).toEqual([{ kind: "select", col: 3, row: 2, level: 1 }]);
  });

  it("pauses on a transport refusal without advancing the program", () => {
    const turn = start([build("a", 3, 2, 1)]);
    const refused = dispatch(turn.state, { type: "transport-error", reason: "camera frame is stale", now: 106 });
    expect(refused.state.phase).toBe("paused");
    expect(refused.state.cursor).toBe(0);
    expect(refused.state.failure).toBe("camera frame is stale");
    expect(refused.effects).toEqual([]);
  });

  it("turns repeated feeder colours into a quiet SAME COLOUR prompt", () => {
    let turn = start([build("a", 3, 2, 0), build("b", 3, 2, 1)], "run");
    expect(feederPrompt(turn.state)).toEqual({ colour: "RED", same: false, text: "block 1 of 2 · B 3 2 0" });
    turn = dispatch(turn.state, { type: "selected", command: "B 3 2 0", now: 110 });
    turn = dispatch(turn.state, { type: "verified", actual: "B 3 2 0", now: 111 });
    turn = dispatch(turn.state, { type: "build-settled", result: "placed", reason: null, now: 711 });
    expect(feederPrompt(turn.state)).toEqual({ colour: "BLUE", same: false, text: "block 2 of 2 · B 3 2 1" });
  });

  it("shows the next feeder instruction while the current RUN block is moving", () => {
    let turn = start([build("a", 3, 2, 0), build("b", 3, 2, 1)], "run");
    turn = dispatch(turn.state, { type: "selected", command: "B 3 2 0", now: 110 });
    turn = dispatch(turn.state, { type: "verified", actual: "B 3 2 0", now: 111 });
    expect(turn.state.phase).toBe("building");
    expect(feederPrompt(turn.state)).toEqual({ colour: "BLUE", same: false, text: "block 2 of 2 · B 3 2 1" });
  });

  it("derives elapsed and ETA from the measured mock cycle constant", () => {
    const turn = start([build("a", 3, 2, 0), mode("horizontal"), build("b", 1, 2, 0)], "run");
    expect(runTiming(turn.state, 3_100, 2.115, 16)).toEqual({ elapsedSeconds: 3, etaSeconds: 20.23 });
  });

  it("marks the reached op and every untouched op read-only after an abort", () => {
    let turn = start([build("a", 3, 2, 0), build("b", 3, 2, 1)], "run");
    turn = dispatch(turn.state, { type: "selected", command: "B 3 2 0", now: 110 });
    turn = dispatch(turn.state, { type: "verified", actual: "B 3 2 0", now: 111 });
    turn = dispatch(turn.state, { type: "build-settled", result: "aborted", reason: "unknown", now: 711 });
    expect(programRows(turn.state).map(row => row.status)).toEqual(["stopped", "future"]);
  });
});

const candidateEvents: RunEvent[] = [
  { type: "selected", command: "B 2 1 0", now: 2 },
  { type: "selected", command: "wrong", now: 2 },
  { type: "verified", actual: "B 2 1 0", now: 3 },
  { type: "verified", actual: "wrong", now: 3 },
  { type: "confirm", now: 4 },
  { type: "build-running", now: 5 },
  { type: "build-settled", result: "placed", reason: null, now: 6 },
  { type: "build-settled", result: "rejected", reason: "no", now: 6 },
  { type: "build-settled", result: "aborted", reason: "unknown", now: 6 },
  { type: "mode-settled", now: 6 },
  { type: "stop-after", now: 7 },
  { type: "continue", now: 8 },
  { type: "end", now: 8 },
  { type: "socket", connected: false, now: 9 },
  { type: "socket", connected: true, now: 10 },
  { type: "server-build-state", buildState: "RUNNING", now: 11 },
  { type: "server-build-state", buildState: "READY", now: 12 },
  { type: "server-build-state", buildState: "LOCKED", now: 13 },
  { type: "transport-error", reason: "refused", now: 14 },
];

function effectIsSerialCommand(effect: Effect): boolean {
  if (effect.kind === "select") return effect.dry !== true;
  if (effect.kind === "build" || effect.kind === "mode") return !effect.dry;
  return false;
}

describe("runner safety walk", () => {
  it("never emits two builds and never issues a command while build_state is RUNNING", () => {
    const beginnings = (["step", "run", "dry"] as const).map(style =>
      start([build("a", 2, 1, 0), mode("horizontal"), build("b", 1, 2, 0)], style).state,
    );
    const queue = [...beginnings];
    const seen = new Set<string>();
    let walked = 0;
    const keyOf = (value: RunState) => JSON.stringify({
      ...value, log: [], startedAt: 0, opStartedAt: 0, finishedAt: 0,
    });

    while (queue.length && walked < 50_000) {
      const state = queue.shift()!;
      const key = keyOf(state);
      if (seen.has(key)) continue;
      seen.add(key);
      walked++;
      for (const event of candidateEvents) {
        const turn = step(state, event);
        const builds = turn.effects.filter(effect => effect.kind === "build");
        if (builds.length > 1) throw new Error(`two build effects from ${state.phase} / ${event.type}`);
        if (state.inFlight && builds.length) throw new Error(`second build from ${state.phase} / ${event.type}`);
        if (turn.state.buildState === "RUNNING" && turn.effects.some(effectIsSerialCommand)) {
          throw new Error(`serial effect while RUNNING from ${state.phase} / ${event.type}`);
        }
        if (!seen.has(keyOf(turn.state))) queue.push(turn.state);
      }
    }
    expect(walked).toBeGreaterThan(20);
    expect(queue).toHaveLength(0);
  }, 15_000);
});
