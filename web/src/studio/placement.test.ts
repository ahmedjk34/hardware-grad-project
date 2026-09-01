import { describe, expect, it } from "vitest";
import { emptyModel, applyEdit, type ModelBlock } from "./model";
import { placementStatus } from "./placement";

const block: ModelBlock = {
  id: "b1", mode: "vertical", col: 2, row: 1, level: 0, colour: "red",
};

describe("M2 local placement checks", () => {
  it("reserves [0,0] as the feeder in either mode", () => {
    expect(placementStatus(emptyModel(), "vertical", { col: 0, row: 0, level: 0 }))
      .toEqual({ legal: false, reason: "[0,0] is the feeder" });
    expect(placementStatus(emptyModel(), "horizontal", { col: 0, row: 0, level: 4 }).legal)
      .toBe(false);
  });

  it("rejects a cell outside that mode's grid", () => {
    expect(placementStatus(emptyModel(), "horizontal", { col: 3, row: 1, level: 0 }))
      .toEqual({ legal: false, reason: "outside the grid" });
  });

  it("rejects an occupied same-mode cell and level", () => {
    const model = applyEdit(emptyModel(), { type: "place", block });
    expect(placementStatus(model, "vertical", { col: 2, row: 1, level: 0 }))
      .toEqual({ legal: false, reason: "already a block here" });
  });

  it("allows an empty target without starting M3 support or collision rules", () => {
    const model = applyEdit(emptyModel(), { type: "place", block });
    expect(placementStatus(model, "horizontal", { col: 2, row: 1, level: 0 }))
      .toEqual({ legal: true, reason: null });
  });
});
