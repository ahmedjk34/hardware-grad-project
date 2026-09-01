export type Point = [number, number];

export interface CellGeometry { col: number; row: number; polygon: Point[] }

export interface Geometry {
  image_size: [number, number];
  calibrated: boolean;
  grid: CellGeometry[];
  selected: CellGeometry | null;
  detections: { color: string; center: Point; box: Point[] }[];
  paper: unknown | null;
}

export interface StateModel {
  mode: "vertical" | "horizontal";
  cols: number;
  rows: number;
  calibrated: boolean;
  selected: Point | null;
  command: string | null;
  level: number;
  build_state: "READY" | "RUNNING" | "LOCKED";
  locked_reason: string | null;
  camera: "LIVE" | "STALE" | "WAITING";
  camera_age_ms: number | null;
  last_result: "placed" | "rejected" | "aborted" | null;
  last_result_reason: string | null;
  views: Record<string, boolean>;
  geometry: Geometry | null;
}

/** One serial line, timestamped on arrival because the rig sends no clock. */
export interface LogLine { id: number; text: string; at: number }
