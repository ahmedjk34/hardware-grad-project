/**
 * The socket. It parses frames and hands them to the store — nothing else.
 *
 * NOTHING IS BATCHED BEHIND A TIMER. The old client collected log frames in a
 * `setTimeout(…, 0)` because the server re-sent its whole 200-line deque on
 * every new line and the store had to find the overlap by comparing text. Both
 * halves of that are gone: each line is now one event with one id, delivered
 * once, and a build phase is a `build_step` event that must reach React on the
 * turn it arrives — a progress display that lags by a frame is a progress
 * display that is wrong.
 *
 * The one batch left is the RECONNECT REPLAY, which arrives as a single
 * envelope precisely so it is one render rather than several hundred.
 */
import type { ConsoleStore } from "./store";
import type { ServerEvent } from "./types";

/** Reconnect backoff: quick enough to be invisible, capped so it stays polite. */
const FIRST_RETRY_MS = 250;
const MAX_RETRY_MS = 5000;

export function connectEvents(store: ConsoleStore): () => void {
  let stopped = false;
  let socket: WebSocket | null = null;
  let delay = FIRST_RETRY_MS;

  const open = () => {
    if (stopped) return;
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    // Resume from the last DURABLE event this client applied, so a socket that
    // drops mid-build costs only the seconds it was down. Duplicates are free:
    // the store deduplicates by id, so the server may replay generously.
    const after = store.snapshot.resumeId;
    const query = after > 0 ? `?after=${after}` : "";
    socket = new WebSocket(`${scheme}://${location.host}/api/events${query}`);
    socket.onopen = () => { delay = FIRST_RETRY_MS; store.connected(); };
    socket.onmessage = event => {
      let message: ServerEvent;
      try {
        message = JSON.parse(event.data as string) as ServerEvent;
      } catch {
        return;  // A frame we cannot read is not a frame we may guess at.
      }
      if (message.type === "replay") {
        store.noteGap(message.gap);
        store.applyEvents(message.events);
        return;
      }
      store.applyEvent(message);
    };
    socket.onclose = () => {
      // The runner and the twin both go stale on this, and neither may assume
      // the build carried on: the machine may have finished, failed, or be
      // half way through a phase nobody can see.
      store.disconnected();
      if (stopped) return;
      setTimeout(open, delay);
      delay = Math.min(delay * 2, MAX_RETRY_MS);
    };
  };

  open();
  return () => { stopped = true; socket?.close(); };
}
