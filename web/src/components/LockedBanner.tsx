import type { StateModel } from "../types";
export function LockedBanner({ state }: { state: StateModel }) { return state.build_state === "LOCKED" ? <section className="locked" role="alert"><strong>SESSION LOCKED</strong>: <span>{state.locked_reason}</span>. A human must inspect the rig and restart the service.</section> : null; }
