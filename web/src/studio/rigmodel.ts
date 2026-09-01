/**
 * `rigmodel/1` — the file on disk, and the one place a stranger's JSON is
 * allowed to become a Model.
 *
 * A model is a plain document: human-readable, diffable, emailable, and small
 * enough to sit in `localStorage`. Two rules shape everything here.
 *
 * **Nothing throws.** Every entry point returns `Result<T>` with a reason a
 * person can act on. A Studio that dies on a truncated download is a worse tool
 * than one that says which field is missing and carries on, and this is a tool
 * people will use the night before a demo.
 *
 * **The `rig` block is a snapshot, not a dependency.** It records the geometry
 * the model was authored against so that opening a model written before someone
 * edited `config/rig.json` raises M3's `GEOMETRY_DRIFT` warning rather than
 * quietly building the wrong thing. It is never applied and never rewritten on
 * open — `fromFileRig` hands it to the validator, which compares and warns.
 *
 * Import order is fixed and is the whole safety argument: validate the schema,
 * run the migration hook, validate the structure, and only then let the caller
 * warn on drift. A migration that ran after structural validation would be
 * validating the wrong document.
 *
 * ONE DEVIATION, recorded in docs/STUDIO.md: Plan 4 §5's `rig` example lists
 * `cols`, `rows`, `block_cm` and `pitch_cm` per mode. This writes `trim_cm`,
 * `error_offset_cm` and `max_edge_overhang_cm` too, because drift detection
 * compares against `snapshotRigGeometry()` and a snapshot missing those fields
 * would have to invent them — reporting drift on every model the moment anyone
 * sets a non-zero trim.
 */
import type { ModeName } from "./coords";
import type { BlockColour, Model, ModelBlock } from "./model";
import { snapshotRigGeometry, type RigGeometrySnapshot } from "./validate";

export const SCHEMA = "rigmodel/1";

export type Result<T> = { ok: true; value: T } | { ok: false; reason: string };

export const ok = <T>(value: T): Result<T> => ({ ok: true, value });
export const fail = <T = never>(reason: string): Result<T> => ({ ok: false, reason });

// ── The document ───────────────────────────────────────────────────────────

/** One mode's geometry as the file stores it: snake_case, cm, tuples. */
export interface FileRigMode {
  cols: number;
  rows: number;
  block_cm: [number, number, number];
  pitch_cm: [number, number];
  trim_cm: [number, number];
  error_offset_cm: [number, number];
  max_edge_overhang_cm: [number | null, number | null];
}

export interface FileRig {
  workspace_cm: [number, number];
  modes: Record<ModeName, FileRigMode>;
  shift_cm: Record<ModeName, [number, number]>;
}

/**
 * The whole document in memory, minus the `schema` tag that `serialiseModel`
 * writes. Metadata and structure sit side by side rather than nested, so
 * `structureOf` is the only conversion the editor needs.
 */
export interface StudioModel {
  id: string;
  name: string;
  description: string;
  created: string;
  modified: string;
  rig: FileRig;
  blocks: ModelBlock[];
  order: string[];
  /** Rendered from the viewport on save. Absent until a save with a GPU. */
  thumbnail?: string;
}

const MODES: ModeName[] = ["vertical", "horizontal"];
const COLOURS: BlockColour[] = ["white", "red", "orange", "yellow", "green", "blue"];

// ── The rig snapshot, both directions ──────────────────────────────────────

export function toFileRig(snapshot: RigGeometrySnapshot): FileRig {
  const mode = (name: ModeName): FileRigMode => {
    const value = snapshot.modes[name];
    return {
      cols: value.cols,
      rows: value.rows,
      block_cm: [...value.blockCm],
      pitch_cm: [...value.pitchCm],
      trim_cm: [...value.trimCm],
      error_offset_cm: [...value.errorOffsetCm],
      max_edge_overhang_cm: [...value.maxEdgeOverhangCm],
    };
  };
  return {
    workspace_cm: [...snapshot.workspaceCm],
    modes: { vertical: mode("vertical"), horizontal: mode("horizontal") },
    shift_cm: {
      vertical: [...snapshot.modes.vertical.shiftCm],
      horizontal: [...snapshot.modes.horizontal.shiftCm],
    },
  };
}

/** The shape M3's `GEOMETRY_DRIFT` compares, rebuilt from the file. */
export function fromFileRig(rig: FileRig): RigGeometrySnapshot {
  const mode = (name: ModeName) => {
    const value = rig.modes[name];
    return {
      cols: value.cols,
      rows: value.rows,
      blockCm: [...value.block_cm] as [number, number, number],
      pitchCm: [...value.pitch_cm] as [number, number],
      trimCm: [...value.trim_cm] as [number, number],
      errorOffsetCm: [...value.error_offset_cm] as [number, number],
      shiftCm: [...rig.shift_cm[name]] as [number, number],
      maxEdgeOverhangCm: [...value.max_edge_overhang_cm] as [number | null, number | null],
    };
  };
  return {
    workspaceCm: [...rig.workspace_cm] as [number, number],
    modes: { vertical: mode("vertical"), horizontal: mode("horizontal") },
  };
}

export function snapshotFileRig(): FileRig {
  return toFileRig(snapshotRigGeometry());
}

/** The live shift each mode was authored under, as the validator wants it. */
export function shiftsOf(rig: FileRig): Record<ModeName, { x_cm: number; y_cm: number }> {
  return {
    vertical: { x_cm: rig.shift_cm.vertical[0], y_cm: rig.shift_cm.vertical[1] },
    horizontal: { x_cm: rig.shift_cm.horizontal[0], y_cm: rig.shift_cm.horizontal[1] },
  };
}

// ── Document ⇄ editable structure ──────────────────────────────────────────

export function structureOf(document: StudioModel): Model {
  return { blocks: document.blocks, order: document.order };
}

export function newModelId(): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  if (uuid) return uuid;
  return `m${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
}

export function documentOf(model: Model, meta: Partial<StudioModel> = {}): StudioModel {
  const now = new Date().toISOString();
  return {
    id: meta.id ?? newModelId(),
    name: meta.name ?? "Untitled",
    description: meta.description ?? "",
    created: meta.created ?? now,
    modified: meta.modified ?? now,
    rig: meta.rig ?? snapshotFileRig(),
    blocks: model.blocks,
    order: model.order,
    ...(meta.thumbnail === undefined ? {} : { thumbnail: meta.thumbnail }),
  };
}

// ── Serialise ──────────────────────────────────────────────────────────────

/** Two-space JSON, because a model file that cannot be read in a diff is not
 *  actually the plain, inspectable document Plan 4 §5 promises. */
export function serialiseModel(document: StudioModel): string {
  return JSON.stringify({ schema: SCHEMA, ...document }, null, 2);
}

export function serialiseLibrary(documents: StudioModel[]): string {
  return JSON.stringify(documents.map(item => ({ schema: SCHEMA, ...item })), null, 2);
}

// ── The migration hook ─────────────────────────────────────────────────────

export type Migration = (document: Record<string, unknown>) => Record<string, unknown>;

/**
 * Version 1 is the only version today; the hook exists so version 2 is not a
 * crisis. A migration returns a document tagged with a LATER schema, and
 * `migrate` keeps applying until it reaches `SCHEMA` or runs out of hops.
 */
export const MIGRATIONS: Record<string, Migration> = {
  [SCHEMA]: document => document,
};

const MAX_MIGRATION_HOPS = 8;

export function migrate(document: Record<string, unknown>): Result<Record<string, unknown>> {
  let current = document;
  for (let hop = 0; hop <= MAX_MIGRATION_HOPS; hop++) {
    const schema = current.schema;
    if (typeof schema !== "string") return fail("this file has no `schema` tag — it is not a rigmodel document");
    const migration = MIGRATIONS[schema];
    if (!migration) return fail(`unknown model schema ${schema}; this Studio writes ${SCHEMA}`);
    if (schema === SCHEMA) return ok(current);
    current = migration(current);
  }
  return fail(`migration from ${document.schema} did not reach ${SCHEMA}`);
}

// ── Schema validation ──────────────────────────────────────────────────────

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const isFinite2 = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);

function numberPair(value: unknown): [number, number] | null {
  return Array.isArray(value) && value.length === 2 && value.every(isFinite2)
    ? [value[0] as number, value[1] as number] : null;
}

function parseRig(value: unknown): Result<FileRig> {
  if (!isObject(value)) return fail("this file has no `rig` snapshot — the geometry it was designed for is unknown");
  const workspace = numberPair(value.workspace_cm);
  if (!workspace) return fail("the `rig` snapshot has no valid `workspace_cm` pair");
  if (!isObject(value.modes) || !isObject(value.shift_cm))
    return fail("the `rig` snapshot is missing `modes` or `shift_cm`");
  const modes = {} as Record<ModeName, FileRigMode>;
  const shifts = {} as Record<ModeName, [number, number]>;
  for (const name of MODES) {
    const mode = (value.modes as Record<string, unknown>)[name];
    const shift = numberPair((value.shift_cm as Record<string, unknown>)[name]);
    if (!isObject(mode)) return fail(`the \`rig\` snapshot is missing the ${name} mode`);
    if (!shift) return fail(`the \`rig\` snapshot has no valid ${name} \`shift_cm\` pair`);
    const block = mode.block_cm;
    const pitch = numberPair(mode.pitch_cm);
    if (!isFinite2(mode.cols) || !isFinite2(mode.rows))
      return fail(`the \`rig\` snapshot's ${name} mode has no cols/rows`);
    if (!Array.isArray(block) || block.length !== 3 || !block.every(isFinite2) || !pitch)
      return fail(`the \`rig\` snapshot's ${name} mode has no valid block_cm/pitch_cm`);
    modes[name] = {
      cols: mode.cols, rows: mode.rows,
      block_cm: [block[0] as number, block[1] as number, block[2] as number],
      pitch_cm: pitch,
      trim_cm: numberPair(mode.trim_cm) ?? [0, 0],
      error_offset_cm: numberPair(mode.error_offset_cm) ?? [0, 0],
      max_edge_overhang_cm: overhangPair(mode.max_edge_overhang_cm),
    };
    shifts[name] = shift;
  }
  return ok({ workspace_cm: workspace, modes, shift_cm: shifts });
}

/** `null` means "do not check this edge at all", exactly as rig/config.py does. */
function overhangPair(value: unknown): [number | null, number | null] {
  const each = (item: unknown) => (isFinite2(item) ? item : null);
  return Array.isArray(value) && value.length === 2
    ? [each(value[0]), each(value[1])] : [null, null];
}

function parseBlock(value: unknown, index: number): Result<ModelBlock> {
  const at = `block ${index + 1}`;
  if (!isObject(value)) return fail(`${at} is not an object`);
  const id = typeof value.id === "string" && value.id.length > 0 ? value.id : null;
  if (!id) return fail(`${at} has no id`);
  if (value.mode !== "vertical" && value.mode !== "horizontal")
    return fail(`${id} has no mode — every block is laid by a vertical or horizontal grid`);
  for (const key of ["col", "row", "level"] as const) {
    if (!Number.isInteger(value[key])) return fail(`${id} has a non-integer ${key}`);
  }
  const colour = COLOURS.includes(value.colour as BlockColour) ? value.colour as BlockColour : "white";
  return ok({
    id, mode: value.mode,
    col: value.col as number, row: value.row as number, level: value.level as number,
    colour,
  });
}

/**
 * The author's order, repaired rather than refused. A dropped id or a missing
 * one is a file that has been edited by hand or written by an older Studio; it
 * is not a reason to lose the geometry. Unknown ids go, missing ids go on the
 * end in block order, so the result is always a permutation of the blocks.
 */
export function repairOrder(blocks: ModelBlock[], order: unknown): string[] {
  const ids = blocks.map(block => block.id);
  const known = new Set(ids);
  const seen = new Set<string>();
  const kept = (Array.isArray(order) ? order : []).filter((id): id is string => {
    if (typeof id !== "string" || !known.has(id) || seen.has(id)) return false;
    seen.add(id);
    return true;
  });
  return [...kept, ...ids.filter(id => !seen.has(id))];
}

// ── parse ──────────────────────────────────────────────────────────────────

/** Schema, then migration, then structure. Never the other way round. */
export function parseModelDocument(value: unknown): Result<StudioModel> {
  if (!isObject(value)) return fail("this file is not a rigmodel document — the top level is not an object");
  const migrated = migrate(value);
  if (!migrated.ok) return migrated;
  const document = migrated.value;

  if (!Array.isArray(document.blocks)) return fail("this file has no `blocks` array");
  const blocks: ModelBlock[] = [];
  for (let index = 0; index < document.blocks.length; index++) {
    const block = parseBlock(document.blocks[index], index);
    if (!block.ok) return fail(block.reason);
    if (blocks.some(item => item.id === block.value.id)) return fail(`${block.value.id} appears twice`);
    blocks.push(block.value);
  }

  const rig = parseRig(document.rig);
  if (!rig.ok) return rig;

  const text = (key: string, fallback: string) =>
    typeof document[key] === "string" ? document[key] as string : fallback;
  const now = new Date(0).toISOString();
  return ok({
    id: text("id", newModelId()),
    name: text("name", "Untitled"),
    description: text("description", ""),
    created: text("created", now),
    modified: text("modified", now),
    rig: rig.value,
    blocks,
    order: repairOrder(blocks, document.order),
    ...(typeof document.thumbnail === "string" ? { thumbnail: document.thumbnail } : {}),
  });
}

function readJson(text: string): Result<unknown> {
  try {
    return ok(JSON.parse(text) as unknown);
  } catch {
    return fail("this file is not valid JSON — it may have been truncated or edited by hand");
  }
}

export function parseModel(text: string): Result<StudioModel> {
  const json = readJson(text);
  return json.ok ? parseModelDocument(json.value) : json;
}

/** A `.rigmodels.json` array, or a single `.rigmodel.json` — both are accepted,
 *  because an operator dragging one file in should not have to know which. */
export function parseLibraryFile(text: string): Result<StudioModel[]> {
  const json = readJson(text);
  if (!json.ok) return json;
  if (!Array.isArray(json.value)) {
    const single = parseModelDocument(json.value);
    return single.ok ? ok([single.value]) : fail(single.reason);
  }
  const models: StudioModel[] = [];
  for (let index = 0; index < json.value.length; index++) {
    const parsed = parseModelDocument(json.value[index]);
    if (!parsed.ok) return fail(`model ${index + 1} of ${json.value.length}: ${parsed.reason}`);
    models.push(parsed.value);
  }
  return ok(models);
}
