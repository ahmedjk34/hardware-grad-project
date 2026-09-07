import { useEffect, useState, useSyncExternalStore } from "react";
import type { StateModel, Supervision, SupervisionVerdict } from "../types";
import { Icon } from "./Icon";

type ActivityKind = "success" | "warn" | "error" | "info";
interface Activity { id: string; at: number; kind: ActivityKind; title: string; detail: string; }

// This is a mini-log, not an audit archive. The append-only server log remains
// the full record; the operator sees only the latest meaningful dozen facts.
const CAP = 12;
let items: Activity[] = [];
const listeners = new Set<() => void>();
const seen = new Set<string>();
const notify = () => listeners.forEach(listener => listener());
const subscribe = (listener: () => void) => { listeners.add(listener); return () => listeners.delete(listener); };
const snapshot = () => items;

function cell([col, row]: [number, number]) { return `[${col},${row}]`; }
function cells(value: [number, number][]) { return value.map(cell).join(", "); }

function verdictActivity(supervision: Supervision): Activity | null {
  const verdict = supervision.verdict as SupervisionVerdict | null;
  if (!verdict) return null;
  const named = cells(supervision.cells as [number, number][]);
  switch (verdict) {
    // The per-placement `vision_verification` below already says exactly which
    // block was seen. Adding this whole-board success immediately afterwards
    // makes every successful placement read twice, with no extra information.
    case "VERIFIED": return null;
    case "NOT_DETECTED": return { id: "", at: 0, kind: "warn", title: "Block not detected", detail: named ? `${named} was not seen after placement.` : "The placed block was not seen." };
    case "REMOVED": return { id: "", at: 0, kind: "warn", title: "Block removed", detail: `${named} is no longer on the board.` };
    case "MOVED": return { id: "", at: 0, kind: "warn", title: "Block moved", detail: `${cell(supervision.cells[0] as [number, number])} → ${cell((supervision.cells[1] ?? supervision.cells[0]) as [number, number])}.` };
    case "DISPLACED": return { id: "", at: 0, kind: "warn", title: "Block displaced", detail: named ? `${named} was knocked off its cell into a gap.` : "A block was knocked off its cell into a gap." };
    case "FOREIGN": return { id: "", at: 0, kind: "error", title: "Unexpected block", detail: named ? `${named} is occupied but was not in the plan.` : "A block is outside a board cell." };
    case "DISAGREES": return { id: "", at: 0, kind: "error", title: "Board disagrees", detail: `${supervision.cells.length} cells differ from the plan.` };
  }
}

function add(key: string, activity: Activity) {
  if (seen.has(key)) return;
  seen.add(key);
  items = [...items, { ...activity, id: key }].slice(-CAP);
  notify();
}

/** A small browser-session event ledger. The server remains the authority; this
 * only retains its published facts while the operator moves between routes. */
export function useSupervisionActivity(state: StateModel) {
  useEffect(() => {
    const supervision = state.supervision;
    if (!supervision?.verdict || supervision.judged_at_ms === null) return;
    const activity = verdictActivity(supervision);
    if (activity) add(`verdict:${supervision.judged_at_ms}:${supervision.verdict}:${supervision.cells.join("/")}`, {
      ...activity, at: supervision.judged_at_ms,
    });
  }, [state.supervision]);

  useEffect(() => {
    if (!state.vision_verification) return;
    const detail = state.vision_verification;
    const kind: ActivityKind = /not seen|not detected/i.test(detail) ? "warn"
      : /unchecked|unconfirmed/i.test(detail) ? "info" : "success";
    add(`verification:${state.vision_verification}`, {
      id: "", at: Date.now(), kind, title: "Placement check", detail,
    });
  }, [state.vision_verification]);

  return useSyncExternalStore(subscribe, snapshot, snapshot);
}

export function SupervisionActivity({ state, defaultOpen = false, className = "" }: {
  state: StateModel;
  defaultOpen?: boolean;
  className?: string;
}) {
  const activity = useSupervisionActivity(state);
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className={`supervision-activity ${className}`}>
      <header>
        <div>
          <h2><Icon name="waiting" size={14} />Detector activity</h2>
          <p>Recent placement checks and board changes</p>
        </div>
        <span className="activity-count">{activity.length}</span>
        <button type="button" className="btn btn-ghost btn-icon" aria-expanded={open}
                aria-label={open ? "Collapse detector activity" : "Open detector activity"}
                onClick={() => setOpen(value => !value)}>
          <Icon name="chevron" size={16} className={open ? "chevron up" : "chevron"} />
        </button>
      </header>
      {open ? <div className="activity-body" role="log" aria-label="Detector activity">
        {activity.length === 0 ? <p className="activity-empty">No detector feedback yet.</p> : activity.slice().reverse().map(item => (
          <article key={item.id} className={`activity-row is-${item.kind}`}>
            <span aria-hidden="true">{item.kind === "success" ? "●" : item.kind === "error" ? "■" : "▲"}</span>
            <div><strong>{item.title}</strong><p>{item.detail}</p></div>
            <time dateTime={new Date(item.at).toISOString()}>{new Date(item.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time>
          </article>
        ))}
      </div> : null}
    </section>
  );
}
