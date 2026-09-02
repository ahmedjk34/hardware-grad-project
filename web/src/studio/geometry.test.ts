import { describe, expect, it, afterEach } from "vitest";
import { rigConfig, setRigConfig, type Block } from "./coords";
import {
  aabbOf, clippedCells, convexHull, footprintOverlapArea, intersects,
  supportPolygonContains, topFaceZ, type AABB,
} from "./geometry";

const shipped = rigConfig();
afterEach(() => setRigConfig(shipped));

const block = (mode: Block["mode"], col: number, row: number, level: number): Block =>
  ({ mode, col, row, level });

describe("machine-space geometry", () => {
  it("puts a block's AABB around its centre", () => {
    const box = aabbOf(block("vertical", 1, 1, 0));
    expect(box.min).toEqual({ x: 38 - 11, y: 76 - 30, z: 0 });
    expect(box.max).toEqual({ x: 38 + 11, y: 76 + 30, z: 15 });
  });

  it("reports the top face as the next level's base", () => {
    expect(topFaceZ(block("vertical", 1, 1, 0))).toBe(15);
    expect(topFaceZ(block("vertical", 1, 1, 2))).toBe(45);
  });

  it("keeps cells of one mode apart and lets the modes interleave", () => {
    // The 1.6 cm gap means no vertical block can bridge two vertical cells...
    expect(intersects(aabbOf(block("vertical", 1, 1, 0)), aabbOf(block("vertical", 2, 1, 0)))).toBe(false);
    // ...but a horizontal block is 6.0 cm along X where the vertical pitch is
    // 3.8, so it can sit across two vertical stacks. Plan 4 section 3 fact 6.
    expect(intersects(aabbOf(block("horizontal", 1, 1, 0)), aabbOf(block("vertical", 2, 1, 0)))).toBe(true);
    expect(intersects(aabbOf(block("horizontal", 1, 1, 0)), aabbOf(block("vertical", 3, 1, 0)))).toBe(true);
  });

  it("ignores blocks on different levels", () => {
    expect(intersects(aabbOf(block("vertical", 1, 1, 0)), aabbOf(block("vertical", 1, 1, 1)))).toBe(false);
  });

  it("measures footprint overlap in square millimetres", () => {
    const a = aabbOf(block("vertical", 1, 1, 0));
    expect(footprintOverlapArea(a, a)).toBeCloseTo(22 * 60, 6);
    expect(footprintOverlapArea(a, aabbOf(block("vertical", 3, 1, 0)))).toBe(0);
    // A horizontal block spanning X overlaps a vertical one by the vertical
    // block's own 22 mm width. With horizontal's +1.9 cm Y registration the
    // horizontal block's full 22 mm depth now lands within the vertical block's
    // Y run, so the cross-mode contact is the whole 22 x 22 mm.
    const overlap = footprintOverlapArea(aabbOf(block("horizontal", 1, 1, 1)), aabbOf(block("vertical", 2, 1, 0)));
    expect(overlap).toBeCloseTo(22 * 22, 6);
  });

  it("touching faces do not count as an intersection", () => {
    const stacked = aabbOf(block("vertical", 1, 1, 1));
    expect(stacked.min.z).toBe(topFaceZ(block("vertical", 1, 1, 0)));
    expect(intersects(aabbOf(block("vertical", 1, 1, 0)), stacked)).toBe(false);
  });
});

describe("the support polygon — the toppling test", () => {
  const flat = (minX: number, maxX: number, minY: number, maxY: number): AABB =>
    ({ min: { x: minX, y: minY, z: 0 }, max: { x: maxX, y: maxY, z: 1 } });

  it("hulls a set of points and drops the collinear and interior ones", () => {
    const hull = convexHull([
      { x: 0, y: 0 }, { x: 2, y: 0 }, { x: 4, y: 0 }, // 2,0 is collinear
      { x: 4, y: 4 }, { x: 0, y: 4 }, { x: 2, y: 2 }, // 2,2 is interior
    ]);
    expect(hull).toHaveLength(4);
    expect(new Set(hull.map(p => `${p.x},${p.y}`)))
      .toEqual(new Set(["0,0", "4,0", "4,4", "0,4"]));
  });

  it("reduces to a plain footprint test for a single support", () => {
    const clip = flat(0, 10, 0, 10);
    expect(supportPolygonContains([flat(0, 10, 0, 10)], clip, 5, 5)).toBe(true);
    expect(supportPolygonContains([flat(0, 4, 0, 10)], clip, 5, 5)).toBe(false);
  });

  it("carries a span whose centre is over the gap between two supports", () => {
    const clip = flat(0, 30, 0, 10);
    const supports = [flat(0, 12, 0, 10), flat(18, 30, 0, 10)];
    // Centre of mass at x = 15 is over the 12..18 gap — no single footprint holds
    // it — but it is inside the hull that spans both supports.
    expect(supportPolygonContains(supports, clip, 15, 5)).toBe(true);
  });

  it("rejects a centre of mass that hangs past every support", () => {
    const clip = flat(0, 30, 0, 10);
    const supports = [flat(0, 8, 0, 10), flat(9, 12, 0, 10)];
    expect(supportPolygonContains(supports, clip, 15, 5)).toBe(false);
  });

  it("is unsupported when nothing is beneath", () => {
    expect(supportPolygonContains([], flat(0, 10, 0, 10), 5, 5)).toBe(false);
  });
});

describe("grid shift clipping, as the firmware does it", () => {
  it("clips nothing when the shift is zero", () => {
    const clip = clippedCells("vertical");
    expect(clip.requested).toEqual({ cols: 7, rows: 6 });
    expect(clip.reachable).toEqual({ cols: 7, rows: 6 });
    expect(clip.cells).toEqual([]);
    expect(clip.refused).toBe(false);
  });

  it("keeps the requested grid and clips the reachable one", () => {
    const clip = clippedCells("vertical", { x_cm: 1.2, y_cm: 0 });
    expect(clip.requested).toEqual({ cols: 7, rows: 6 });
    expect(clip.reachable).toEqual({ cols: 6, rows: 6 });
    expect(clip.cells).toHaveLength(6); // the far column, every row
    expect(clip.cells.every(cell => cell.col === 6)).toBe(true);
  });

  it("clips both axes at once", () => {
    const clip = clippedCells("horizontal", { x_cm: 8.0, y_cm: 3.8 });
    expect(clip.reachable).toEqual({ cols: 2, rows: 9 });
    expect(clip.cells).toContainEqual({ col: 2, row: 0 });
    expect(clip.cells).toContainEqual({ col: 0, row: 9 });
    expect(clip.cells).toHaveLength(3 * 10 - 2 * 9);
  });

  it("restores the full grid when the shift is cleared", () => {
    expect(clippedCells("vertical", { x_cm: 3.8, y_cm: 0 }).reachable.cols).toBe(6);
    expect(clippedCells("vertical", { x_cm: 0, y_cm: 0 }).reachable.cols).toBe(7);
  });

  it("refuses a shift that leaves no cell on the machine", () => {
    // Only X is ruined; the firmware reports -1 columns and its untouched six
    // rows, and a grid with no columns has no reachable cell at all.
    const clip = clippedCells("vertical", { x_cm: -1.0, y_cm: 0 });
    expect(clip.refused).toBe(true);
    expect(clip.reachable).toEqual({ cols: 0, rows: 6 });
    expect(clip.cells).toHaveLength(7 * 6);
  });

  it("checks the block EDGES against this mode's overhang budget", () => {
    // Horizontal X tolerates 3.0 cm of edge overhang and its last centre sits
    // at trim_x 1.9 + 2 * 7.6 = 17.1 cm, so on top of that registration a
    // further 5.7 cm of shift still lands the last centre on the 22.8 cm cap
    // and 5.8 cm does not.
    expect(clippedCells("horizontal", { x_cm: 5.7, y_cm: 0 }).reachable.cols).toBe(3);
    expect(clippedCells("horizontal", { x_cm: 5.8, y_cm: 0 }).reachable.cols).toBe(2);
  });
});
