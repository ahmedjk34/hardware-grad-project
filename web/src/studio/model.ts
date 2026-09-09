/**
 * The editable structure in cell space.
 *
 * Geometry and build order are separate because moving a real placement must
 * not rewrite author intent, and timeline reordering must not move a block.
 * Every mutation passes through `applyEdit`, leaving one small, pure boundary
 * where either invariant could be broken and one place for the tests to guard.
 */
import type { BondShifts, ModeName } from "./coords";

export type BlockColour = "white" | "red" | "orange" | "yellow" | "green" | "blue";

export interface ModelBlock {
  id: string;
  mode: ModeName;
  col: number;
  row: number;
  level: number;
  colour: BlockColour;
  /**
   * The grid shift, in `[x_cm, y_cm]`, that was live when this block was
   * placed - FROZEN here at placement. It is the block's own registration and
   * nothing re-derives it: re-dialling a course later moves only blocks placed
   * after the change, never this one. Absent ⇒ this block sits on its plain
   * integer cell. Rendered from and compiled from directly.
   */
  shiftCm?: [number, number];
}

export interface Model {
  blocks: ModelBlock[];
  order: string[];
  /**
   * Running-bond course offsets: per mode, per level, an `[x_cm, y_cm]` the
   * lattice is shifted by ON TOP OF the rig's live shift. Author intent, not a
   * geometry snapshot, so it lives beside `blocks` / `order` and is undo-tracked.
   * Absent ⇒ no bond, and every reader treats it that way.
   */
  bondShifts?: BondShifts;
}

export type Edit =
  | { type: "place"; block: ModelBlock }
  | { type: "placeRun"; blocks: ModelBlock[] }
  | { type: "remove"; id: string }
  | { type: "move"; id: string; mode: ModeName; col: number; row: number; level: number }
  | { type: "recolour"; id: string; colour: BlockColour }
  | { type: "reorder"; id: string; toIndex: number }
  /** Set (or clear, with `offsetCm: null`) one mode+level bond offset. */
  | { type: "setBond"; mode: ModeName; level: number; offsetCm: [number, number] | null };

export function emptyModel(): Model { return { blocks: [], order: [] }; }

function placeMany(model: Model, candidates: ModelBlock[]): Model {
  if (candidates.length === 0) return model;
  const ids = new Set(model.blocks.map(block => block.id));
  const additions: ModelBlock[] = [];
  for (const block of candidates) {
    if (ids.has(block.id)) continue;
    ids.add(block.id);
    additions.push(block);
  }
  return additions.length === 0 ? model : {
    blocks: [...model.blocks, ...additions],
    order: [...model.order, ...additions.map(block => block.id)],
  };
}

/** Drop levels whose offset is `[0, 0]` and modes with no levels left. */
function pruneBond(bond: BondShifts): BondShifts | undefined {
  const out: BondShifts = {};
  for (const mode of Object.keys(bond) as ModeName[]) {
    const levels = bond[mode];
    if (!levels) continue;
    const kept: Record<number, [number, number]> = {};
    for (const [level, offset] of Object.entries(levels)) {
      if (offset[0] !== 0 || offset[1] !== 0) kept[Number(level)] = offset;
    }
    if (Object.keys(kept).length > 0) out[mode] = kept;
  }
  return Object.keys(out).length > 0 ? out : undefined;
}

export function applyEdit(model: Model, edit: Edit): Model {
  // `bondShifts` is author intent carried through every structural edit; only
  // `setBond` changes it, and the switch below returns fresh `{blocks, order}`
  // objects, so it is re-attached here rather than in every branch.
  if (edit.type === "setBond") {
    const next: BondShifts = {};
    for (const mode of Object.keys(model.bondShifts ?? {}) as ModeName[]) {
      next[mode] = { ...(model.bondShifts?.[mode] ?? {}) };
    }
    const levels = next[edit.mode] ?? (next[edit.mode] = {});
    if (edit.offsetCm === null) delete levels[edit.level];
    else levels[edit.level] = edit.offsetCm;
    return { blocks: model.blocks, order: model.order, bondShifts: pruneBond(next) };
  }
  const next = applyStructuralEdit(model, edit);
  return next === model ? model
    : model.bondShifts === undefined ? next
    : { ...next, bondShifts: model.bondShifts };
}

function applyStructuralEdit(model: Model, edit: Exclude<Edit, { type: "setBond" }>): Model {
  switch (edit.type) {
    case "place":
      return placeMany(model, [edit.block]);
    case "placeRun":
      return placeMany(model, edit.blocks);
    case "remove": {
      if (!model.blocks.some(block => block.id === edit.id)) return model;
      return {
        blocks: model.blocks.filter(block => block.id !== edit.id),
        order: model.order.filter(id => id !== edit.id),
      };
    }
    case "move": {
      const index = model.blocks.findIndex(block => block.id === edit.id);
      if (index < 0) return model;
      const current = model.blocks[index];
      if (current.mode === edit.mode && current.col === edit.col && current.row === edit.row
          && current.level === edit.level) return model;
      return {
        blocks: model.blocks.map(block => block.id === edit.id ? {
          ...block, mode: edit.mode, col: edit.col, row: edit.row, level: edit.level,
        } : block),
        order: model.order,
      };
    }
    case "recolour": {
      const current = model.blocks.find(block => block.id === edit.id);
      if (!current || current.colour === edit.colour) return model;
      return {
        blocks: model.blocks.map(block => block.id === edit.id
          ? { ...block, colour: edit.colour } : block),
        order: model.order,
      };
    }
    case "reorder": {
      const from = model.order.indexOf(edit.id);
      if (from < 0) return model;
      const to = Math.max(0, Math.min(edit.toIndex, model.order.length - 1));
      if (from === to) return model;
      const order = [...model.order];
      order.splice(from, 1);
      order.splice(to, 0, edit.id);
      return { blocks: model.blocks, order };
    }
  }
}
