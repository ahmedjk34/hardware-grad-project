import type { StateModel } from "./types";

async function post<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}

export const level = (delta: number) => post<StateModel>("level", { delta });
export const setLevel = (value: number) => post<StateModel>("level", { value: Math.max(0, Math.trunc(value)) });
export const deselect = () => post<StateModel>("deselect");
export const view = (changes: Record<string, boolean>) => post<StateModel>("view", changes);
export const mode = (next: "vertical" | "horizontal") => post<StateModel>("mode", { mode: next });
export const select = (x: number, y: number, img_w: number, img_h: number) => post<StateModel>("select", { x, y, img_w, img_h });
export const selectAxis = (axis: "col" | "row", value: number) => post<StateModel>("select/axis", { axis, value });
export const build = (command: string) => post<StateModel>("build", { confirm: true, command });

export interface BlockCalibrationReport {
  observations: number;
  mean_residual_px: number;
  max_residual_px: number;
  worst_cell: [number, number] | null;
  short_pitch_px: number;
  size_agreement: number;
  max_bearing_error_deg: number;
  residuals: Record<string, number>;
}

export interface BlockCalibrationStatus {
  mode: string;
  planned: [number, number][];
  observed: [number, number][];
  remaining: [number, number][];
  ready: boolean;
  reasons: string[];
  started: boolean;
  finished_reason: string | null;
  summary: string;
  report: BlockCalibrationReport | null;
  last_step?: { cell: [number, number]; residual_px: number | null; summary: string };
}

export const calibration = {
  start: () => post("calibration/start"),
  corner: (x: number, y: number, img_w: number, img_h: number) => post("calibration/corner", { x, y, img_w, img_h }),
  undo: () => post("calibration/undo"),
  cancel: () => post("calibration/cancel"),
  save: () => post<StateModel>("calibration/save"),
  paper: (selection?: number) => post<StateModel>("calibration/paper", selection === undefined ? {} : { selection }),
  // Re-read config/workspace_map.json. The server loads it once at startup, so
  // a calibration saved on the Pi by Camera Studio or block_grid_calibrate.py
  // while this console was running is otherwise invisible until a restart.
  reload: () => post<StateModel>("calibration/reload"),
  // The placed-block route: the rig puts a block on a cell it was told, so
  // the correspondence is labelled rather than inferred. Each step is one
  // full pick-and-place and blocks for as long as that takes.
  block: {
    start: (options?: { count?: number; inset?: number; cells?: [number, number][] }) =>
      post<BlockCalibrationStatus>("calibration/block/start", options ?? {}),
    step: () => post<BlockCalibrationStatus>("calibration/block/step"),
    undo: (cell: [number, number]) => post<BlockCalibrationStatus>("calibration/block/undo", { cell }),
    cancel: () => post("calibration/block/cancel"),
    save: () => post<StateModel>("calibration/block/save"),
  },
};
