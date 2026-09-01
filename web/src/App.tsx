import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { CameraView } from "./components/CameraView";
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
import { createConsoleStore } from "./store";
import { connectEvents } from "./ws";
import * as api from "./api";
import type { StateModel } from "./types";

const store = createConsoleStore();
const PHONE = "(max-width: 899px)";

function usePhone(): boolean {
  const [phone, setPhone] = useState(() => window.matchMedia?.(PHONE).matches ?? false);
  useEffect(() => {
    const query = window.matchMedia?.(PHONE);
    if (!query) return;
    const update = () => setPhone(query.matches);
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);
  return phone;
}

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
  const phone = usePhone();
  const [cornerHandler, setCornerHandler] = useState<((point: [number, number], imageSize: [number, number]) => void) | null>(null);
  const changeHandler = useCallback((handler: ((point: [number, number], imageSize: [number, number]) => void) | null) => setCornerHandler(() => handler), []);

  useEffect(() => connectEvents(store), []);

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

  if (!state) return <main className="boot">Connecting to rig…</main>;

  return (
    <div className="app">
      <StatusBar state={state} connected={snapshot.connected} />
      <LockedBanner state={state} />
      {state.build_state !== "LOCKED" && <BuildBanner state={state} connected={snapshot.connected} />}

      <div className="console">
        <div className="column-camera">
          <CameraView
            state={state}
            connected={snapshot.connected}
            onCalibrationPoint={cornerHandler ?? undefined}
          />
          <ResultToast state={state} />
          <RigLog log={snapshot.log} defaultOpen={!phone} />
        </div>

        <div className="column-rail">
          <ControlPanel
            state={state}
            connected={snapshot.connected}
            onBuild={() => {}}
            primaryElsewhere={phone}
          />
          <ModeSwitch state={state} disabled={!mutable} />
          <Calibrate
            ready={snapshot.connected && state.build_state === "READY" && !collecting}
            onCollecting={setCollecting}
            onPointChange={changeHandler}
          />
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
