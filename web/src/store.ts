import type {
  BuildPhaseAction, BuildPhaseStatus, BuildResultEvent, BuildStepEvent,
  LogKind, LogLine, ServerEvent, StateModel,
} from "./types";

/** The rig log's window. The server keeps its own 200; this is the browser's. */
export const LOG_CAP = 200;

/**
 * What the console believes about the build in flight.
 *
 * Every field here came off the serial cable. `step`, `phase` and `label` move
 * ONLY when a `build_step` event arrives or a state snapshot carries a newer
 * one — never on a timer, and never because this browser sent a command. If the
 * socket goes quiet the phase simply stops advancing, which is the truth.
 *
 * `eventId` is the id of the event that last moved any of it. It is what makes
 * the two sources safe to mix: a state snapshot folded from event 40 cannot
 * overwrite a phase this client already applied from event 43, however the
 * network reordered them.
 */
export interface BuildProgress {
  commandSeq: number | null;
  step: number | null;
  total: number | null;
  phase: string | null;
  label: string | null;
  action: BuildPhaseAction | null;
  status: BuildPhaseStatus;
  /** The confirmed release: phase 11 said `done`. Not the same as placed. */
  releaseConfirmed: boolean;
  /** When this phase started, by the SERVER's clock. */
  startedAt: number | null;
  /**
   * When this browser was TOLD, by its own clock.
   *
   * Separate from `startedAt` because the two clocks are not the same one:
   * `startedAt` is the server's epoch and may be seconds off this machine's.
   * Anything that animates must count from a local anchor, so it counts
   * from here.
   */
  receivedAt: number | null;
  /**
   * The firmware's predicted duration for this phase, in ms, or null.
   *
   * A FLOOR, not a schedule — the real phase can only take longer. See
   * `docs/ack-protocol.md`. Its expiry means nothing; only the next event
   * says a phase is over.
   */
  etaMs: number | null;
  eventId: number;
}

/**
 * Statuses in which NO phase is executing: the command settled, or none has
 * started. A settled command's snapshot still carries the phase it stopped on
 * — `web/progress.py` deliberately keeps it, because "where it got to" is the
 * last thing anyone knows about a FAILED build — so the status, not the
 * presence of a phase, is what says whether the rig is mid-command.
 */
const SETTLED_STATUSES: ReadonlySet<BuildPhaseStatus> =
  new Set<BuildPhaseStatus>(["idle", "placed", "rejected", "aborted", "locked"]);

/** True while the rig is working on a command. False once one has settled. */
export function phaseInFlight(progress: BuildProgress): boolean {
  return !SETTLED_STATUSES.has(progress.status);
}

export function emptyProgress(): BuildProgress {
  return {
    commandSeq: null, step: null, total: null, phase: null, label: null,
    action: null, status: "idle", releaseConfirmed: false, startedAt: null,
    receivedAt: null, etaMs: null, eventId: 0,
  };
}

export interface ConsoleSnapshot {
  state: StateModel | null;
  connected: boolean;
  log: LogLine[];
  /** When the last state message arrived. The twin's STALE age counts from it. */
  updatedAt: number | null;
  /** The current build phase, from the serial stream. */
  progress: BuildProgress;
  /** The last settled build, as the server reported it. Null until one settles. */
  lastResult: (BuildResultEvent & { eventId: number }) | null;
  /** The newest id of ANY applied event, durable or not. */
  lastEventId: number;
  /**
   * The cursor a reconnect resumes from: the newest DURABLE id applied.
   *
   * Deliberately not `lastEventId`. A fresh socket is sent its opening state
   * snapshot before the replay, and that snapshot's id is newer than every
   * event in the replay — resuming from it would skip the whole backlog.
   */
  resumeId: number;
  /** True when a reconnect could not be filled from the replay buffer. */
  gap: boolean;
}

export interface ConsoleStore {
  snapshot: ConsoleSnapshot;
  subscribe(listener: () => void): () => void;
  /** Apply one server event. Out-of-order and repeated ids are safe. */
  applyEvent(event: ServerEvent): void;
  /** Apply a batch — a reconnect's replay — with one notification at the end. */
  applyEvents(events: ServerEvent[]): void;
  connected(): void;
  disconnected(): void;
  /** A reconnect whose `after` predated the server's replay buffer. */
  noteGap(gap: boolean): void;
}

/** How a raw line is drawn. The `@n STEP` lines earn their own treatment. */
export function logKindOf(text: string, stream: "rig" | "error"): LogKind {
  if (stream === "error") return "error";
  const trimmed = text.trimStart();
  if (/^@\d+\s+STEP\b/.test(trimmed)) return "step";
  if (trimmed.startsWith("@")) return "ack";
  return "prose";
}

function progressFromStep(
  previous: BuildProgress, event: BuildStepEvent & { event_id: number; at: number },
): BuildProgress {
  if (event.status === "done") {
    // The confirmed release. The phase itself does not advance — the next
    // `begin` does that — so only the release flag and the id move.
    return { ...previous, releaseConfirmed: true, eventId: event.event_id };
  }
  return {
    commandSeq: event.command_seq,
    step: event.step,
    total: event.total,
    phase: event.phase,
    label: event.label,
    action: event.action,
    status: event.action === "park" ? "parking" : "running",
    // A new command's first phase clears the last one's release.
    releaseConfirmed:
      event.command_seq !== null && event.command_seq !== previous.commandSeq
        ? false : previous.releaseConfirmed,
    startedAt: event.at,
    receivedAt: Date.now(),
    etaMs: event.eta_ms ?? null,
    eventId: event.event_id,
  };
}

function progressFromState(previous: BuildProgress, state: StateModel): BuildProgress {
  // The snapshot is folded from `serial_event_id`. If this client has already
  // applied something newer, the snapshot is stale progress and is ignored —
  // the rest of the state still applies.
  if (state.serial_event_id < previous.eventId) return previous;
  return {
    commandSeq: state.build_command_seq,
    step: state.build_step,
    total: state.build_total_steps,
    phase: state.build_phase,
    label: state.build_phase_label,
    action: state.build_phase_action,
    status: state.build_phase_status,
    releaseConfirmed: state.build_release_confirmed,
    startedAt: state.build_phase_started_at,
    // A snapshot says when the phase started on the SERVER's clock, and this
    // client is learning it now — so the local anchor is only as good as how
    // long the snapshot took to arrive. Good enough to resume an animation
    // mid-phase; the clamp below is what stops that mattering.
    receivedAt: previous.eventId === state.serial_event_id
      ? previous.receivedAt : Date.now(),
    etaMs: state.build_phase_eta_ms,
    eventId: state.serial_event_id,
  };
}

export function createConsoleStore(): ConsoleStore {
  let snapshot: ConsoleSnapshot = {
    state: null, connected: false, log: [], updatedAt: null,
    progress: emptyProgress(), lastResult: null, lastEventId: 0, resumeId: 0,
    gap: false,
  };
  // The two dedupe cursors are separate because the two streams have separate
  // priorities on the wire: a coalesced state can legitimately arrive with a
  // NEWER id than a durable event still queued behind it.
  let lastStateId = 0;
  let sequence = 0;
  const listeners = new Set<() => void>();
  const publish = () => listeners.forEach(listener => listener());

  /** Fold one event in. Returns false when it changed nothing. */
  function fold(event: ServerEvent): boolean {
    // Deduplicate by ID, never by content. Two identical serial lines are two
    // real lines the rig printed; the same id twice is one event delivered
    // twice, which a generous replay does on purpose.
    const durable = event.type === "serial" || event.type === "build_step"
      || event.type === "build_result";
    if (durable && event.event_id <= snapshot.resumeId) return false;
    if (event.type === "state" && event.event_id <= lastStateId) return false;

    const lastEventId = Math.max(snapshot.lastEventId, event.event_id);
    const resumeId = durable ? Math.max(snapshot.resumeId, event.event_id)
                             : snapshot.resumeId;

    if (event.type === "state") {
      lastStateId = event.event_id;
      snapshot = {
        ...snapshot, state: event.state, connected: true, updatedAt: Date.now(),
        // Only the PROGRESS half of a snapshot can be stale relative to a
        // phase event; the rest of it is always the newest description of now.
        progress: progressFromState(snapshot.progress, event.state),
        lastEventId, resumeId,
      };
      return true;
    }
    if (event.type === "build_step") {
      snapshot = {
        ...snapshot, progress: progressFromStep(snapshot.progress, event),
        lastEventId, resumeId,
      };
      return true;
    }
    if (event.type === "build_result") {
      const status: BuildPhaseStatus =
        event.locked ? "locked"
        : event.result === "placed" ? "placed"
        : event.result === "rejected" ? "rejected" : "aborted";
      snapshot = {
        ...snapshot,
        // The ONLY route to a terminal status on the client, exactly as
        // `web/progress.py` is the only route to one on the server.
        progress: { ...snapshot.progress, status, eventId: event.event_id },
        lastResult: { ...event, eventId: event.event_id },
        lastEventId, resumeId,
      };
      return true;
    }
    if (event.type === "serial") {
      snapshot = {
        ...snapshot,
        log: [...snapshot.log, {
          id: sequence++, text: event.line, at: event.at,
          kind: logKindOf(event.line, event.stream),
        }].slice(-LOG_CAP),
        lastEventId, resumeId,
      };
      return true;
    }
    // A heartbeat carries nothing but its id, and that is the point: it proves
    // the socket is alive without pretending anything changed.
    snapshot = { ...snapshot, lastEventId };
    return true;
  }

  return {
    get snapshot() { return snapshot; },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    applyEvent(event) {
      if (fold(event)) publish();
    },
    applyEvents(events) {
      let changed = false;
      for (const event of events) changed = fold(event) || changed;
      if (changed) publish();
    },
    connected() {
      snapshot = { ...snapshot, connected: true };
      publish();
    },
    disconnected() {
      snapshot = { ...snapshot, connected: false };
      publish();
    },
    noteGap(gap) {
      if (gap === snapshot.gap) return;
      snapshot = { ...snapshot, gap };
      publish();
    },
  };
}
