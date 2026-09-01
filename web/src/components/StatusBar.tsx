import type { StateModel } from "../types";
export function StatusBar({ state, connected }: { state: StateModel; connected: boolean }) { return <footer>Socket: {connected ? "connected" : "disconnected"} · Camera: {state.camera}</footer>; }
