import { useEffect, useRef, useState } from "react";
import { Icon } from "./Icon";
import type { LogLine } from "../types";

function tone(text: string) {
  if (/ERROR|ABORT/.test(text)) return "error";
  if (text.includes("PLACED")) return "placed";
  if (text.trimStart().startsWith("@")) return "ack";
  return "";
}

const stamp = (at: number) => new Date(at).toLocaleTimeString([], { hour12: false });

export function RigLog({ log, defaultOpen }: { log: LogLine[]; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const [following, setFollowing] = useState(true);
  const body = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open || !following) return;
    const element = body.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [log, open, following]);

  const onScroll = () => {
    const element = body.current;
    if (!element) return;
    setFollowing(element.scrollHeight - element.scrollTop - element.clientHeight < 24);
  };

  const toLatest = () => {
    const element = body.current;
    if (element) element.scrollTop = element.scrollHeight;
    setFollowing(true);
  };

  return (
    <section className="panel log">
      <header>
        <h2><Icon name="power" size={13} />Rig log</h2>
        <span className="log-count">{log.length} lines</span>
        <span className="spacer" />
        <button
          type="button"
          className="btn btn-ghost btn-icon"
          aria-expanded={open}
          aria-label={open ? "Collapse" : `Expand (${log.length})`}
          onClick={() => setOpen(value => !value)}
        >
          <Icon name="chevron" size={16} className={open ? "chevron up" : "chevron"} />
        </button>
      </header>

      {open && (
        <>
          <div className="log-body" ref={body} onScroll={onScroll} role="log" aria-label="Rig serial log">
            {log.length === 0 && <div className="log-empty">No serial lines yet.</div>}
            {log.map(line => (
              <div key={line.id} className={`log-line ${tone(line.text)}`}>
                <time dateTime={new Date(line.at).toISOString()}>{stamp(line.at)}</time>
                <span>{line.text}</span>
              </div>
            ))}
          </div>
          {!following && (
            <button type="button" className="btn btn-ghost jump-latest" onClick={toLatest}>
              <Icon name="down" size={13} />Jump to latest
            </button>
          )}
        </>
      )}
    </section>
  );
}
