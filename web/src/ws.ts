import type { ConsoleStore } from "./store";
import type { StateModel } from "./types";

export function connectEvents(store: ConsoleStore): () => void {
  let stopped = false;
  let socket: WebSocket | null = null;
  let delay = 250;
  // The server replays its entire log deque as one burst of frames; batching
  // them back together lets the store recognise the overlap and append once.
  let pending: string[] = [];
  let flush: number | null = null;

  const drain = () => {
    flush = null;
    const lines = pending;
    pending = [];
    store.mergeLog(lines);
  };

  const open = () => {
    if (stopped) return;
    socket = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/events`);
    socket.onopen = () => { delay = 250; store.connected(); };
    socket.onmessage = event => {
      const message = JSON.parse(event.data);
      if (message.type === "state") store.apply(message.state as StateModel);
      else if (message.type === "log" && typeof message.line === "string") {
        pending.push(message.line);
        if (flush === null) flush = window.setTimeout(drain, 0);
      }
    };
    socket.onclose = () => {
      store.disconnected();
      if (!stopped) setTimeout(open, delay), delay = Math.min(delay * 2, 5000);
    };
  };

  open();
  return () => { stopped = true; socket?.close(); };
}
