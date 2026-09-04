/**
 * Execute one reducer-described effect, then report facts back as events.
 *
 * There is deliberately no queue here. A component calls this for the effects
 * returned by one reducer turn, and each effect is awaited. Real transport is
 * checked against the latest server snapshot immediately before use; the
 * backend performs the authoritative copy of the same guard. Dry transport
 * calls none of these methods and uses the same event vocabulary.
 */
import * as realApi from "../api";
import type { StateModel } from "../types";
import type { Effect, RunEvent } from "./runner";

export interface RunnerApi {
  setLevel(value: number): Promise<StateModel>;
  select(x: number, y: number, imgW: number, imgH: number): Promise<StateModel>;
  selectAxis(axis: "col" | "row", value: number): Promise<StateModel>;
  build(command: string): Promise<StateModel>;
  mode(next: "vertical" | "horizontal"): Promise<StateModel>;
  stop?(): Promise<StateModel>;
}

export interface DriverContext {
  api?: RunnerApi;
  state(): StateModel | null;
  dispatch(event: RunEvent): void;
  now?: () => number;
  delay?: (milliseconds: number) => Promise<void>;
}

export const DRY_EFFECT_MS = 600;

const browserDelay = (milliseconds: number) => new Promise<void>(resolve => {
  globalThis.setTimeout(resolve, milliseconds);
});

function assertTransportReady(state: StateModel | null): asserts state is StateModel {
  if (!state) throw new Error("runner has no server state");
  if (state.build_state === "RUNNING") throw new Error("runner refused transport: build_state is RUNNING");
  if (state.build_state === "LOCKED") throw new Error("runner refused transport: session is LOCKED");
}

function polygonCentre(polygon: [number, number][]): [number, number] {
  return polygon.reduce<[number, number]>(
    (sum, point) => [sum[0] + point[0] / polygon.length, sum[1] + point[1] / polygon.length],
    [0, 0],
  );
}

/** Execute exactly one effect. Calls to `dispatch` are synchronous facts. */
export async function executeEffect(effect: Effect, context: DriverContext): Promise<void> {
  const api = context.api ?? realApi;
  const now = context.now ?? Date.now;
  const delay = context.delay ?? browserDelay;

  if (effect.kind === "warn") return;
  if (effect.kind === "verify") {
    context.dispatch({ type: "verified", actual: effect.actual, now: now() });
    return;
  }

  if (effect.kind === "select" && effect.dry) {
    context.dispatch({
      type: "selected", command: `B ${effect.col} ${effect.row} ${effect.level}`, now: now(),
    });
    return;
  }
  if (effect.kind === "build" && effect.dry) {
    context.dispatch({ type: "build-running", now: now() });
    await delay(DRY_EFFECT_MS);
    context.dispatch({ type: "build-settled", result: "placed", reason: null, now: now() });
    return;
  }
  if (effect.kind === "mode" && effect.dry) {
    await delay(DRY_EFFECT_MS);
    context.dispatch({ type: "mode-settled", now: now() });
    return;
  }

  let snapshot = context.state();
  assertTransportReady(snapshot);

  if (effect.kind === "select") {
    if (snapshot.level !== effect.level) {
      snapshot = await api.setLevel(effect.level);
      assertTransportReady(snapshot);
    }
    let selected: StateModel;
    if (effect.row === 0 && effect.col !== 0) {
      selected = await api.selectAxis("col", effect.col);
    } else if (effect.col === 0 && effect.row !== 0) {
      selected = await api.selectAxis("row", effect.row);
    } else {
      const geometry = snapshot.geometry;
      const cell = geometry?.grid.find(item => item.col === effect.col && item.row === effect.row);
      if (!geometry || !cell) throw new Error(`runner cannot map cell [${effect.col},${effect.row}] to the camera`);
      const [x, y] = polygonCentre(cell.polygon);
      selected = await api.select(x, y, geometry.image_size[0], geometry.image_size[1]);
    }
    context.dispatch({ type: "selected", command: selected.command, now: now() });
    return;
  }

  if (effect.kind === "build") {
    const response = await api.build(effect.command);
    if (response.build_state !== "RUNNING") {
      throw new Error(`runner expected build_state RUNNING, got ${response.build_state}`);
    }
    context.dispatch({ type: "build-running", now: now() });
    return;
  }

  const response = await api.mode(effect.mode);
  if (response.build_state !== "READY") {
    throw new Error(`runner expected mode response READY, got ${response.build_state}`);
  }
  context.dispatch({ type: "mode-settled", now: now() });
}
