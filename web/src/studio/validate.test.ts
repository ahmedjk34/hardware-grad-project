import { afterEach, describe, expect, it } from "vitest";
import { rigConfig, setRigConfig, type RigConfig, type Shift } from "./coords";
import { aabbOf, footprintContains, intersects } from "./geometry";
import { type Model, type ModelBlock } from "./model";
import { DEFAULT_STUDIO_SETTINGS } from "./settings";
import {
  RULES, clawClearance, clippedByShift, collision, duplicateCell,
  edgeOverhang, feederCell, geometryDrift, island, levelCeiling,
  outOfGrid, primaryDiagnostic, snapshotRigGeometry, supportMetrics,
  unsupported, validateModel, validatePlacement,
  type Rule, type ValidationContext,
} from "./validate";

const shipped = structuredClone(rigConfig());
afterEach(() => setRigConfig(structuredClone(shipped)));

function block(id: string, mode: ModelBlock["mode"], col: number, row: number,
               level: number): ModelBlock {
  return { id, mode, col, row, level, colour: "white" };
}

function modelOf(...blocks: ModelBlock[]): Model {
  return { blocks, order: blocks.map(item => item.id) };
}

function changed(change: (config: RigConfig) => void): RigConfig {
  const config = structuredClone(shipped);
  change(config);
  return config;
}

function context(overrides: Partial<ValidationContext> = {}): ValidationContext {
  return {
    mode: "vertical",
    settings: DEFAULT_STUDIO_SETTINGS,
    rigSnapshot: snapshotRigGeometry(),
    ...overrides,
  };
}

interface RuleCase {
  name: string;
  code: string;
  rule: Rule;
  blocks: ModelBlock[];
  subject?: string;
  config?: RigConfig;
  ctx?: Partial<ValidationContext>;
  fires: boolean;
}

const cases: RuleCase[] = [
  { name: "permits an ordinary target", code: "FEEDER_CELL", rule: feederCell,
    blocks: [block("b1", "vertical", 1, 0, 0)], subject: "b1", fires: false },
  { name: "reserves [0,0] in either mode", code: "FEEDER_CELL", rule: feederCell,
    blocks: [block("b1", "horizontal", 0, 0, 2)], subject: "b1", fires: true },

  { name: "uses a modified mode count for a legal edge cell", code: "OUT_OF_GRID", rule: outOfGrid,
    config: changed(c => { c.grid.modes.horizontal.cols = 2; }),
    blocks: [block("b1", "horizontal", 1, 1, 0)], subject: "b1", fires: false },
  { name: "uses a modified mode count to reject the next column", code: "OUT_OF_GRID", rule: outOfGrid,
    config: changed(c => { c.grid.modes.horizontal.cols = 2; }),
    blocks: [block("b1", "horizontal", 2, 1, 0)], subject: "b1", fires: true },

  { name: "keeps a reachable cell under a modified shift", code: "CLIPPED_BY_SHIFT", rule: clippedByShift,
    config: changed(c => { c.grid.modes.vertical.shift_x_cm = 1.2; }),
    blocks: [block("b1", "vertical", 5, 1, 0)], subject: "b1", fires: false },
  { name: "mirrors firmware clipping under a modified shift", code: "CLIPPED_BY_SHIFT", rule: clippedByShift,
    config: changed(c => { c.grid.modes.vertical.shift_x_cm = 1.2; }),
    blocks: [block("b1", "vertical", 6, 1, 0)], subject: "b1", fires: true },

  { name: "accepts an edge inside a modified zero budget", code: "EDGE_OVERHANG", rule: edgeOverhang,
    config: changed(c => { c.grid.modes.vertical.max_edge_overhang_x_cm = 0; }),
    blocks: [block("b1", "vertical", 5, 1, 0)], subject: "b1", fires: false },
  { name: "rejects an edge beyond a modified zero budget", code: "EDGE_OVERHANG", rule: edgeOverhang,
    config: changed(c => { c.grid.modes.vertical.max_edge_overhang_x_cm = 0; }),
    blocks: [block("b1", "vertical", 6, 1, 0)], subject: "b1", fires: true },

  { name: "allows the configured ceiling", code: "LEVEL_CEILING", rule: levelCeiling,
    blocks: [block("b1", "vertical", 1, 1, 6)], subject: "b1", fires: false },
  { name: "warns above the configured ceiling", code: "LEVEL_CEILING", rule: levelCeiling,
    blocks: [block("b1", "vertical", 1, 1, 7)], subject: "b1", fires: true },

  { name: "allows the same cell at another level", code: "DUPLICATE_CELL", rule: duplicateCell,
    blocks: [block("b1", "vertical", 1, 1, 0), block("b2", "vertical", 1, 1, 1)], subject: "b2", fires: false },
  { name: "rejects the same mode, cell and level", code: "DUPLICATE_CELL", rule: duplicateCell,
    blocks: [block("b1", "vertical", 1, 1, 0), block("b2", "vertical", 1, 1, 0)], subject: "b2", fires: true },

  { name: "allows separated boxes under modified geometry", code: "COLLISION", rule: collision,
    config: changed(c => { c.grid.modes.horizontal.block_x_cm = 5.8; }),
    blocks: [block("b1", "vertical", 1, 1, 0), block("b2", "horizontal", 2, 8, 0)], subject: "b2", fires: false },
  { name: "catches a cross-mode overlap under modified geometry", code: "COLLISION", rule: collision,
    config: changed(c => { c.grid.modes.horizontal.block_x_cm = 5.8; }),
    blocks: [block("b1", "vertical", 2, 1, 0), block("b2", "horizontal", 1, 2, 0)], subject: "b2", fires: true },

  { name: "accepts a full footprint under modified pitch", code: "UNSUPPORTED", rule: unsupported,
    config: changed(c => { c.grid.modes.vertical.gap_x_cm = 1.7; }),
    blocks: [block("b1", "vertical", 1, 1, 0), block("b2", "vertical", 1, 1, 1)], subject: "b2", fires: false },
  { name: "rejects empty air under modified pitch", code: "UNSUPPORTED", rule: unsupported,
    config: changed(c => { c.grid.modes.vertical.gap_x_cm = 1.7; }),
    blocks: [block("b1", "vertical", 1, 1, 1)], subject: "b1", fires: true },

  { name: "allows a descent outside a modified gap", code: "CLAW_CLEARANCE", rule: clawClearance,
    config: changed(c => { c.grid.modes.vertical.gap_x_cm = 0.6; }),
    ctx: { settings: { ...DEFAULT_STUDIO_SETTINGS, clawMarginMm: 4 } },
    blocks: [block("b1", "vertical", 2, 1, 2), block("b2", "vertical", 1, 1, 0)], subject: "b2", fires: false },
  { name: "warns when a taller earlier block enters the modified-gap prism", code: "CLAW_CLEARANCE", rule: clawClearance,
    config: changed(c => { c.grid.modes.vertical.gap_x_cm = 0.6; }),
    blocks: [block("b1", "vertical", 2, 1, 2), block("b2", "vertical", 1, 1, 0)], subject: "b2", fires: true },

  { name: "accepts a snapshot of the modified live rig", code: "GEOMETRY_DRIFT", rule: geometryDrift,
    config: changed(c => { c.grid.modes.horizontal.rows = 9; }), blocks: [], fires: false },
  { name: "warns when a snapshot differs from the modified live rig", code: "GEOMETRY_DRIFT", rule: geometryDrift,
    config: changed(c => { c.grid.modes.horizontal.rows = 9; }), blocks: [],
    ctx: { rigSnapshot: snapshotRigGeometry(shipped) }, fires: true },

  { name: "accepts one connected component under modified geometry", code: "ISLAND", rule: island,
    config: changed(c => { c.grid.modes.vertical.gap_y_cm = 1.7; }),
    blocks: [block("b1", "vertical", 1, 1, 0), block("b2", "vertical", 1, 1, 1)], subject: "b2", fires: false },
  { name: "warns on a detached component under modified geometry", code: "ISLAND", rule: island,
    config: changed(c => { c.grid.modes.vertical.gap_y_cm = 1.7; }),
    blocks: [block("b1", "vertical", 1, 1, 0), block("b2", "vertical", 4, 3, 0)], subject: "b2", fires: true },
];

describe("Plan 4 section 6.4 rule table", () => {
  for (const testCase of cases) {
    it(`${testCase.code} — ${testCase.name}`, () => {
      setRigConfig(structuredClone(testCase.config ?? shipped));
      const model = modelOf(...testCase.blocks);
      const subject = testCase.subject
        ? model.blocks.find(item => item.id === testCase.subject)
        : undefined;
      const ctx = context(testCase.ctx);
      if (testCase.code === "GEOMETRY_DRIFT" && !testCase.ctx?.rigSnapshot)
        ctx.rigSnapshot = snapshotRigGeometry();
      const diagnostics = testCase.rule(model, subject, ctx);
      expect(diagnostics.some(item => item.code === testCase.code)).toBe(testCase.fires);
    });
  }
});

describe("footprint-area support", () => {
  it("finds and then pins a legal cross-mode bridge from real coordinate geometry", () => {
    setRigConfig(structuredClone(shipped));
    let found: { supports: [ModelBlock, ModelBlock]; candidate: ModelBlock; shift: Shift } | undefined;

    for (let row = 0; row < 3 && !found; row++) {
      for (let left = 1; left < 4 && !found; left++) {
        for (let candidateRow = 1; candidateRow < 5 && !found; candidateRow++) {
          for (let candidateCol = 0; candidateCol < 3 && !found; candidateCol++) {
            const supports: [ModelBlock, ModelBlock] = [
              block("v1", "vertical", left, row, 0),
              block("v2", "vertical", left + 1, row, 0),
            ];
            const candidate = block("h1", "horizontal", candidateCol, candidateRow, 1);
            const supportEdge = aabbOf(supports[0]).max.x;
            const centre = (aabbOf(candidate).min.x + aabbOf(candidate).max.x) / 2;
            const shift = { x_cm: (supportEdge - 0.1 - centre) / 10, y_cm: 0 };
            const ctx = context({ mode: "horizontal", shifts: { horizontal: shift } });
            const metrics = supportMetrics(modelOf(...supports, candidate), candidate, ctx);
            const candidateBox = aabbOf(candidate, shift);
            if (metrics.ratio >= ctx.settings.supportRatio && metrics.centreStable
                && supports.every(item => !intersects(aabbOf(item), candidateBox))) {
              found = { supports, candidate, shift };
            }
          }
        }
      }
    }

    expect(found).toBeDefined();
    // The scan above finds this named fixture from the shipped pitches and
    // horizontal's +1.9 cm registration. The shift is derived from the support
    // edge, never from a copied centre.
    expect(found?.supports.map(item => [item.col, item.row])).toEqual([[1, 1], [2, 1]]);
    expect([found?.candidate.col, found?.candidate.row]).toEqual([0, 1]);
    const model = modelOf(...found!.supports, found!.candidate);
    const ctx = context({ mode: "horizontal", shifts: { horizontal: found!.shift } });
    expect(unsupported(model, found!.candidate, ctx)).toEqual([]);
  });

  it("supports a span whose centre of mass sits over a gap but inside the two-tower hull", () => {
    const supports = [
      block("v1", "vertical", 1, 1, 0),
      block("v2", "vertical", 2, 1, 0),
    ];
    const candidate = block("h1", "horizontal", 1, 2, 1);
    const a = aabbOf(supports[0]);
    const b = aabbOf(supports[1]);
    const candidateCentre = (aabbOf(candidate).min.x + aabbOf(candidate).max.x) / 2;
    const gapCentre = (a.max.x + b.min.x) / 2;
    const shift = { x_cm: (gapCentre - candidateCentre) / 10, y_cm: 0 };
    const ctx = context({ mode: "horizontal", shifts: { horizontal: shift } });
    const model = modelOf(...supports, candidate);
    const metrics = supportMetrics(model, candidate, ctx);

    // Nothing is under the exact centre — a single-footprint centroid test fails
    // here — but the centre of mass still projects between the two towers.
    expect(footprintContains(aabbOf(supports[0], shift), gapCentre, candidateCentre)).toBe(false);
    expect(footprintContains(aabbOf(supports[1], shift), gapCentre, candidateCentre)).toBe(false);
    expect(metrics.centreStable).toBe(true);
    expect(unsupported(model, candidate, ctx)).toEqual([]);
  });

  it("rejects a span whose centre of mass hangs past its only support", () => {
    const support = block("v1", "vertical", 1, 1, 0);
    const candidate = block("h1", "horizontal", 1, 2, 1);
    const s = aabbOf(support);
    const candidateCentre = (aabbOf(candidate).min.x + aabbOf(candidate).max.x) / 2;
    // Slide the span so a strip of its left side still rests on the tower while
    // the centre of mass sits 1 mm beyond the tower's right edge.
    const shift = { x_cm: (s.max.x + 1 - candidateCentre) / 10, y_cm: 0 };
    const ctx = context({ mode: "horizontal", shifts: { horizontal: shift } });
    const model = modelOf(support, candidate);
    const metrics = supportMetrics(model, candidate, ctx);

    expect(metrics.centreStable).toBe(false);
    expect(unsupported(model, candidate, ctx).map(item => item.code)).toEqual(["UNSUPPORTED"]);
  });
});

describe("clearance follows authored build order", () => {
  it("clears the warning when the taller neighbour is reordered after the target", () => {
    setRigConfig(changed(c => { c.grid.modes.vertical.gap_x_cm = 0.6; }));
    const blocker = block("b1", "vertical", 2, 1, 2);
    const target = block("b2", "vertical", 1, 1, 0);
    const model = modelOf(blocker, target);
    expect(clawClearance(model, target, context())).toHaveLength(1);
    expect(clawClearance({ ...model, order: [target.id, blocker.id] }, target, context())).toEqual([]);
  });
});

describe("the two validator entry points", () => {
  it("runs the same ordered RULES for a model and a ghost candidate", () => {
    expect(RULES.map(rule => rule.code)).toEqual([
      "FEEDER_CELL", "OUT_OF_GRID", "CLIPPED_BY_SHIFT", "EDGE_OVERHANG",
      "LEVEL_CEILING", "DUPLICATE_CELL", "COLLISION", "UNSUPPORTED",
      "CLAW_CLEARANCE", "GEOMETRY_DRIFT", "ISLAND",
    ]);
    const existing = block("b1", "vertical", 1, 1, 0);
    const candidate = block("ghost", "vertical", 1, 1, 0);
    const ctx = context();
    expect(validatePlacement(modelOf(existing), candidate, ctx).map(item => item.code))
      .toEqual(validateModel(modelOf(existing, candidate), ctx)
        .filter(item => item.blockId === candidate.id).map(item => item.code));
  });

  it("uses fixed priority when the ghost has more than one reason", () => {
    const candidate = block("ghost", "vertical", 0, 0, 20);
    const diagnostic = primaryDiagnostic(validatePlacement(modelOf(), candidate, context()));
    expect(diagnostic?.code).toBe("FEEDER_CELL");
  });
});
