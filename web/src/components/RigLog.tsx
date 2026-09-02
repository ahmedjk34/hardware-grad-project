import { useEffect, useRef, useState } from "react";
import { Icon } from "./Icon";
import type { LogLine } from "../types";

/**
 * The log shows EVERY raw line: prose, `@` acknowledgements, `@n STEP` phases,
 * terminal results and serial errors. It is the transcript, not the state — the
 * console's build progress comes from the structured events, never from
 * scraping this. The tone is display only.
 */
function tone(line: LogLine) {
  if (line.kind === "error" || /ERROR|ABORT/.test(line.text)) return "error";
  if (line.text.includes("PLACED")) return "placed";
  // Structured phases get their own treatment so a build reads as a sequence
  // rather than as more ack noise.
  if (line.kind === "step") return "step";
  if (line.kind === "ack") return "ack";
  return "";
}

/** `@12 STEP step=8 total=14 phase=… text=Move_XY…` -> `8/14 Move XY…`. */
function stepSummary(text: string): string | null {
  const step = /\bstep=(\d+)\b/.exec(text);
  const total = /\btotal=(\d+)\b/.exec(text);
  const label = /\btext=(\S+)/.exec(text);
  if (!step || !total) return null;
  const status = /\bstatus=done\b/.test(text) ? " · released" : "";
  return `${step[1]}/${total[1]} ${label ? label[1].replace(/_/g, " ") : ""}${status}`;
}

const stamp = (at: number) => new Date(at).toLocaleTimeString([], { hour12: false });

export function RigLog({ log, defaultOpen, gap = false }: {
  log: LogLine[];
  defaultOpen: boolean;
  /** True when a reconnect could not be filled from the server's replay buffer. */
  gap?: boolean;
}) {
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
            {gap && (
              <div className="log-line error" role="status">
                <span>— lines were missed while the socket was down —</span>
              </div>
            )}
            {log.map(line => (
              <div key={line.id} className={`log-line ${tone(line)}`}>
                <time dateTime={new Date(line.at).toISOString()}>{stamp(line.at)}</time>
                {line.kind === "step" && stepSummary(line.text) && (
                  <span className="log-step" aria-hidden="true">{stepSummary(line.text)}</span>
                )}
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
