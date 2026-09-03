/**
 * The runner draws one pure state machine and executes its described effects.
 * It has no authority of its own: every real action still travels through the
 * console's existing guarded routes, one at a time. In particular, this panel
 * contains no batch, cancel, retry or optimistic "placed" path.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { StateModel } from "../types";
import { emptyProgress, type BuildProgress, type ConsoleSnapshot } from "../store";
import { compile, formatDuration } from "../studio/compile";
import { fromFileRig, shiftsOf, structureOf } from "../studio/rigmodel";
import { BLOCK_CYCLE_SECONDS, DEFAULT_STUDIO_SETTINGS, LATCH_HOMING_SECONDS } from "../studio/settings";
import { loadTwinModel } from "../studio/twin";
import {
  buildPosition, currentOp, currentOperationText, feederPrompt, initialRun,
  programRows, runTiming, step,
  type RunEvent, type RunState, type RunStyle,
} from "../studio/runner";
import { captureCameraThumbnail, downloadMarkdown } from "../studio/run-report";
import { executeEffect, type RunnerApi } from "../studio/runner-driver";
import { BuildButton } from "./BuildButton";
import { Icon } from "./Icon";

const STYLES: { style: RunStyle; label: string }[] = [
  { style: "step", label: "STEP" },
  { style: "run", label: "RUN" },
  { style: "dry", label: "DRY RUN" },
];

const activePhase = (phase: RunState["phase"]) =>
  phase !== "idle" && phase !== "done";

/** A toast building mode can surface. The runner only DESCRIBES them; it owns
 *  no toast UI of its own, and passing no `onToast` (the console does) changes
 *  nothing about how this panel behaves. */
export interface RunnerToast {
  key: string;
  kind: "info" | "success" | "warn" | "error";
  title: string;
  detail?: string;
  sticky?: boolean;
}

/** The one place a run phase becomes an operator-facing headline. */
const PHASE_TOAST: Partial<Record<RunState["phase"], Omit<RunnerToast, "key">>> = {
  done: { kind: "success", title: "RUN COMPLETE" },
  rejected: { kind: "warn", title: "REJECTED — RUN PAUSED" },
  paused: { kind: "warn", title: "RUN PAUSED" },
  "stopped-mismatch": { kind: "error", title: "COMMAND MISMATCH — RUN STOPPED", sticky: true },
  locked: { kind: "error", title: "SESSION LOCKED", sticky: true },
};

export function RunnerPanel({ state, connected, modelId, api, delay, onActiveChange,
                              onToast, compact = false,
                              progress = emptyProgress(), lastResult = null }: {
  state: StateModel;
  connected: boolean;
  modelId: string;
  api?: RunnerApi;
  delay?: (milliseconds: number) => Promise<void>;
  onActiveChange?: (active: boolean) => void;
  /** Building mode listens; the console does not pass this. */
  onToast?: (toast: RunnerToast) => void;
  /**
   * Building mode's floating control cluster. Drops everything now carried by
   * the toasts — the phase readout, the feeder card, the elapsed/ETA line, the
   * run-report table, the read-only program dump — and keeps only the controls
   * an operator presses. The state machine and every guarded route are
   * untouched; the console renders this panel without the flag.
   */
  compact?: boolean;
  /** The rig's current phase, straight from the serial event stream. */
  progress?: BuildProgress;
  /** The last settled build, as the server's `build_result` event reported it. */
  lastResult?: ConsoleSnapshot["lastResult"];
}) {
  const [style, setStyle] = useState<RunStyle>("step");
  const [now, setNow] = useState(() => Date.now());
  const [run, setRun] = useState<RunState>(() => ({
    ...initialRun(), connected, buildState: state.build_state,
  }));
  const runRef = useRef(run);
  const serverRef = useRef(state);
  const dispatchRef = useRef<(event: RunEvent) => void>(() => {});
  const observedRunning = useRef(false);
  const settledResultId = useRef(0);
  const terminalStateRef = useRef<"READY" | "LOCKED" | null>(null);
  // `build_result` is a durable event and intentionally arrives before the
  // coalesced state snapshot.  Until that snapshot catches up, preserve the
  // terminal state the server has already confirmed; otherwise RUN would try
  // its next select against the previous build's stale RUNNING snapshot.
  const terminalState = terminalStateRef.current;
  serverRef.current = terminalState !== null && state.build_state === "RUNNING"
    ? { ...state, build_state: terminalState }
    : state;

  const modelDocument = useMemo(() => modelId ? loadTwinModel(modelId) : null, [modelId]);
  const compiled = useMemo(() => modelDocument ? compile(structureOf(modelDocument), {
    mode: state.mode,
    settings: DEFAULT_STUDIO_SETTINGS,
    shifts: shiftsOf(modelDocument.rig),
    rigSnapshot: fromFileRig(modelDocument.rig),
  }) : null, [modelDocument, state.mode]);

  const applyEvent = useCallback((event: RunEvent) => {
    // This is the acceptance of a *new* B, so any prior terminal-state bridge
    // must no longer mask the real RUNNING snapshot.
    if (event.type === "build-running") terminalStateRef.current = null;
    const turn = step(runRef.current, event);
    runRef.current = turn.state;
    setRun(turn.state);
    for (const effect of turn.effects) {
      void executeEffect(effect, {
        api,
        delay,
        state: () => serverRef.current,
        dispatch: next => dispatchRef.current(next),
      }).catch(error => dispatchRef.current({
        type: "transport-error",
        reason: error instanceof Error ? error.message : String(error),
        now: Date.now(),
      }));
    }
  }, [api, delay]);
  dispatchRef.current = applyEvent;

  useEffect(() => {
    applyEvent({ type: "socket", connected, now: Date.now() });
  }, [connected, applyEvent]);

  // Every real phase the rig announced, in order, exactly once. The reducer
  // deduplicates by event id, so a replayed reconnect costs nothing.
  useEffect(() => {
    if (progress.phase === null || progress.step === null) return;
    applyEvent({
      type: "build-step", commandSeq: progress.commandSeq, step: progress.step,
      total: progress.total ?? progress.step, phaseId: progress.phase,
      label: progress.label ?? progress.phase,
      action: progress.action ?? "move",
      status: progress.releaseConfirmed && progress.phase === "release" ? "done" : "begin",
      eventId: progress.eventId, now: Date.now(),
    });
  }, [progress, applyEvent]);

  // The build settles on the SERVER'S `build_result` event and on nothing
  // else. It used to be inferred from `build_state` leaving RUNNING with a
  // `last_result` beside it, which could not tell one build's result from the
  // next one's; the event carries the command it belongs to.
  useEffect(() => {
    const current = runRef.current;
    let observed = serverRef.current;
    if (observed.build_state === "RUNNING" && current.inFlight && currentOp(current)?.op === "build") {
      observedRunning.current = true;
    }
    if (lastResult && lastResult.eventId !== settledResultId.current
        && current.inFlight && currentOp(current)?.op === "build"
        && lastResult.result !== null) {
      settledResultId.current = lastResult.eventId;
      observedRunning.current = false;
      // A terminal result is authoritative: BuildJob has stopped, so the
      // controller is READY unless the result says the session is locked.  The
      // matching state snapshot is queued behind this durable event.
      terminalStateRef.current = lastResult.locked ? "LOCKED" : "READY";
      serverRef.current = { ...observed, build_state: terminalStateRef.current };
      observed = serverRef.current;
      const verification = (observed as StateModel & { vision_verification?: string | null }).vision_verification ?? undefined;
      const thumbnail = captureCameraThumbnail(document.querySelector<HTMLImageElement>('img[alt="Live rig camera"]'));
      applyEvent({
        type: "build-settled", result: lastResult.result, reason: lastResult.reason,
        verification, thumbnail, now: Date.now(),
      });
    }
    applyEvent({ type: "server-build-state", buildState: observed.build_state, now: Date.now() });
  }, [state.build_state, lastResult, applyEvent]);

  const isActive = activePhase(run.phase);
  useEffect(() => onActiveChange?.(isActive), [isActive, onActiveChange]);
  useEffect(() => {
    if (!isActive) return;
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [isActive]);

  const begin = () => {
    if (!modelDocument || !compiled?.valid) return;
    const colours = Object.fromEntries(modelDocument.blocks.map(block => [block.id, block.colour]));
    applyEvent({
      type: "start", program: compiled.program, style, modelName: modelDocument.name,
      colours, now: Date.now(),
    });
  };
  const previewRun = useMemo<RunState>(() => {
    if (!modelDocument || !compiled?.valid) return run;
    return {
      ...initialRun(), program: compiled.program,
      colours: Object.fromEntries(modelDocument.blocks.map(block => [block.id, block.colour])),
    };
  }, [compiled, modelDocument, run]);
  const prompt = feederPrompt(run.phase === "idle" ? previewRun : run);
  const position = buildPosition(run);
  const timing = runTiming(run, now, BLOCK_CYCLE_SECONDS, LATCH_HOMING_SECONDS);
  const op = currentOp(run);
  const operation = currentOperationText(run);
  const canStart = !!modelDocument && !!compiled?.valid && connected && state.build_state === "READY";

  // ── toasts for building mode ────────────────────────────────────────────
  // Purely a mirror of state this panel already derives. The console mounts
  // this without `onToast` and none of it runs.
  const promptKey = prompt ? `${prompt.same ? "same" : prompt.colour}|${prompt.text}` : null;
  useEffect(() => {
    if (!onToast || !prompt) return;
    // `idle` is included on purpose: with a build chosen, "what needs to be
    // done" is already "load block 1 into the feeder".
    if (run.phase === "done" || run.phase === "locked"
        || run.phase === "stopped-mismatch") return;
    onToast({
      key: "runner:feed",
      kind: "info",
      title: prompt.same ? "FEEDER · SAME COLOUR" : `FEEDER · LOAD ${prompt.colour}`,
      detail: prompt.text,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onToast, promptKey, run.phase]);
  useEffect(() => {
    if (!onToast) return;
    const toast = PHASE_TOAST[run.phase];
    if (toast) onToast({ ...toast, key: `runner:phase:${run.phase}`, detail: run.failure ?? toast.detail });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onToast, run.phase]);
  useEffect(() => {
    if (!onToast || run.phase !== "awaiting-confirm") return;
    onToast({
      key: "runner:confirm",
      kind: "warn",
      title: run.pendingConfirm === "mode" ? "CONFIRM MODE CHANGE" : "CONFIRM BUILD",
      detail: run.pendingConfirm === "mode"
        ? "Switching grid mode homes X and Y. Confirm in the dock."
        : "Press BUILD in the dock to send the next block.",
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onToast, run.phase, run.pendingConfirm]);

  return (
    <section className={`runner panel${run.style === "dry" && run.phase !== "idle" ? " is-dry" : ""}${compact ? " is-compact" : ""}`}
             aria-label="Program runner">
      <header className="runner-head">
        {compact
          ? <h2><Icon name="power" size={13} />{position.current} / {position.total}</h2>
          : <h2><Icon name="power" size={13} />Program runner</h2>}
        <span className="spacer" />
        {!compact && <span className="runner-count">{position.current} / {position.total}</span>}
        {!compact && !(["idle", "done", "locked", "stopped-mismatch"] as RunState["phase"][]).includes(run.phase) && (
          <span className="runner-count" title="An estimate from the average cycle time. The phase above is the rig's own report.">
            elapsed {formatDuration(timing.elapsedSeconds)} · ETA ~{formatDuration(timing.etaSeconds)} (est.)
          </span>
        )}
        {run.style === "dry" && run.phase !== "idle" && (
          <span className="chip is-motion">DRY RUN{compact ? "" : " — no serial traffic"}</span>
        )}
      </header>

      <div className="runner-style segmented" role="group" aria-label="Run style">
        {STYLES.map(item => (
          <button key={item.style} type="button" className="btn"
                  aria-pressed={style === item.style} disabled={isActive}
                  onClick={() => setStyle(item.style)}>{item.label}</button>
        ))}
      </div>

      {run.phase === "idle" && (
        <div className="runner-idle">
          <p className="runner-model">{modelDocument ? modelDocument.name : "NO MODEL LOADED"}</p>
          <p className="reason">
            {compiled && !compiled.valid
              ? "This model has compiler errors and cannot be run."
              : modelDocument ? `${compiled?.stats.blocks ?? 0} blocks · ${compiled?.stats.latches ?? 0} latches` : "Choose a model in the twin."}
          </p>
          <button type="button" className="btn btn-build" disabled={!canStart} onClick={begin}>
            START {style === "dry" ? "DRY RUN" : style.toUpperCase()}
          </button>
        </div>
      )}

      {!compact && prompt && run.phase !== "done" && run.phase !== "locked" && run.phase !== "stopped-mismatch" && (
        <div className="feeder" aria-live="polite">
          <strong className={prompt.same ? "is-same" : ""}>
            {!prompt.same && <span className="feeder-swatch" data-colour={prompt.colour.toLowerCase()} aria-hidden="true" />}
            {prompt.same ? "SAME COLOUR" : `FEED: ${prompt.colour}`}
          </strong>
          <span>{prompt.text}</span>
        </div>
      )}

      {run.phase === "awaiting-confirm" && run.pendingConfirm === "mode" && op?.op === "mode" && (
        <div className="runner-warning" role="alert">
          <strong>MODE CHANGE · {op.text}</strong>
          <span>Switching to {op.mode.toUpperCase()} homes X and Y. The rig will move without a B.</span>
          <button type="button" className="btn" onClick={() => applyEvent({ type: "confirm", now: Date.now() })}>
            HOME X/Y AND SWITCH
          </button>
        </div>
      )}

      {run.phase === "awaiting-confirm" && run.pendingConfirm === "build" && (
        <BuildButton state={state} connected={connected}
                     onBuild={() => applyEvent({ type: "confirm", now: Date.now() })} />
      )}

      {!compact && run.inFlight && run.style !== "dry" && (
        <div className="runner-operation" role="status" aria-live="polite"
             aria-label="Current rig operation">
          <strong>{operation ?? "WAITING FOR THE RIG"}</strong>
          <span>
            {!connected
              ? "socket lost — the phase shown is the last one the rig reported"
              : operation === null
                ? "the command is out; the rig has not announced a phase yet"
                : run.progress.released
                  ? "block released — parking; not placed until the rig acknowledges"
                  : "reported by the rig, phase by phase"}
          </span>
          {run.progress.total !== null && run.progress.step !== null && (
            <progress className="runner-phase-bar" value={run.progress.step}
                      max={run.progress.total}
                      aria-label={`Phase ${run.progress.step} of ${run.progress.total}`} />
          )}
        </div>
      )}

      {run.style === "run" && run.phase !== "idle" && run.phase !== "done" && run.phase !== "locked" && (
        <div className="runner-stop">
          <button type="button" className="btn btn-ghost"
                  disabled={run.stopAfterCurrent || run.phase === "stopped-mismatch"}
                  onClick={() => applyEvent({ type: "stop-after", now: Date.now() })}>
            {run.stopAfterCurrent ? "STOPPING AFTER THIS BLOCK" : "STOP AFTER THIS BLOCK"}
          </button>
        </div>
      )}
      {!compact && (
        <p className="reason runner-honest">the block in flight will finish — the rig cannot be interrupted</p>
      )}

      {run.phase === "rejected" && (
        <div className="runner-result is-rejected" role="alert">
          <strong>REJECTED — RUN PAUSED</strong><span>{run.failure}</span>
          <div className="row">
            <button type="button" className="btn" onClick={() => applyEvent({ type: "continue", now: Date.now() })}>CONTINUE</button>
            <button type="button" className="btn btn-ghost" onClick={() => applyEvent({ type: "end", now: Date.now() })}>END RUN</button>
          </div>
        </div>
      )}

      {run.phase === "paused" && (
        <div className="runner-result is-paused" role="status">
          <strong>{run.pauseReason === "stale" ? "STALE — RUN PAUSED" : "RUN PAUSED"}</strong>
          <span>{run.failure ?? (run.pauseReason === "operator-stop" ? "Stopped after the completed block." : "No next command will be sent.")}</span>
          {!run.inFlight && connected && (
            <div className="row">
              <button type="button" className="btn" onClick={() => applyEvent({ type: "continue", now: Date.now() })}>CONTINUE</button>
              <button type="button" className="btn btn-ghost" onClick={() => applyEvent({ type: "end", now: Date.now() })}>END RUN</button>
            </div>
          )}
        </div>
      )}

      {run.phase === "stopped-mismatch" && run.mismatch && (
        <div className="runner-result is-locked" role="alert">
          <strong>COMMAND MISMATCH — RUN STOPPED</strong>
          <span>program: {run.mismatch.program}</span>
          <span>rig: {run.mismatch.rig}</span>
          <span>The model and rig disagree about the world. Nothing else was sent.</span>
        </div>
      )}

      {run.phase === "locked" && (
        <div className="runner-result is-locked" role="alert">
          <strong>SESSION LOCKED</strong><span>{run.failure}</span>
          <span>stopped at step {position.current} of {position.total}</span>
          <span>Program state is read-only. Inspect the rig and restart the service.</span>
          {!compact && (
            <ol className="runner-program" aria-label="Read-only program position">
              {programRows(run).map(row => (
                <li key={row.index} className={`is-${row.status}`}>
                  <span>{String(row.index + 1).padStart(2, "0")}</span><code>{row.text}</code>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}

      {run.phase === "done" && <div className="runner-result is-done" role="status"><strong>RUN COMPLETE</strong></div>}

      {!compact && run.log.length > 0 && (
        <div className="runner-report">
          <div className="runner-report-head"><strong>RUN REPORT</strong><span className="spacer" />
            <button type="button" className="btn btn-ghost" onClick={() => downloadMarkdown(run)}>EXPORT MARKDOWN</button>
          </div>
          <div className="runner-report-scroll">
            <table><thead><tr><th>Step</th><th>Command</th><th>Result</th><th>Duration</th></tr></thead>
              <tbody>{run.log.map((entry, index) => (
                <tr key={`${entry.index}-${entry.startedAt}`}><td>{index + 1}</td><td>{entry.command}</td>
                  <td>{entry.result}</td><td>{((entry.finishedAt - entry.startedAt) / 1000).toFixed(2)}s</td></tr>
              ))}</tbody></table>
          </div>
        </div>
      )}
    </section>
  );
}
