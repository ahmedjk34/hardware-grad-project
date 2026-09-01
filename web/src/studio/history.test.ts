import { describe, expect, it } from "vitest";
import { canRedo, canUndo, createHistory, push, redo, undo } from "./history";

describe("generic bounded history", () => {
  it("undoes and redoes pushed values", () => {
    const start = createHistory(0);
    const two = push(push(start, 1), 2);

    expect(canUndo(two)).toBe(true);
    expect(canRedo(two)).toBe(false);
    const one = undo(two);
    expect(one.present).toBe(1);
    expect(undo(one).present).toBe(0);
    expect(redo(one).present).toBe(2);
  });

  it("clears redo when a new branch is pushed", () => {
    const branched = push(undo(push(push(createHistory(0), 1), 2)), 9);
    expect(branched.present).toBe(9);
    expect(canRedo(branched)).toBe(false);
  });

  it("keeps at least 100 undo entries by default and caps older entries", () => {
    let history = createHistory(0);
    for (let value = 1; value <= 105; value++) history = push(history, value);

    expect(history.past).toHaveLength(100);
    for (let count = 0; count < 100; count++) history = undo(history);
    expect(history.present).toBe(5);
    expect(canUndo(history)).toBe(false);
  });

  it("treats a shift-drag run as one history entry", () => {
    const run = [1, 2, 3, 4];
    const after = push(createHistory<number[]>([]), run);
    expect(undo(after).present).toEqual([]);
    expect(after.past).toHaveLength(1);
  });
});
