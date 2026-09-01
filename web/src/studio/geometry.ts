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
export function aabbOf(block: Block, shift?: Shift): AABB {
  const centre = cellToMachine(block.mode, block.col, block.row, block.level, shift);
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

/** Does an XY footprint contain a point? Edges count as supported contact. */
export function footprintContains(box: AABB, x: number, y: number): boolean {
  return x >= box.min.x && x <= box.max.x && y >= box.min.y && y <= box.max.y;
}

/**
 * Area of the union of axis-aligned footprints, clipped to one target. The
 * sweep prevents two overlapping supports from being counted twice.
 */
export function footprintUnionArea(boxes: AABB[], clip: AABB): number {
  const rectangles = boxes.flatMap(box => {
    const minX = Math.max(box.min.x, clip.min.x);
    const maxX = Math.min(box.max.x, clip.max.x);
    const minY = Math.max(box.min.y, clip.min.y);
    const maxY = Math.min(box.max.y, clip.max.y);
    return minX < maxX && minY < maxY ? [{ minX, maxX, minY, maxY }] : [];
  });
  const xs = [...new Set(rectangles.flatMap(rect => [rect.minX, rect.maxX]))].sort((a, b) => a - b);
  let area = 0;
  for (let index = 0; index < xs.length - 1; index++) {
    const left = xs[index];
    const right = xs[index + 1];
    const intervals = rectangles
      .filter(rect => rect.minX < right && rect.maxX > left)
      .map(rect => [rect.minY, rect.maxY] as const)
      .sort((a, b) => a[0] - b[0]);
    let covered = 0;
    let start = 0;
    let end = 0;
    intervals.forEach((interval, intervalIndex) => {
      if (intervalIndex === 0) { [start, end] = interval; return; }
      if (interval[0] > end) { covered += end - start; [start, end] = interval; }
      else end = Math.max(end, interval[1]);
    });
    if (intervals.length) covered += end - start;
    area += (right - left) * covered;
  }
  return area;
}

/** The vertical descent volume over a footprint, inflated on every XY side. */
export function descentPrism(box: AABB, marginMm: number, travelHeightMm: number): AABB {
  return {
    min: { x: box.min.x - marginMm, y: box.min.y - marginMm, z: box.max.z },
    max: { x: box.max.x + marginMm, y: box.max.y + marginMm, z: travelHeightMm },
  };
}

/** Physical face contact or shared volume; a corner/edge alone is not support. */
export function contacts(a: AABB, b: AABB): boolean {
  const overlap = (amin: number, amax: number, bmin: number, bmax: number) =>
    Math.min(amax, bmax) - Math.max(amin, bmin);
  const axes = [
    overlap(a.min.x, a.max.x, b.min.x, b.max.x),
    overlap(a.min.y, a.max.y, b.min.y, b.max.y),
    overlap(a.min.z, a.max.z, b.min.z, b.max.z),
  ];
  return axes.every(value => value >= 0) && axes.filter(value => value > 0).length >= 2;
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
