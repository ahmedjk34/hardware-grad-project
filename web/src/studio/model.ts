/**
 * The editable structure in cell space.
 *
 * Geometry and build order are separate because moving a real placement must
 * not rewrite author intent, and timeline reordering must not move a block.
 * Every mutation passes through `applyEdit`, leaving one small, pure boundary
 * where either invariant could be broken and one place for the tests to guard.
 */
import type { ModeName } from "./coords";

export type BlockColour = "white" | "red" | "orange" | "yellow" | "green" | "blue";

export interface ModelBlock {
  id: string;
  mode: ModeName;
  col: number;
  row: number;
  level: number;
  colour: BlockColour;
}

export interface Model {
  blocks: ModelBlock[];
  order: string[];
}

export type Edit =
  | { type: "place"; block: ModelBlock }
  | { type: "placeRun"; blocks: ModelBlock[] }
  | { type: "remove"; id: string }
  | { type: "move"; id: string; mode: ModeName; col: number; row: number; level: number }
  | { type: "recolour"; id: string; colour: BlockColour }
  | { type: "reorder"; id: string; toIndex: number };

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

export function applyEdit(model: Model, edit: Edit): Model {
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
