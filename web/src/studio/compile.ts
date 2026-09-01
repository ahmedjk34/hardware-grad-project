/**
 * A model becomes an ordered `B` / `R` / `RR` program, or it becomes nothing.
 *
 * `B <col> <row> <level>` carries no orientation. How a block is laid comes from
 * a mode latch — `R` vertical, `RR` horizontal — which homes X and Y, is refused
 * mid-air unless X and Y are homed, and is refused outright when the board is
 * already in that mode. So a mixed-orientation model is not a flat list: it is a
 * partial order (support before supported, then bottom-up) sorted into same-mode
 * runs so the machine homes as few times as it can.
 *
 * Four named steps, each its own function so a test can point at one claim:
 *
 *     supportGraph(model)                 → who must precede whom
 *     orderBlocks(model, graph, mode)     → the Kahn walk, one total order
 *     emitOps(ordered, mode)              → the latch state machine, and text
 *     summarise(ops, settings)            → blocks, latches, levels, ~duration
 *
 * The latch state machine lives only in `emitOps`; the ordering never emits a
 * command. Serial text is built only in `commandText`. No React, no three.js —
 * the part that must be correct is the part that needs no GPU.
 *
 * Determinism is a requirement, not a nicety: the same model compiles to
 * byte-identical output every time, or the tests here and the demo are both
 * worthless. Every collection is built from `model` order and every comparator
 * chain ends in `byId`, so no `Set` or `Map` iteration order can leak out.
 */
import { aabbOf, footprintOverlapArea } from "./geometry";
import type { Model, ModelBlock } from "./model";
import type { ModeName, Shift } from "./coords";
import type { StudioSettings } from "./settings";
import {
  validateModel, type Diagnostic, type RigGeometrySnapshot, type ValidationContext,
} from "./validate";

// ── Program shape (Plan 4 §6.1) ──────────────────────────────────────────────

export interface BuildOp {
  op: "build";
  id: string;
  col: number;
  row: number;
  level: number;
  text: string;
}

export interface ModeOp {
  op: "mode";
  mode: ModeName;
  /** Every latch homes X and Y — the runner warns before the rig moves. */
  cost: "homes X and Y";
  text: string;
}

export type Op = BuildOp | ModeOp;

export interface Stats {
  blocks: number;
  latches: number;
  /** Alias of `latches`, kept for the Plan 4 §6.1 output shape. */
  modeSwitches: number;
  levels: number;
  estimateSeconds: number;
}

export interface Program {
  valid: boolean;
  program: Op[];
  stats: Stats;
  diagnostics: Diagnostic[];
}

export interface CompileOptions {
  /** The live board mode when there is one, `vertical` otherwise (boot state). */
  mode?: ModeName;
  settings: StudioSettings;
  shifts?: Partial<Record<ModeName, Shift>>;
  rigSnapshot?: RigGeometrySnapshot;
  travelHeightMm?: number;
}

const ZERO_STATS: Stats = { blocks: 0, latches: 0, modeSwitches: 0, levels: 0, estimateSeconds: 0 };

// ── Step 1: the support graph ───────────────────────────────────────────────

/**
 * `id → the ids it rests on`. A block at level `L` may not be placed before
 * everything under it: its base Z sits on those blocks' top faces and their
 * footprints overlap its own in machine space. This is the §6.5 support test's
 * partner — footprint area, not a same-cell shortcut — so a horizontal block
 * bridging two vertical stacks depends on both of them.
 *
 * Built by iterating `model.blocks` twice, so the edge set is a pure function of
 * model order; the `Set` values are only ever asked `has` / `size`.
 */
export function supportGraph(
  model: Model, shifts?: Partial<Record<ModeName, Shift>>,
): Map<string, Set<string>> {
  const graph = new Map<string, Set<string>>();
  for (const block of model.blocks) graph.set(block.id, new Set<string>());
  for (const block of model.blocks) {
    if (block.level <= 0) continue;
    const box = aabbOf(block, shifts?.[block.mode]);
    for (const other of model.blocks) {
      if (other.id === block.id) continue;
      const otherBox = aabbOf(other, shifts?.[other.mode]);
      if (Math.abs(otherBox.max.z - box.min.z) > 1e-6) continue;
      if (footprintOverlapArea(otherBox, box) > 1e-6) graph.get(block.id)!.add(other.id);
    }
  }
  return graph;
}

// ── Step 2: the ordering ────────────────────────────────────────────────────

export type Comparator = (a: ModelBlock, b: ModelBlock) => number;
export type OrderTerm = "level" | "currentMode" | "authorIndex" | "cell" | "id";

/**
 * The comparator terms, in priority order. A milestone requirement is a test
 * that goes red when a constraint is removed; "remove a constraint" is then
 * "drop one term from this list", which `orderBlocks` and `comparatorFor` both
 * accept as an argument.
 */
export const ORDER_TERMS: OrderTerm[] = ["level", "currentMode", "authorIndex", "cell", "id"];

/** Bottom-up. A block can never precede its support, so this is also safety. */
export const byLevel = (): Comparator => (a, b) => a.level - b.level;

/**
 * Prefer the mode already latched. STATEFUL: `mode` is the emitter's state at
 * THIS point in the walk, not the starting mode, so `comparatorFor` is rebuilt
 * on every pop. A static preference re-homes on every level band; the
 * interesting bug in this milestone is choosing the greedy same-mode block when
 * support order has made it illegal, which Kahn already prevents by keeping it
 * out of the ready set.
 */
export const byCurrentMode = (mode: ModeName): Comparator => (a, b) =>
  (a.mode === mode ? 0 : 1) - (b.mode === mode ? 0 : 1);

/** The author's order, wherever it is still legal. Absent ids sort last. */
export const byAuthorIndex = (order: string[]): Comparator => {
  const rank = (id: string) => {
    const index = order.indexOf(id);
    return index < 0 ? Number.MAX_SAFE_INTEGER : index;
  };
  return (a, b) => rank(a.id) - rank(b.id);
};

/** Deterministic tie-break: column, then row. */
export const byCell = (): Comparator => (a, b) => (a.col - b.col) || (a.row - b.row);

/** The total order, so ties cannot exist and a sort cannot be non-deterministic. */
export const byId = (): Comparator => (a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);

/** Apply each comparator until one is decisive. */
export const chain = (...comparators: Comparator[]): Comparator => (a, b) => {
  for (const comparator of comparators) {
    const result = comparator(a, b);
    if (result !== 0) return result;
  }
  return 0;
};

export function comparatorFor(
  model: Model, currentMode: ModeName, terms: OrderTerm[] = ORDER_TERMS,
): Comparator {
  const build: Record<OrderTerm, Comparator> = {
    level: byLevel(),
    currentMode: byCurrentMode(currentMode),
    authorIndex: byAuthorIndex(model.order),
    cell: byCell(),
    id: byId(),
  };
  return chain(...terms.map(term => build[term]));
}

/**
 * Kahn's algorithm with a ready-set that is re-sorted on every pop. With n in
 * the hundreds this is O(n² log n) and obviously deterministic, which beats fast
 * here. `byCurrentMode` is recomputed at every pop against the mode the emitter
 * would be in by then.
 */
export function orderBlocks(
  model: Model, graph: Map<string, Set<string>>, startingMode: ModeName,
  terms: OrderTerm[] = ORDER_TERMS,
): ModelBlock[] {
  const byIdMap = new Map(model.blocks.map(block => [block.id, block]));
  const indegree = new Map<string, number>();
  const dependents = new Map<string, string[]>();
  for (const block of model.blocks) {
    indegree.set(block.id, graph.get(block.id)?.size ?? 0);
    dependents.set(block.id, []);
  }
  // Built by iterating model.blocks, so each dependent list is in model order.
  for (const block of model.blocks) {
    for (const supportId of graph.get(block.id) ?? []) {
      dependents.get(supportId)?.push(block.id);
    }
  }

  const ready = model.blocks.filter(block => (indegree.get(block.id) ?? 0) === 0);
  const ordered: ModelBlock[] = [];
  let currentMode = startingMode;

  while (ready.length > 0) {
    ready.sort(comparatorFor(model, currentMode, terms));
    const next = ready.shift()!;
    ordered.push(next);
    currentMode = next.mode;
    for (const dependentId of dependents.get(next.id) ?? []) {
      const remaining = (indegree.get(dependentId) ?? 0) - 1;
      indegree.set(dependentId, remaining);
      if (remaining === 0) ready.push(byIdMap.get(dependentId)!);
    }
  }

  if (ordered.length !== model.blocks.length) {
    throw new Error("compile: the support graph has a cycle — this should be impossible");
  }
  return ordered;
}

// ── Step 3: the latch state machine ─────────────────────────────────────────

/**
 * The one place serial text is built. The runner (M7) and `ProgramView` both
 * consume `op.text`; a second formatter is how a project ends up sending
 * `B 3 2 1 ccw` to a firmware that reads a fourth word as a parse error.
 */
export function commandText(op: Omit<BuildOp, "text"> | Omit<ModeOp, "text">): string {
  if (op.op === "mode") return op.mode === "horizontal" ? "RR" : "R";
  return `B ${op.col} ${op.row} ${op.level}`;
}

/**
 * Walk the ordered blocks; the board's mode is one variable. Emit a `mode` op
 * ONLY on an actual change — the firmware refuses a latch that confirms a state
 * nobody asked for, and a redundant one turns a working program into a failed
 * one. Initial state is the caller's `startingMode` (the live `state.mode` when
 * there is one, `vertical` otherwise, because a board reset returns to vertical).
 */
export function emitOps(ordered: ModelBlock[], startingMode: ModeName): Op[] {
  const ops: Op[] = [];
  let mode = startingMode;
  for (const block of ordered) {
    if (block.mode !== mode) {
      mode = block.mode;
      const spec = { op: "mode" as const, mode, cost: "homes X and Y" as const };
      ops.push({ ...spec, text: commandText(spec) });
    }
    const spec = {
      op: "build" as const, id: block.id, col: block.col, row: block.row, level: block.level,
    };
    ops.push({ ...spec, text: commandText(spec) });
  }
  return ops;
}

// ── Step 4: the estimate ───────────────────────────────────────────────────

export function summarise(ops: Op[], settings: StudioSettings): Stats {
  const builds = ops.filter((op): op is BuildOp => op.op === "build");
  const latches = ops.length - builds.length;
  const levels = new Set(builds.map(op => op.level)).size;
  const estimateSeconds = Math.round(
    builds.length * settings.blockCycleSeconds + latches * settings.latchHomingSeconds,
  );
  return { blocks: builds.length, latches, modeSwitches: latches, levels, estimateSeconds };
}

/** `M:SS`. Callers prepend `~` — this is an estimate, and it says so every time. */
export function formatDuration(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

export function estimateLabel(stats: Stats): string {
  const blocks = `${stats.blocks} block${stats.blocks === 1 ? "" : "s"}`;
  const latches = stats.latches === 1 ? "1 latch" : `${stats.latches} latches`;
  return `${blocks} · ${latches} · ~${formatDuration(stats.estimateSeconds)}`;
}

// ── compile() ──────────────────────────────────────────────────────────────

/**
 * The only public entry point. An invalid model compiles to nothing — a
 * half-program is the single most dangerous artefact this codebase could
 * produce — and the diagnostics come from M3's validator, run here, never
 * re-implemented.
 */
export function compile(model: Model, options: CompileOptions): Program {
  const startingMode: ModeName = options.mode ?? "vertical";
  const context: ValidationContext = {
    mode: startingMode,
    settings: options.settings,
    shifts: options.shifts,
    rigSnapshot: options.rigSnapshot,
    travelHeightMm: options.travelHeightMm,
  };
  const diagnostics = validateModel(model, context);
  if (diagnostics.some(diagnostic => diagnostic.severity === "error")) {
    return { valid: false, program: [], stats: { ...ZERO_STATS }, diagnostics };
  }

  const graph = supportGraph(model, options.shifts);
  const ordered = orderBlocks(model, graph, startingMode);
  const program = emitOps(ordered, startingMode);
  const stats = summarise(program, options.settings);
  return { valid: true, program, stats, diagnostics };
}
