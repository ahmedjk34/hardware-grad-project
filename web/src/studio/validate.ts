/**
 * The machine's placement rules, once, for both complete models and the ghost.
 *
 * The two grids share real space but not cells, shifts clip the firmware's
 * reachable request, and cross-mode support is footprint area rather than a
 * same-cell shortcut. Keeping every predicate here makes the safety claims
 * testable without React, three.js, a browser or a GPU.
 */
import {
  MM_PER_CM, cellCount, modeGeometry, rigConfig, type ModeName,
  type RigConfig, type Shift,
} from "./coords";
import {
  aabbOf, clippedCells, contacts, descentPrism, footprintArea,
  footprintContains, footprintUnionArea, intersects,
} from "./geometry";
import type { Model, ModelBlock } from "./model";
import type { StudioSettings } from "./settings";
import { ENVELOPE_Z_CM } from "./view";

export type DiagnosticSeverity = "error" | "warning";
export type DiagnosticCode =
  | "FEEDER_CELL" | "OUT_OF_GRID" | "CLIPPED_BY_SHIFT" | "EDGE_OVERHANG"
  | "LEVEL_CEILING" | "DUPLICATE_CELL" | "COLLISION" | "UNSUPPORTED"
  | "CLAW_CLEARANCE" | "GEOMETRY_DRIFT" | "ISLAND";

export interface DiagnosticFix {
  label: string;
  edit: Record<string, unknown>;
}

export interface Diagnostic {
  severity: DiagnosticSeverity;
  code: DiagnosticCode;
  blockId?: string;
  message: string;
  fix?: DiagnosticFix;
  /** Numeric evidence retained for concise ghost copy and the future compiler. */
  detail?: { supportedRatio?: number };
}

export interface RigGeometrySnapshot {
  workspaceCm: [number, number];
  modes: Record<ModeName, {
    cols: number; rows: number;
    blockCm: [number, number, number];
    pitchCm: [number, number];
    trimCm: [number, number];
    errorOffsetCm: [number, number];
    shiftCm: [number, number];
    maxEdgeOverhangCm: [number | null, number | null];
  }>;
}

export interface ValidationContext {
  /** The lattice the operator is authoring in; every block still owns its mode. */
  mode: ModeName;
  shifts?: Partial<Record<ModeName, Shift>>;
  settings: StudioSettings;
  rigSnapshot?: RigGeometrySnapshot;
  travelHeightMm?: number;
}

export interface Rule {
  (model: Model, block: ModelBlock | undefined, ctx: ValidationContext): Diagnostic[];
  code: DiagnosticCode;
}

type RuleRun = (model: Model, block: ModelBlock | undefined, ctx: ValidationContext) => Diagnostic[];
const defineRule = (code: DiagnosticCode, run: RuleRun): Rule =>
  Object.assign(run, { code });

const shiftFor = (block: ModelBlock, ctx: ValidationContext): Shift | undefined => ctx.shifts?.[block.mode];
const boxOf = (block: ModelBlock, ctx: ValidationContext) => aabbOf(block, shiftFor(block, ctx));
const indexOf = (model: Model, block: ModelBlock) => model.blocks.findIndex(item => item === block || item.id === block.id);
const earlierBlocks = (model: Model, block: ModelBlock): ModelBlock[] => {
  const index = indexOf(model, block);
  return index < 0 ? model.blocks : model.blocks.slice(0, index);
};
const earlierInOrder = (model: Model, block: ModelBlock): ModelBlock[] => {
  const index = model.order.indexOf(block.id);
  const ids = new Set(index < 0 ? model.order : model.order.slice(0, index));
  return model.blocks.filter(item => ids.has(item.id));
};

export function snapshotRigGeometry(config: RigConfig = rigConfig()): RigGeometrySnapshot {
  const snapshotMode = (mode: ModeName) => {
    const value = config.grid.modes[mode];
    return {
      cols: value.cols,
      rows: value.rows,
      blockCm: [value.block_x_cm, value.block_y_cm, value.block_z_cm ?? 1.5] as [number, number, number],
      pitchCm: [value.block_x_cm + value.gap_x_cm, value.block_y_cm + value.gap_y_cm] as [number, number],
      trimCm: [value.trim_x_cm ?? 0, value.trim_y_cm ?? 0] as [number, number],
      errorOffsetCm: [value.error_offset_x_cm ?? 0, value.error_offset_y_cm ?? 0] as [number, number],
      shiftCm: [value.shift_x_cm ?? 0, value.shift_y_cm ?? 0] as [number, number],
      maxEdgeOverhangCm: [
        value.max_edge_overhang_x_cm ?? null,
        value.max_edge_overhang_y_cm ?? null,
      ] as [number | null, number | null],
    };
  };
  return {
    workspaceCm: [config.workspace.width_cm, config.workspace.height_cm],
    modes: { vertical: snapshotMode("vertical"), horizontal: snapshotMode("horizontal") },
  };
}

export const feederCell = defineRule("FEEDER_CELL", (_model, block) => {
  if (!block || block.col !== 0 || block.row !== 0) return [];
  return [{
    severity: "error", code: "FEEDER_CELL", blockId: block.id,
    message: "[0,0] is the feeder — blocks are picked up there, never built there",
  }];
});

export const outOfGrid = defineRule("OUT_OF_GRID", (_model, block) => {
  if (!block) return [];
  const { cols, rows } = cellCount(block.mode);
  const outside = !Number.isInteger(block.col) || !Number.isInteger(block.row)
    || block.col < 0 || block.col >= cols || block.row < 0 || block.row >= rows || block.level < 0;
  if (!outside) return [];
  return [{
    severity: "error", code: "OUT_OF_GRID", blockId: block.id,
    message: `${block.id} targets [${block.col},${block.row}] level ${block.level}, outside the ${cols}×${rows} ${block.mode} grid`,
  }];
});

export const clippedByShift = defineRule("CLIPPED_BY_SHIFT", (_model, block, ctx) => {
  if (!block) return [];
  const clipping = clippedCells(block.mode, shiftFor(block, ctx));
  if (!clipping.cells.some(cell => cell.col === block.col && cell.row === block.row)) return [];
  const axisMessage = block.col >= clipping.reachable.cols
    ? `column ${block.col} is past the travel cap at the current shift`
    : `row ${block.row} is past the travel cap at the current shift`;
  return [{ severity: "error", code: "CLIPPED_BY_SHIFT", blockId: block.id, message: axisMessage }];
});

export const edgeOverhang = defineRule("EDGE_OVERHANG", (_model, block, ctx) => {
  if (!block) return [];
  const geometry = modeGeometry(block.mode);
  const box = boxOf(block, ctx);
  const travelX = rigConfig().workspace.width_cm * MM_PER_CM;
  const travelY = rigConfig().workspace.height_cm * MM_PER_CM;
  const budgetX = geometry.max_edge_overhang_x_cm;
  const budgetY = geometry.max_edge_overhang_y_cm;
  const xBad = budgetX !== undefined
    && (box.min.x < -budgetX * MM_PER_CM - 1e-3 || box.max.x > travelX + budgetX * MM_PER_CM + 1e-3);
  const yBad = budgetY !== undefined
    && (box.min.y < -budgetY * MM_PER_CM - 1e-3 || box.max.y > travelY + budgetY * MM_PER_CM + 1e-3);
  if (!xBad && !yBad) return [];
  const edge = xBad ? "X" : "Y";
  return [{
    severity: "error", code: "EDGE_OVERHANG", blockId: block.id,
    message: `${block.id}'s ${edge} edge exceeds the ${block.mode} overhang allowance`,
  }];
});

export const levelCeiling = defineRule("LEVEL_CEILING", (_model, block, ctx) => {
  if (!block || block.level <= ctx.settings.levelCeiling) return [];
  return [{
    severity: "warning", code: "LEVEL_CEILING", blockId: block.id,
    message: `${block.id} is at level ${block.level} — the operator ceiling is ${ctx.settings.levelCeiling}`,
    fix: {
      label: `Drop to level ${ctx.settings.levelCeiling}`,
      edit: { type: "move", id: block.id, level: ctx.settings.levelCeiling },
    },
  }];
});

export const duplicateCell = defineRule("DUPLICATE_CELL", (model, block) => {
  if (!block) return [];
  const duplicate = earlierBlocks(model, block).find(other => other.mode === block.mode
    && other.col === block.col && other.row === block.row && other.level === block.level);
  if (!duplicate) return [];
  return [{
    severity: "error", code: "DUPLICATE_CELL", blockId: block.id,
    message: `${block.id} duplicates ${duplicate.id} at [${block.col},${block.row}] level ${block.level}`,
  }];
});

export const collision = defineRule("COLLISION", (model, block, ctx) => {
  if (!block) return [];
  const box = boxOf(block, ctx);
  const hit = earlierBlocks(model, block).find(other => intersects(boxOf(other, ctx), box));
  if (!hit) return [];
  return [{
    severity: "error", code: "COLLISION", blockId: block.id,
    message: `${block.id} would collide with ${hit.id}`,
  }];
});

export interface SupportMetrics {
  ratio: number;
  centroidSupported: boolean;
  supportIds: string[];
}

export function supportMetrics(model: Model, block: ModelBlock, ctx: ValidationContext): SupportMetrics {
  if (block.level <= 0) return { ratio: 1, centroidSupported: true, supportIds: [] };
  const target = boxOf(block, ctx);
  const base = target.min.z;
  const beneath = model.blocks.filter(other => other.id !== block.id
    && Math.abs(boxOf(other, ctx).max.z - base) <= 1e-6);
  const boxes = beneath.map(other => boxOf(other, ctx));
  const area = footprintUnionArea(boxes, target);
  const centroid = { x: (target.min.x + target.max.x) / 2, y: (target.min.y + target.max.y) / 2 };
  return {
    ratio: footprintArea(target) === 0 ? 0 : area / footprintArea(target),
    centroidSupported: boxes.some(box => footprintContains(box, centroid.x, centroid.y)),
    supportIds: beneath.filter((_, index) => footprintUnionArea([boxes[index]], target) > 0).map(item => item.id),
  };
}

export const unsupported = defineRule("UNSUPPORTED", (model, block, ctx) => {
  if (!block || block.level <= 0) return [];
  const support = supportMetrics(model, block, ctx);
  if (support.ratio >= ctx.settings.supportRatio && support.centroidSupported) return [];
  const percent = Math.round(support.ratio * 100);
  const needed = Math.round(ctx.settings.supportRatio * 100);
  const message = support.ratio >= ctx.settings.supportRatio
    ? `${block.id} has ${percent}% contact, but its centre is over unsupported space`
    : `${block.id} rests on ${percent}% of its footprint — it needs ${needed}%`;
  return [{
    severity: "error", code: "UNSUPPORTED", blockId: block.id, message,
    detail: { supportedRatio: support.ratio },
  }];
});

export const clawClearance = defineRule("CLAW_CLEARANCE", (model, block, ctx) => {
  if (!block) return [];
  const prism = descentPrism(
    boxOf(block, ctx), ctx.settings.clawMarginMm,
    ctx.travelHeightMm ?? ENVELOPE_Z_CM * MM_PER_CM,
  );
  const blocker = earlierInOrder(model, block).find(other => intersects(prism, boxOf(other, ctx)));
  if (!blocker) return [];
  const targetIndex = Math.max(0, model.order.indexOf(block.id));
  return [{
    severity: "warning", code: "CLAW_CLEARANCE", blockId: block.id,
    message: `${block.id}'s guessed ${ctx.settings.clawMarginMm} mm claw margin would hit ${blocker.id} on descent — measure the claw to confirm`,
    fix: {
      label: `Place ${blocker.id} after ${block.id}`,
      edit: { type: "reorder", id: blocker.id, toIndex: targetIndex },
    },
  }];
});

export const geometryDrift = defineRule("GEOMETRY_DRIFT", (_model, _block, ctx) => {
  if (!ctx.rigSnapshot || JSON.stringify(ctx.rigSnapshot) === JSON.stringify(snapshotRigGeometry())) return [];
  return [{
    severity: "warning", code: "GEOMETRY_DRIFT",
    message: "This model was designed for different rig geometry — review every placement before compiling",
  }];
});

function connectedComponent(model: Model, start: ModelBlock, ctx: ValidationContext): Set<string> {
  const reached = new Set<string>([start.id]);
  const queue = [start];
  while (queue.length) {
    const current = queue.shift()!;
    for (const other of model.blocks) {
      if (reached.has(other.id) || !contacts(boxOf(current, ctx), boxOf(other, ctx))) continue;
      reached.add(other.id);
      queue.push(other);
    }
  }
  return reached;
}

export const island = defineRule("ISLAND", (model, block, ctx) => {
  if (!block || model.blocks.length < 2) return [];
  const anchorId = model.order.find(id => model.blocks.some(item => item.id === id)) ?? model.blocks[0].id;
  const anchor = model.blocks.find(item => item.id === anchorId) ?? model.blocks[0];
  if (connectedComponent(model, anchor, ctx).has(block.id)) return [];
  return [{
    severity: "warning", code: "ISLAND", blockId: block.id,
    message: `${block.id} is detached from the structure — legal, but usually a mistake`,
  }];
});

/** The Plan 4 section 6.4 table, in its one greppable execution order. */
export const RULES: Rule[] = [
  feederCell, outOfGrid, clippedByShift, edgeOverhang, levelCeiling,
  duplicateCell, collision, unsupported, clawClearance, geometryDrift, island,
];

const PRIORITY: DiagnosticCode[] = [
  "FEEDER_CELL", "OUT_OF_GRID", "CLIPPED_BY_SHIFT", "EDGE_OVERHANG",
  "LEVEL_CEILING", "DUPLICATE_CELL", "COLLISION", "UNSUPPORTED",
  "CLAW_CLEARANCE", "GEOMETRY_DRIFT", "ISLAND",
];

export function primaryDiagnostic(diagnostics: Diagnostic[]): Diagnostic | undefined {
  return [...diagnostics].sort((a, b) => PRIORITY.indexOf(a.code) - PRIORITY.indexOf(b.code))[0];
}

/** Concise cursor copy, still derived from the same structured diagnostic. */
export function placementDiagnosticMessage(diagnostic: Diagnostic): string {
  if (diagnostic.code === "UNSUPPORTED" && diagnostic.detail?.supportedRatio !== undefined)
    return `unsupported: ${Math.round(diagnostic.detail.supportedRatio * 100)}% contact`;
  return diagnostic.message.replace(/^ghost\s+/, "");
}

export function validateModel(model: Model, ctx: ValidationContext): Diagnostic[] {
  const diagnostics: Diagnostic[] = [];
  for (const rule of RULES) {
    if (rule === geometryDrift) diagnostics.push(...rule(model, undefined, ctx));
    else for (const block of model.blocks) diagnostics.push(...rule(model, block, ctx));
  }
  return diagnostics;
}

export function validatePlacement(model: Model, candidate: ModelBlock,
                                  ctx: ValidationContext): Diagnostic[] {
  const evaluation = {
    blocks: [...model.blocks, candidate],
    order: [...model.order, candidate.id],
  };
  return RULES.flatMap(rule => rule(evaluation, candidate, ctx));
}
