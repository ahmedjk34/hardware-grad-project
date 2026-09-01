import { describe, expect, it } from "vitest";
import { cellToMachine, machineToScene } from "./coords";
import {
  chooseHit, resolveGroundTarget, resolveTopTarget, runCells,
  type PlacementHit,
} from "./pick";

function sceneAt(mode: "vertical" | "horizontal", col: number, row: number,
                 machineOffset = { x: 0, y: 0, z: 0 }) {
  const centre = cellToMachine(mode, col, row, 0);
  return machineToScene({
    x: centre.x + machineOffset.x,
    y: centre.y + machineOffset.y,
    z: machineOffset.z,
  });
}

describe("raycast hit resolution without a GPU", () => {
  it("resolves the centre and a point just inside the block edge", () => {
    expect(resolveGroundTarget(sceneAt("vertical", 2, 3), "vertical"))
      .toEqual({ col: 2, row: 3, level: 0 });
    expect(resolveGroundTarget(
      sceneAt("vertical", 2, 3, { x: 10.999, y: 29.999, z: 0 }), "vertical",
    )).toEqual({ col: 2, row: 3, level: 0 });
  });

  it("returns null in the 1.6 cm gap instead of snapping to a neighbour", () => {
    expect(resolveGroundTarget(
      sceneAt("vertical", 2, 3, { x: 11.001, y: 0, z: 0 }), "vertical",
    )).toBeNull();
  });

  it("returns null outside the requested grid", () => {
    expect(resolveGroundTarget(sceneAt("vertical", -1, 2), "vertical")).toBeNull();
  });

  it("uses the active mode for a block-top cell and the hit block for level", () => {
    const block = { mode: "vertical" as const, col: 4, row: 1, level: 2 };
    const horizontalCell = sceneAt("horizontal", 2, 2);
    expect(resolveTopTarget(block, horizontalCell, "horizontal"))
      .toEqual({ col: 2, row: 2, level: 3 });
  });

  it("takes the nearest hit and lets a block top win a distance tie", () => {
    const ground: PlacementHit = { kind: "ground", distance: 4, target: { col: 1, row: 1, level: 0 } };
    const top: PlacementHit = { kind: "top", distance: 4, target: { col: 1, row: 1, level: 1 } };
    expect(chooseHit([ground, top])).toBe(top);
    expect(chooseHit([{ ...ground, distance: 3 }, top])).toEqual({ ...ground, distance: 3 });
  });

  it("builds a one-axis run along whichever axis dominates", () => {
    expect(runCells({ col: 1, row: 1 }, { col: 4, row: 2 }))
      .toEqual([{ col: 1, row: 1 }, { col: 2, row: 1 }, { col: 3, row: 1 }, { col: 4, row: 1 }]);
    expect(runCells({ col: 2, row: 4 }, { col: 1, row: 1 }))
      .toEqual([{ col: 2, row: 4 }, { col: 2, row: 3 }, { col: 2, row: 2 }, { col: 2, row: 1 }]);
  });
});
