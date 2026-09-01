/**
 * Generic bounded undo/redo history.
 *
 * The Studio records completed edits, not pointer samples. Keeping this module
 * ignorant of blocks is what makes a shift-drag placement one understandable
 * command and keeps the undo contract independently testable.
 */
export interface History<T> {
  past: T[];
  present: T;
  future: T[];
  limit: number;
}

export const DEFAULT_HISTORY_LIMIT = 100;

export function createHistory<T>(initial: T, limit = DEFAULT_HISTORY_LIMIT): History<T> {
  return { past: [], present: initial, future: [], limit: Math.max(100, limit) };
}

export function canUndo<T>(history: History<T>): boolean { return history.past.length > 0; }
export function canRedo<T>(history: History<T>): boolean { return history.future.length > 0; }

export function push<T>(history: History<T>, value: T): History<T> {
  if (Object.is(value, history.present)) return history;
  const past = [...history.past, history.present];
  return {
    past: past.length > history.limit ? past.slice(past.length - history.limit) : past,
    present: value,
    future: [],
    limit: history.limit,
  };
}

export function undo<T>(history: History<T>): History<T> {
  if (!canUndo(history)) return history;
  const present = history.past[history.past.length - 1];
  return {
    past: history.past.slice(0, -1),
    present,
    future: [history.present, ...history.future],
    limit: history.limit,
  };
}

export function redo<T>(history: History<T>): History<T> {
  if (!canRedo(history)) return history;
  const [present, ...future] = history.future;
  const past = [...history.past, history.present];
  return {
    past: past.length > history.limit ? past.slice(past.length - history.limit) : past,
    present,
    future,
    limit: history.limit,
  };
}
