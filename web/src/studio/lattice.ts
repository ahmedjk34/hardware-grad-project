/**
 * Which cells the viewport draws, where, and in what state. No three.js here.
 *
 * `Lattice.tsx` asks this module for a list and draws it; the decision about
 * WHICH cells exist, which one is the feeder and which the live grid shift has
 * pushed off the machine is a rule about the rig, so it lives in the pure layer
 * where `lattice.test.ts` can hold it to `coords.ts` and `geometry.ts`.
 *
 * Everything handed out is in SCENE units, converted only by `machineToScene`.
 */
import {
  blockExtents, cellToMachine, isFeeder, machineToScene,
  type ModeName, type Shift, type Vec3,
} from "./coords";
import { clippedCells } from "./geometry";

export type CellKind = "feeder" | "cell" | "clipped";

export interface LatticeCell {
  col: number; row: number; kind: CellKind;
  /** The cell's footprint centre on the ground plane, in scene units. */
  centre: Vec3;
  /** The block's true footprint: sizeX along screen X, sizeZ along screen Z. */
  sizeX: number; sizeZ: number;
}

/**
 * Every addressable cell of a mode, at its true footprint with the true gaps.
 *
 * The REQUESTED grid is always returned whole - a shift clips what the machine
 * can reach without changing what was asked for, and the Studio draws the
 * clipped cells struck through rather than deleting them.
 */
export function latticeCells(mode: ModeName, shift?: Shift): LatticeCell[] {
  const { requested, reachable } = clippedCells(mode, shift);
  const block = blockExtents(mode);
  const sizeX = machineToScene({ x: block.x, y: 0, z: 0 }).x;
  const sizeZ = Math.abs(machineToScene({ x: 0, y: block.y, z: 0 }).z);

  const cells: LatticeCell[] = [];
  for (let row = 0; row < requested.rows; row++) {
    for (let col = 0; col < requested.cols; col++) {
      const centre = machineToScene(cellToMachine(mode, col, row, 0, shift));
      const clipped = col >= reachable.cols || row >= reachable.rows;
      cells.push({
        col, row,
        // The feeder is never built on, so it reads as the feeder in every
        // state - including one a shift has put out of reach.
        kind: isFeeder(col, row) ? "feeder" : clipped ? "clipped" : "cell",
        centre: { x: centre.x, y: 0, z: centre.z },
        sizeX, sizeZ,
      });
    }
  }
  return cells;
}

export interface Ticks { cm: number; major: boolean; at: number }

/** Centimetre ticks along an envelope edge, in scene units, every fifth major. */
export function rulerTicks(lengthCm: number, stepCm = 1, majorEvery = 5): Ticks[] {
  const ticks: Ticks[] = [];
  if (stepCm <= 0) return ticks;
  for (let index = 0; index * stepCm <= lengthCm + 1e-9; index++) {
    const cm = Number((index * stepCm).toFixed(6));
    ticks.push({ cm, major: index % majorEvery === 0, at: machineToScene({ x: cm * 10, y: 0, z: 0 }).x });
  }
  return ticks;
}
