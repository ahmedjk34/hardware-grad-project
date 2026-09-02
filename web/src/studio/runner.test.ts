import { describe, expect, it } from "vitest";
import type { Op } from "./compile";
import {
  initialRun,
  currentOperationText,
  feederPrompt,
  noProgress,
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

  it("STEP warns before a mode op, then calls mode only after confirmation", () => {
    let turn = start([mode("horizontal"), build("a", 1, 2, 0)], "step");
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

  it("RUN switches mode automatically as part of its compiled program", () => {
    const turn = start([mode("horizontal"), build("a", 1, 2, 0)], "run");
    expect(turn.state.phase).toBe("building");
    expect(turn.effects).toEqual([{ kind: "mode", mode: "horizontal", command: "RR", dry: false }]);
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

/**
 * The reducer learns where a build has got to from the SERIAL STREAM. These
 * are the rules that separate "showing progress" from "assuming progress".
 */
describe("build-step: progress within one command, never past it", () => {
  const phase = (stepNumber: number, phaseId: string, label: string, eventId: number,
                 extra: Partial<Extract<RunEvent, { type: "build-step" }>> = {}) =>
    ({ type: "build-step" as const, commandSeq: 1, step: stepNumber, total: 14,
       phaseId, label, action: "move" as const, status: "begin" as const, eventId,
       now: 1000 + eventId, ...extra });

  /** A run with one build in flight, the way `issueBuild` leaves it. */
  function inFlight() {
    let turn = start([build("a", 3, 2, 0), build("b", 3, 2, 1)]);
    turn = dispatch(turn.state, { type: "selected", command: "B 3 2 0", now: 200 });
    turn = dispatch(turn.state, { type: "verified", actual: "B 3 2 0", now: 300 });
    expect(turn.state.inFlight).toBe(true);
    return dispatch(turn.state, { type: "build-running", now: 350 });
  }

  it("shows the rig's phase and issues nothing at all", () => {
    let turn = inFlight();
    const before = turn.state.cursor;
    for (const event of [
      phase(1, "raise_clear", "Raise Z into the top switch", 11),
      phase(6, "grip", "Close the claw and grip", 12),
      phase(8, "move_to_target", "Move XY to the target cell", 13),
    ]) {
      turn = dispatch(turn.state, event);
      expect(turn.effects).toEqual([]);
    }
    expect(turn.state.progress).toMatchObject({
      step: 8, total: 14, phaseId: "move_to_target",
      label: "Move XY to the target cell", commandSeq: 1,
    });
    expect(currentOperationText(turn.state)).toBe("8/14 · Move XY to the target cell");
    // Eight phases in, and the program has not moved on by one row.
    expect(turn.state.cursor).toBe(before);
    expect(turn.state.inFlight).toBe(true);
  });

  it("does not advance the cursor for the release, or for parking", () => {
    let turn = inFlight();
    turn = dispatch(turn.state, phase(11, "release", "Open the claw and release", 20,
                                      { action: "release" }));
    turn = dispatch(turn.state, phase(11, "release", "Open the claw and release", 21,
                                      { action: "release", status: "done" }));
    expect(turn.state.progress.released).toBe(true);
    expect(turn.state.cursor).toBe(0);

    turn = dispatch(turn.state, phase(14, "park_rotation", "Return the claw to neutral",
                                      22, { action: "park" }));
    expect(turn.state.cursor).toBe(0);
    expect(turn.state.inFlight).toBe(true);

    // ONLY the terminal placed moves it on.
    turn = dispatch(turn.state, { type: "build-settled", result: "placed", reason: null, now: 500 });
    expect(turn.state.cursor).toBe(1);
    expect(turn.state.progress).toEqual(noProgress());
  });

  it("ignores a phase that is older than one already applied", () => {
    let turn = inFlight();
    turn = dispatch(turn.state, phase(9, "rotate_to_grid", "Apply the grid rotation", 30));
    turn = dispatch(turn.state, phase(8, "move_to_target", "Move XY to the target cell", 25));
    expect(turn.state.progress.step).toBe(9);
    // And a repeat of the same id changes nothing.
    turn = dispatch(turn.state, phase(9, "rotate_to_grid", "Apply the grid rotation", 30));
    expect(turn.state.progress.step).toBe(9);
  });

  it("ignores phases when nothing is in flight — they belong to nobody here", () => {
    const turn = dispatch(initialRun(), phase(8, "move_to_target", "Move", 10));
    expect(turn.state.progress).toEqual(noProgress());
  });

  it("says nothing rather than guessing when the rig has not spoken", () => {
    expect(currentOperationText(inFlight().state)).toBeNull();
  });
});

describe("a lost socket pauses, and a later phase resumes", () => {
  function running() {
    let turn = start([build("a", 3, 2, 0)]);
    turn = dispatch(turn.state, { type: "selected", command: "B 3 2 0", now: 200 });
    turn = dispatch(turn.state, { type: "verified", actual: "B 3 2 0", now: 300 });
    turn = dispatch(turn.state, { type: "build-running", now: 350 });
    return dispatch(turn.state, {
      type: "build-step", commandSeq: 1, step: 8, total: 14, phaseId: "move_to_target",
      label: "Move XY to the target cell", action: "move", status: "begin",
      eventId: 40, now: 400,
    });
  }

  it("pauses stale and keeps the last phase as the last thing known", () => {
    const turn = dispatch(running().state, { type: "socket", connected: false, now: 500 });
    expect(turn.state.phase).toBe("paused");
    expect(turn.state.pauseReason).toBe("stale");
    expect(turn.effects).toEqual([]);
    // The phase is NOT cleared: it is the last thing anyone knows, and
    // blanking it would look like the build had finished.
    expect(turn.state.progress.step).toBe(8);
    expect(turn.state.cursor).toBe(0);
  });

  it("assumes nothing while it is down, however long that is", () => {
    let turn = dispatch(running().state, { type: "socket", connected: false, now: 500 });
    for (let tick = 0; tick < 20; tick += 1) {
      turn = dispatch(turn.state, { type: "socket", connected: false, now: 500 + tick });
      expect(turn.state.progress.step).toBe(8);
      expect(turn.state.cursor).toBe(0);
    }
  });

  it("picks itself up from a later phase, because a phase proves the rig is talking", () => {
    let turn = dispatch(running().state, { type: "socket", connected: false, now: 500 });
    turn = dispatch(turn.state, {
      type: "build-step", commandSeq: 1, step: 10, total: 14, phaseId: "lower_to_level",
      label: "Lower Z to the target level", action: "move", status: "begin",
      eventId: 41, now: 600,
    });
    expect(turn.state.phase).toBe("building");
    expect(turn.state.pauseReason).toBeNull();
    expect(turn.state.progress.step).toBe(10);
  });

  it("locks on HELD and stops there, phase and all", () => {
    let turn = running();
    turn = dispatch(turn.state, {
      type: "build-settled", result: "aborted", reason: "could not reach the target cell",
      now: 700,
    });
    expect(turn.state.phase).toBe("locked");
    expect(turn.state.readOnly).toBe(true);
    expect(turn.state.inFlight).toBe(false);
    expect(turn.state.cursor).toBe(0);
    expect(turn.effects).toEqual([]);
    // The phase it died at survives — that IS the information.
    expect(turn.state.progress.step).toBe(8);
    // And nothing gets it going again.
    for (const event of [
      { type: "continue" as const, now: 800 },
      { type: "confirm" as const, now: 800 },
      { type: "socket" as const, connected: true, now: 800 },
    ]) {
      const after = dispatch(turn.state, event);
      expect(after.effects).toEqual([]);
      expect(after.state.phase).toBe("locked");
    }
  });

  it("does NOT lock on a SAFE rejection — nothing moved, and it can continue", () => {
    let turn = running();
    turn = dispatch(turn.state, {
      type: "build-settled", result: "rejected", reason: "no block at the feeder", now: 700,
    });
    expect(turn.state.phase).toBe("rejected");
    expect(turn.state.readOnly).toBe(false);
    expect(turn.state.cursor).toBe(0);
    expect(dispatch(turn.state, { type: "continue", now: 800 }).state.phase)
      .not.toBe("locked");
  });
});
