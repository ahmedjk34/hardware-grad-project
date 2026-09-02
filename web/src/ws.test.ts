/**
 * The socket, against a fake `WebSocket`.
 *
 * What is worth asserting here is not "it parses JSON". It is the two things
 * that would silently cost the operator information: that a build phase reaches
 * the store on the turn it arrives rather than after a timer, and that a
 * reconnect asks for what it missed by ID rather than starting blank.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createConsoleStore } from "./store";
import { connectEvents } from "./ws";
import { testState } from "./test-state";
import type { ServerEvent } from "./types";

class FakeSocket {
  static opened: FakeSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;

  constructor(readonly url: string) {
    FakeSocket.opened.push(this);
  }

  open() { this.onopen?.(); }
  send(message: unknown) { this.onmessage?.({ data: JSON.stringify(message) }); }
  drop() { this.closed = true; this.onclose?.(); }
  close() { this.closed = true; }
}

const original = globalThis.WebSocket;

beforeEach(() => {
  FakeSocket.opened = [];
  vi.useFakeTimers();
  // The client builds its URL from `location`; jsdom supplies a real one.
  (globalThis as { WebSocket: unknown }).WebSocket = FakeSocket;
});

afterEach(() => {
  vi.useRealTimers();
  (globalThis as { WebSocket: unknown }).WebSocket = original;
});

const latest = () => FakeSocket.opened.at(-1)!;

const step = (id: number, stepNumber: number): ServerEvent => ({
  type: "build_step", event_id: id, at: id, command_seq: 1, step: stepNumber,
  total: 14, phase: "move_to_target", label: "Move XY to the target cell",
  action: "move", status: "begin",
});

describe("connectEvents", () => {
  it("applies a build_step with NO timer advanced at all", () => {
    const store = createConsoleStore();
    const stop = connectEvents(store);
    latest().open();

    latest().send(step(10, 8));

    // vi.useFakeTimers() is in force and nothing has been advanced. If the
    // client batched progress behind a `setTimeout`, this would still be null.
    expect(store.snapshot.progress.step).toBe(8);
    expect(store.snapshot.progress.phase).toBe("move_to_target");
    stop();
  });

  it("applies each serial line as it arrives, in order", () => {
    const store = createConsoleStore();
    const stop = connectEvents(store);
    latest().open();
    for (const [id, line] of [[1, "first"], [2, "second"], [3, "third"]] as const) {
      latest().send({ type: "serial", event_id: id, at: id, line, stream: "rig" });
      expect(store.snapshot.log.at(-1)?.text).toBe(line);
    }
    expect(store.snapshot.log.map(entry => entry.text))
      .toEqual(["first", "second", "third"]);
    stop();
  });

  it("opens with no cursor, and reconnects asking for what it missed", () => {
    const store = createConsoleStore();
    const stop = connectEvents(store);
    expect(latest().url).toMatch(/\/api\/events$/);
    latest().open();

    latest().send({ type: "state", event_id: 100, at: 1, state: testState() });
    latest().send(step(101, 8));
    latest().send({ type: "serial", event_id: 102, at: 1, line: "@1 OK", stream: "rig" });

    latest().drop();
    expect(store.snapshot.connected).toBe(false);

    vi.advanceTimersByTime(300);
    // 102 is the newest DURABLE id — not 100, and not the state's.
    expect(latest().url).toMatch(/\/api\/events\?after=102$/);
    stop();
  });

  it("marks the client disconnected the moment the socket drops", () => {
    const store = createConsoleStore();
    const stop = connectEvents(store);
    latest().open();
    expect(store.snapshot.connected).toBe(true);
    latest().drop();
    // The runner and the twin both read this and must go stale on it: nobody
    // knows whether the build carried on.
    expect(store.snapshot.connected).toBe(false);
    stop();
  });

  it("applies a replay envelope as one batch, and records a gap", () => {
    const store = createConsoleStore();
    const stop = connectEvents(store);
    latest().open();
    latest().send({
      type: "replay", event_id: 50, at: 1, gap: true,
      events: [step(41, 6), step(42, 7), step(43, 8)],
    });
    expect(store.snapshot.progress.step).toBe(8);
    expect(store.snapshot.gap).toBe(true);
    expect(store.snapshot.resumeId).toBe(43);
    stop();
  });

  it("ignores a frame it cannot parse rather than guessing at it", () => {
    const store = createConsoleStore();
    const stop = connectEvents(store);
    latest().open();
    latest().onmessage?.({ data: "not json" });
    expect(store.snapshot.progress.step).toBeNull();
    expect(store.snapshot.log).toEqual([]);
    stop();
  });

  it("backs off between reconnects and stops when told to", () => {
    const store = createConsoleStore();
    const stop = connectEvents(store);
    latest().open();
    latest().drop();
    vi.advanceTimersByTime(250);
    expect(FakeSocket.opened).toHaveLength(2);
    latest().drop();
    vi.advanceTimersByTime(250);
    expect(FakeSocket.opened).toHaveLength(2);  // the delay doubled
    vi.advanceTimersByTime(250);
    expect(FakeSocket.opened).toHaveLength(3);

    stop();
    latest().drop();
    vi.advanceTimersByTime(10_000);
    expect(FakeSocket.opened).toHaveLength(3);
  });
});
