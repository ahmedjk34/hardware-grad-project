/**
 * Cell space, machine space, scene space - and nothing else that handles an axis.
 *
 * This is the TypeScript counterpart of `python/rig/grid.py`, held to it by
 * `coords.test.ts` against fixtures dumped by `python/tools/dump_grid_fixtures.py`.
 * When the two disagree, Python is right.
 *
 * The lattice, in one line, exactly as the firmware and MachineGrid state it:
 *
 *     centre(i) = trim + error_offset + shift + i * pitch     pitch = block + gap
 *
 * Cell indices are 0-based, cell 0's CENTRE sits on the home corner, and there
 * is no leading gap, no trailing gap and no centring. `[0,0]` is the feeder in
 * both modes. The two modes are two different grids, not one rotated grid: each
 * declares both block extents outright and nothing here swaps a width for a
 * length.
 *
 * Units: the config and the lattice speak centimetres, because that is what the
 * machine's own numbers are. Everything this module HANDS OUT is millimetres -
 * machine space - or scene units. The conversion happens here and nowhere else.
 */
import rigJson from "../../../config/rig.json";

export type ModeName = "vertical" | "horizontal";

/** One `grid.modes.<mode>` entry of config/rig.json. */
export interface ModeGeometry {
  cols: number; rows: number;
  block_x_cm: number; block_y_cm: number;
  gap_x_cm: number; gap_y_cm: number;
  trim_x_cm?: number; trim_y_cm?: number;
  /** Absent means "do not check block edges at all", as in rig/config.py. */
  max_edge_overhang_x_cm?: number; max_edge_overhang_y_cm?: number;
  error_offset_x_cm?: number; error_offset_y_cm?: number;
  shift_x_cm?: number; shift_y_cm?: number;
  /** Block height has no partner in rig.json today; see BLOCK_HEIGHT_CM. */
  block_z_cm?: number;
}

export interface RigConfig {
  grid: { active_mode: string; modes: Record<string, ModeGeometry> };
  workspace: { width_cm: number; height_cm: number };
}

export interface Vec3 { x: number; y: number; z: number }
/** A live grid shift in centimetres, the firmware's shiftX / shiftY. */
export interface Shift { x_cm: number; y_cm: number }
/** A placed block in cell space. The only thing the model file stores. */
export interface Block { mode: ModeName; col: number; row: number; level: number }

export const MM_PER_CM = 10;
/** arduino/build_test_v1: BLOCK_HEIGHT_CM. A level is one block high. */
export const BLOCK_HEIGHT_CM = 1.5;
export const BLOCK_HEIGHT_MM = BLOCK_HEIGHT_CM * MM_PER_CM;
/** The scene group's transform, Plan 4 section 4: 1 unit = 10 mm, Z up. */
export const SCENE_UNITS_PER_MM = 0.1;
export const SCENE_ROTATION_X = -Math.PI / 2;
/** The firmware's gridGeometryFits() slack, in centimetres. */
const SLACK_CM = 1e-4;

let current = rigJson as unknown as RigConfig;

/** Swap in a config - a preview, a model's snapshot, or a fixture. */
export function setRigConfig(config: RigConfig): void { current = config; }
export function rigConfig(): RigConfig { return current; }
export function activeMode(): ModeName { return current.grid.active_mode as ModeName; }

export function modeGeometry(mode: ModeName): ModeGeometry {
  const geometry = current.grid.modes[mode];
  if (!geometry) throw new Error(`unknown grid mode ${mode}; rig.json defines: ${Object.keys(current.grid.modes).join(", ")}`);
  return geometry;
}

/**
 * One mode's resolved lattice, in centimetres. `origin` is the whole of
 * `trim + error_offset + shift` - the three knobs are separate in the config
 * for good reasons (a shift must never masquerade as calibration) but they
 * enter the lattice identically.
 */
export interface Lattice {
  mode: ModeName; cols: number; rows: number;
  blockXCm: number; blockYCm: number; blockZCm: number;
  pitchXCm: number; pitchYCm: number;
  originXCm: number; originYCm: number;
  overhangXCm: number | null; overhangYCm: number | null;
  travelXCm: number; travelYCm: number;
}

export function latticeOf(mode: ModeName, shift?: Shift): Lattice {
  const g = modeGeometry(mode);
  const shiftX = shift ? shift.x_cm : g.shift_x_cm ?? 0;
  const shiftY = shift ? shift.y_cm : g.shift_y_cm ?? 0;
  return {
    mode, cols: g.cols, rows: g.rows,
    blockXCm: g.block_x_cm, blockYCm: g.block_y_cm, blockZCm: g.block_z_cm ?? BLOCK_HEIGHT_CM,
    pitchXCm: g.block_x_cm + g.gap_x_cm, pitchYCm: g.block_y_cm + g.gap_y_cm,
    originXCm: (g.trim_x_cm ?? 0) + (g.error_offset_x_cm ?? 0) + shiftX,
    originYCm: (g.trim_y_cm ?? 0) + (g.error_offset_y_cm ?? 0) + shiftY,
    overhangXCm: g.max_edge_overhang_x_cm ?? null,
    overhangYCm: g.max_edge_overhang_y_cm ?? null,
    travelXCm: current.workspace.width_cm, travelYCm: current.workspace.height_cm,
  };
}

/** Cell space to machine space, in millimetres. Z is the block CENTRE. */
export function cellToMachine(mode: ModeName, col: number, row: number, level: number, shift?: Shift): Vec3 {
  const l = latticeOf(mode, shift);
  return {
    x: (l.originXCm + col * l.pitchXCm) * MM_PER_CM,
    y: (l.originYCm + row * l.pitchYCm) * MM_PER_CM,
    z: levelCentreZ(level, l.blockZCm),
  };
}

/** Ground to the block's base. Level 0 sits on the surface. */
export function levelBaseZ(level: number, blockZCm = BLOCK_HEIGHT_CM): number {
  return level * blockZCm * MM_PER_CM;
}

export function levelCentreZ(level: number, blockZCm = BLOCK_HEIGHT_CM): number {
  return levelBaseZ(level, blockZCm) + (blockZCm * MM_PER_CM) / 2;
}

/** The block's extent along each machine axis, in mm. Never a swap. */
export function blockExtents(mode: ModeName): Vec3 {
  const l = latticeOf(mode);
  return { x: l.blockXCm * MM_PER_CM, y: l.blockYCm * MM_PER_CM, z: l.blockZCm * MM_PER_CM };
}

export function cellCount(mode: ModeName): { cols: number; rows: number } {
  const l = latticeOf(mode);
  return { cols: l.cols, rows: l.rows };
}

/** `[0,0]` is where blocks come FROM, in both modes, and is never built on. */
export function isFeeder(col: number, row: number): boolean { return col === 0 && row === 0; }

/** The feeder is a plain home to raw [0,0]: no shift, no tool offset. */
export function feederCentre(): Vec3 { return { x: 0, y: 0, z: 0 }; }

export interface LatticeBounds {
  minX: number; minY: number; maxX: number; maxY: number;
  firstCentreX: number; firstCentreY: number; lastCentreX: number; lastCentreY: number;
}

/**
 * Block edges and first/last centres of the lattice, in mm. Of the REACHABLE
 * grid by default - the one a shift has clipped, which is what MachineGrid
 * reports - or of the requested one, which is what the Studio draws in amber
 * behind it.
 */
export function latticeBounds(mode: ModeName, shift?: Shift,
                              counts: "reachable" | "requested" = "reachable"): LatticeBounds {
  const l = latticeOf(mode, shift);
  const { cols, rows } = counts === "requested" ? { cols: l.cols, rows: l.rows } : reachableCells(mode, shift);
  const first = { x: l.originXCm, y: l.originYCm };
  const last = { x: l.originXCm + (cols - 1) * l.pitchXCm, y: l.originYCm + (rows - 1) * l.pitchYCm };
  return {
    minX: (first.x - l.blockXCm / 2) * MM_PER_CM, minY: (first.y - l.blockYCm / 2) * MM_PER_CM,
    maxX: (last.x + l.blockXCm / 2) * MM_PER_CM, maxY: (last.y + l.blockYCm / 2) * MM_PER_CM,
    firstCentreX: first.x * MM_PER_CM, firstCentreY: first.y * MM_PER_CM,
    lastCentreX: last.x * MM_PER_CM, lastCentreY: last.y * MM_PER_CM,
  };
}

/**
 * Machine millimetres to scene units. The scene group is rotated -90 degrees
 * about X so that machine Z is screen up, then scaled to 1 unit = 10 mm, so
 * (x, y, z) becomes (x, z, -y) / 10. This is the whole of the axis juggling in
 * the Studio; no component is allowed to do its own.
 */
export function machineToScene(point: Vec3): Vec3 {
  return { x: point.x * SCENE_UNITS_PER_MM, y: point.z * SCENE_UNITS_PER_MM, z: -point.y * SCENE_UNITS_PER_MM };
}

export function sceneToMachine(point: Vec3): Vec3 {
  return { x: point.x / SCENE_UNITS_PER_MM, y: -point.z / SCENE_UNITS_PER_MM, z: point.y / SCENE_UNITS_PER_MM };
}

type Axis = "x" | "y";

function axisOf(l: Lattice, axis: Axis) {
  return axis === "x"
    ? { origin: l.originXCm, pitch: l.pitchXCm, block: l.blockXCm, budget: l.overhangXCm, travel: l.travelXCm, requested: l.cols }
    : { origin: l.originYCm, pitch: l.pitchYCm, block: l.blockYCm, budget: l.overhangYCm, travel: l.travelYCm, requested: l.rows };
}

/**
 * Whether an axis carrying cells `0..index` fits, WITH whatever shift is live.
 * The firmware's `gridGeometryFits`, kept identical on purpose: the holder must
 * reach every centre, AND the blocks those centres carry must land on the
 * machine within this mode's edge budget.
 */
export function axisFits(mode: ModeName, axis: Axis, index: number, shift?: Shift): boolean {
  const a = axisOf(latticeOf(mode, shift), axis);
  if (index < 0 || a.pitch <= 0 || a.block <= 0) return false;
  const firstCentre = a.origin;
  const lastCentre = a.origin + index * a.pitch;
  if (firstCentre < -SLACK_CM || lastCentre > a.travel + SLACK_CM) return false;
  if (a.budget === null) return true;
  if (!Number.isFinite(a.budget) || a.budget < 0) return false;
  return firstCentre - a.block / 2 >= -a.budget - SLACK_CM
    && lastCentre + a.block / 2 <= a.travel + a.budget + SLACK_CM;
}

/**
 * How many cells of each axis the live shift actually leaves reachable -
 * `gridColsNow()` / `gridRowsNow()`, as counts rather than highest indices.
 * The REQUEST is untouched (`cellCount`), so clearing the shift restores the
 * full grid with no re-`S`. Zero means not even cell 0 survives, which is the
 * firmware's -1 and a shift `applyGridShift()` refuses up front.
 */
export function reachableCells(mode: ModeName, shift?: Shift): { cols: number; rows: number } {
  return { cols: reachableCount(mode, "x", shift), rows: reachableCount(mode, "y", shift) };
}

function reachableCount(mode: ModeName, axis: Axis, shift?: Shift): number {
  const a = axisOf(latticeOf(mode, shift), axis);
  if (a.pitch <= 0 || a.travel <= 0) return 0;
  const plausible = Math.ceil((a.travel + 2 * Math.abs(a.origin) + 2 * a.pitch) / a.pitch);
  let highest = -1;
  for (let index = 0; index <= plausible; index++) if (axisFits(mode, axis, index, shift)) highest = index;
  return Math.min(a.requested, highest + 1);
}
