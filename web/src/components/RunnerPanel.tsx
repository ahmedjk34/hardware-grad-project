/**
 * The runner draws one pure state machine and executes its described effects.
 * It has no authority of its own: every real action still travels through the
 * console's existing guarded routes, one at a time. In particular, this panel
 * contains no batch, cancel, retry or optimistic "placed" path.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { StateModel } from "../types";
import { compile, formatDuration } from "../studio/compile";
import { fromFileRig, shiftsOf, structureOf } from "../studio/rigmodel";
import { BLOCK_CYCLE_SECONDS, DEFAULT_STUDIO_SETTINGS, LATCH_HOMING_SECONDS } from "../studio/settings";
import { loadTwinModel } from "../studio/twin";
import {
  buildPosition, currentOp, feederPrompt, initialRun, programRows, runTiming, step,
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

export function RunnerPanel({ state, connected, modelId, api, delay, onActiveChange }: {
  state: StateModel;
  connected: boolean;
  modelId: string;
  api?: RunnerApi;
  delay?: (milliseconds: number) => Promise<void>;
  onActiveChange?: (active: boolean) => void;
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
  serverRef.current = state;

  const modelDocument = useMemo(() => modelId ? loadTwinModel(modelId) : null, [modelId]);
  const compiled = useMemo(() => modelDocument ? compile(structureOf(modelDocument), {
    mode: state.mode,
    settings: DEFAULT_STUDIO_SETTINGS,
    shifts: shiftsOf(modelDocument.rig),
    rigSnapshot: fromFileRig(modelDocument.rig),
  }) : null, [modelDocument, state.mode]);

  const applyEvent = useCallback((event: RunEvent) => {
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

  useEffect(() => {
    const current = runRef.current;
    const observed = serverRef.current;
    if (observed.build_state === "RUNNING" && current.inFlight && currentOp(current)?.op === "build") {
      observedRunning.current = true;
    }
    if (observedRunning.current && observed.build_state !== "RUNNING" && current.inFlight
        && currentOp(current)?.op === "build" && observed.last_result) {
      observedRunning.current = false;
      const verification = (observed as StateModel & { vision_verification?: string | null }).vision_verification ?? undefined;
      const thumbnail = captureCameraThumbnail(document.querySelector<HTMLImageElement>('img[alt="Live rig camera"]'));
      applyEvent({
        type: "build-settled", result: observed.last_result, reason: observed.last_result_reason,
        verification, thumbnail, now: Date.now(),
      });
    }
    applyEvent({ type: "server-build-state", buildState: observed.build_state, now: Date.now() });
  }, [state.build_state, state.last_result, state.last_result_reason, applyEvent]);

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
  const canStart = !!modelDocument && !!compiled?.valid && connected && state.build_state === "READY";

  return (
    <section className={`runner panel${run.style === "dry" && run.phase !== "idle" ? " is-dry" : ""}`}
             aria-label="Program runner">
      <header className="runner-head">
        <h2><Icon name="power" size={13} />Program runner</h2>
        <span className="spacer" />
        <span className="runner-count">{position.current} / {position.total}</span>
        {!(["idle", "done", "locked", "stopped-mismatch"] as RunState["phase"][]).includes(run.phase) && (
          <span className="runner-count">elapsed {formatDuration(timing.elapsedSeconds)} · ETA ~{formatDuration(timing.etaSeconds)}</span>
        )}
        {run.style === "dry" && run.phase !== "idle" && (
          <span className="chip is-motion">DRY RUN — no serial traffic</span>
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

      {prompt && run.phase !== "done" && run.phase !== "locked" && run.phase !== "stopped-mismatch" && (
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

      {run.style === "run" && run.phase !== "idle" && run.phase !== "done" && run.phase !== "locked" && (
        <div className="runner-stop">
          <button type="button" className="btn btn-ghost"
                  disabled={run.stopAfterCurrent || run.phase === "stopped-mismatch"}
                  onClick={() => applyEvent({ type: "stop-after", now: Date.now() })}>
            {run.stopAfterCurrent ? "STOPPING AFTER THIS BLOCK" : "STOP AFTER THIS BLOCK"}
          </button>
        </div>
      )}
      <p className="reason runner-honest">the block in flight will finish — the rig cannot be interrupted</p>

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
          <ol className="runner-program" aria-label="Read-only program position">
            {programRows(run).map(row => (
              <li key={row.index} className={`is-${row.status}`}>
                <span>{String(row.index + 1).padStart(2, "0")}</span><code>{row.text}</code>
              </li>
            ))}
          </ol>
        </div>
      )}

      {run.phase === "done" && <div className="runner-result is-done" role="status"><strong>RUN COMPLETE</strong></div>}

      {run.log.length > 0 && (
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
