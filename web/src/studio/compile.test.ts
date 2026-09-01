import { afterEach, describe, expect, it } from "vitest";
import { rigConfig, setRigConfig } from "./coords";
import { aabbOf } from "./geometry";
import type { Model, ModelBlock } from "./model";
import { DEFAULT_STUDIO_SETTINGS } from "./settings";
import {
  ORDER_TERMS, byCell, byId, chain, byAuthorIndex, byCurrentMode, byLevel,
  commandText, compile, comparatorFor, emitOps, estimateLabel, formatDuration,
  orderBlocks, summarise, supportGraph, type OrderTerm,
} from "./compile";

const shipped = structuredClone(rigConfig());
afterEach(() => setRigConfig(structuredClone(shipped)));

function block(id: string, mode: ModelBlock["mode"], col: number, row: number,
               level: number): ModelBlock {
  return { id, mode, col, row, level, colour: "white" };
}

/** A model whose author order is exactly the array order unless `order` given. */
function modelOf(blocks: ModelBlock[], order?: string[]): Model {
  return { blocks, order: order ?? blocks.map(b => b.id) };
}

const options = (over: Partial<Parameters<typeof compile>[1]> = {}) => ({
  settings: DEFAULT_STUDIO_SETTINGS, ...over,
});

const buildIds = (program: ReturnType<typeof compile>["program"]) =>
  program.filter(op => op.op === "build").map(op => (op as { id: string }).id);
const buildLevels = (program: ReturnType<typeof compile>["program"]) =>
  program.filter(op => op.op === "build").map(op => (op as { level: number }).level);
const modeTexts = (program: ReturnType<typeof compile>["program"]) =>
  program.filter(op => op.op === "mode").map(op => op.text);

// A self-supported vertical stack in one cell: every level rests on the one below.
const verticalStack = (cell: [number, number], levels: number, prefix = "v") =>
  Array.from({ length: levels }, (_, level) => block(`${prefix}${level}`, "vertical", cell[0], cell[1], level));
const horizontalStack = (cell: [number, number], levels: number, prefix = "h") =>
  Array.from({ length: levels }, (_, level) => block(`${prefix}${level}`, "horizontal", cell[0], cell[1], level));

// ── The four named steps in isolation ──────────────────────────────────────────

describe("supportGraph — who must precede whom", () => {
  it("makes a stacked block depend on the one it rests on, and ground blocks depend on nothing", () => {
    const [b0, b1, b2] = verticalStack([1, 1], 3);
    const graph = supportGraph(modelOf([b0, b1, b2]));
    expect([...graph.get("v0")!]).toEqual([]);
    expect([...graph.get("v1")!]).toEqual(["v0"]);
    expect([...graph.get("v2")!]).toEqual(["v1"]);
  });

  it("captures a cross-mode bridge: a horizontal block resting on two vertical stacks depends on both", () => {
    // Two vertical L0 blocks one pitch apart; a horizontal block laid across
    // their tops at level 1, shifted so it actually spans both (the same
    // support-edge derivation validate.test.ts uses for its bridge fixture).
    const left = block("L", "vertical", 1, 1, 0);
    const right = block("R", "vertical", 2, 1, 0);
    const span = block("S", "horizontal", 0, 2, 1);
    const supportEdge = aabbOf(left).max.x;
    const centre = (aabbOf(span).min.x + aabbOf(span).max.x) / 2;
    const shift = { x_cm: (supportEdge - 0.1 - centre) / 10, y_cm: 0 };
    const graph = supportGraph(modelOf([left, right, span]), { horizontal: shift });
    expect(new Set(graph.get("S"))).toEqual(new Set(["L", "R"]));
  });
});

describe("orderBlocks — Kahn walk over the support graph", () => {
  it("CONSTRAINT 1, support before supported: keeps the base first even when the author put the top first and byLevel is gone", () => {
    const [b0, b1] = verticalStack([1, 1], 2);
    const model = modelOf([b0, b1], ["v1", "v0"]);
    const noLevel: OrderTerm[] = ["currentMode", "authorIndex", "cell", "id"];

    // With the graph, the base is forced first regardless of author intent.
    expect(orderBlocks(model, supportGraph(model), "vertical", noLevel).map(b => b.id))
      .toEqual(["v0", "v1"]);
    // Remove the graph (empty Map) and, with byLevel also gone, the illegal
    // author order is honoured — the support ends up after the block on it.
    expect(orderBlocks(model, new Map(), "vertical", noLevel).map(b => b.id))
      .toEqual(["v1", "v0"]);
  });

  it("CONSTRAINT 2, bottom-up: every emitted level is >= the one before it; removing byLevel breaks that", () => {
    // Two independent stacks. byLevel interleaves them by height; author order
    // would drain stack A (0,1,2) before touching stack B (0,1).
    const a = verticalStack([1, 1], 3, "a");
    const b = verticalStack([3, 1], 2, "b");
    const model = modelOf([...a, ...b], ["a0", "a1", "a2", "b0", "b1"]);
    const graph = supportGraph(model);

    const withLevel = orderBlocks(model, graph, "vertical").map(x => x.level);
    expect(withLevel).toEqual([...withLevel].sort((p, q) => p - q));

    const noLevel = orderBlocks(model, graph, "vertical",
      ["currentMode", "authorIndex", "cell", "id"]).map(x => x.level);
    const monotone = noLevel.every((lvl, i) => i === 0 || lvl >= noLevel[i - 1]);
    expect(monotone).toBe(false);
  });

  it("CONSTRAINT 3 + the stateful comparator: the run is re-keyed on the emitter's CURRENT mode at every pop", () => {
    // vertical stack v0<v1<v2, horizontal stack h0<h1, authored interleaved.
    const model = interleavedModel();
    const graph = supportGraph(model);

    const latchesWith = countLatches(orderBlocks(model, graph, "vertical"));
    const latchesWithout = countLatches(orderBlocks(model, graph, "vertical",
      ["level", "authorIndex", "cell", "id"]));

    expect(latchesWith).toBe(2);        // one run each of V and H per level band
    expect(latchesWithout).toBe(4);     // static preference re-latches every band

    // Directly: the same ready pair sorts differently under each current mode.
    const ready = [block("h", "horizontal", 0, 5, 1), block("v", "vertical", 1, 1, 1)];
    expect([...ready].sort(comparatorFor(model, "vertical")).map(b => b.id)).toEqual(["v", "h"]);
    expect([...ready].sort(comparatorFor(model, "horizontal")).map(b => b.id)).toEqual(["h", "v"]);
  });

  it("CONSTRAINT 4, author order wins where it is legal; removing byAuthorIndex lets the cell tie-break take over", () => {
    const blocks = [
      block("a", "vertical", 5, 1, 0), block("b", "vertical", 2, 1, 0),
      block("c", "vertical", 4, 1, 0), block("d", "vertical", 1, 1, 0),
    ];
    const model = modelOf(blocks, ["a", "b", "c", "d"]);
    const graph = supportGraph(model);
    expect(orderBlocks(model, graph, "vertical").map(x => x.id)).toEqual(["a", "b", "c", "d"]);
    expect(orderBlocks(model, graph, "vertical", ["level", "currentMode", "cell", "id"]).map(x => x.id))
      .toEqual(["d", "b", "c", "a"]);
  });

  it("CONSTRAINT 5, deterministic tie-break: byCell then byId, and byId is the only thing that stops a 0 comparison", () => {
    const p = block("p", "vertical", 3, 1, 0);
    const q = block("q", "vertical", 1, 1, 0);
    const model = modelOf([p, q], []);           // no author order for either
    const graph = supportGraph(model);
    // byCell orders them by column...
    expect(orderBlocks(model, graph, "vertical").map(x => x.id)).toEqual(["q", "p"]);
    // ...drop byCell and only byId remains, which orders by id.
    expect(orderBlocks(model, graph, "vertical", ["level", "currentMode", "authorIndex", "id"]).map(x => x.id))
      .toEqual(["p", "q"]);

    // byId as the last line of defence: with everything else stripped, two
    // distinct blocks that tie on all earlier terms compare 0 without it.
    const same1 = block("a", "vertical", 1, 1, 0);
    const same2 = block("b", "vertical", 1, 1, 0);
    const withoutId = chain(byLevel(), byCurrentMode("vertical"), byAuthorIndex([]), byCell());
    expect(withoutId(same1, same2)).toBe(0);
    expect(Math.sign(chain(withoutId, byId())(same1, same2))).toBe(-1);
  });
});

describe("emitOps — the mode-latch state machine", () => {
  it("emits a latch only on an actual change and annotates it 'homes X and Y'", () => {
    const ops = emitOps([
      block("v0", "vertical", 1, 1, 0),
      block("v1", "vertical", 1, 1, 1),
      block("h0", "horizontal", 0, 5, 0),
      block("h1", "horizontal", 0, 5, 1),
      block("v2", "vertical", 2, 1, 0),
    ], "vertical");
    expect(ops.map(op => op.op)).toEqual([
      "build", "build", "mode", "build", "build", "mode", "build",
    ]);
    for (const op of ops) if (op.op === "mode") expect(op.cost).toBe("homes X and Y");
  });

  it("starts from the live board mode: a pure-horizontal program needs no latch when the board is already horizontal", () => {
    const blocks = horizontalStack([0, 5], 2);
    expect(emitOps(blocks, "horizontal").every(op => op.op === "build")).toBe(true);
    expect(emitOps(blocks, "vertical")[0]).toMatchObject({ op: "mode", mode: "horizontal", text: "RR" });
  });
});

describe("commandText — the one place serial text is built", () => {
  it("formats B with exactly three numbers, and R / RR for the latch", () => {
    expect(commandText({ op: "build", id: "b", col: 3, row: 2, level: 1 })).toBe("B 3 2 1");
    expect(commandText({ op: "mode", mode: "vertical", cost: "homes X and Y" })).toBe("R");
    expect(commandText({ op: "mode", mode: "horizontal", cost: "homes X and Y" })).toBe("RR");
  });

  it("is the text carried on every op the compiler emits", () => {
    const { program } = compile(modelOf([
      ...verticalStack([1, 1], 1), block("h", "horizontal", 0, 5, 0),
    ]), options());
    expect(program.map(op => op.text)).toEqual(["B 1 1 0", "RR", "B 0 5 0"]);
  });
});

describe("summarise + estimates", () => {
  it("counts blocks, latches, levels and derives ~duration from the visible settings", () => {
    const { stats } = compile(flatFourWithOneLatch(), options());
    expect(stats).toEqual({
      blocks: 4, latches: 1, modeSwitches: 1, levels: 1,
      estimateSeconds: Math.round(4 * DEFAULT_STUDIO_SETTINGS.blockCycleSeconds
        + 1 * DEFAULT_STUDIO_SETTINGS.latchHomingSeconds),
    });
    expect(stats.estimateSeconds).toBe(24);
    expect(estimateLabel(stats)).toBe("4 blocks · 1 latch · ~0:24");
    expect(formatDuration(176)).toBe("2:56");
  });

  it("scales with the configurable per-block and per-latch costs", () => {
    const custom = { ...DEFAULT_STUDIO_SETTINGS, blockCycleSeconds: 10, latchHomingSeconds: 5 };
    const { program } = compile(interleavedModel(), options({ settings: custom }));
    const stats = summarise(program, custom);
    expect(stats).toMatchObject({ blocks: 5, latches: 2 });
    expect(stats.estimateSeconds).toBe(5 * 10 + 2 * 5);
  });
});

// ── compile(): the whole pipeline ─────────────────────────────────────────────

describe("compile — model to program", () => {
  it("a pure-vertical model latches nothing and starts building immediately", () => {
    const { valid, program, stats } = compile(modelOf(verticalStack([1, 1], 3)), options());
    expect(valid).toBe(true);
    expect(program[0].op).toBe("build");
    expect(modeTexts(program)).toEqual([]);
    expect(stats.latches).toBe(0);
    expect(buildIds(program)).toEqual(["v0", "v1", "v2"]);
  });

  it("a pure-horizontal model latches once from the vertical boot state", () => {
    const { program, stats } = compile(modelOf(horizontalStack([0, 5], 2)), options());
    expect(program[0]).toMatchObject({ op: "mode", mode: "horizontal", text: "RR", cost: "homes X and Y" });
    expect(stats.latches).toBe(1);
    expect(program.slice(1).every(op => op.op === "build")).toBe(true);
  });

  it("a pure-horizontal model latches nothing when the live board mode is already horizontal", () => {
    const { program, stats } = compile(modelOf(horizontalStack([0, 5], 2)), options({ mode: "horizontal" }));
    expect(stats.latches).toBe(0);
    expect(program.every(op => op.op === "build")).toBe(true);
  });

  it("an interleaved mixed-mode model compiles to a minimal-latch run per level band", () => {
    const { program, stats } = compile(interleavedModel(), options());
    expect(stats.latches).toBe(2);
    expect(modeTexts(program)).toEqual(["RR", "R"]);
    // support is respected: every build's level is monotone non-decreasing
    expect(buildLevels(program)).toEqual([...buildLevels(program)].sort((a, b) => a - b));
  });

  it("preserves a legal author order and overrides an illegal one", () => {
    const legal = compile(modelOf([
      block("a", "vertical", 5, 1, 0), block("b", "vertical", 2, 1, 0),
      block("c", "vertical", 4, 1, 0),
    ], ["a", "b", "c"]), options());
    expect(buildIds(legal.program)).toEqual(["a", "b", "c"]);

    const [b0, b1] = verticalStack([1, 1], 2);
    const illegal = compile(modelOf([b0, b1], ["v1", "v0"]), options());
    expect(buildIds(illegal.program)).toEqual(["v0", "v1"]);
  });

  it("runs the M3 validator itself: an invalid model yields valid=false, an empty program, and the diagnostics", () => {
    const feeder = compile(modelOf([block("bad", "vertical", 0, 0, 0)]), options());
    expect(feeder.valid).toBe(false);
    expect(feeder.program).toEqual([]);
    expect(feeder.stats).toEqual({ blocks: 0, latches: 0, modeSwitches: 0, levels: 0, estimateSeconds: 0 });
    expect(feeder.diagnostics.some(d => d.code === "FEEDER_CELL" && d.severity === "error")).toBe(true);

    const floating = compile(modelOf([block("air", "vertical", 1, 1, 2)]), options());
    expect(floating.valid).toBe(false);
    expect(floating.program).toEqual([]);
  });

  it("a warning does not block compilation", () => {
    // Two detached components -> ISLAND warning, still a valid program.
    const model = modelOf([
      ...verticalStack([1, 1], 1), block("far", "vertical", 5, 4, 0),
    ]);
    const { valid, diagnostics, program } = compile(model, options());
    expect(valid).toBe(true);
    expect(diagnostics.some(d => d.severity === "warning")).toBe(true);
    expect(program.length).toBe(2);
  });

  it("an empty model is a valid, empty program", () => {
    expect(compile({ blocks: [], order: [] }, options())).toEqual({
      valid: true, program: [],
      stats: { blocks: 0, latches: 0, modeSwitches: 0, levels: 0, estimateSeconds: 0 },
      diagnostics: [],
    });
  });

  it("stats.modeSwitches mirrors stats.latches for the Plan 4 §6.1 output shape", () => {
    const { stats } = compile(interleavedModel(), options());
    expect(stats.modeSwitches).toBe(stats.latches);
  });
});

describe("DETERMINISM — the alarm", () => {
  it("compiles the same model to byte-identical output twenty times", () => {
    const model = interleavedModel();
    const first = JSON.stringify(compile(model, options()));
    for (let i = 0; i < 20; i++) {
      expect(JSON.stringify(compile(model, options()))).toBe(first);
    }
  });

  it("orders the program from the model's declared order, not the blocks array order", () => {
    const model = interleavedModel();
    const reversed: Model = { blocks: [...model.blocks].reverse(), order: model.order };
    const shape = (m: Model) => {
      const { program, stats } = compile(m, options());
      return JSON.stringify({ program, stats });
    };
    expect(shape(reversed)).toBe(shape(model));
  });
});

describe("the exported comparator terms compose in the documented order", () => {
  it("ORDER_TERMS is level, currentMode, authorIndex, cell, id", () => {
    expect(ORDER_TERMS).toEqual(["level", "currentMode", "authorIndex", "cell", "id"]);
  });
});

// ── shared fixtures ──────────────────────────────────────────────────────────

/** vertical stack v0<v1<v2, horizontal stack h0<h1, authored interleaved so a
 *  static mode preference would re-home on every level band. */
function interleavedModel(): Model {
  const v = verticalStack([1, 1], 3);
  const h = horizontalStack([0, 5], 2);
  return modelOf([...v, ...h], ["v0", "h0", "v1", "h1", "v2"]);
}

/** Three vertical ground blocks then one horizontal ground block: exactly one
 *  latch, four blocks, one level — the Plan 4 §6.1 estimate fixture. */
function flatFourWithOneLatch(): Model {
  return modelOf([
    block("a", "vertical", 1, 1, 0), block("b", "vertical", 2, 1, 0),
    block("c", "vertical", 3, 1, 0), block("d", "horizontal", 0, 5, 0),
  ], ["a", "b", "c", "d"]);
}

function countLatches(ordered: { mode: string }[]): number {
  let mode = "vertical";
  let latches = 0;
  for (const b of ordered) if (b.mode !== mode) { mode = b.mode; latches++; }
  return latches;
}
