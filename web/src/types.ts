export type Point = [number, number];

export interface CellGeometry {
  col: number; row: number; polygon: Point[];
  /** A cell the feeder belt occupies: real and drawn, never a build target. */
  blocked?: boolean;
}

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

/** The observer's own state. BUSY / QUIET / NO_MEMORY are NOT faults and take
 *  no state colour — BUSY is the normal condition for a whole build. NO_VISION
 *  is verdict-less too: the detector failed on the frame, or the analysed image
 *  went stale before its result arrived. It is NOT an empty board and NOT
 *  BUSY. */
export type SupervisionPhase =
  | "NO_MEMORY" | "NO_MAP" | "NO_VISION" | "WARMING" | "BUSY" | "QUIET" | "VERDICT";

export type SupervisionVerdict =
  | "VERIFIED" | "NOT_DETECTED" | "REMOVED" | "MOVED" | "DISPLACED"
  | "FOREIGN" | "DISAGREES";

/** ONE server field, four readers. Nothing here is re-derived in the browser:
 *  four renderers of one field cannot disagree, which is why "stays in sync"
 *  is not something anyone has to maintain. */
export interface Supervision {
  state: SupervisionPhase;
  verdict: SupervisionVerdict | null;
  /** `amber` pauses the runner, `red` stops it. NEVER `LOCKED`. */
  severity: "none" | "amber" | "red";
  /** The cells named. For MOVED they are ordered [from, to]; DISPLACED carries
   *  only the origin cell (the block landed on no site). */
  cells: Point[];
  mode: string;
  expected: Point[];
  observed: Point[];
  /** D6's refusals. Drawn as a HATCH, never a colour. */
  unjudged: Point[];
  reason: string | null;
  judged_at_ms: number | null;
  acknowledged: boolean;
  /** The operator CORRECTION action (`docs/features/correction-action.md`).
   *  `correctable` is true ONLY for a MOVED / DISPLACED verdict the claw may
   *  safely return: vertical mode, level 0, the block axis-aligned, no taller
   *  neighbour stack, the destination clear, the pick offset above the 0.5 cm
   *  floor, and (DISPLACED) the detection consistent with one block whose
   *  descent corridor is clear. `correction_reason` always says what the state
   *  is in a sentence — either "the claw can move it back" or exactly why not.
   *  The browser NEVER acts on `pick_offset_cm`: `/api/supervision/correct`
   *  re-derives everything server-side (DESIGN.md §8, no client-side verdict). */
  correctable?: boolean;
  correction_reason?: string | null;
  /** The cell the block belongs on — where the operator will watch it land. */
  correction_cell?: Point | null;
  correction_level?: number | null;
  /** Debug/telemetry only. Not an instruction. */
  pick_offset_cm?: [number, number] | null;
  /** ADVISORY — cm the offending block is from its planned cell centre, for a
   *  MOVED / DISPLACED verdict. Display-only; gates nothing, no state colour. */
  residual_cm?: number | null;
  /** ADVISORY — the worst on-cell drift anywhere on the board, cm. Present for
   *  VERIFIED too (a board can be correct with a block 0.8 cm off its centre).
   *  Display-only; gates nothing, no state colour. */
  max_cell_residual_cm?: number | null;
}

export interface StateModel {
  mode: "vertical" | "horizontal";
  cols: number;
  rows: number;
  /** The ACTIVE mode's live grid shift (`shiftX` / `shiftY`), in cm. */
  shift_cm: [number, number];
  /** `[cols, rows]` a `B` can actually reach under `shift_cm`. Equals `[cols, rows]`. */
  reachable: [number, number];
  /** `[cols, rows]` asked for before a shift clipped them. */
  requested: [number, number];
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
  cell_phase: "idle" | "feeding" | "staging" | "ready_for_pick" | "awaiting_manual_close" | "placing" | "complete" | "error";
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
  /** One sentence about the placement that just settled. Arrives AFTER the
   *  build result — the server needs a still, settled scene to form it. */
  vision_verification?: string | null;
  supervision?: Supervision;
  /** The outcome of the last operator CORRECTION action this session, or null.
   *  The banner shows it; the runner resumes only after the board re-verifies. */
  last_correction?: CorrectionResult | null;
  views: Record<string, boolean>;
  geometry: Geometry | null;
}

export interface CorrectionResult {
  result: "placed" | "rejected" | "aborted";
  reason: string | null;
  cell: Point;
  verdict: "MOVED" | "DISPLACED";
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
