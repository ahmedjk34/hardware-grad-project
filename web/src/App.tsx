import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { CameraView } from "./components/CameraView";
import { Instrument } from "./components/Instrument";
import { TwinPanel } from "./components/TwinPanel";
import { CommandReadout } from "./components/CommandReadout";
import { ControlPanel } from "./components/ControlPanel";
import { BuildButton } from "./components/BuildButton";
import { LevelStepper } from "./components/LevelStepper";
import { LockedBanner } from "./components/LockedBanner";
import { ModeSwitch } from "./components/ModeSwitch";
import { RigLog } from "./components/RigLog";
import { Shortcuts } from "./components/Shortcuts";
import { StatusBar } from "./components/StatusBar";
import { BuildBanner } from "./components/BuildBanner";
import { ResultToast } from "./components/ResultToast";
import { Calibrate } from "./components/Calibrate";
import { store } from "./consoleStore";
import { Icon } from "./components/Icon";
import * as api from "./api";
import type { StateModel } from "./types";
import { preloadStudio } from "./routes/studio-loader";
import { preloadTwin } from "./routes/twin-loader";
import { usePhone } from "./media";
import { RunnerPanel } from "./components/RunnerPanel";

/** Arrow keys move the selection one cell by re-selecting the neighbour's
 *  centre pixel — the server still decides whether that cell is legal. */
function nudge(state: StateModel, dx: number, dy: number) {
  const geometry = state.geometry;
  if (!geometry || !state.selected) return;
  const target = geometry.grid.find(cell =>
    cell.col === state.selected![0] + dx && cell.row === state.selected![1] + dy);
  if (!target) return;
  const centre = target.polygon.reduce(
    (sum, point) => [sum[0] + point[0] / target.polygon.length, sum[1] + point[1] / target.polygon.length],
    [0, 0] as [number, number]);
  void api.select(centre[0], centre[1], geometry.image_size[0], geometry.image_size[1]);
}

export function App() {
  const snapshot = useSyncExternalStore(store.subscribe, () => store.snapshot);
  const [collecting, setCollecting] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [runnerModelId, setRunnerModelId] = useState<string | null>(null);
  const [runnerActive, setRunnerActive] = useState(false);
  const phone = usePhone();
  // A laptop viewport can't show the camera, twin, runner AND an open log at a
  // usable size at once. The log is the one that starts collapsed there.
  const [shortViewport] = useState(
    () => typeof window !== "undefined" && window.innerHeight < 900);
  const [cornerHandler, setCornerHandler] = useState<((point: [number, number], imageSize: [number, number]) => void) | null>(null);
  const changeHandler = useCallback((handler: ((point: [number, number], imageSize: [number, number]) => void) | null) => setCornerHandler(() => handler), []);

  // The socket subscription lives in `routes/Root.tsx` for the life of the
  // page, so switching to `#/build` and back never drops it.

  // Three.js stays out of first paint, then downloads when the browser is idle.
  // Pointer/focus intent below starts the same cached import immediately.
  useEffect(() => {
    const idleWindow = window as Window & {
      requestIdleCallback?: Window["requestIdleCallback"];
      cancelIdleCallback?: Window["cancelIdleCallback"];
    };
    if (idleWindow.requestIdleCallback) {
      const id = idleWindow.requestIdleCallback(() => { void preloadStudio(); }, { timeout: 4000 });
      return () => idleWindow.cancelIdleCallback?.(id);
    }
    const id = globalThis.setTimeout(() => { void preloadStudio(); }, 2200);
    return () => globalThis.clearTimeout(id);
  }, []);

  const state = snapshot.state;
  const mutable = !!state && snapshot.connected && state.build_state === "READY";

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      if (event.key === "?") return setHelpOpen(open => !open);
      if (event.key === "Escape") { setHelpOpen(false); if (mutable) void api.deselect(); return; }
      if (!state || !mutable) return;
      if (event.key === "ArrowLeft") return nudge(state, -1, 0);
      if (event.key === "ArrowRight") return nudge(state, 1, 0);
      if (event.key === "ArrowUp") return nudge(state, 0, -1);
      if (event.key === "ArrowDown") return nudge(state, 0, 1);
      if (event.key === "+" || event.key === "=") return void api.level(1);
      if (event.key === "-" || event.key === "_") return void api.level(-1);
      // `B` arms and `Enter` confirms by pressing the one BUILD control, so the
      // two-tap guard is exactly the same from the keyboard as from a finger.
      if (event.key === "b" || event.key === "B" || event.key === "Enter") {
        document.querySelector<HTMLButtonElement>(".btn-build:not(:disabled)")?.click();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [state, mutable]);

  if (!state) return (
    <main className="boot">
      <Icon name="waiting" size={28} />
      Connecting to rig…
    </main>
  );

  return (
    <div className="app">
      <StatusBar state={state} connected={snapshot.connected} />
      <LockedBanner state={state} />
      {state.build_state !== "LOCKED" && <BuildBanner state={state} connected={snapshot.connected} />}

      <div className="workspace">
        <div className="pane-camera">
          {/* Real workspace and virtual workspace, in step: Plan 4 section 9. */}
          <Instrument
            camera={
              <CameraView
                state={state}
                connected={snapshot.connected}
                onCalibrationPoint={cornerHandler ?? undefined}
              />
            }
            twin={
              <TwinPanel state={state} connected={snapshot.connected}
                         lastUpdateAt={snapshot.updatedAt}
                         build={snapshot.progress}
                         modelId={runnerModelId ?? undefined}
                         onModelIdChange={setRunnerModelId}
                         modelSelectionDisabled={runnerActive} />
            }
          />
          <RunnerPanel state={state} connected={snapshot.connected}
                       modelId={runnerModelId ?? ""} onActiveChange={setRunnerActive}
                       progress={snapshot.progress} lastResult={snapshot.lastResult} />
          <RigLog log={snapshot.log} defaultOpen={!phone && !shortViewport} gap={snapshot.gap} />
        </div>

        <div className="pane-rail">
          <div className="rail-primary">
            <ResultToast state={state} />
            <ControlPanel
              state={state}
              connected={snapshot.connected}
              onBuild={() => {}}
              primaryElsewhere={phone}
            />
          </div>
          <ModeSwitch state={state} disabled={!mutable} />
          <Calibrate
            ready={snapshot.connected && state.build_state === "READY" && !collecting}
            onCollecting={setCollecting}
            onPointChange={changeHandler}
          />
          <p className="reason">
            <Icon name="waiting" size={14} />Press ? for keyboard shortcuts
          </p>
          <div className="rail-links">
            <p className="reason">
              <a className="studio-link" href="#/studio"
                 onPointerEnter={() => { void preloadStudio(); }}
                 onFocus={() => { void preloadStudio(); }}
                 onPointerDown={() => { void preloadStudio(); }}>
                Open the 3D Build Studio
              </a>
            </p>
            <a className="buildmode-enter" href="#/build"
               onPointerEnter={() => { void preloadTwin(); }}
               onFocus={() => { void preloadTwin(); }}>
              <Icon name="power" size={16} />
              <span>
                Enter building mode
                <small>Full-screen camera + twin, one build at a time</small>
              </span>
            </a>
          </div>
        </div>
      </div>

      {phone && (
        <div className="action-sheet">
          <CommandReadout state={state} />
          <LevelStepper level={state.level} disabled={!mutable} />
          <BuildButton state={state} connected={snapshot.connected} />
        </div>
      )}

      {helpOpen && <Shortcuts onClose={() => setHelpOpen(false)} />}
    </div>
  );
}
