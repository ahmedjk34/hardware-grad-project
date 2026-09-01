import type { StateModel } from "./types";

export interface ConsoleSnapshot { state: StateModel | null; connected: boolean }
export interface ConsoleStore { snapshot: ConsoleSnapshot; subscribe(listener: () => void): () => void; apply(state: StateModel): void; connected(): void; disconnected(): void }
export function createConsoleStore(): ConsoleStore {
  let snapshot: ConsoleSnapshot = { state: null, connected: false };
  const listeners = new Set<() => void>();
  const publish = () => listeners.forEach(listener => listener());
  return { get snapshot() { return snapshot; }, subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); }, apply(state) { snapshot = { state, connected: true }; publish(); }, connected() { snapshot = { ...snapshot, connected: true }; publish(); }, disconnected() { snapshot = { ...snapshot, connected: false }; publish(); } };
}
