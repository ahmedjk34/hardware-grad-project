/**
 * Running-bond grid shift: the resolver, the compiler's `shiftX` / `shiftY`
 * latches, the model edit, and the file roundtrip.
 *
 * The bond course is a HORIZONTAL-grid feature only — `BOND_MODE` gates the
 * vertical grid out in `resolveShift`. The increment (`3.8 cm = half the
 * 7.6 cm run-axis pitch`) is derived, not asserted as a literal.
 */
import { describe, expect, it } from "vitest";
import {
  BOND_MODE, bondIncrementCm, latticeOf, resolveShift, runAxisOf, type BondShifts,
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

const options = (over = {}) => ({ settings: DEFAULT_STUDIO_SETTINGS, mode: "horizontal" as const, ...over });
const shiftTexts = (program: ReturnType<typeof compile>["program"]) =>
  program.filter((op): op is ShiftOp => op.op === "shift").map(op => op.text);

describe("the increment, the run axis, and the one grid it applies to", () => {
  it("is half the run-axis pitch — 3.8 cm — on the horizontal grid's X axis", () => {
    expect(BOND_MODE).toBe("horizontal");
    expect(runAxisOf("horizontal")).toBe("x");
    expect(bondIncrementCm("horizontal")).toBeCloseTo(latticeOf("horizontal").pitchXCm / 2);
    expect(bondIncrementCm("horizontal")).toBeCloseTo(3.8);
  });
});

describe("resolveShift — the one place the two sources combine", () => {
  const bond: BondShifts = { horizontal: { 1: [3.8, 0], 3: [3.8, 0] } };

  it("adds the level's bond offset on top of the live rig shift", () => {
    expect(resolveShift({ mode: "horizontal", level: 1 }, { horizontal: { x_cm: 0.5, y_cm: 0 } }, bond))
      .toEqual({ x_cm: 4.3, y_cm: 0 });
  });

  it("never shifts the vertical grid, whatever the map says", () => {
    expect(resolveShift({ mode: "vertical", level: 1 }, undefined,
      { vertical: { 1: [0, 3.8] }, horizontal: { 1: [3.8, 0] } })).toBeUndefined();
  });

  it("skips level 0 and any level with no entry", () => {
    expect(resolveShift({ mode: "horizontal", level: 0 }, undefined, bond)).toBeUndefined();
    expect(resolveShift({ mode: "horizontal", level: 2 }, undefined, bond)).toBeUndefined();
  });

  it("returns undefined when the sum is zero, so unbonded models are byte-identical", () => {
    expect(resolveShift({ mode: "horizontal", level: 1 }, undefined, undefined)).toBeUndefined();
    expect(resolveShift({ mode: "horizontal", level: 1 }, { horizontal: { x_cm: 0, y_cm: 0 } }, {}))
      .toBeUndefined();
  });
});

describe("the compiler emits shiftX / shiftY latches at course changes", () => {
  // A horizontal running-bond wall along X. The horizontal grid is 3 columns
  // (0-2). Course 0 flush (cols 0-2), course 1 offset (cols 0-1, each block
  // bridging two course-0 blocks), course 2 flush again (col 1). Every block
  // clears SUPPORT_RATIO.
  const wall = modelOf([
    b("l0a", "horizontal", 0, 1, 0), b("l0b", "horizontal", 1, 1, 0), b("l0c", "horizontal", 2, 1, 0),
    b("l1a", "horizontal", 0, 1, 1), b("l1b", "horizontal", 1, 1, 1),
    b("l2b", "horizontal", 1, 1, 2),
  ], { horizontal: { 1: [3.8, 0] } });

  it("shifts on before the odd course and back off before the even one", () => {
    const { program, stats } = compile(wall, options());
    expect(shiftTexts(program)).toEqual(["shiftX 3.8", "shiftX 0"]);
    expect(stats.shifts).toBe(2);
    const kinds = program.map(op => op.op);
    expect(kinds[0]).toBe("build");
    expect(kinds.filter(k => k === "shift").length).toBe(2);
  });

  it("does not emit a latch for an unbonded model", () => {
    const { program } = compile(modelOf(wall.blocks), options());
    expect(shiftTexts(program)).toEqual([]);
  });

  it("re-asserts the course shift after a mode latch resets it", () => {
    const program = emitOps(
      [b("v", "vertical", 1, 1, 0), b("h0", "horizontal", 1, 1, 0), b("h1", "horizontal", 1, 1, 1)],
      "vertical", undefined, { horizontal: { 1: [3.8, 0] } },
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
    // A full-pitch offset (beyond what the panel's clamped incrementer allows —
    // the validator is the safety net): the far horizontal column goes off the
    // X cap plus its overhang budget.
    const model = modelOf([
      b("base", "horizontal", 2, 1, 0),
      b("bond", "horizontal", 2, 1, 1),
    ], { horizontal: { 1: [7.6, 0] } });
    const diagnostics = validateModel(model, {
      mode: "horizontal", settings: DEFAULT_STUDIO_SETTINGS, bondShifts: model.bondShifts,
    });
    const clipped = diagnostics.filter(d => d.code === "CLIPPED_BY_SHIFT");
    expect(clipped).toHaveLength(1);
    expect(clipped[0].blockId).toBe("bond");
    expect(clipped[0].severity).toBe("error");
    expect(compile(model, options()).valid).toBe(false);
  });

  it("a single half-pitch course keeps every horizontal column (it has X slack)", () => {
    const model = modelOf([
      b("base", "horizontal", 2, 9, 0),
      b("bond", "horizontal", 2, 9, 1),
    ], { horizontal: { 1: [3.8, 0] } });
    const diagnostics = validateModel(model, {
      mode: "horizontal", settings: DEFAULT_STUDIO_SETTINGS, bondShifts: model.bondShifts,
    });
    expect(diagnostics.filter(d => d.code === "CLIPPED_BY_SHIFT")).toHaveLength(0);
  });
});

describe("the model edit and the file roundtrip", () => {
  it("setBond writes, clears, and prunes a zero offset", () => {
    let model = emptyModel();
    model = applyEdit(model, { type: "setBond", mode: "horizontal", level: 1, offsetCm: [3.8, 0] });
    expect(model.bondShifts).toEqual({ horizontal: { 1: [3.8, 0] } });
    model = applyEdit(model, { type: "setBond", mode: "horizontal", level: 3, offsetCm: [0, 0] });
    expect(model.bondShifts).toEqual({ horizontal: { 1: [3.8, 0] } });
    model = applyEdit(model, { type: "setBond", mode: "horizontal", level: 1, offsetCm: null });
    expect(model.bondShifts).toBeUndefined();
  });

  it("carries bondShifts through an unrelated structural edit", () => {
    let model: Model = { blocks: [], order: [], bondShifts: { horizontal: { 1: [3.8, 0] } } };
    model = applyEdit(model, { type: "place", block: b("x", "horizontal", 1, 1, 0) });
    expect(model.bondShifts).toEqual({ horizontal: { 1: [3.8, 0] } });
  });

  it("serialises and parses back the same map, and an older file just has none", () => {
    const doc = documentOf(modelOf([b("x", "horizontal", 1, 1, 0)], { horizontal: { 1: [3.8, 0] } }));
    const round = parseModel(serialiseModel(doc));
    expect(round.ok).toBe(true);
    if (round.ok) expect(structureOf(round.value).bondShifts).toEqual({ horizontal: { 1: [3.8, 0] } });

    const legacy = parseModel(serialiseModel(documentOf(modelOf([b("x", "horizontal", 1, 1, 0)]))));
    expect(legacy.ok).toBe(true);
    if (legacy.ok) expect(legacy.value.bondShifts).toBeUndefined();
  });
});
