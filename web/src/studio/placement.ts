/**
 * The intentionally small M2 placement gate.
 *
 * Only machine-local facts belong here today: the feeder is not a target, the
 * cell must exist in its own mode, and a cell-space slot cannot be occupied
 * twice. Structural support, collision and reachability are M3 rules.
 */
import { cellCount, isFeeder, type ModeName } from "./coords";
import type { Model } from "./model";
import type { CellTarget } from "./pick";

export interface PlacementStatus { legal: boolean; reason: string | null }

export function placementStatus(model: Model, mode: ModeName, target: CellTarget): PlacementStatus {
  if (isFeeder(target.col, target.row)) return { legal: false, reason: "[0,0] is the feeder" };
  const count = cellCount(mode);
  if (target.col < 0 || target.col >= count.cols || target.row < 0 || target.row >= count.rows
      || target.level < 0) return { legal: false, reason: "outside the grid" };
  const occupied = model.blocks.some(block => block.mode === mode && block.col === target.col
    && block.row === target.row && block.level === target.level);
  return occupied
    ? { legal: false, reason: "already a block here" }
    : { legal: true, reason: null };
}
