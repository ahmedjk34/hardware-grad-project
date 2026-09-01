import { describe, expect, it, afterEach } from "vitest";
import fixtures from "./coords.fixtures.json";
import {
  blockExtents, cellCount, cellToMachine, isFeeder, latticeBounds, machineToScene,
  reachableCells, rigConfig, setRigConfig, type RigConfig, type ModeName,
} from "./coords";
import { aabbOf } from "./geometry";

const shipped = rigConfig();
afterEach(() => setRigConfig(shipped));

/** Python is right; this suite exists to prove the port agrees with it. */
describe("Studio coordinates against python/rig/grid.py", () => {
  for (const testCase of fixtures.cases) {
    const mode = testCase.mode as ModeName;

    it(`${testCase.name}: cell centres, footprints and AABBs`, () => {
      setRigConfig(testCase.config as unknown as RigConfig);
      expect(testCase.cells.length > 0 || testCase.refused).toBe(true);
      for (const cell of testCase.cells) {
        const centre = cellToMachine(mode, cell.col, cell.row, cell.level);
        expect(centre.x).toBeCloseTo(cell.center_mm[0], 6);
        expect(centre.y).toBeCloseTo(cell.center_mm[1], 6);
        expect(centre.z).toBeCloseTo(cell.center_mm[2], 6);

        const box = aabbOf({ mode, col: cell.col, row: cell.row, level: cell.level });
        expect(box.min.x).toBeCloseTo(cell.footprint_mm[0], 6);
        expect(box.min.y).toBeCloseTo(cell.footprint_mm[1], 6);
        expect(box.max.x).toBeCloseTo(cell.footprint_mm[2], 6);
        expect(box.max.y).toBeCloseTo(cell.footprint_mm[3], 6);
        expect(box.min.z).toBeCloseTo(cell.aabb_mm.min[2], 6);
        expect(box.max.z).toBeCloseTo(cell.aabb_mm.max[2], 6);
        expect(isFeeder(cell.col, cell.row)).toBe(cell.feeder);
      }
    });

    it(`${testCase.name}: block extents, bounds and reachable counts`, () => {
      setRigConfig(testCase.config as unknown as RigConfig);
      expect(cellCount(mode)).toEqual(testCase.requested);
      if (testCase.refused) {
        // MachineGrid raises before it can say which axis died, so all the
        // fixture claims is that one did.
        const reachable = reachableCells(mode);
        expect(Math.min(reachable.cols, reachable.rows)).toBe(0);
        return;
      }
      expect(reachableCells(mode)).toEqual(testCase.reachable);
      const extents = blockExtents(mode);
      expect(extents.x).toBeCloseTo(testCase.block_mm![0], 6);
      expect(extents.y).toBeCloseTo(testCase.block_mm![1], 6);
      expect(extents.z).toBeCloseTo(testCase.block_mm![2], 6);
      const bounds = latticeBounds(mode);
      expect(bounds.minX).toBeCloseTo(testCase.bounds!.x_start_mm, 6);
      expect(bounds.minY).toBeCloseTo(testCase.bounds!.y_start_mm, 6);
      expect(bounds.maxX).toBeCloseTo(testCase.bounds!.x_end_mm, 6);
      expect(bounds.maxY).toBeCloseTo(testCase.bounds!.y_end_mm, 6);
      expect(bounds.firstCentreX).toBeCloseTo(testCase.bounds!.x_first_center_mm, 6);
      expect(bounds.firstCentreY).toBeCloseTo(testCase.bounds!.y_first_center_mm, 6);
      expect(bounds.lastCentreX).toBeCloseTo(testCase.bounds!.x_last_center_mm, 6);
      expect(bounds.lastCentreY).toBeCloseTo(testCase.bounds!.y_last_center_mm, 6);
    });
  }
});

describe("the facts the fixtures cannot state on their own", () => {
  it("puts cell 0's centre on the home corner in both modes", () => {
    expect(cellToMachine("vertical", 0, 0, 0)).toEqual({ x: 0, y: 0, z: 7.5 });
    expect(cellToMachine("horizontal", 0, 0, 0).x).toBeCloseTo(0, 6);
    expect(cellToMachine("horizontal", 0, 0, 0).y).toBeCloseTo(16, 6); // trim_y +1.6 cm
  });

  it("never swaps a width for a length", () => {
    expect(blockExtents("vertical")).toEqual({ x: 22, y: 60, z: 15 });
    expect(blockExtents("horizontal")).toEqual({ x: 60, y: 22, z: 15 });
  });

  it("measures Z from the ground to the block CENTRE", () => {
    expect(cellToMachine("vertical", 1, 1, 0).z).toBe(7.5);
    expect(cellToMachine("vertical", 1, 1, 1).z).toBe(22.5);
    expect(cellToMachine("vertical", 1, 1, 2).z).toBe(37.5);
  });

  it("treats [0,0] as the feeder and nothing else", () => {
    expect(isFeeder(0, 0)).toBe(true);
    expect(isFeeder(1, 0)).toBe(false);
    expect(isFeeder(0, 1)).toBe(false);
  });

  it("previews a shift without editing the config", () => {
    expect(cellToMachine("vertical", 1, 0, 0, { x_cm: 1.2, y_cm: 0 }).x).toBeCloseTo(50, 6);
    expect(cellToMachine("vertical", 1, 0, 0).x).toBeCloseTo(38, 6);
    expect(reachableCells("vertical", { x_cm: 1.2, y_cm: 0 })).toEqual({ cols: 6, rows: 6 });
  });

  it("turns machine millimetres into scene units with one transform", () => {
    // machine Z is up; the scene group is rotated -90 degrees about X and scaled
    // to 1 unit = 10 mm, so (x, y, z) -> (x, z, -y) / 10.
    expect(machineToScene({ x: 100, y: 200, z: 15 })).toEqual({ x: 10, y: 1.5, z: -20 });
    expect(machineToScene({ x: 0, y: 0, z: 0 })).toEqual({ x: 0, y: 0, z: -0 });
  });
});
