/**
 * The toast queue for building mode.
 *
 * Toasts are keyed. Pushing a toast whose `key` already matches the newest
 * visible toast is a no-op — the rig sends the same phase description ~20 times
 * a second and none of those repeats is news. A different key, or the same key
 * after it has aged out, is a new toast.
 *
 * Non-sticky toasts age out on a timer. Sticky ones (a lock, a lost socket)
 * stay until something explicitly dismisses them by key — `SOCKET LOST` clears
 * itself when the socket returns.
 */
import { useCallback, useEffect, useRef, useState } from "react";

export type ToastKind = "info" | "success" | "warn" | "error";

export interface Toast {
  id: number;
  key: string;
  kind: ToastKind;
  title: string;
  detail?: string;
  sticky?: boolean;
}

export interface ToastInput {
  key: string;
  kind: ToastKind;
  title: string;
  detail?: string;
  sticky?: boolean;
}

const VISIBLE_CAP = 4;
const TTL_MS = 6000;

export function useBuildToasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);
  const timers = useRef(new Map<number, number>());

  const dismiss = useCallback((key: string) => {
    setToasts(current => current.filter(toast => toast.key !== key));
  }, []);

  const push = useCallback((input: ToastInput) => {
    setToasts(current => {
      const existing = current.find(toast => toast.key === input.key);
      // A byte-identical repeat is not news — the rig re-sends the same phase
      // ~20 times a second. Drop it so nothing re-renders or re-animates.
      if (existing && existing.title === input.title && existing.detail === input.detail
          && existing.kind === input.kind && existing.sticky === input.sticky) {
        return current;
      }
      // Same key, changed content: refresh that toast where it sits (a new id,
      // so its expiry timer restarts — an updating status should not age out
      // on the clock of its first line). A key never stacks.
      if (existing) {
        return current.map(toast =>
          toast.key === input.key ? { ...input, id: nextId.current++ } : toast);
      }
      const toast: Toast = { ...input, id: nextId.current++ };
      const next = [...current, toast];
      return next.length > VISIBLE_CAP ? next.slice(next.length - VISIBLE_CAP) : next;
    });
  }, []);

  // One expiry timer per non-sticky toast, cleared if it leaves early.
  useEffect(() => {
    for (const toast of toasts) {
      if (toast.sticky || timers.current.has(toast.id)) continue;
      const handle = window.setTimeout(() => {
        timers.current.delete(toast.id);
        setToasts(current => current.filter(item => item.id !== toast.id));
      }, TTL_MS);
      timers.current.set(toast.id, handle);
    }
    const live = new Set(toasts.map(toast => toast.id));
    for (const [id, handle] of timers.current) {
      if (!live.has(id)) { window.clearTimeout(handle); timers.current.delete(id); }
    }
  }, [toasts]);

  useEffect(() => () => {
    for (const handle of timers.current.values()) window.clearTimeout(handle);
    timers.current.clear();
  }, []);

  return { toasts, push, dismiss };
}
