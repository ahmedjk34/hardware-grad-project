import { Icon } from "./Icon";
import type { StateModel } from "../types";

export function LockedBanner({ state }: { state: StateModel }) {
  if (state.build_state !== "LOCKED") return null;
  return (
    <section className="banner locked" role="alert">
      <Icon name="lock" size={20} />
      <strong>SESSION LOCKED</strong>
      <span className="detail">
        <span>{state.locked_reason}</span>. A human must inspect the rig and restart the service.
      </span>
    </section>
  );
}
