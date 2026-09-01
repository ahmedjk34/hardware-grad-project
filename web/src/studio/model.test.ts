import { describe, expect, it } from "vitest";
import { applyEdit, emptyModel, type ModelBlock } from "./model";

const red: ModelBlock = {
  id: "b1", mode: "vertical", col: 1, row: 1, level: 0, colour: "red",
};
const blue: ModelBlock = {
  id: "b2", mode: "horizontal", col: 1, row: 2, level: 1, colour: "blue",
};

describe("the immutable Studio model", () => {
  it("places one block without changing the input", () => {
    const before = emptyModel();
    const after = applyEdit(before, { type: "place", block: red });

    expect(after).toEqual({ blocks: [red], order: ["b1"] });
    expect(before).toEqual({ blocks: [], order: [] });
    expect(after).not.toBe(before);
  });

  it("places a drag run as one edit and ignores ids already present", () => {
    const before = applyEdit(emptyModel(), { type: "place", block: red });
    const after = applyEdit(before, {
      type: "placeRun",
      blocks: [red, blue, { ...blue, id: "b3", col: 2 }],
    });

    expect(after.blocks.map(block => block.id)).toEqual(["b1", "b2", "b3"]);
    expect(after.order).toEqual(["b1", "b2", "b3"]);
  });

  it("removes a block from geometry and order", () => {
    const placed = applyEdit(
      applyEdit(emptyModel(), { type: "place", block: red }),
      { type: "place", block: blue },
    );
    const after = applyEdit(placed, { type: "remove", id: "b1" });

    expect(after).toEqual({ blocks: [blue], order: ["b2"] });
  });

  it("recolours without changing geometry or order", () => {
    const placed = applyEdit(emptyModel(), { type: "place", block: red });
    const after = applyEdit(placed, { type: "recolour", id: "b1", colour: "green" });

    expect(after.blocks[0]).toEqual({ ...red, colour: "green" });
    expect(after.order).toEqual(placed.order);
  });

  it("moves geometry without reordering the block", () => {
    const placed = applyEdit(
      applyEdit(emptyModel(), { type: "place", block: red }),
      { type: "place", block: blue },
    );
    const after = applyEdit(placed, {
      type: "move", id: "b1", mode: "horizontal", col: 2, row: 3, level: 4,
    });

    expect(after.blocks[0]).toEqual({ ...red, mode: "horizontal", col: 2, row: 3, level: 4 });
    expect(after.blocks.map(block => block.id)).toEqual(["b1", "b2"]);
    expect(after.order).toEqual(["b1", "b2"]);
  });

  it("reorders without moving or reordering the geometry list", () => {
    const placed = applyEdit(
      applyEdit(emptyModel(), { type: "place", block: red }),
      { type: "place", block: blue },
    );
    const after = applyEdit(placed, { type: "reorder", id: "b2", toIndex: 0 });

    expect(after.order).toEqual(["b2", "b1"]);
    expect(after.blocks).toEqual([red, blue]);
  });

  it("returns the same value for an edit that changes nothing", () => {
    const model = applyEdit(emptyModel(), { type: "place", block: red });
    expect(applyEdit(model, { type: "remove", id: "missing" })).toBe(model);
    expect(applyEdit(model, { type: "reorder", id: "missing", toIndex: 0 })).toBe(model);
  });
});
