/**
 * The model library: CRUD over `localStorage`, and nothing that can throw.
 *
 * Storage is genuinely unavailable in a private window, genuinely full at about
 * 5 MB, and in some browsers genuinely throws on ACCESS rather than on write.
 * So every function here returns `Result<T>` and every touch of the store is
 * wrapped. A Studio that dies because storage is disabled is a worse tool than
 * one that says `storage unavailable — your work will not be kept` in an amber
 * strip and carries on.
 *
 * THE CARDS ARE SEPARATE FROM THE BODIES. `rig.studio.models.v1.index` holds
 * the cards — id, name, counts, dates, thumbnail, size — and
 * `rig.studio.models.v1.<id>` holds each model. The drawer then renders without
 * parsing every model, and a single corrupt body costs one card rather than the
 * whole library.
 *
 * THE BUDGET IS 4 MB OF AN ASSUMED 5, AND IT REFUSES. When a write would exceed
 * it, this says so and names the largest models so the drawer can offer to
 * delete them. It never evicts anything by itself: silently deleting an
 * operator's saved work to make room for a save is the kind of behaviour that
 * ends trust in a tool permanently.
 *
 * The seam for Plan 4 §8.7's optional `GET/PUT /api/models` is `LibraryStorage`
 * — a four-method interface this module is written against. A server-backed
 * implementation would satisfy it. That is the whole seam; there is no sync
 * engine here and this milestone makes no network call.
 */
import { compile } from "./compile";
import { DEFAULT_STUDIO_SETTINGS, type StudioSettings } from "./settings";
import {
  fail, ok, parseLibraryFile, parseModel, serialiseLibrary, serialiseModel,
  shiftsOf, structureOf, fromFileRig, newModelId,
  type Result, type StudioModel,
} from "./rigmodel";

export type { Result, StudioModel } from "./rigmodel";

export const KEY_PREFIX = "rig.studio.models.v1";
export const INDEX_KEY = `${KEY_PREFIX}.index`;
export const bodyKey = (id: string): string => `${KEY_PREFIX}.${id}`;

/** 4 MB of an assumed 5. A 320×200 WebP at quality 0.7 is 10–20 kB, so this is
 *  roughly two hundred models — far more than anyone will author by hand. */
export const BUDGET_BYTES = 4 * 1024 * 1024;

export const MODEL_FILE_EXTENSION = ".rigmodel.json";
export const LIBRARY_FILE_EXTENSION = ".rigmodels.json";

/** The seam. `localStorage` satisfies this; so would a server-backed store. */
export interface LibraryStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
  readonly length?: number;
  key?(index: number): string | null;
}

export interface LibraryOptions {
  storage?: LibraryStorage;
  settings?: StudioSettings;
}

export interface ModelCard {
  id: string;
  name: string;
  blocks: number;
  latches: number;
  estimateSeconds: number;
  modified: string;
  /** Size of this model's stored body, in UTF-16 units — what the store bills. */
  bytes: number;
  thumbnail?: string;
}

const STORAGE_UNAVAILABLE = "storage unavailable — your work will not be kept";

/** `localStorage` itself can throw on the property access, not just on use. */
export function browserStorage(): LibraryStorage | undefined {
  try {
    return typeof localStorage === "undefined" ? undefined : localStorage;
  } catch {
    return undefined;
  }
}

const storageOf = (options: LibraryOptions): LibraryStorage | undefined =>
  "storage" in options ? options.storage : browserStorage();
const settingsOf = (options: LibraryOptions): StudioSettings =>
  options.settings ?? DEFAULT_STUDIO_SETTINGS;

/** Every read goes through here, so "storage threw" has exactly one spelling. */
function read(storage: LibraryStorage | undefined, key: string): Result<string | null> {
  if (!storage) return fail(STORAGE_UNAVAILABLE);
  try {
    return ok(storage.getItem(key));
  } catch {
    return fail(STORAGE_UNAVAILABLE);
  }
}

function write(storage: LibraryStorage, key: string, value: string): Result<void> {
  try {
    storage.setItem(key, value);
    return ok(undefined as void);
  } catch (error) {
    // A DOMException is not an Error in every runtime, so this reads the shape
    // rather than the class: a quota rejection must not be reported as a
    // missing store, because the two have completely different remedies.
    const detail = error as { name?: unknown; message?: unknown } | null;
    const quota = /quota|exceed/i.test(`${detail?.name ?? ""} ${detail?.message ?? ""}`);
    return fail(quota
      ? "your browser's storage is full — delete a model, or export the library and clear it"
      : STORAGE_UNAVAILABLE);
  }
}

function drop(storage: LibraryStorage, key: string): void {
  try { storage.removeItem(key); } catch { /* nothing left to do about it */ }
}

/** UTF-16 units of key plus value — the unit browsers actually bill for. */
const entryBytes = (key: string, value: string): number => key.length + value.length;

// ── The index ──────────────────────────────────────────────────────────────

function readIndex(options: LibraryOptions): Result<ModelCard[]> {
  const raw = read(storageOf(options), INDEX_KEY);
  if (!raw.ok) return raw;
  if (raw.value === null) return ok([]);
  try {
    const parsed = JSON.parse(raw.value) as unknown;
    // A corrupt INDEX is the one failure that would cost the whole library, so
    // it degrades to "no cards" and the bodies stay on disk for an export.
    return ok(Array.isArray(parsed) ? parsed.filter(isCard) : []);
  } catch {
    return ok([]);
  }
}

function isCard(value: unknown): value is ModelCard {
  const card = value as ModelCard | null;
  return !!card && typeof card === "object"
    && typeof card.id === "string" && typeof card.name === "string";
}

function writeIndex(storage: LibraryStorage, cards: ModelCard[]): Result<void> {
  return write(storage, INDEX_KEY, JSON.stringify(cards));
}

export function cardOf(document: StudioModel, settings: StudioSettings, bytes: number): ModelCard {
  const program = compile(structureOf(document), {
    settings,
    shifts: shiftsOf(document.rig),
    rigSnapshot: fromFileRig(document.rig),
  });
  return {
    id: document.id,
    name: document.name,
    blocks: document.blocks.length,
    latches: program.stats.latches,
    estimateSeconds: program.stats.estimateSeconds,
    modified: document.modified,
    bytes,
    ...(document.thumbnail === undefined ? {} : { thumbnail: document.thumbnail }),
  };
}

/** Biggest first — what the refusal message and the drawer's delete control
 *  both need, and the only ordering that helps somebody free space. */
export function largestFirst(cards: ModelCard[]): ModelCard[] {
  return [...cards].sort((a, b) => b.bytes - a.bytes || a.name.localeCompare(b.name));
}

// ── The budget ─────────────────────────────────────────────────────────────

export interface StorageReport {
  available: boolean;
  usedBytes: number;
  budgetBytes: number;
  remainingBytes: number;
  message: string | null;
}

/** Everything this module has stored, measured from the store's own keys so a
 *  body orphaned by an interrupted write still counts against the budget. */
function usedBytes(storage: LibraryStorage): number {
  let total = 0;
  const count = storage.length;
  if (typeof count !== "number" || typeof storage.key !== "function") return 0;
  for (let index = 0; index < count; index++) {
    const key = storage.key(index);
    if (key === null || !key.startsWith(KEY_PREFIX)) continue;
    total += entryBytes(key, storage.getItem(key) ?? "");
  }
  return total;
}

export function storageReport(options: LibraryOptions = {}): StorageReport {
  const storage = storageOf(options);
  const empty = {
    available: false, usedBytes: 0, budgetBytes: BUDGET_BYTES,
    remainingBytes: 0, message: STORAGE_UNAVAILABLE,
  };
  if (!storage) return empty;
  try {
    // Probe with a real read: some browsers throw on ACCESS rather than on
    // write, and an empty store would otherwise look like a healthy one.
    storage.getItem(INDEX_KEY);
    const used = usedBytes(storage);
    return {
      available: true,
      usedBytes: used,
      budgetBytes: BUDGET_BYTES,
      remainingBytes: Math.max(0, BUDGET_BYTES - used),
      message: null,
    };
  } catch {
    return empty;
  }
}

const kB = (bytes: number): string => `${Math.max(1, Math.round(bytes / 1024))} kB`;

function budgetRefusal(needed: number, free: number, cards: ModelCard[]): string {
  const worst = largestFirst(cards).slice(0, 3)
    .map(card => `${card.name} (${kB(card.bytes)})`).join(", ");
  const head = `this model needs ${kB(needed)} and only ${kB(free)} of the ${kB(BUDGET_BYTES)} budget is free`;
  return worst
    ? `over budget — ${head}. Largest: ${worst}. Delete one, or export the library.`
    : `over budget — ${head}.`;
}

// ── CRUD ───────────────────────────────────────────────────────────────────

export function listModels(options: LibraryOptions = {}): Result<ModelCard[]> {
  return readIndex(options);
}

export function readModel(id: string, options: LibraryOptions = {}): Result<StudioModel> {
  const raw = read(storageOf(options), bodyKey(id));
  if (!raw.ok) return raw;
  if (raw.value === null) return fail(`no model ${id} is stored — its card may have outlived its body`);
  return parseModel(raw.value);
}

/**
 * Body first, then the index. If the index write fails the body is removed
 * again, so the store never grows a card-less body that would silently eat the
 * budget. The budget check happens BEFORE either write, and refuses.
 */
export function writeModel(
  document: StudioModel, options: LibraryOptions = {},
): Result<{ bytes: number; remaining: number }> {
  const storage = storageOf(options);
  if (!storage) return fail(STORAGE_UNAVAILABLE);
  const cards = readIndex(options);
  if (!cards.ok) return cards;

  const key = bodyKey(document.id);
  const body = serialiseModel(document);
  const bytes = entryBytes(key, body);
  const existing = cards.value.find(card => card.id === document.id);
  const report = storageReport(options);
  if (!report.available) return fail(STORAGE_UNAVAILABLE);
  const free = report.remainingBytes + (existing?.bytes ?? 0);
  if (bytes > free) {
    return fail(budgetRefusal(bytes, free, cards.value.filter(card => card.id !== document.id)));
  }

  const bodyWritten = write(storage, key, body);
  if (!bodyWritten.ok) return fail(bodyWritten.reason);

  const next = [
    cardOf(document, settingsOf(options), bytes),
    ...cards.value.filter(card => card.id !== document.id),
  ];
  const indexWritten = writeIndex(storage, next);
  if (!indexWritten.ok) {
    if (!existing) drop(storage, key);
    return fail(indexWritten.reason);
  }
  return ok({ bytes, remaining: Math.max(0, BUDGET_BYTES - usedBytes(storage)) });
}

export function removeModel(id: string, options: LibraryOptions = {}): Result<void> {
  const storage = storageOf(options);
  if (!storage) return fail(STORAGE_UNAVAILABLE);
  const cards = readIndex(options);
  if (!cards.ok) return cards;
  drop(storage, bodyKey(id));
  return writeIndex(storage, cards.value.filter(card => card.id !== id));
}

export function duplicateModel(id: string, options: LibraryOptions = {}): Result<StudioModel> {
  const source = readModel(id, options);
  if (!source.ok) return source;
  const now = new Date().toISOString();
  const copy: StudioModel = {
    ...source.value,
    id: newModelId(),
    name: `${source.value.name} copy`,
    created: now,
    modified: now,
  };
  const written = writeModel(copy, options);
  return written.ok ? ok(copy) : fail(written.reason);
}

export function renameModel(id: string, name: string, options: LibraryOptions = {}): Result<StudioModel> {
  const source = readModel(id, options);
  if (!source.ok) return source;
  const renamed: StudioModel = {
    ...source.value, name: name.trim() || source.value.name, modified: new Date().toISOString(),
  };
  const written = writeModel(renamed, options);
  return written.ok ? ok(renamed) : fail(written.reason);
}

// ── Export / import ────────────────────────────────────────────────────────

export function exportModel(document: StudioModel): string {
  return serialiseModel(document);
}

export function importModel(text: string): Result<StudioModel> {
  return parseModel(text);
}

/**
 * The whole library as ONE `.rigmodels.json` array, not a zip. A zip would mean
 * either a new dependency in a bundle served off a Pi or a hand-written
 * stored-entry writer, to produce a file harder to inspect, diff and email than
 * the JSON inside it. Recorded as a deliberate deviation in docs/STUDIO.md.
 */
export function exportLibrary(options: LibraryOptions = {}): Result<string> {
  const cards = readIndex(options);
  if (!cards.ok) return cards;
  const documents: StudioModel[] = [];
  for (const card of cards.value) {
    const document = readModel(card.id, options);
    if (document.ok) documents.push(document.value);
  }
  return ok(serialiseLibrary(documents));
}

/**
 * Drag-and-drop gatekeeping. Only `.json`, and a rejection says which file and
 * what was wanted — an import that fails silently on a dropped `.zip` reads as
 * a broken drop target rather than as a refused file.
 */
export function acceptsDroppedFile(name: string): Result<void> {
  if (/\.json$/i.test(name.trim())) return ok(undefined as void);
  return fail(`${name} is not a .json file — models import as ${MODEL_FILE_EXTENSION} and a whole library as ${LIBRARY_FILE_EXTENSION}`);
}

export function importLibrary(text: string): Result<StudioModel[]> {
  return parseLibraryFile(text);
}
