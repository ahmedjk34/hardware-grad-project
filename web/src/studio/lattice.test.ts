import { describe, expect, it, afterEach } from "vitest";
import {
  blockExtents, cellCount, cellToMachine, machineToScene, rigConfig, setRigConfig,
  type ModeName, type RigConfig,
} from "./coords";
import { clippedCells } from "./geometry";
import { latticeCells, rulerTicks, type LatticeCell } from "./lattice";

const shipped = rigConfig();
afterEach(() => setRigConfig(shipped));

const find = (cells: LatticeCell[], col: number, row: number) =>
  cells.find(cell => cell.col === col && cell.row === row)!;

describe("which cells the lattice draws", () => {
  for (const mode of ["vertical", "horizontal"] as ModeName[]) {
    it(`${mode}: one cell per address, and only the addresses the rig has`, () => {
      const { cols, rows } = cellCount(mode);
      const cells = latticeCells(mode);
      expect(cells).toHaveLength(cols * rows);
      expect(new Set(cells.map(cell => `${cell.col},${cell.row}`)).size).toBe(cells.length);
      expect(cells.every(cell => cell.col < cols && cell.row < rows)).toBe(true);
    });

    it(`${mode}: [0,0] is the feeder and nothing else is`, () => {
      const cells = latticeCells(mode);
      expect(cells.filter(cell => cell.kind === "feeder").map(cell => [cell.col, cell.row]))
        .toEqual([[0, 0]]);
    });

    it(`${mode}: every cell sits where coords.ts puts it, at its true footprint`, () => {
      const size = blockExtents(mode);
      for (const cell of latticeCells(mode)) {
        const centre = machineToScene(cellToMachine(mode, cell.col, cell.row, 0));
        expect(cell.centre.x).toBeCloseTo(centre.x, 6);
        expect(cell.centre.z).toBeCloseTo(centre.z, 6);
        expect(cell.centre.y).toBeCloseTo(0, 6);
        expect(cell.sizeX).toBeCloseTo(machineToScene({ x: size.x, y: 0, z: 0 }).x, 6);
        expect(cell.sizeZ).toBeCloseTo(Math.abs(machineToScene({ x: 0, y: size.y, z: 0 }).z), 6);
      }
    });
  }

  it("leaves the true gap between neighbours — cells never touch within a mode", () => {
    const cells = latticeCells("vertical");
    const first = find(cells, 0, 0);
    const next = find(cells, 1, 0);
    const gap = (next.centre.x - next.sizeX / 2) - (first.centre.x + first.sizeX / 2);
    expect(gap).toBeCloseTo(machineToScene({ x: 16, y: 0, z: 0 }).x, 6);
  });

  it("the two modes are different grids, not one rotated grid", () => {
    const vertical = latticeCells("vertical");
    const horizontal = latticeCells("horizontal");
    expect(vertical).toHaveLength(42);
    expect(horizontal).toHaveLength(30);
    expect(find(vertical, 0, 0).sizeX).toBeLessThan(find(vertical, 0, 0).sizeZ);
    expect(find(horizontal, 0, 0).sizeX).toBeGreaterThan(find(horizontal, 0, 0).sizeZ);
  });
});

describe("a shift clips the far cells, and the lattice says which", () => {
  it("marks exactly the cells the firmware would put out of reach", () => {
    const shift = { x_cm: 3.0, y_cm: 0 };
    const clipping = clippedCells("vertical", shift);
    expect(clipping.cells.length).toBeGreaterThan(0);

    const cells = latticeCells("vertical", shift);
    const clipped = cells.filter(cell => cell.kind === "clipped").map(cell => `${cell.col},${cell.row}`);
    expect(clipped.sort()).toEqual(clipping.cells.map(cell => `${cell.col},${cell.row}`).sort());
    expect(cells).toHaveLength(clipping.requested.cols * clipping.requested.rows);
  });

  it("slides every cell by the shift, in real millimetres", () => {
    const shift = { x_cm: 1.2, y_cm: -0.4 };
    const shifted = find(latticeCells("vertical", shift), 1, 1);
    const centre = machineToScene(cellToMachine("vertical", 1, 1, 0, shift));
    expect(shifted.centre.x).toBeCloseTo(centre.x, 6);
    expect(shifted.centre.z).toBeCloseTo(centre.z, 6);
  });

  it("the feeder stays the feeder even when the shift clips it out", () => {
    const refused = JSON.parse(JSON.stringify(rigConfig())) as RigConfig;
    refused.grid.modes.vertical.shift_x_cm = 40;
    setRigConfig(refused);
    const cells = latticeCells("vertical");
    expect(find(cells, 0, 0).kind).toBe("feeder");
    expect(cells.filter(cell => cell.kind === "clipped").length).toBeGreaterThan(0);
  });
});

describe("the envelope's centimetre rulers", () => {
  it("ticks every centimetre from the home corner to the travel cap", () => {
    const ticks = rulerTicks(22.8);
    expect(ticks[0].cm).toBe(0);
    expect(ticks.at(-1)!.cm).toBe(22);
    expect(ticks).toHaveLength(23);
  });

  it("puts each tick where coords.ts puts that centimetre", () => {
    for (const tick of rulerTicks(38)) {
      expect(tick.at).toBeCloseTo(machineToScene({ x: tick.cm * 10, y: 0, z: 0 }).x, 6);
    }
  });

  it("marks every fifth centimetre as major, so the ruler is readable", () => {
    const ticks = rulerTicks(22.8);
    expect(ticks.filter(tick => tick.major).map(tick => tick.cm)).toEqual([0, 5, 10, 15, 20]);
  });
});
