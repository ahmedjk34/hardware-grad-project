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

export const calibration = {
  start: () => post("calibration/start"),
  corner: (x: number, y: number, img_w: number, img_h: number) => post("calibration/corner", { x, y, img_w, img_h }),
  undo: () => post("calibration/undo"),
  cancel: () => post("calibration/cancel"),
  save: () => post<StateModel>("calibration/save"),
  paper: (selection?: number) => post<StateModel>("calibration/paper", selection === undefined ? {} : { selection }),
};
