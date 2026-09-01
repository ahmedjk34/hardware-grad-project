import { describe, expect, it } from "vitest";
import { BRIDGE_SHIFT_CM, EXAMPLES, exampleById } from "./examples";
import { compile } from "./compile";
import { DEFAULT_STUDIO_SETTINGS } from "./settings";
import { validateModel } from "./validate";
import { fromFileRig, parseModel, serialiseModel, shiftsOf, structureOf } from "./rigmodel";
import { cellCount } from "./coords";

const contextFor = (id: string) => {
  const example = exampleById(id)!;
  return {
    mode: "vertical" as const,
    settings: DEFAULT_STUDIO_SETTINGS,
    shifts: shiftsOf(example.rig),
    rigSnapshot: fromFileRig(example.rig),
  };
};

describe("the three built-in examples are fixtures as well as demos", () => {
  it("ships exactly the tower, the bridge and the pyramid", () => {
    expect(EXAMPLES.map(example => example.id))
      .toEqual(["example-tower", "example-bridge", "example-pyramid"]);
    expect(EXAMPLES.map(example => example.name))
      .toEqual(["Single tower", "Two towers, one span", "Stepped pyramid"]);
  });

  for (const example of EXAMPLES) {
    it(`${example.name} survives a save-and-reload round trip`, () => {
      const parsed = parseModel(serialiseModel(example));
      expect(parsed.ok).toBe(true);
      if (!parsed.ok) return;
      expect(parsed.value).toEqual(example);
    });

    it(`${example.name} has no validation errors against the shipped rig.json`, () => {
      const errors = validateModel(structureOf(example), contextFor(example.id))
        .filter(diagnostic => diagnostic.severity === "error");
      expect(errors).toEqual([]);
    });

    it(`${example.name} compiles to a program the runner could send`, () => {
      const program = compile(structureOf(example), contextFor(example.id));
      expect(program.valid).toBe(true);
      expect(program.stats.blocks).toBe(example.blocks.length);
      for (const op of program.program) expect(op.text).toMatch(/^(B \d+ \d+ \d+|R|RR)$/);
    });

    it(`${example.name} stays inside the grid it declares`, () => {
      for (const block of example.blocks) {
        const { cols, rows } = cellCount(block.mode);
        expect(block.col).toBeLessThan(cols);
        expect(block.row).toBeLessThan(rows);
        expect([block.col, block.row]).not.toEqual([0, 0]);
      }
    });

    it(`${example.name} lists every block exactly once in its author order`, () => {
      expect([...example.order].sort()).toEqual(example.blocks.map(block => block.id).sort());
    });
  }
});

describe("Single tower — the short program to rehearse with", () => {
  it("is one cell, five levels, one mode and no latch at all", () => {
    const tower = exampleById("example-tower")!;
    const program = compile(structureOf(tower), contextFor(tower.id));
    expect(program.stats.latches).toBe(0);
    expect(new Set(tower.blocks.map(block => `${block.col},${block.row}`)).size).toBe(1);
    expect(program.program.map(op => op.text)).toEqual([
      "B 3 2 0", "B 3 2 1", "B 3 2 2", "B 3 2 3", "B 3 2 4",
    ]);
  });
});

describe("Two towers, one span — the cross-mode bridge", () => {
  const bridge = () => exampleById("example-bridge")!;

  it("spans two vertical stacks with one horizontal block", () => {
    const blocks = bridge().blocks;
    expect(blocks.filter(block => block.mode === "vertical")).toHaveLength(4);
    const span = blocks.filter(block => block.mode === "horizontal");
    expect(span).toHaveLength(1);
    expect(span[0].level).toBe(2);
  });

  it("forces exactly one latch, emitted only when the span is reached", () => {
    const program = compile(structureOf(bridge()), contextFor("example-bridge"));
    expect(program.stats.latches).toBe(1);
    expect(program.program.map(op => op.text)).toEqual([
      "B 2 2 0", "B 3 2 0", "B 2 2 1", "B 3 2 1", "RR", "B 1 4 2",
    ]);
  });

  it("carries the grid shift the span needs, which the rig is not applying", () => {
    // The shipped lattices do not line up: the vertical pitch is 3.8 cm and the
    // horizontal pitch 7.6 cm, so an unshifted horizontal block sits over the
    // 1.6 cm gap between two vertical stacks and rests on 46.7% of its
    // footprint, under the 55% support ratio. The search in the M5 commit swept
    // every (tower pair, span cell, shift) triple through M3's validator; the
    // shifts that produce a legal bridge are +0.8 to +1.1 and +2.7 to +3.0 cm.
    // +1.0 is the round one, and v[2,2] v[3,2] with h[1,4] is its central case.
    expect(bridge().rig.shift_cm.horizontal).toEqual([BRIDGE_SHIFT_CM, 0]);
    expect(BRIDGE_SHIFT_CM).toBe(1);
  });

  it("says so in a GEOMETRY_DRIFT warning rather than building the wrong thing", () => {
    const diagnostics = validateModel(structureOf(bridge()), contextFor("example-bridge"));
    const drift = diagnostics.filter(diagnostic => diagnostic.code === "GEOMETRY_DRIFT");
    expect(drift).toHaveLength(1);
    expect(drift[0].severity).toBe("warning");
    expect(drift[0].message).toMatch(/horizontal/);
    expect(drift[0].message).toMatch(/shift/i);
    expect(diagnostics.filter(diagnostic => diagnostic.code !== "GEOMETRY_DRIFT")).toEqual([]);
  });
});

describe("Stepped pyramid — the support rule doing real work", () => {
  const pyramid = () => exampleById("example-pyramid")!;

  it("is three levels on a five-wide base, every course resting on the one below", () => {
    const levels = pyramid().blocks.reduce<Record<number, number>>((counts, block) => {
      counts[block.level] = (counts[block.level] ?? 0) + 1;
      return counts;
    }, {});
    expect(levels).toEqual({ 0: 5, 1: 3, 2: 1 });
  });

  it("warns that the five stacks are separate structures — the machine's own gaps", () => {
    const diagnostics = validateModel(structureOf(pyramid()), contextFor("example-pyramid"));
    expect(diagnostics.every(diagnostic => diagnostic.code === "ISLAND")).toBe(true);
    expect(diagnostics.length).toBeGreaterThan(0);
  });
});
