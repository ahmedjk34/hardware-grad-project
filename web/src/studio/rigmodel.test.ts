import { describe, expect, it } from "vitest";
import {
  MIGRATIONS, SCHEMA, documentOf, fromFileRig, parseLibraryFile, parseModel,
  serialiseLibrary, serialiseModel, snapshotFileRig, structureOf, type StudioModel,
} from "./rigmodel";
import { snapshotRigGeometry } from "./validate";
import type { ModelBlock } from "./model";

const blocks: ModelBlock[] = [
  { id: "b1", mode: "vertical", col: 1, row: 1, level: 0, colour: "red" },
  { id: "b2", mode: "vertical", col: 1, row: 1, level: 1, colour: "red" },
  { id: "b3", mode: "horizontal", col: 1, row: 4, level: 2, colour: "yellow" },
];

const sample = (): StudioModel => ({
  id: "0f4c-1234",
  name: "Bridged arch",
  description: "Two towers with a horizontal span",
  created: "2026-09-01T14:02:11.000Z",
  modified: "2026-09-01T14:40:05.000Z",
  rig: snapshotFileRig(),
  blocks,
  order: ["b1", "b3", "b2"],
  thumbnail: "data:image/webp;base64,AAAA",
});

describe("rigmodel/1 — the file format", () => {
  it("round-trips a model through JSON without losing a field", () => {
    const before = sample();
    const parsed = parseModel(serialiseModel(before));
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parsed.value).toEqual(before);
  });

  it("writes the schema tag and the Plan 4 §5 document shape", () => {
    const document = JSON.parse(serialiseModel(sample()));
    expect(document.schema).toBe("rigmodel/1");
    expect(Object.keys(document.rig).sort()).toEqual(["modes", "shift_cm", "workspace_cm"]);
    expect(document.rig.workspace_cm).toEqual([22.8, 38]);
    expect(document.rig.modes.vertical.block_cm).toEqual([2.2, 6, 1.5]);
    expect(document.rig.modes.vertical.pitch_cm[0]).toBeCloseTo(3.8, 9);
    expect(document.rig.modes.vertical.pitch_cm[1]).toBeCloseTo(7.6, 9);
    expect(document.rig.shift_cm.horizontal).toEqual([0, 0]);
    expect(document.blocks).toHaveLength(3);
    expect(document.order).toEqual(["b1", "b3", "b2"]);
  });

  it("carries the rig snapshot back out in the shape GEOMETRY_DRIFT compares", () => {
    expect(fromFileRig(snapshotFileRig())).toEqual(snapshotRigGeometry());
  });

  it("keeps a stored shift through the round trip so drift is detected, not silently applied", () => {
    const before = sample();
    before.rig.shift_cm.horizontal = [1, 0];
    const parsed = parseModel(serialiseModel(before));
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parsed.value.rig.shift_cm.horizontal).toEqual([1, 0]);
    expect(fromFileRig(parsed.value.rig)).not.toEqual(snapshotRigGeometry());
  });

  it("splits document metadata from the editable structure", () => {
    expect(structureOf(sample())).toEqual({ blocks, order: ["b1", "b3", "b2"] });
    const fresh = documentOf({ blocks, order: ["b1", "b2", "b3"] }, { name: "Tower" });
    expect(fresh.name).toBe("Tower");
    expect(fresh.id).toMatch(/\S/);
    expect(fresh.rig).toEqual(snapshotFileRig());
  });
});

describe("rigmodel/1 — a corrupt file is refused, never thrown", () => {
  const cases: [string, string, RegExp][] = [
    ["not JSON at all", "{ this is not json", /not valid JSON/i],
    ["JSON but not an object", "[1, 2, 3]", /not a rigmodel document/i],
    ["a missing schema tag", JSON.stringify({ id: "x", blocks: [] }), /schema/i],
    ["an unknown schema version", JSON.stringify({ schema: "rigmodel/9" }), /rigmodel\/9/],
    ["a missing blocks array", JSON.stringify({ schema: SCHEMA, id: "x", name: "n", rig: snapshotFileRig() }), /blocks/i],
    ["a block with no mode", JSON.stringify({
      ...JSON.parse(serialiseModel(sample())),
      blocks: [{ id: "b1", col: 1, row: 1, level: 0, colour: "red" }],
    }), /b1/],
    ["a non-integer cell", JSON.stringify({
      ...JSON.parse(serialiseModel(sample())),
      blocks: [{ id: "b1", mode: "vertical", col: 1.5, row: 1, level: 0, colour: "red" }],
    }), /b1/],
    ["a missing rig snapshot", JSON.stringify({ schema: SCHEMA, id: "x", name: "n", blocks: [], order: [] }), /rig/i],
  ];
  for (const [name, text, reason] of cases) {
    it(`refuses ${name} with a reason that names the problem`, () => {
      const parsed = parseModel(text);
      expect(parsed.ok).toBe(false);
      if (parsed.ok) return;
      expect(parsed.reason).toMatch(reason);
      expect(parsed.reason.length).toBeLessThan(200);
    });
  }

  it("repairs an order that disagrees with the blocks rather than refusing the file", () => {
    const parsed = parseModel(JSON.stringify({
      ...JSON.parse(serialiseModel(sample())),
      order: ["b2", "ghost-that-was-deleted"],
    }));
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parsed.value.order).toEqual(["b2", "b1", "b3"]);
  });
});

describe("rigmodel/1 — the migration hook", () => {
  it("runs identity for version 1 and leaves the document untouched", () => {
    const document = JSON.parse(serialiseModel(sample()));
    expect(MIGRATIONS[SCHEMA](document)).toEqual(document);
  });

  it("routes another version through its migration instead of refusing it", () => {
    const legacy = { ...JSON.parse(serialiseModel(sample())), schema: "rigmodel/0" };
    MIGRATIONS["rigmodel/0"] = document => ({ ...document, schema: SCHEMA, name: "migrated" });
    try {
      const parsed = parseModel(JSON.stringify(legacy));
      expect(parsed.ok).toBe(true);
      if (!parsed.ok) return;
      expect(parsed.value.name).toBe("migrated");
    } finally {
      delete MIGRATIONS["rigmodel/0"];
    }
  });
});

describe("rigmodel/1 — the whole library as one array file", () => {
  it("round-trips several models through a single .rigmodels.json array", () => {
    const models = [sample(), { ...sample(), id: "second", name: "Tower" }];
    const parsed = parseLibraryFile(serialiseLibrary(models));
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parsed.value).toEqual(models);
  });

  it("accepts a single model file where a library file is expected", () => {
    const parsed = parseLibraryFile(serialiseModel(sample()));
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parsed.value).toHaveLength(1);
    expect(parsed.value[0].name).toBe("Bridged arch");
  });

  it("names the offending entry when one model in the array is corrupt", () => {
    const parsed = parseLibraryFile(JSON.stringify([JSON.parse(serialiseModel(sample())), { schema: "rigmodel/1" }]));
    expect(parsed.ok).toBe(false);
    if (parsed.ok) return;
    expect(parsed.reason).toMatch(/model 2/i);
  });
});
