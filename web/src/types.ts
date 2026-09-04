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

/**
 * Where a command is, as the SERVER says it. Mirrors `web/progress.py`.
 *
 * `parking` is still a running command: the block is down, the rig is tidying
 * up, and `placed` has not been earned yet. `placed` means the terminal `@n OK`
 * and nothing else.
 */
export type BuildPhaseStatus =
  | "idle" | "accepted" | "validating" | "running" | "parking"
  | "placed" | "rejected" | "aborted" | "locked";

/** What one phase is expected to do. Coarse on purpose — see the firmware. */
export type BuildPhaseAction = "move" | "grip" | "release" | "rotate" | "park";

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
  gantry_connected: boolean;
  feeder_connected: boolean;
  hardware_ready: boolean;
  cell_phase: "idle" | "feeding" | "staging" | "ready_for_pick" | "placing" | "complete" | "error";
  feeder_transaction_id: number | null;
  feeder_state: string | null;
  feeder_error: string | null;
  build_command_seq: number | null;
  build_step: number | null;
  build_total_steps: number | null;
  build_phase: string | null;
  build_phase_label: string | null;
  build_phase_action: BuildPhaseAction | null;
  build_phase_started_at: number | null;
  /** The firmware's predicted duration for the phase in flight, in ms. */
  build_phase_eta_ms: number | null;
  build_phase_status: BuildPhaseStatus;
  /** Phase 11's `status=done`: the jaws opened. NOT the same as placed. */
  build_release_confirmed: boolean;
  /** The event this progress was folded from. Used to break ties — see store. */
  serial_event_id: number;
  views: Record<string, boolean>;
  geometry: Geometry | null;
}

/** One serial line, timestamped on arrival because the rig sends no clock. */
export interface LogLine { id: number; text: string; at: number; kind: LogKind }

/** How a log line is drawn: prose, an `@` machine line, a phase, or an error. */
export type LogKind = "prose" | "ack" | "step" | "error";

// ── The `/api/events` wire protocol ────────────────────────────────────────
//
// Every frame carries `event_id` and `at`. Ids are monotonic but MAY HAVE GAPS
// for any one client: coalesced state snapshots and heartbeats consume ids
// without being replayable. So deduplicate with `>`, never `previous + 1`.

interface EventEnvelope { event_id: number; at: number }

export type ServerEvent =
  | (EventEnvelope & { type: "state"; state: StateModel })
  | (EventEnvelope & { type: "build_step" } & BuildStepEvent)
  | (EventEnvelope & { type: "serial"; line: string; stream: "rig" | "feeder" | "error" })
  | (EventEnvelope & { type: "feeder"; request_id: number; message_type: string; fields: Record<string, string> })
  | (EventEnvelope & { type: "build_result" } & BuildResultEvent)
  | (EventEnvelope & { type: "heartbeat" })
  /** Not a fact type: the envelope a reconnect's missed events arrive in. */
  | (EventEnvelope & { type: "replay"; events: ServerEvent[]; gap: boolean });

export interface BuildStepEvent {
  command_seq: number | null;
  step: number;
  total: number;
  phase: string;
  label: string;
  action: BuildPhaseAction;
  /** `begin` before the phase runs; the single `done` is the release. */
  status: "begin" | "done";
  /**
   * The firmware's own prediction of how long this phase takes, in ms, or
   * `null` when it did not say. Present on the Z moves only — they are the
   * phases whose duration is computable, because the steppers have no
   * acceleration ramp.
   *
   * IT IS A FLOOR. Nothing moves faster than its step rate, so the real phase
   * can only take longer. Animate from it if you like; never let it assert
   * that the phase finished.
   */
  eta_ms: number | null;
}

export interface BuildResultEvent {
  command_seq: number | null;
  result: "placed" | "rejected" | "aborted" | null;
  reason: string | null;
  locked: boolean;
  locked_reason: string | null;
  /** True when the rig had to read the prose because no ack arrived. */
  from_prose: boolean;
}
