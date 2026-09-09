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
  blockExtents, cellToMachine, feederCentre, isFeeder, machineToScene,
  type ModeName, type Shift, type Vec3,
} from "./coords";
import { clippedCells } from "./geometry";

export type CellKind = "feeder" | "cell" | "clipped";

export interface FeederMarker {
  /** Footprint centre on the ground plane, in scene units. */
  centre: Vec3;
  sizeX: number; sizeZ: number;
}

/**
 * The PHYSICAL feeder — the VERTICAL grid's `[0,0]`, i.e. the machine home
 * corner — in SCENE units, when it is NOT the drawn `[0,0]` cell.
 *
 * A block is always picked up STANDING there ("a plain home to raw `[0,0]`",
 * AGENTS.md §3a), whatever the active grid. In VERTICAL mode that IS the drawn
 * `[0,0]` cell, so this returns null. In HORIZONTAL mode the drawn `[0,0]` cell
 * is registered `+1.9 cm` out on both axes, so the real pickup point is a
 * distinct, otherwise-unmarked spot and this returns it — the Studio draws a
 * faint marker so the operator (and anyone reading the model) knows the feed
 * and the camera's feeder check both happen there, not at horizontal `[0,0]`.
 */
export function trueFeederMarker(mode: ModeName): FeederMarker | null {
  const home = machineToScene(feederCentre());
  const drawnZero = machineToScene(cellToMachine(mode, 0, 0, 0));
  if (Math.abs(home.x - drawnZero.x) < 1e-6 && Math.abs(home.z - drawnZero.z) < 1e-6) {
    return null;
  }
  const block = blockExtents("vertical");
  const sizeX = machineToScene({ x: block.x, y: 0, z: 0 }).x;
  const sizeZ = Math.abs(machineToScene({ x: 0, y: block.y, z: 0 }).z);
  return { centre: { x: home.x, y: 0, z: home.z }, sizeX, sizeZ };
}

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
      // The feeder `[0,0]` is a plain home to raw `[0,0]` and never rides the
      // grid shift (AGENTS.md §3a); every other cell does. Only `[0,0]` is
      // exempt — `[0,r]` and `[c,0]` are ordinary shifted cells.
      const centre = machineToScene(
        isFeeder(col, row)
          ? cellToMachine(mode, col, row, 0)
          : cellToMachine(mode, col, row, 0, shift));
      const clipped = col >= reachable.cols || row >= reachable.rows;
      cells.push({
        col, row,
        // The feeder is never built on, so it reads as the feeder in every
        // state - including one a shift has put out of reach.
        kind: isFeeder(col, row) ? "feeder"
          : clipped ? "clipped" : "cell",
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
