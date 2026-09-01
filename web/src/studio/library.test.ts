import { beforeEach, describe, expect, it } from "vitest";
import {
  BUDGET_BYTES, INDEX_KEY, KEY_PREFIX, acceptsDroppedFile, bodyKey, cardOf, duplicateModel, exportLibrary,
  exportModel, importModel, largestFirst, listModels, readModel, removeModel,
  renameModel, storageReport, writeModel, type LibraryStorage,
} from "./library";
import { documentOf, parseModel, serialiseModel, snapshotFileRig } from "./rigmodel";
import { DEFAULT_STUDIO_SETTINGS } from "./settings";
import type { Model, ModelBlock } from "./model";

const block = (id: string, col: number, row: number, level: number): ModelBlock =>
  ({ id, mode: "vertical", col, row, level, colour: "white" });

const tower = (n = 3): Model => {
  const blocks = Array.from({ length: n }, (_, level) => block(`b${level}`, 3, 2, level));
  return { blocks, order: blocks.map(item => item.id) };
};

/** A `localStorage` stand-in that can be made unavailable, full, or corrupt. */
class FakeStorage implements LibraryStorage {
  data = new Map<string, string>();
  capacity = Infinity;
  throwOnRead = false;
  get length() { return this.data.size; }
  key(index: number) { return [...this.data.keys()][index] ?? null; }
  getItem(key: string) {
    if (this.throwOnRead) throw new DOMException("access denied", "SecurityError");
    return this.data.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    const after = [...this.data].reduce((total, [k, v]) => total + (k === key ? 0 : k.length + v.length), 0)
      + key.length + value.length;
    if (after > this.capacity) throw new DOMException("quota", "QuotaExceededError");
    this.data.set(key, value);
  }
  removeItem(key: string) { this.data.delete(key); }
}

let storage: FakeStorage;
const options = () => ({ storage, settings: DEFAULT_STUDIO_SETTINGS });
beforeEach(() => { storage = new FakeStorage(); });

const save = (model: Model, name: string) =>
  writeModel(documentOf(model, { id: name, name }), options());

describe("library — CRUD over localStorage", () => {
  it("writes a body and a card, and reads the model back unchanged", () => {
    const document = documentOf(tower(), { id: "m1", name: "Tower" });
    const written = writeModel(document, options());
    expect(written.ok).toBe(true);

    expect(storage.data.has(bodyKey("m1"))).toBe(true);
    expect(storage.data.has(INDEX_KEY)).toBe(true);

    const read = readModel("m1", options());
    expect(read.ok).toBe(true);
    if (!read.ok) return;
    expect(read.value).toEqual(document);
  });

  it("lists cards without parsing a single body", () => {
    save(tower(3), "Tower");
    save(tower(5), "Taller");
    const bodies = [bodyKey("Tower"), bodyKey("Taller")];
    for (const key of bodies) storage.data.set(key, "{ corrupt");

    const cards = listModels(options());
    expect(cards.ok).toBe(true);
    if (!cards.ok) return;
    expect(cards.value.map(card => card.name).sort()).toEqual(["Taller", "Tower"]);
  });

  it("puts the block count, latch count, estimate and date on the card", () => {
    const document = documentOf({
      blocks: [block("b1", 2, 2, 0), { id: "b2", mode: "horizontal", col: 2, row: 8, level: 0, colour: "yellow" }],
      order: ["b1", "b2"],
    }, { id: "m1", name: "Mixed", modified: "2026-09-01T00:00:00.000Z" });
    const card = cardOf(document, DEFAULT_STUDIO_SETTINGS, 1234);
    expect(card).toMatchObject({
      id: "m1", name: "Mixed", blocks: 2, latches: 1, modified: "2026-09-01T00:00:00.000Z", bytes: 1234,
    });
    expect(card.estimateSeconds).toBeGreaterThan(0);
  });

  it("costs one card, not the library, when a single body is corrupt", () => {
    save(tower(), "Good");
    save(tower(), "Bad");
    storage.data.set(bodyKey("Bad"), "{ not json");

    const cards = listModels(options());
    expect(cards.ok).toBe(true);
    if (!cards.ok) return;
    expect(cards.value).toHaveLength(2);

    expect(readModel("Good", options()).ok).toBe(true);
    const bad = readModel("Bad", options());
    expect(bad.ok).toBe(false);
    if (bad.ok) return;
    expect(bad.reason).toMatch(/not valid JSON/i);
  });

  it("names the missing model rather than throwing when it was never stored", () => {
    const read = readModel("nobody", options());
    expect(read.ok).toBe(false);
    if (read.ok) return;
    expect(read.reason).toMatch(/nobody/);
  });

  it("removes a body and its card together", () => {
    save(tower(), "Tower");
    expect(removeModel("Tower", options()).ok).toBe(true);
    expect(storage.data.has(bodyKey("Tower"))).toBe(false);
    const cards = listModels(options());
    expect(cards.ok && cards.value).toEqual([]);
  });

  it("duplicates under a new id and a copy name, leaving the original alone", () => {
    save(tower(), "Tower");
    const copy = duplicateModel("Tower", options());
    expect(copy.ok).toBe(true);
    if (!copy.ok) return;
    expect(copy.value.id).not.toBe("Tower");
    expect(copy.value.name).toBe("Tower copy");
    expect(copy.value.blocks).toEqual(tower().blocks);
    expect(readModel("Tower", options()).ok).toBe(true);
  });

  it("renames in place without touching the id, the blocks or the created date", () => {
    save(tower(), "Tower");
    const before = readModel("Tower", options());
    expect(renameModel("Tower", "Two towers, one span", options()).ok).toBe(true);
    const after = readModel("Tower", options());
    expect(after.ok).toBe(true);
    if (!after.ok || !before.ok) return;
    expect(after.value.name).toBe("Two towers, one span");
    expect(after.value.id).toBe("Tower");
    expect(after.value.created).toBe(before.value.created);
    expect(after.value.blocks).toEqual(before.value.blocks);
  });
});

describe("library — storage that is unavailable, full, or over budget", () => {
  it("degrades to a reason instead of breaking the Studio when storage throws on ACCESS", () => {
    storage.throwOnRead = true;
    const cards = listModels(options());
    expect(cards.ok).toBe(false);
    if (cards.ok) return;
    expect(cards.reason).toMatch(/storage unavailable/i);

    const report = storageReport(options());
    expect(report.available).toBe(false);
    expect(report.message).toMatch(/your work will not be kept/i);
  });

  it("survives having no storage object at all", () => {
    const none = { settings: DEFAULT_STUDIO_SETTINGS, storage: undefined };
    expect(listModels(none).ok).toBe(false);
    expect(writeModel(documentOf(tower()), none).ok).toBe(false);
    expect(storageReport(none).available).toBe(false);
  });

  it("refuses a write that would exceed the budget and names the largest models", () => {
    save(tower(3), "Small");
    const big = documentOf(tower(3), { id: "Huge", name: "Huge", thumbnail: `data:image/webp;base64,${"A".repeat(400)}` });
    expect(writeModel(big, options()).ok).toBe(true);

    const over = documentOf(tower(3), {
      id: "Overflow", name: "Overflow", thumbnail: `data:image/webp;base64,${"A".repeat(BUDGET_BYTES)}`,
    });
    const refused = writeModel(over, options());
    expect(refused.ok).toBe(false);
    if (refused.ok) return;
    expect(refused.reason).toMatch(/budget/i);
    expect(refused.reason).toMatch(/Huge/);
  });

  it("evicts nothing when it refuses — every saved model is still there", () => {
    save(tower(3), "Precious");
    const over = documentOf(tower(3), {
      id: "Overflow", name: "Overflow", thumbnail: "x".repeat(BUDGET_BYTES),
    });
    writeModel(over, options());
    expect(readModel("Precious", options()).ok).toBe(true);
    expect(readModel("Overflow", options()).ok).toBe(false);
    const cards = listModels(options());
    expect(cards.ok && cards.value.map(card => card.id)).toEqual(["Precious"]);
  });

  it("reports a real quota rejection as full storage and leaves no orphan body", () => {
    save(tower(3), "First");
    storage.capacity = [...storage.data].reduce((total, [k, v]) => total + k.length + v.length, 0) + 40;
    const refused = writeModel(documentOf(tower(9), { id: "Second", name: "Second" }), options());
    expect(refused.ok).toBe(false);
    if (refused.ok) return;
    expect(refused.reason).toMatch(/full/i);
    expect(storage.data.has(bodyKey("Second"))).toBe(false);
    expect(readModel("First", options()).ok).toBe(true);
  });

  it("reports how much of the budget is left, and orders the offenders by size", () => {
    save(tower(3), "Small");
    writeModel(documentOf(tower(3), { id: "Big", name: "Big", thumbnail: "y".repeat(5000) }), options());
    const report = storageReport(options());
    expect(report.available).toBe(true);
    expect(report.budgetBytes).toBe(BUDGET_BYTES);
    expect(report.usedBytes).toBeGreaterThan(5000);
    expect(report.usedBytes).toBeLessThan(BUDGET_BYTES);
    const cards = listModels(options());
    expect(cards.ok && largestFirst(cards.value).map(card => card.name)).toEqual(["Big", "Small"]);
  });

  it("counts only its own namespace towards the budget", () => {
    storage.data.set("rig.studio.settings.v1", "z".repeat(2000));
    const report = storageReport(options());
    expect(report.usedBytes).toBe(0);
    expect(KEY_PREFIX).toBe("rig.studio.models.v1");
  });
});

describe("library — export and import", () => {
  it("exports one model as text a fresh import reproduces exactly", () => {
    const document = documentOf(tower(), { id: "m1", name: "Tower" });
    const imported = importModel(exportModel(document));
    expect(imported.ok).toBe(true);
    if (!imported.ok) return;
    expect(imported.value).toEqual(document);
  });

  it("exports the whole library as one array file", () => {
    save(tower(3), "Tower");
    save(tower(5), "Taller");
    const text = exportLibrary(options());
    expect(text.ok).toBe(true);
    if (!text.ok) return;
    expect(JSON.parse(text.value)).toHaveLength(2);
    expect(JSON.parse(text.value)[0].schema).toBe("rigmodel/1");
  });

  it("accepts a dropped .json and names the reason for anything else", () => {
    expect(acceptsDroppedFile("Two towers, one span.rigmodel.json").ok).toBe(true);
    expect(acceptsDroppedFile("library.rigmodels.json").ok).toBe(true);
    expect(acceptsDroppedFile("PLAIN.JSON").ok).toBe(true);
    for (const name of ["tower.zip", "photo.png", "notes"]) {
      const refused = acceptsDroppedFile(name);
      expect(refused.ok).toBe(false);
      if (refused.ok) return;
      expect(refused.reason).toMatch(/\.json/i);
      expect(refused.reason).toContain(name);
    }
  });

  it("refuses a corrupt import with a reason rather than a crash", () => {
    const imported = importModel("{ half a file");
    expect(imported.ok).toBe(false);
    if (imported.ok) return;
    expect(imported.reason).toMatch(/not valid JSON/i);
  });

  it("keeps the imported file's own rig snapshot so drift is visible, not applied", () => {
    const document = documentOf(tower(), { id: "m1", name: "Tower" });
    document.rig.modes.vertical.cols = 99;
    const imported = parseModel(serialiseModel(document));
    expect(imported.ok).toBe(true);
    if (!imported.ok) return;
    expect(imported.value.rig.modes.vertical.cols).toBe(99);
    expect(snapshotFileRig().modes.vertical.cols).toBe(7);
  });
});
