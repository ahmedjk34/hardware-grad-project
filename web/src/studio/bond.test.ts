/**
 * Running-bond grid shift: the resolver, the compiler's `shiftX` / `shiftY`
 * latches, the model edit, and the file roundtrip.
 *
 * See docs/features/running-bond-grid-shift.md. The geometry itself
 * (`3.8 cm = half the 7.6 cm run-axis pitch`) is derived, not asserted as a
 * literal — a pitch change should move this number, not break the test.
 */
import { describe, expect, it } from "vitest";
import {
  bondIncrementCm, latticeOf, resolveShift, runAxisOf, type BondShifts,
} from "./coords";
import { compile, emitOps, cmWord, type ShiftOp } from "./compile";
import { applyEdit, emptyModel, type Model, type ModelBlock } from "./model";
import { validateModel } from "./validate";
import { DEFAULT_STUDIO_SETTINGS } from "./settings";
import { documentOf, parseModel, serialiseModel, structureOf } from "./rigmodel";

const b = (id: string, mode: ModelBlock["mode"], col: number, row: number, level: number): ModelBlock =>
  ({ id, mode, col, row, level, colour: "white" });
const modelOf = (blocks: ModelBlock[], bondShifts?: BondShifts): Model =>
  ({ blocks, order: blocks.map(x => x.id), ...(bondShifts ? { bondShifts } : {}) });

const options = (over = {}) => ({ settings: DEFAULT_STUDIO_SETTINGS, ...over });
const shiftTexts = (program: ReturnType<typeof compile>["program"]) =>
  program.filter((op): op is ShiftOp => op.op === "shift").map(op => op.text);

describe("the increment and the run axis", () => {
  it("is half the run-axis pitch — 3.8 cm on both modes today", () => {
    expect(runAxisOf("vertical")).toBe("y");
    expect(runAxisOf("horizontal")).toBe("x");
    expect(bondIncrementCm("vertical")).toBeCloseTo(latticeOf("vertical").pitchYCm / 2);
    expect(bondIncrementCm("horizontal")).toBeCloseTo(latticeOf("horizontal").pitchXCm / 2);
    expect(bondIncrementCm("vertical")).toBeCloseTo(3.8);
    expect(bondIncrementCm("horizontal")).toBeCloseTo(3.8);
  });
});

describe("resolveShift — the one place the two sources combine", () => {
  const bond: BondShifts = { vertical: { 1: [0, 3.8], 3: [0, 3.8] } };

  it("adds the level's bond offset on top of the live rig shift", () => {
    expect(resolveShift({ mode: "vertical", level: 1 }, { vertical: { x_cm: 0, y_cm: 0.5 } }, bond))
      .toEqual({ x_cm: 0, y_cm: 4.3 });
  });

  it("skips level 0 and any level with no entry", () => {
    expect(resolveShift({ mode: "vertical", level: 0 }, undefined, bond)).toBeUndefined();
    expect(resolveShift({ mode: "vertical", level: 2 }, undefined, bond)).toBeUndefined();
  });

  it("returns undefined when the sum is zero, so unbonded models are byte-identical", () => {
    expect(resolveShift({ mode: "vertical", level: 1 }, undefined, undefined)).toBeUndefined();
    expect(resolveShift({ mode: "horizontal", level: 1 }, { horizontal: { x_cm: 0, y_cm: 0 } }, {}))
      .toBeUndefined();
  });
});

describe("the compiler emits shiftX / shiftY latches at course changes", () => {
  // A vertical running-bond wall in column 3 (clear of the feeder-belt cells at
  // [1,0] [1,1] [2,1]). Course 0 flush (rows 1-3), course 1 offset (rows 1-2,
  // each block bridging two course-0 blocks), course 2 flush again (row 2,
  // bridging two course-1 blocks). Every block clears SUPPORT_RATIO.
  const wall = modelOf([
    b("l0a", "vertical", 3, 1, 0), b("l0b", "vertical", 3, 2, 0), b("l0c", "vertical", 3, 3, 0),
    b("l1a", "vertical", 3, 1, 1), b("l1b", "vertical", 3, 2, 1),
    b("l2b", "vertical", 3, 2, 2),
  ], { vertical: { 1: [0, 3.8] } });

  it("shifts on before the odd course and back off before the even one", () => {
    const { program, stats } = compile(wall, options());
    expect(shiftTexts(program)).toEqual(["shiftY 3.8", "shiftY 0"]);
    expect(stats.shifts).toBe(2);
    // The latch lands between the level groups, never before the first block.
    const kinds = program.map(op => op.op);
    expect(kinds[0]).toBe("build");
    expect(kinds.filter(k => k === "shift").length).toBe(2);
  });

  it("does not emit a latch for an unbonded model", () => {
    const { program } = compile(modelOf(wall.blocks), options());
    expect(shiftTexts(program)).toEqual([]);
  });

  it("re-asserts the course shift after a mode latch resets it", () => {
    const mixed = modelOf([
      b("v", "vertical", 1, 1, 0),
      b("h0", "horizontal", 1, 1, 0), b("h1", "horizontal", 1, 1, 1),
    ], { horizontal: { 1: [3.8, 0] } });
    const program = emitOps(
      // support order is fixed by level; force horizontal after vertical
      [mixed.blocks[0], mixed.blocks[1], mixed.blocks[2]], "vertical",
      undefined, mixed.bondShifts,
    );
    expect(program.map(op => op.text)).toEqual(["B 1 1 0", "RR", "B 1 1 0", "shiftX 3.8", "B 1 1 1"]);
  });

  it("formats cm the firmware's %g way", () => {
    expect(cmWord(3.8)).toBe("3.8");
    expect(cmWord(0)).toBe("0");
    expect(cmWord(-3.8)).toBe("-3.8");
  });
});

describe("a course that pushes a block off the travel cap", () => {
  it("raises CLIPPED_BY_SHIFT so RUN is blocked, and nothing is deleted", () => {
    // Vertical sits exactly on its Y cap: a +3.8 cm course loses row 5.
    const model = modelOf([
      b("base", "vertical", 1, 5, 0),
      b("bond", "vertical", 1, 5, 1),
    ], { vertical: { 1: [0, 3.8] } });
    const diagnostics = validateModel(model, { mode: "vertical", settings: DEFAULT_STUDIO_SETTINGS, bondShifts: model.bondShifts });
    const clipped = diagnostics.filter(d => d.code === "CLIPPED_BY_SHIFT");
    expect(clipped).toHaveLength(1);
    expect(clipped[0].blockId).toBe("bond");
    expect(clipped[0].severity).toBe("error");
    // The base course on the same row is fine — only the shifted level clips.
    expect(compile(model, options()).valid).toBe(false);
  });
});

describe("the model edit and the file roundtrip", () => {
  it("setBond writes, clears, and prunes a zero offset", () => {
    let model = emptyModel();
    model = applyEdit(model, { type: "setBond", mode: "vertical", level: 1, offsetCm: [0, 3.8] });
    expect(model.bondShifts).toEqual({ vertical: { 1: [0, 3.8] } });
    model = applyEdit(model, { type: "setBond", mode: "vertical", level: 3, offsetCm: [0, 0] });
    expect(model.bondShifts).toEqual({ vertical: { 1: [0, 3.8] } });
    model = applyEdit(model, { type: "setBond", mode: "vertical", level: 1, offsetCm: null });
    expect(model.bondShifts).toBeUndefined();
  });

  it("carries bondShifts through an unrelated structural edit", () => {
    let model: Model = { blocks: [], order: [], bondShifts: { vertical: { 1: [0, 3.8] } } };
    model = applyEdit(model, { type: "place", block: b("x", "vertical", 1, 1, 0) });
    expect(model.bondShifts).toEqual({ vertical: { 1: [0, 3.8] } });
  });

  it("serialises and parses back the same map, and an older file just has none", () => {
    const doc = documentOf(modelOf([b("x", "vertical", 1, 1, 0)], { vertical: { 1: [0, 3.8] } }));
    const round = parseModel(serialiseModel(doc));
    expect(round.ok).toBe(true);
    if (round.ok) expect(structureOf(round.value).bondShifts).toEqual({ vertical: { 1: [0, 3.8] } });

    const legacy = parseModel(serialiseModel(documentOf(modelOf([b("x", "vertical", 1, 1, 0)]))));
    expect(legacy.ok).toBe(true);
    if (legacy.ok) expect(legacy.value.bondShifts).toBeUndefined();
  });
});
