/**
 * The toast column, top-right of the building-mode stage.
 *
 * It is a status mirror, not a control surface — the only affordance is a
 * dismiss on each card, and even a dismissed sticky toast comes straight back
 * if its condition still holds (the socket is still down, the session is still
 * locked). `aria-live="polite"` so a screen reader hears each new status
 * without being interrupted mid-sentence.
 */
import type { Toast } from "./useBuildToasts";

const ICON: Record<Toast["kind"], string> = {
  info: "●",
  success: "✓",
  warn: "▲",
  error: "✕",
};

export function ToastStack({ toasts, onDismiss }: {
  toasts: Toast[];
  onDismiss: (key: string) => void;
}) {
  return (
    <div className="bm-toasts" role="status" aria-live="polite">
      {toasts.map(toast => (
        <div key={toast.id} className={`bm-toast is-${toast.kind}`}>
          <span className="bm-toast-glyph" aria-hidden="true">{ICON[toast.kind]}</span>
          <div className="bm-toast-body">
            <strong>{toast.title}</strong>
            {toast.detail ? <span>{toast.detail}</span> : null}
          </div>
          <button type="button" className="bm-toast-x" aria-label="Dismiss"
                  onClick={() => onDismiss(toast.key)}>×</button>
        </div>
      ))}
    </div>
  );
}
