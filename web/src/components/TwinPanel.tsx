/**
 * The twin's chrome: what surrounds Plan 4 §9's read-only 3D panel.
 *
 * Everything this draws is decided in `studio/twin.ts` — the appearances, the
 * banner, whether anything is animating — so the only decisions left here are
 * which model to show and whether the camera is synced.
 *
 * THE MODE INDICATOR IS THE TRAP IN THIS MILESTONE. In the Studio a mode switch
 * is free and instant, because there it is a view change. On the index page it
 * is a physical latch that HOMES X AND Y. So the twin's indicator is a plain
 * read-only label mirroring `state.mode` — never the Studio's `[V|H]` segmented
 * control — and there is no control here that could latch anything. Mode changes
 * go through the console's own confirmed `POST /api/mode` in the rail. If an
 * operator can build a habit in the Studio that moves the machine here, the
 * design has failed regardless of what the code does.
 */
import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import { Icon } from "./Icon";
import { useDocumentVisible, useReducedMotion } from "../media";
import { preloadTwin } from "../routes/twin-loader";
import {
  emptyTwinProgress, foldTwinProgress, loadTwinModel, twinModelChoices, twinModelOf, twinScene,
  twinSignature,
} from "../studio/twin";
import { emptyProgress, type BuildProgress } from "../store";
import type { StateModel } from "../types";

const Twin = lazy(preloadTwin);

/** Which model the twin is showing, remembered across reloads. Building mode
 *  (`#/build`) reads and writes the same key so a build chosen in one place is
 *  the build shown in the other. */
export const TWIN_MODEL_KEY = "rig.console.twin.model.v1";

export function storedModelId(): string {
  try {
    return localStorage.getItem(TWIN_MODEL_KEY) ?? "";
  } catch {
    return "";
  }
}

export function rememberModelId(id: string): void {
  try {
    if (id) localStorage.setItem(TWIN_MODEL_KEY, id);
    else localStorage.removeItem(TWIN_MODEL_KEY);
  } catch {
    // A private window keeps no preference. It is a preference; carry on.
  }
}

/** Seconds since the last state message. Only ticks while the socket is down. */
function useStaleSeconds(connected: boolean, lastUpdateAt: number | null): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (connected) return;
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [connected]);
  if (connected || lastUpdateAt === null) return 0;
  return Math.max(0, Math.round((now - lastUpdateAt) / 1000));
}

export function TwinPanel({ state, connected, lastUpdateAt, modelId: controlledModelId,
  onModelIdChange, modelSelectionDisabled = false, build = emptyProgress() }: {
  state: StateModel | null;
  connected: boolean;
  /** The phase the RIG reported. What the twin animates, and the only thing. */
  build?: BuildProgress;
  /** When the last state message arrived, for the STALE age. */
  lastUpdateAt: number | null;
  /** Controlled by App while a program is armed so the twin cannot diverge. */
  modelId?: string;
  onModelIdChange?: (id: string) => void;
  modelSelectionDisabled?: boolean;
}) {
  const [localModelId, setLocalModelId] = useState(storedModelId);
  const modelId = controlledModelId ?? localModelId;
  const [progress, setProgress] = useState(emptyTwinProgress);
  const [synced, setSynced] = useState(false);
  const reducedMotion = useReducedMotion();
  const visible = useDocumentVisible();
  const choices = useMemo(() => twinModelChoices(), []);
  const document = useMemo(() => (modelId ? loadTwinModel(modelId) : null), [modelId]);
  const model = useMemo(() => twinModelOf(document), [document]);
  const staleSeconds = useStaleSeconds(connected, lastUpdateAt);

  useEffect(() => { onModelIdChange?.(modelId); }, [modelId, onModelIdChange]);

  // A different model is a different set of ids; nothing carries over.
  useEffect(() => { setProgress(emptyTwinProgress()); }, [modelId]);
  // The fold is idempotent, which is what makes it safe under StrictMode's
  // double invocation and under a server that repeats its last result.
  useEffect(() => { setProgress(current => foldTwinProgress(current, state, model)); },
            [state, model]);

  const options = { connected, reducedMotion, staleSeconds };
  // `/api/events` delivers ~20 states a second and almost all of them differ
  // only in the camera's frame age. `twinSignature` is the pure statement of
  // what the twin actually depends on; re-rendering the canvas for anything
  // else would cost the video stream frames for no picture change at all.
  const signature = twinSignature(state, progress, options, build);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const scene = useMemo(() => twinScene(state, model, progress, options, build),
                        [signature, model]);

  return (
    <div className={`twin${scene.desaturate ? " is-locked" : ""}${scene.banner === "stale" ? " is-stale" : ""}`}>
      <div className="stage-toolbar">
        <span className="chip is-idle twin-mode" aria-label="Rig grid mode">
          <Icon name="axes" size={13} />{scene.mode ? scene.mode.toUpperCase() : "—"}
        </span>
        <select className="twin-model" aria-label="Model shown in the twin" disabled={modelSelectionDisabled}
                value={modelId}
                onChange={event => {
                  setLocalModelId(event.target.value);
                  onModelIdChange?.(event.target.value);
                  rememberModelId(event.target.value);
                }}>
          <option value="">No model loaded</option>
          {choices.map(choice => (
            <option key={choice.id} value={choice.id}>{choice.name}</option>
          ))}
        </select>
        <span className="spacer" />
        {synced && <span className="twin-synced">synced to camera</span>}
        <button type="button" className="toggle" aria-pressed={synced}
                onClick={() => setSynced(pressed => !pressed)}>
          <Icon name="grid" size={13} />SYNC VIEW
        </button>
      </div>

      <div className="stage-area twin-stage">
        <div className="stage twin-canvas">
          {/* The envelope, the lattice and the feeder are always drawn — the
              twin is a picture of the machine's workspace whether or not a
              model is loaded. Blocks the rig places appear on it regardless. */}
          <Suspense fallback={<div className="stage-plate waiting">LOADING THE TWIN…</div>}>
            <Twin scene={scene} synced={synced} active={visible}
                  mode={scene.mode ?? "vertical"} />
          </Suspense>

          {scene.banner === "locked" && (
            <div className="stage-plate locked" role="alert">
              <Icon name="lock" size={20} />
              <strong>SESSION LOCKED</strong>
              <span className="sub">
                <span>{scene.bannerText}</span>. A human must inspect the rig and
                restart the service. The twin shows only what the rig confirmed
                before the abort.
              </span>
            </div>
          )}

          {scene.banner === "stale" && (
            <div className="stage-plate stale" role="status">
              <strong>STALE</strong>
              <span className="sub">{scene.bannerText}</span>
            </div>
          )}
        </div>
      </div>

      <p className="twin-meta">
        <span className="twin-count">
          {model.blocks.length > 0
            ? `${model.blocks.length} blocks · ${progress.confirmed.length + progress.placements.length} placed`
            : progress.placements.length > 0
              ? `${progress.placements.length} placed by the rig`
              : "No model — mirroring the rig"}
        </span>
        {scene.banner === "running" && (
          <span className="chip is-motion" aria-live="polite">
            <Icon name="stale" size={13} />
            {scene.phaseStep !== null && scene.phaseTotal !== null
              ? `${scene.phaseStep}/${scene.phaseTotal} · `: ""}
            {scene.phaseLabel ?? scene.bannerText ?? "waiting for the rig"}
          </span>
        )}
        {scene.released && scene.banner === "running" && (
          <span className="chip is-idle">RELEASED · parking — not placed yet</span>
        )}
        {scene.banner === "rejected" && (
          <span className="chip is-motion">
            <Icon name="stale" size={13} />REJECTED · {scene.bannerText}
          </span>
        )}
      </p>

      <p className="reason twin-readonly">
        <Icon name="waiting" size={14} />
        Read-only mirror of the rig, phase by phase as the firmware reports them.
        There is no continuous position telemetry, so nothing here claims to know
        where the arm is between phases. Switching grid mode homes the rig — it is
        in the Grid mode panel, never here.
      </p>
    </div>
  );
}
