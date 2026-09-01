import { describe, expect, it } from "vitest";
import {
  ARRIVAL_DROP_SCENE, ARRIVAL_FADE_MS, ARRIVAL_SETTLE_MS, ROW_STAGGER_MS,
  arrivalFrame, rowArrivalDelays,
} from "./motion";

describe("smooth row-aware block arrival", () => {
  it("groups new blocks by row and staggers rows in gesture order", () => {
    const delays = rowArrivalDelays([
      { id: "a", row: 4 }, { id: "b", row: 4 },
      { id: "c", row: 3 }, { id: "d", row: 6 }, { id: "e", row: 3 },
    ]);
    expect(delays).toEqual(new Map([
      ["a", 0], ["b", 0],
      ["c", ROW_STAGGER_MS],
      ["d", ROW_STAGGER_MS * 2],
      ["e", ROW_STAGGER_MS],
    ]));
  });

  it("combines a smooth spawn fade with a downward settle", () => {
    expect(arrivalFrame(0, 0, false)).toEqual({
      active: true, opacity: 0, offsetScene: ARRIVAL_DROP_SCENE,
    });
    const middle = arrivalFrame(ARRIVAL_FADE_MS / 2, 0, false);
    expect(middle.active).toBe(true);
    expect(middle.opacity).toBeGreaterThan(0);
    expect(middle.opacity).toBeLessThan(1);
    expect(middle.offsetScene).toBeGreaterThan(0);
    expect(middle.offsetScene).toBeLessThan(ARRIVAL_DROP_SCENE);
    expect(arrivalFrame(ARRIVAL_SETTLE_MS, 0, false)).toEqual({
      active: false, opacity: 1, offsetScene: 0,
    });
  });

  it("waits invisibly for a later row, then gives it the full animation", () => {
    expect(arrivalFrame(ROW_STAGGER_MS - 1, ROW_STAGGER_MS, false)).toEqual({
      active: true, opacity: 0, offsetScene: ARRIVAL_DROP_SCENE,
    });
    expect(arrivalFrame(ROW_STAGGER_MS, ROW_STAGGER_MS, false)).toEqual({
      active: true, opacity: 0, offsetScene: ARRIVAL_DROP_SCENE,
    });
  });

  it("places immediately under prefers-reduced-motion", () => {
    expect(arrivalFrame(0, ROW_STAGGER_MS * 3, true)).toEqual({
      active: false, opacity: 1, offsetScene: 0,
    });
  });
});
