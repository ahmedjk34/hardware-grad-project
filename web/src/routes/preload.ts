/** One cached promise shared by idle, intent and navigation preloads. */
export function createPreloader<T>(load: () => Promise<T>): () => Promise<T> {
  let pending: Promise<T> | null = null;
  return () => pending ??= load();
}
