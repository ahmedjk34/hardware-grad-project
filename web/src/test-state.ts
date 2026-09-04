/**
 * One baseline `StateModel` for the tests, so that adding a field to the
 * server's snapshot does not mean editing eight object literals.
 *
 * It is deliberately the DULL state: connected, calibrated, READY, nothing
 * selected, no build. Every test says only what it is actually about.
 */
import type { StateModel } from "./types";

export const BASE_STATE: StateModel = {
  mode: "vertical", cols: 7, rows: 6, calibrated: true, selected: null,
  command: null, level: 0, build_state: "READY", locked_reason: null,
  camera: "LIVE", camera_age_ms: 10, last_result: null,
  last_result_reason: null,
  build_command_seq: null, build_step: null, build_total_steps: null,
  build_phase: null, build_phase_label: null, build_phase_action: null,
  build_phase_started_at: null, build_phase_eta_ms: null,
  build_phase_status: "idle",
  build_release_confirmed: false, serial_event_id: 0,
  gantry_connected: true, feeder_connected: true, hardware_ready: true,
  cell_phase: "idle", feeder_transaction_id: null, feeder_state: "idle",
  feeder_error: null,
  views: {}, geometry: null,
};

export const testState = (overrides: Partial<StateModel> = {}): StateModel =>
  ({ ...BASE_STATE, ...overrides });
