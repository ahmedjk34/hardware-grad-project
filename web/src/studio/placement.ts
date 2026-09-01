/**
 * Compatibility wrapper for M2 callers. M3 owns the one real validator in
 * `validate.ts`; this module only preserves the older `{legal, reason}` shape.
 */
import { type ModeName } from "./coords";
import type { Model } from "./model";
import type { CellTarget } from "./pick";
import { DEFAULT_STUDIO_SETTINGS } from "./settings";
import {
  primaryDiagnostic, snapshotRigGeometry, validatePlacement, type DiagnosticCode,
} from "./validate";

export interface PlacementStatus { legal: boolean; reason: string | null }

export function placementStatus(model: Model, mode: ModeName, target: CellTarget): PlacementStatus {
  const diagnostics = validatePlacement(model, {
    id: "ghost", mode, col: target.col, row: target.row, level: target.level, colour: "white",
  }, { mode, settings: DEFAULT_STUDIO_SETTINGS, rigSnapshot: snapshotRigGeometry() });
  const error = primaryDiagnostic(diagnostics.filter(item => item.severity === "error"));
  if (!error) return { legal: true, reason: null };
  const legacyReasons: Partial<Record<DiagnosticCode, string>> = {
    FEEDER_CELL: "[0,0] is the feeder",
    OUT_OF_GRID: "outside the grid",
    DUPLICATE_CELL: "already a block here",
  };
  const legacyReason = legacyReasons[error.code];
  return { legal: false, reason: legacyReason ?? error.message };
}
