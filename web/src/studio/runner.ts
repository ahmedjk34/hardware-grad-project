/**
 * A compiled program is still only a sequence of individually guarded builds.
 *
 * This reducer is the safety boundary on the client side: it describes one
 * effect at a time, but owns no fetch, timer, socket or React state. The driver
 * may execute an effect and feed the result back; it may never invent the next
 * command. That makes "no queue" and "nothing while RUNNING" reachable-state
 * properties that Vitest can exhaust instead of promises hidden in callbacks.
 * Server guards remain authoritative. This layer only refuses to ask for an
 * unsafe thing in the first place.
 *
 * WHERE PROGRESS COMES FROM. Once a build is in flight this reducer learns
 * nothing from its own clock. `build-step` events carry the phase the FIRMWARE
 * announced, and they are the only thing that moves `phase`/`phaseStep`. The
 * cursor still advances on nothing but a terminal `placed`, exactly as before —
 * a phase is progress WITHIN one command, never a reason to send the next one.
 *
 * `runTiming` remains an estimate and is labelled as one wherever it is drawn.
 * An estimate the operator can see is honest; an estimate dressed up as the
 * machine's position is not.
 */
import type { BuildPhaseAction } from "../types";
import type { ModeName } from "./coords";
import type { Op } from "./compile";

export type RunStyle = "step" | "run" | "dry";
export type RunPhase =
  | "idle" | "arming" | "verifying" | "awaiting-confirm" | "building"
  | "settled" | "rejected" | "aborted" | "paused" | "stopped-mismatch"
  | "locked" | "done";
export type ServerBuildState = "READY" | "RUNNING" | "LOCKED";

export interface RunLogEntry {
  index: number;
  kind: "build" | "mode";
  command: string;
  result: "placed" | "rejected" | "aborted" | "switched";
  startedAt: number;
  finishedAt: number;
  reason?: string | null;
  thumbnail?: string;
  verification?: string;
}

/** The rig's own account of the phase in flight, or nulls when none is. */
export interface RunProgress {
  commandSeq: number | null;
  step: number | null;
  total: number | null;
  /** The firmware's stable phase id, e.g. `move_to_target`. */
  phaseId: string | null;
  label: string | null;
  action: BuildPhaseAction | null;
  /** Phase 11 confirmed the jaws opened. Still not a placement. */
  released: boolean;
  /** The event id it came from, so a stale one cannot roll it backwards. */
  eventId: number;
}

export function noProgress(): RunProgress {
  return {
    commandSeq: null, step: null, total: null, phaseId: null, label: null,
    action: null, released: false, eventId: 0,
  };
}

export interface RunState {
  phase: RunPhase;
  style: RunStyle;
  program: Op[];
  cursor: number;
  modelName: string;
  colours: Record<string, string>;
  inFlight: boolean;
  buildState: ServerBuildState;
  connected: boolean;
  pendingConfirm: "build" | "mode" | null;
  selectedCommand: string | null;
  stopAfterCurrent: boolean;
  pauseReason: "stale" | "operator-stop" | "server-running" | null;
  mismatch: { program: string; rig: string } | null;
  failure: string | null;
  readOnly: boolean;
  startedAt: number | null;
  opStartedAt: number | null;
  finishedAt: number | null;
  log: RunLogEntry[];
  /** What the rig says it is doing right now. Never inferred, never timed. */
  progress: RunProgress;
}

export type Effect =
  | { kind: "select"; col: number; row: number; level: number; dry?: true }
  | { kind: "verify"; expect: string; actual: string | null }
  | { kind: "build"; command: string; dry: boolean }
  | { kind: "mode"; mode: ModeName; command: string; dry: boolean }
  | { kind: "warn"; text: string };

export type RunEvent =
  | { type: "start"; program: Op[]; style: RunStyle; modelName: string; colours: Record<string, string>; now: number }
  | { type: "selected"; command: string | null; now: number }
  | { type: "verified"; actual: string | null; now: number }
  | { type: "confirm"; now: number }
  | { type: "build-running"; now: number }
  | { type: "build-step"; commandSeq: number | null; step: number; total: number;
      phaseId: string; label: string; action: BuildPhaseAction;
      status: "begin" | "done"; eventId: number; now: number }
  | { type: "build-settled"; result: "placed" | "rejected" | "aborted"; reason: string | null; now: number; thumbnail?: string; verification?: string }
  | { type: "mode-settled"; now: number }
  | { type: "stop-after"; now: number }
  | { type: "continue"; now: number }
  | { type: "end"; now: number }
  | { type: "socket"; connected: boolean; now: number }
  | { type: "server-build-state"; buildState: ServerBuildState; now: number }
  | { type: "transport-error"; reason: string; now: number };

export interface Turn { state: RunState; effects: Effect[] }

export function initialRun(): RunState {
  return {
    phase: "idle", style: "step", program: [], cursor: 0, modelName: "",
    colours: {}, inFlight: false, buildState: "READY", connected: true,
    pendingConfirm: null, selectedCommand: null, stopAfterCurrent: false,
    pauseReason: null, mismatch: null, failure: null, readOnly: false,
    startedAt: null, opStartedAt: null, finishedAt: null, log: [],
    progress: noProgress(),
  };
}

const noEffects = (state: RunState): Turn => ({ state, effects: [] });

function guarded(state: RunState): Turn | null {
  if (state.readOnly || state.phase === "locked" || state.buildState === "LOCKED") {
    return noEffects({ ...state, phase: "locked", readOnly: true, inFlight: false });
  }
  if (!state.connected) {
    return noEffects({ ...state, phase: "paused", pauseReason: "stale" });
  }
  if (state.buildState === "RUNNING") {
    return noEffects({ ...state, phase: "paused", pauseReason: "server-running" });
  }
  if (state.inFlight) return noEffects(state);
  return null;
}

function advance(state: RunState, now: number): Turn {
  const blocked = guarded(state);
  if (blocked) return blocked;
  if (state.cursor >= state.program.length) {
    return noEffects({ ...state, phase: "done", finishedAt: now, pendingConfirm: null });
  }
  const op = state.program[state.cursor];
  if (op.op === "mode") {
    const text = `Switching to ${op.mode.toUpperCase()} homes X and Y. The rig will move without a B.`;
    return {
      state: { ...state, phase: "awaiting-confirm", pendingConfirm: "mode", selectedCommand: null },
      effects: [{ kind: "warn", text }],
    };
  }
  const effect: Effect = {
    kind: "select", col: op.col, row: op.row, level: op.level,
    ...(state.style === "dry" ? { dry: true as const } : {}),
  };
  return {
    state: { ...state, phase: "arming", pendingConfirm: null, selectedCommand: null, opStartedAt: now },
    effects: [effect],
  };
}

function issueBuild(state: RunState, now: number): Turn {
  const blocked = guarded(state);
  if (blocked) return blocked;
  const op = state.program[state.cursor];
  if (!op || op.op !== "build") return noEffects(state);
  return {
    state: {
      ...state, phase: "building", pendingConfirm: null, inFlight: true,
      opStartedAt: now, buildState: state.style === "dry" ? "RUNNING" : state.buildState,
      // The last block's phases describe the last block. Nothing is claimed
      // about this one until the rig says something about it.
      progress: noProgress(),
    },
    effects: [{ kind: "build", command: op.text, dry: state.style === "dry" }],
  };
}

function issueMode(state: RunState, now: number): Turn {
  const blocked = guarded(state);
  if (blocked) return blocked;
  const op = state.program[state.cursor];
  if (!op || op.op !== "mode") return noEffects(state);
  return {
    state: { ...state, phase: "building", pendingConfirm: null, inFlight: true, opStartedAt: now },
    effects: [{ kind: "mode", mode: op.mode, command: op.text, dry: state.style === "dry" }],
  };
}

function logResult(
  state: RunState,
  result: RunLogEntry["result"],
  now: number,
  extra: Pick<RunLogEntry, "reason" | "thumbnail" | "verification"> = {},
): RunLogEntry[] {
  const op = state.program[state.cursor];
  if (!op) return state.log;
  return [...state.log, {
    index: state.cursor,
    kind: op.op,
    command: op.text,
    result,
    startedAt: state.opStartedAt ?? now,
    finishedAt: now,
    ...extra,
  }];
}

/** The only transition function. Unknown/out-of-order events are inert. */
export function step(state: RunState, event: RunEvent): Turn {
  if (event.type === "start") {
    if (state.inFlight || state.buildState === "RUNNING") return noEffects(state);
    const next: RunState = {
      ...initialRun(), style: event.style, program: event.program, modelName: event.modelName,
      colours: event.colours, startedAt: event.now, connected: state.connected,
      buildState: state.buildState,
    };
    return advance(next, event.now);
  }

  if (event.type === "socket") {
    const next = { ...state, connected: event.connected };
    if (!event.connected && state.phase !== "idle" && state.phase !== "done" && state.phase !== "locked") {
      return noEffects({ ...next, phase: "paused", pauseReason: "stale" });
    }
    return noEffects(next);
  }

  if (event.type === "server-build-state") {
    const next = { ...state, buildState: event.buildState };
    if (event.buildState === "LOCKED") {
      return noEffects({ ...next, phase: "locked", readOnly: true, inFlight: false,
        failure: state.failure ?? "server session locked", finishedAt: event.now });
    }
    if (event.buildState === "RUNNING" && !state.inFlight && state.phase !== "idle") {
      return noEffects({ ...next, phase: "paused", pauseReason: "server-running" });
    }
    return noEffects(next);
  }

  if (event.type === "transport-error") {
    return noEffects({ ...state, phase: "paused", pauseReason: "stale", failure: event.reason });
  }

  if (state.phase === "locked" || state.readOnly) return noEffects(state);

  if (event.type === "selected") {
    if (state.phase !== "arming" || state.inFlight || state.buildState === "RUNNING") return noEffects(state);
    const op = state.program[state.cursor];
    if (!op || op.op !== "build") return noEffects(state);
    return {
      state: { ...state, phase: "verifying", selectedCommand: event.command },
      effects: [{ kind: "verify", expect: op.text, actual: event.command }],
    };
  }

  if (event.type === "verified") {
    if (state.phase !== "verifying" || state.inFlight || state.buildState === "RUNNING") return noEffects(state);
    const op = state.program[state.cursor];
    if (!op || op.op !== "build") return noEffects(state);
    if (event.actual !== op.text) {
      return noEffects({
        ...state, phase: "stopped-mismatch", readOnly: true, finishedAt: event.now,
        failure: "command mismatch",
        mismatch: { program: op.text, rig: event.actual ?? "null" },
      });
    }
    if (state.style === "step") {
      return noEffects({ ...state, phase: "awaiting-confirm", pendingConfirm: "build" });
    }
    return issueBuild(state, event.now);
  }

  if (event.type === "confirm") {
    if (state.phase !== "awaiting-confirm") return noEffects(state);
    if (state.pendingConfirm === "mode") return issueMode(state, event.now);
    if (state.pendingConfirm === "build") return issueBuild(state, event.now);
    return noEffects(state);
  }

  if (event.type === "build-running") {
    if (!state.inFlight) return noEffects(state);
    return noEffects({ ...state, buildState: "RUNNING" });
  }

  if (event.type === "build-step") {
    // Progress WITHIN one command. It never advances the cursor, never
    // completes an op and never issues an effect: only a terminal `placed`
    // does that. All it does is say what the rig is doing.
    if (!state.inFlight) return noEffects(state);
    if (event.eventId <= state.progress.eventId) return noEffects(state);
    if (event.status === "done") {
      return noEffects({
        ...state,
        progress: { ...state.progress, released: true, eventId: event.eventId },
      });
    }
    // A phase arriving means the socket is alive and the rig is working, so a
    // run paused only because the socket went quiet may pick itself back up.
    const resumed = state.phase === "paused" && state.pauseReason === "stale"
      ? { phase: "building" as const, pauseReason: null } : {};
    return noEffects({
      ...state, ...resumed, connected: true,
      progress: {
        commandSeq: event.commandSeq, step: event.step, total: event.total,
        phaseId: event.phaseId, label: event.label, action: event.action,
        released: event.commandSeq !== null
          && event.commandSeq !== state.progress.commandSeq
          ? false : state.progress.released,
        eventId: event.eventId,
      },
    });
  }

  if (event.type === "build-settled") {
    const op = state.program[state.cursor];
    if (!state.inFlight || !op || op.op !== "build") return noEffects(state);
    const log = logResult(state, event.result, event.now, {
      reason: event.reason, thumbnail: event.thumbnail, verification: event.verification,
    });
    // Keep the last phase on a failure — it is the last thing anyone knows
    // about where the machine is — and clear it on success, where the command
    // is over and the rig is parked.
    const base = { ...state, inFlight: false, buildState: "READY" as const, log };
    if (event.result === "rejected") {
      return noEffects({ ...base, phase: "rejected", failure: event.reason, pauseReason: null });
    }
    if (event.result === "aborted") {
      return noEffects({ ...base, phase: "locked", readOnly: true, failure: event.reason,
        finishedAt: event.now });
    }
    const placed = { ...base, cursor: state.cursor + 1, failure: null,
      progress: noProgress() };
    if (state.stopAfterCurrent) {
      return noEffects({ ...placed, phase: "paused", pauseReason: "operator-stop" });
    }
    return advance(placed, event.now);
  }

  if (event.type === "mode-settled") {
    const op = state.program[state.cursor];
    if (!state.inFlight || !op || op.op !== "mode") return noEffects(state);
    const next = {
      ...state, inFlight: false, buildState: "READY" as const, cursor: state.cursor + 1,
      log: logResult(state, "switched", event.now),
    };
    return advance(next, event.now);
  }

  if (event.type === "stop-after") {
    if (state.phase === "done" || state.phase === "idle") return noEffects(state);
    if (state.inFlight) return noEffects({ ...state, stopAfterCurrent: true });
    return noEffects({ ...state, phase: "paused", stopAfterCurrent: true, pauseReason: "operator-stop" });
  }

  if (event.type === "continue") {
    if (state.phase !== "rejected" && state.phase !== "paused") return noEffects(state);
    const next = { ...state, phase: "settled" as const, failure: null,
      stopAfterCurrent: false, pauseReason: null };
    return advance(next, event.now);
  }

  if (event.type === "end") {
    if (state.inFlight) return noEffects(state);
    return noEffects({ ...state, phase: "done", finishedAt: event.now, pendingConfirm: null });
  }

  return noEffects(state);
}

/**
 * What to show as the current operation. The rig's words when it has any.
 *
 * `null` is not "nothing is happening": it is "the rig has not said". The
 * caller draws that as a waiting state rather than as a guess.
 */
export function currentOperationText(state: RunState): string | null {
  const { step, total, label } = state.progress;
  if (label === null || step === null) return null;
  return total === null ? label : `${step}/${total} · ${label}`;
}

export function currentOp(state: RunState): Op | null {
  return state.program[state.cursor] ?? null;
}

export function buildPosition(state: RunState): { current: number; total: number } {
  const total = state.program.filter(op => op.op === "build").length;
  const before = state.program.slice(0, state.cursor).filter(op => op.op === "build").length;
  const current = Math.min(total, before + (currentOp(state)?.op === "build" ? 1 : 0));
  return { current, total };
}

export function feederPrompt(state: RunState): { colour: string; same: boolean; text: string } | null {
  let targetIndex = state.cursor;
  const current = currentOp(state);
  // Once a build is in flight its feeder block has already been picked up.
  // Use that otherwise-dead motion time to tell the human what must be loaded
  // for the next B, which is how RUN can be continuous with a manual feeder.
  if (state.inFlight && current?.op === "build") {
    const next = state.program.findIndex((item, index) => index > state.cursor && item.op === "build");
    if (next < 0) return null;
    targetIndex = next;
  }
  const op = state.program[targetIndex];
  if (!op || op.op !== "build") return null;
  const total = state.program.filter(item => item.op === "build").length;
  const number = state.program.slice(0, targetIndex + 1).filter(item => item.op === "build").length;
  const colour = (state.colours[op.id] ?? "white").toUpperCase();
  const previousBuild = [...state.program.slice(0, targetIndex)].reverse().find(item => item.op === "build");
  const previous = previousBuild?.op === "build" ? (state.colours[previousBuild.id] ?? "white").toUpperCase() : null;
  return { colour, same: previous === colour, text: `block ${number} of ${total} · ${op.text}` };
}

export function runTiming(
  state: RunState,
  now: number,
  blockCycleSeconds: number,
  latchHomingSeconds: number,
): { elapsedSeconds: number; etaSeconds: number } {
  const started = state.startedAt ?? now;
  const finished = state.finishedAt ?? now;
  const remaining = state.program.slice(state.cursor);
  const builds = remaining.filter(op => op.op === "build").length;
  const latches = remaining.length - builds;
  return {
    elapsedSeconds: Math.max(0, (finished - started) / 1000),
    etaSeconds: builds * blockCycleSeconds + latches * latchHomingSeconds,
  };
}

export function programRows(state: RunState): { index: number; text: string; status: "reached" | "stopped" | "future" }[] {
  return state.program.map((op, index) => ({
    index,
    text: op.text,
    status: index < state.cursor ? "reached" : index === state.cursor ? "stopped" : "future",
  }));
}
