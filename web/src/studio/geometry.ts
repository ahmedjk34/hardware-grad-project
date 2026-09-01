/**
 * Machine-space geometry: boxes, overlaps and what a grid shift puts out of reach.
 *
 * Everything here works in the millimetres `coords.ts` hands out, and every axis
 * question is asked of `coords.ts` rather than answered here. No React, no
 * three.js: the rules that must be right are the ones that need no GPU.
 */
import {
  blockExtents, cellCount, cellToMachine, latticeOf, reachableCells,
  type Block, type ModeName, type Shift, type Vec3,
} from "./coords";

export interface AABB { min: Vec3; max: Vec3 }

/** The block's axis-aligned box in machine space, in millimetres. */
export function aabbOf(block: Block): AABB {
  const centre = cellToMachine(block.mode, block.col, block.row, block.level);
  const size = blockExtents(block.mode);
  return {
    min: { x: centre.x - size.x / 2, y: centre.y - size.y / 2, z: centre.z - size.z / 2 },
    max: { x: centre.x + size.x / 2, y: centre.y + size.y / 2, z: centre.z + size.z / 2 },
  };
}

/** Where the next level up would rest: the block's own top face, in mm. */
export function topFaceZ(block: Block): number { return aabbOf(block).max.z; }

/** Do two boxes share volume? Touching faces do not - a stack is not a collision. */
export function intersects(a: AABB, b: AABB): boolean {
  return a.min.x < b.max.x && b.min.x < a.max.x
    && a.min.y < b.max.y && b.min.y < a.max.y
    && a.min.z < b.max.z && b.min.z < a.max.z;
}

/** Shared XY area of two boxes, in square millimetres. The support measure. */
export function footprintOverlapArea(a: AABB, b: AABB): number {
  const width = Math.min(a.max.x, b.max.x) - Math.max(a.min.x, b.min.x);
  const depth = Math.min(a.max.y, b.max.y) - Math.max(a.min.y, b.min.y);
  return width <= 0 || depth <= 0 ? 0 : width * depth;
}

export function footprintArea(box: AABB): number {
  return (box.max.x - box.min.x) * (box.max.y - box.min.y);
}

export interface Clipping {
  requested: { cols: number; rows: number };
  reachable: { cols: number; rows: number };
  /** Cells of the requested grid the shift has pushed off the machine. */
  cells: { col: number; row: number }[];
  /** Nothing survives: the firmware would refuse this shift outright. */
  refused: boolean;
}

/**
 * Which cells the shift pushes past the travel cap, exactly as the firmware
 * reports it: the requested grid is KEPT, the reachable grid is clipped, and
 * clearing the shift restores the request with no re-`S`. Judged against this
 * mode's own `max_edge_overhang_*_cm`, because a centre-only check happily
 * accepts a grid whose far block hangs off the machine.
 */
export function clippedCells(mode: ModeName, shift?: Shift): Clipping {
  const requested = cellCount(mode);
  const reachable = reachableCells(mode, shift);
  const cells: { col: number; row: number }[] = [];
  for (let row = 0; row < requested.rows; row++)
    for (let col = 0; col < requested.cols; col++)
      if (col >= reachable.cols || row >= reachable.rows) cells.push({ col, row });
  return { requested, reachable, cells, refused: reachable.cols === 0 || reachable.rows === 0 };
}

/** The lattice's own footprint in mm, for the envelope cage to draw against. */
export function latticeFootprint(mode: ModeName, shift?: Shift): { widthCm: number; heightCm: number } {
  const l = latticeOf(mode, shift);
  return {
    widthCm: (l.cols - 1) * l.pitchXCm + l.blockXCm,
    heightCm: (l.rows - 1) * l.pitchYCm + l.blockYCm,
  };
}
