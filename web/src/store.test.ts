/**
 * The store is where the browser decides what it believes about the machine.
 *
 * Two rules, and everything below is one of them:
 *
 * **Progress is applied immediately.** A `build_step` moves the phase on the
 * turn it arrives — no timer, no batch, no waiting for the next state snapshot.
 *
 * **Nothing is claimed twice, and nothing is claimed by resemblance.** Events
 * are deduplicated by ID. Two identical serial lines are two real lines; the
 * same id twice is one event delivered twice, which a generous replay does on
 * purpose.
 */
import { describe, expect, it, vi } from "vitest";
import { createConsoleStore, emptyProgress, logKindOf, LOG_CAP } from "./store";
import { testState } from "./test-state";
import type { ServerEvent, StateModel } from "./types";

const stateEvent = (id: number, overrides: Partial<StateModel> = {}): ServerEvent =>
  ({ type: "state", event_id: id, at: id * 10, state: testState(overrides) });

const stepEvent = (id: number, step: number, phase: string, label: string,
                   extra: Partial<{ action: "move" | "grip" | "release" | "rotate" | "park";
                                    status: "begin" | "done"; command_seq: number }> = {}):
  ServerEvent => ({
    type: "build_step", event_id: id, at: id * 10, command_seq: 1, step, total: 14,
    phase, label, action: "move", status: "begin", ...extra,
  });

const resultEvent = (id: number, result: "placed" | "rejected" | "aborted",
                     reason: string | null = null, locked = false): ServerEvent =>
  ({ type: "build_result", event_id: id, at: id * 10, command_seq: 1, result, reason,
     locked, locked_reason: locked ? reason : null, from_prose: false });

const serialEvent = (id: number, line: string): ServerEvent =>
  ({ type: "serial", event_id: id, at: id * 10, line, stream: "rig" });

describe("build_step is applied immediately", () => {
  it("moves the phase on the turn the event arrives, and notifies once", () => {
    const store = createConsoleStore();
    const listener = vi.fn();
    store.subscribe(listener);

    store.applyEvent(stepEvent(10, 8, "move_to_target", "Move XY to the target cell"));

    // Synchronous. No timer has been advanced and no promise awaited.
    expect(store.snapshot.progress.step).toBe(8);
    expect(store.snapshot.progress.phase).toBe("move_to_target");
    expect(store.snapshot.progress.label).toBe("Move XY to the target cell");
    expect(store.snapshot.progress.total).toBe(14);
    expect(store.snapshot.progress.status).toBe("running");
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("calls a park action parking, which is still a running command", () => {
    const store = createConsoleStore();
    store.applyEvent(stepEvent(11, 13, "park_home", "Return XY to the origin",
                               { action: "park" }));
    expect(store.snapshot.progress.status).toBe("parking");
  });

  it("records the release without calling it a placement", () => {
    const store = createConsoleStore();
    store.applyEvent(stepEvent(10, 11, "release", "Open the claw and release",
                               { action: "release" }));
    store.applyEvent(stepEvent(11, 11, "release", "Open the claw and release",
                               { action: "release", status: "done" }));
    expect(store.snapshot.progress.releaseConfirmed).toBe(true);
    // The phase has not advanced — the next `begin` does that — and the
    // command has not settled.
    expect(store.snapshot.progress.step).toBe(11);
    expect(store.snapshot.progress.status).toBe("running");
    expect(store.snapshot.lastResult).toBeNull();
  });

  it("only build_result can say placed", () => {
    const store = createConsoleStore();
    for (let step = 1; step <= 14; step += 1) {
      store.applyEvent(stepEvent(step, step, `phase_${step}`, `Phase ${step}`));
      expect(store.snapshot.progress.status).not.toBe("placed");
    }
    store.applyEvent(resultEvent(50, "placed"));
    expect(store.snapshot.progress.status).toBe("placed");
    expect(store.snapshot.lastResult?.result).toBe("placed");
  });

  it("keeps a lock apart from the word aborted", () => {
    const store = createConsoleStore();
    store.applyEvent(resultEvent(50, "aborted", "claw did not release", true));
    expect(store.snapshot.progress.status).toBe("locked");
    store.applyEvent(resultEvent(51, "rejected", "cell out of range"));
    expect(store.snapshot.progress.status).toBe("rejected");
  });

  it("clears the previous build's release when a new command's phases start", () => {
    const store = createConsoleStore();
    store.applyEvent(stepEvent(10, 11, "release", "Open", { status: "done" }));
    store.applyEvent(resultEvent(11, "placed"));
    expect(store.snapshot.progress.releaseConfirmed).toBe(true);
    store.applyEvent(stepEvent(20, 1, "raise_clear", "Raise Z", { command_seq: 2 }));
    expect(store.snapshot.progress.releaseConfirmed).toBe(false);
    expect(store.snapshot.progress.commandSeq).toBe(2);
  });
});

describe("deduplication is by event id, never by content", () => {
  it("drops a repeated id and applies a genuinely new one", () => {
    const store = createConsoleStore();
    store.applyEvent(stepEvent(10, 8, "move_to_target", "Move"));
    const listener = vi.fn();
    store.subscribe(listener);

    store.applyEvent(stepEvent(10, 8, "move_to_target", "Move"));
    expect(listener).not.toHaveBeenCalled();
    store.applyEvent(stepEvent(11, 9, "rotate_to_grid", "Rotate"));
    expect(store.snapshot.progress.step).toBe(9);
  });

  it("never lets an older durable event roll the phase backwards", () => {
    const store = createConsoleStore();
    store.applyEvent(stepEvent(20, 9, "rotate_to_grid", "Rotate"));
    store.applyEvent(stepEvent(15, 8, "move_to_target", "Move"));
    expect(store.snapshot.progress.step).toBe(9);
  });

  it("keeps two identical lines, because the rig printed two", () => {
    const store = createConsoleStore();
    store.applyEvent(serialEvent(1, "  AT ORIGIN. Position = X 0 / Y 0"));
    store.applyEvent(serialEvent(2, "  AT ORIGIN. Position = X 0 / Y 0"));
    expect(store.snapshot.log).toHaveLength(2);
  });

  it("caps the log at the browser's own window", () => {
    const store = createConsoleStore();
    store.applyEvents(Array.from({ length: LOG_CAP + 20 },
      (_, index) => serialEvent(index + 1, `line ${index}`)));
    expect(store.snapshot.log).toHaveLength(LOG_CAP);
  });
});

describe("state snapshots and phase events cannot fight", () => {
  it("takes the snapshot's progress when the snapshot is the newer of the two", () => {
    const store = createConsoleStore();
    store.applyEvent(stepEvent(10, 8, "move_to_target", "Move"));
    store.applyEvent(stateEvent(20, {
      build_state: "RUNNING", build_step: 9, build_total_steps: 14,
      build_phase: "rotate_to_grid", build_phase_label: "Apply the grid rotation",
      build_phase_status: "running", serial_event_id: 18,
    }));
    expect(store.snapshot.progress.step).toBe(9);
  });

  it("ignores a snapshot folded from an OLDER event than the phase it has", () => {
    // The two travel by different priorities: a coalesced state can arrive
    // after a phase event that is newer than the state it was built from.
    const store = createConsoleStore();
    store.applyEvent(stepEvent(30, 9, "rotate_to_grid", "Rotate"));
    store.applyEvent(stateEvent(31, {
      build_state: "RUNNING", build_step: 8, build_phase: "move_to_target",
      build_phase_status: "running", serial_event_id: 25,
    }));
    expect(store.snapshot.progress.step).toBe(9);
    // The rest of the snapshot still applies — only the progress half defers.
    expect(store.snapshot.state?.build_state).toBe("RUNNING");
  });

  it("adopts a snapshot's progress on a fresh page, mid-build", () => {
    const store = createConsoleStore();
    store.applyEvent(stateEvent(80, {
      build_state: "RUNNING", build_command_seq: 4, build_step: 8,
      build_total_steps: 14, build_phase: "move_to_target",
      build_phase_label: "Move XY to the target cell", build_phase_action: "move",
      build_phase_status: "running", serial_event_id: 77,
    }));
    expect(store.snapshot.progress).toMatchObject({
      commandSeq: 4, step: 8, total: 14, phase: "move_to_target", status: "running",
    });
  });
});

describe("the reconnect cursor", () => {
  it("resumes from the newest DURABLE id, not from the opening snapshot's", () => {
    const store = createConsoleStore();
    store.applyEvent(serialEvent(40, "@0 READY"));
    // A fresh socket's opening state is minted AFTER everything in the replay
    // buffer. Resuming from its id would skip the whole backlog.
    store.applyEvent(stateEvent(100));
    expect(store.snapshot.resumeId).toBe(40);
    expect(store.snapshot.lastEventId).toBe(100);
  });

  it("applies a replay whose ids predate the opening snapshot", () => {
    const store = createConsoleStore();
    store.applyEvent(stateEvent(100));
    store.applyEvents([
      serialEvent(61, "@12 RECV cmd=B col=3 row=2 level=0"),
      stepEvent(62, 1, "raise_clear", "Raise Z into the top switch"),
      stepEvent(63, 8, "move_to_target", "Move XY to the target cell"),
    ]);
    expect(store.snapshot.log).toHaveLength(1);
    expect(store.snapshot.progress.step).toBe(8);
    expect(store.snapshot.resumeId).toBe(63);
  });

  it("a replay that overlaps what is already applied costs nothing", () => {
    const store = createConsoleStore();
    const replay = [serialEvent(1, "a"), serialEvent(2, "b"), stepEvent(3, 1, "raise_clear", "Raise")];
    store.applyEvents(replay);
    const listener = vi.fn();
    store.subscribe(listener);
    store.applyEvents(replay);
    expect(listener).not.toHaveBeenCalled();
    expect(store.snapshot.log).toHaveLength(2);
  });

  it("a heartbeat proves the socket is alive and changes nothing else", () => {
    const store = createConsoleStore();
    store.applyEvent(stepEvent(10, 8, "move_to_target", "Move"));
    const before = store.snapshot.progress;
    store.applyEvent({ type: "heartbeat", event_id: 11, at: 110 });
    expect(store.snapshot.progress).toBe(before);
    expect(store.snapshot.lastEventId).toBe(11);
    expect(store.snapshot.resumeId).toBe(10);
  });

  it("records a gap it could not fill, rather than pretending to be complete", () => {
    const store = createConsoleStore();
    expect(store.snapshot.gap).toBe(false);
    store.noteGap(true);
    expect(store.snapshot.gap).toBe(true);
  });
});

describe("the log's kinds", () => {
  it("tells a structured phase from ordinary ack noise and from prose", () => {
    expect(logKindOf("@12 STEP step=8 total=14 phase=move_to_target", "rig")).toBe("step");
    expect(logKindOf("@12 OK col=3 row=2 level=0", "rig")).toBe("ack");
    expect(logKindOf("[BUILD 8/14] Move X/Y to the target cell", "rig")).toBe("prose");
    expect(logKindOf("serial port went away", "error")).toBe("error");
  });

  it("starts idle, with nothing claimed about any build", () => {
    expect(createConsoleStore().snapshot.progress).toEqual(emptyProgress());
    expect(createConsoleStore().snapshot.progress.status).toBe("idle");
  });
});
