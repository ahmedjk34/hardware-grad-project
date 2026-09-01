/**
 * Raycast hit points resolved back into cell space.
 *
 * Three.js decides what surface a ray touched; this module decides what that
 * means to the machine. It inverts the centre-anchored lattice from `coords.ts`
 * and rejects the real 1.6 cm gaps instead of snapping them to a neighbour.
 */
import {
  latticeOf, levelBaseZ, sceneToMachine,
  type Block, type ModeName, type Shift, type Vec3,
} from "./coords";
import { topFaceZ } from "./geometry";

export interface CellTarget { col: number; row: number; level: number }
export interface PlacementHit {
  kind: "ground" | "top";
  distance: number;
  target: CellTarget;
}

const EDGE_EPSILON_MM = 1e-6;

function resolveCell(pointScene: Vec3, mode: ModeName, shift?: Shift): { col: number; row: number } | null {
  const point = sceneToMachine(pointScene);
  const lattice = latticeOf(mode, shift);
  const xCm = point.x / 10;
  const yCm = point.y / 10;
  const col = Math.round((xCm - lattice.originXCm) / lattice.pitchXCm);
  const row = Math.round((yCm - lattice.originYCm) / lattice.pitchYCm);
  if (col < 0 || col >= lattice.cols || row < 0 || row >= lattice.rows) return null;

  const centreXCm = lattice.originXCm + col * lattice.pitchXCm;
  const centreYCm = lattice.originYCm + row * lattice.pitchYCm;
  const insideX = Math.abs(xCm - centreXCm) * 10 <= lattice.blockXCm * 5 + EDGE_EPSILON_MM;
  const insideY = Math.abs(yCm - centreYCm) * 10 <= lattice.blockYCm * 5 + EDGE_EPSILON_MM;
  return insideX && insideY ? { col, row } : null;
}

export function resolveGroundTarget(pointScene: Vec3, mode: ModeName, shift?: Shift): CellTarget | null {
  const cell = resolveCell(pointScene, mode, shift);
  return cell ? { ...cell, level: 0 } : null;
}

function levelAtBaseZ(baseZMm: number): number | null {
  for (let level = 0; level <= 100; level++) {
    const candidate = levelBaseZ(level);
    if (Math.abs(candidate - baseZMm) <= EDGE_EPSILON_MM) return level;
    if (candidate > baseZMm) return null;
  }
  return null;
}

/** The hit block supplies height; the currently latched mode supplies the cell. */
export function resolveTopTarget(hitBlock: Block, pointScene: Vec3, mode: ModeName,
                                 shift?: Shift): CellTarget | null {
  const cell = resolveCell(pointScene, mode, shift);
  const level = levelAtBaseZ(topFaceZ(hitBlock));
  return cell && level !== null ? { ...cell, level } : null;
}

/** Nearest surface wins; equal-distance block tops win over the ground. */
export function chooseHit(hits: PlacementHit[]): PlacementHit | null {
  let chosen: PlacementHit | null = null;
  for (const hit of hits) {
    if (!chosen || hit.distance < chosen.distance
        || (hit.distance === chosen.distance && hit.kind === "top" && chosen.kind === "ground")) {
      chosen = hit;
    }
  }
  return chosen;
}

/** Shift-drag is deliberately a straight run along the dominant axis. */
export function runCells(anchor: { col: number; row: number }, current: { col: number; row: number }) {
  const deltaCol = current.col - anchor.col;
  const deltaRow = current.row - anchor.row;
  const alongCols = Math.abs(deltaCol) >= Math.abs(deltaRow);
  const distance = alongCols ? deltaCol : deltaRow;
  const step = Math.sign(distance);
  const cells: { col: number; row: number }[] = [];
  for (let index = 0; index <= Math.abs(distance); index++) {
    cells.push({
      col: anchor.col + (alongCols ? index * step : 0),
      row: anchor.row + (alongCols ? 0 : index * step),
    });
  }
  return cells;
}
