import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { CameraView } from "./components/CameraView";
import { ControlPanel } from "./components/ControlPanel";
import { LockedBanner } from "./components/LockedBanner";
import { StatusBar } from "./components/StatusBar";
import { BuildBanner } from "./components/BuildBanner";
import { ResultToast } from "./components/ResultToast";
import { Calibrate } from "./components/Calibrate";
import { createConsoleStore } from "./store";
import { connectEvents } from "./ws";
const store = createConsoleStore();
export function App() { const snapshot = useSyncExternalStore(store.subscribe, () => store.snapshot); const [collecting, setCollecting] = useState(false); const [cornerHandler, setCornerHandler] = useState<((point: [number, number], imageSize: [number, number]) => void) | null>(null); const changeHandler = useCallback((handler: ((point: [number, number], imageSize: [number, number]) => void) | null) => setCornerHandler(() => handler), []); useEffect(() => connectEvents(store), []); const state = snapshot.state; if (!state) return <main>Connecting to rig…</main>; return <div className="app"><LockedBanner state={state} /><BuildBanner state={state} connected={snapshot.connected} /><div className="console"><CameraView state={state} connected={snapshot.connected} onCalibrationPoint={cornerHandler ?? undefined} /><div><ControlPanel state={state} connected={snapshot.connected} onBuild={() => {}} /><Calibrate ready={snapshot.connected && state.build_state === "READY" && !collecting} onCollecting={setCollecting} onPointChange={changeHandler} /></div></div><ResultToast state={state} /><StatusBar state={state} connected={snapshot.connected} /></div>; }
