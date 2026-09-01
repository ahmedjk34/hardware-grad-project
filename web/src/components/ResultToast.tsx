import { useEffect, useState } from "react";
import { Icon } from "./Icon";
import type { StateModel } from "../types";

/** PLACED clears itself after four seconds; REJECTED persists so the operator
 *  can read the reason. Neither ever covers the video. */
export function ResultToast({ state }: { state: StateModel }) {
  const result = state.last_result;
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    setDismissed(false);
    if (result !== "placed") return;
    const timer = window.setTimeout(() => setDismissed(true), 4000);
    return () => clearTimeout(timer);
  }, [result, state.last_result_reason]);

  if (state.build_state === "LOCKED" || !result || dismissed) return null;
  if (result === "placed") return (
    <output className="result placed"><Icon name="check" size={15} />PLACED — select the next cell</output>
  );
  if (result === "rejected") return (
    <output className="result rejected"><Icon name="stale" size={15} />REJECTED — {state.last_result_reason}</output>
  );
  return null;
}
