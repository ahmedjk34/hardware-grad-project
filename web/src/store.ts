import type { LogLine, StateModel } from "./types";

/** The backend replays its whole 200-line deque on every log revision, so the
 *  client keeps the same cap and folds each replay onto what it already has. */
export const LOG_CAP = 200;

export interface ConsoleSnapshot {
  state: StateModel | null;
  connected: boolean;
  log: LogLine[];
  /** When the last state message arrived. The twin's STALE age counts from it. */
  updatedAt: number | null;
}

export interface ConsoleStore {
  snapshot: ConsoleSnapshot;
  subscribe(listener: () => void): () => void;
  apply(state: StateModel): void;
  connected(): void;
  disconnected(): void;
  /** Merge one replayed log window; only the lines beyond the overlap are new. */
  mergeLog(lines: string[]): void;
}

function overlap(previous: LogLine[], lines: string[]): number {
  for (let size = Math.min(previous.length, lines.length); size > 0; size--) {
    const tail = previous.slice(previous.length - size);
    if (tail.every((entry, index) => entry.text === lines[index])) return size;
  }
  return 0;
}

export function createConsoleStore(): ConsoleStore {
  let snapshot: ConsoleSnapshot = { state: null, connected: false, log: [], updatedAt: null };
  let sequence = 0;
  const listeners = new Set<() => void>();
  const publish = () => listeners.forEach(listener => listener());
  return {
    get snapshot() { return snapshot; },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    apply(state) {
      snapshot = { ...snapshot, state, connected: true, updatedAt: Date.now() };
      publish();
    },
    connected() {
      snapshot = { ...snapshot, connected: true };
      publish();
    },
    disconnected() {
      snapshot = { ...snapshot, connected: false };
      publish();
    },
    mergeLog(lines) {
      if (!lines.length) return;
      const fresh = lines.slice(overlap(snapshot.log, lines));
      if (!fresh.length) return;
      const now = Date.now();
      const appended = fresh.map(text => ({ id: sequence++, text, at: now }));
      snapshot = { ...snapshot, log: [...snapshot.log, ...appended].slice(-LOG_CAP) };
      publish();
    },
  };
}
