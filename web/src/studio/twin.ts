/**
 * The twin is a claim about the machine, and this module is the whole claim.
 *
 * Plan 4 §9's twin sits beside the live camera on the index page and shows the
 * model filling in as the rig builds it. That is only worth anything if it is
 * TRUE, so every decision about what the twin shows is made here, in a pure
 * function over a fixture `/api/events` payload, and `scene/Twin.tsx` holds no
 * logic at all — it draws the object this returns.
 *
 * TWO RULES, AND THEY ARE THE WHOLE DESIGN.
 *
 * **It never invents state.** A block is `placed` because it is in `confirmed`,
 * and it is in `confirmed` because the SERVER reported `placed` for the build
 * that was in flight. There is no optimistic placement and no "we sent the
 * command so it probably worked". The moment the twin predicts, it stops being
 * a mirror and becomes decoration.
 *
 * **After an abort it stops.** `LOCKED` means the machine's real position is
 * unknown: which block the claw is holding, what fell over, where the arm is.
 * So LOCKED desaturates every block toward `--text-faint`, drops the target
 * entirely, and sets `animating: false`. A twin that keeps cheerfully animating
 * the plan is at its most misleading exactly when misleading is most expensive.
 * "Stops animating" is a FIELD here, asserted in `twin.test.ts`, rather than an
 * absence of a `useFrame` call in a component nobody can test.
 *
 * ONE DEVIATION from the milestone prompt, recorded in docs/STUDIO.md: the
 * signature is `twinScene(state, model, progress, options)` rather than
 * `(state, model, confirmed)`. `progress` IS the confirmed set — plus the
 * rejection the server reported, which arrives by exactly the same route and
 * which the component would otherwise have to remember itself. Remembering is a
 * rule, and rules do not live in components.
 */
import { commandText } from "./compile";
import { MM_PER_CM, SCENE_UNITS_PER_MM, type ModeName } from "./coords";
import { EXAMPLES, exampleById } from "./examples";
import { listModels, readModel, type LibraryOptions } from "./library";
import type { Model, ModelBlock } from "./model";
import { structureOf, type StudioModel } from "./rigmodel";
import { ENVELOPE_Z_CM, easeInOut } from "./view";
import type { StateModel } from "../types";

/** The five appearances of Plan 4 §9.2, and nothing between them. */
export type TwinAppearance = "ghost" | "target" | "building" | "placed" | "rejected";
export type TwinBanner = "none" | "running" | "rejected" | "locked" | "stale";

/** Present, but clearly not real. Plan 4 §9.2's own number; the milestone
 *  prompt's 12% disappears completely against `--void` at twin scale. */
export const GHOST_OPACITY = 0.2;
/** The next block: `--signal`, with a full-opacity edge drawn by the component. */
export const TARGET_OPACITY = 0.45;
export const BUILDING_OPACITY = 0.85;
/** Where LOCKED drags every colour. */
export const DESATURATE_TOKEN = "--text-faint";
/** How far. Not all the way: a completely flat twin reads as a broken canvas. */
export const LOCKED_MIX = 0.85;

/** One descent, start to finish. Illustrative — see `descentOffsetScene`. */
export const DESCENT_MS = 1600;

export interface TwinBlock {
  id: string;
  mode: ModeName;
  col: number;
  row: number;
  level: number;
  appearance: TwinAppearance;
  /** The token this block's material starts from. Tokens only, never a hex. */
  token: string;
  /** How far to lerp `token` toward `--text-faint`. Non-zero only when LOCKED. */
  mix: number;
  opacity: number;
  /** `B 3 2 1`, on the target and the block in flight only. */
  label: string | null;
  /** The server's own words, on a rejected block only. */
  reason: string | null;
}

export interface TwinScene {
  blocks: TwinBlock[];
  banner: TwinBanner;
  /** The banner's detail line: the locked reason, the rejection, or the age. */
  bannerText: string | null;
  animating: boolean;
  desaturate: boolean;
  /** A READ-ONLY mirror of `state.mode`. The twin never latches anything. */
  mode: ModeName | null;
  targetId: string | null;
}

export interface TwinOptions {
  connected: boolean;
  reducedMotion?: boolean;
  /** Seconds since the last state message, shown by the STALE banner. */
  staleSeconds?: number;
}

// ── What the server has actually said ──────────────────────────────────────

/**
 * The confirmed set, folded out of the state stream — never out of a command
 * this browser sent.
 *
 * `pendingId` is the block the server's OWN selection last pointed at, kept
 * across states because `BuildController.build()` clears `selected` the moment
 * a build is PLACED. That clearing is the signal: a `placed` result arriving
 * with a selection still set cannot belong to that selection, so it is ignored.
 * It is what stops a page load that happens to find `last_result: placed` on
 * screen from crediting whichever block is selected at the time.
 *
 * `consumed` de-duplicates the result, which the server repeats in every
 * subsequent state message. RUNNING re-arms it, so two identical results from
 * two different builds are both seen.
 */
export interface TwinProgress {
  /** Block ids the SERVER said were placed, in the order it said them. */
  confirmed: string[];
  pendingId: string | null;
  /** The `last_result` already folded in, as a key. */
  consumed: string | null;
  rejectedId: string | null;
  rejectedReason: string | null;
}

export function emptyTwinProgress(): TwinProgress {
  return { confirmed: [], pendingId: null, consumed: null, rejectedId: null, rejectedReason: null };
}

/** The model block the server's selection, level and mode all point at. */
export function targetBlock(state: StateModel | null, model: Model): ModelBlock | null {
  if (!state || !state.selected) return null;
  const [col, row] = state.selected;
  return model.blocks.find(block =>
    block.mode === state.mode && block.col === col && block.row === row
    && block.level === state.level) ?? null;
}

const resultKey = (state: StateModel): string =>
  `${state.last_result ?? "none"}|${state.last_result_reason ?? ""}`;

export function foldTwinProgress(progress: TwinProgress, state: StateModel | null,
                                 model: Model): TwinProgress {
  if (!state) return progress;
  const target = targetBlock(state, model);
  const pendingId = target?.id ?? progress.pendingId;

  if (state.build_state === "RUNNING") {
    // A build is in flight: arm for its result and drop the previous one.
    return { ...progress, pendingId, consumed: null, rejectedId: null, rejectedReason: null };
  }

  const key = resultKey(state);
  if (key === progress.consumed) return current({ ...progress, pendingId }, target);

  const settled = { ...progress, pendingId, consumed: key };
  if (state.last_result === "placed") {
    // The server clears the selection on PLACED; a selection that survived
    // means this result belongs to some earlier build we cannot attribute.
    if (state.selected !== null || pendingId === null) return current(settled, target);
    return {
      ...settled,
      confirmed: settled.confirmed.includes(pendingId)
        ? settled.confirmed : [...settled.confirmed, pendingId],
      pendingId: null, rejectedId: null, rejectedReason: null,
    };
  }
  if (state.last_result === "rejected") {
    // Nothing moved, so the selection is still the operator's and still ours.
    return { ...settled, rejectedId: pendingId, rejectedReason: state.last_result_reason };
  }
  // `aborted`, or no result at all: confirm nothing. The rig's state is unknown.
  return current({ ...settled, pendingId: null }, target);
}

/** A rejection belongs to the selection it was reported against; the moment the
 *  server points somewhere else, it is history and the block is a ghost again. */
function current(progress: TwinProgress, target: ModelBlock | null): TwinProgress {
  return target && target.id !== progress.rejectedId
    ? { ...progress, rejectedId: null, rejectedReason: null } : progress;
}

// ── The descent ────────────────────────────────────────────────────────────

/** Travel height in scene units, from the firmware's own Z_TRAVEL_CM. */
export const TRAVEL_SCENE_Y = ENVELOPE_Z_CM * MM_PER_CM * SCENE_UNITS_PER_MM;

/**
 * How far above its cell the block in flight is drawn, in scene units.
 *
 * This is an ILLUSTRATION OF A DESCENT, NOT A TELEMETRY READ-OUT. The firmware
 * reports nothing during a build — the Arduino is deaf until `buildBlock()`
 * returns — so nothing here is timed against the real cycle and nothing here
 * should ever be read as the arm's real height. It loops until the result lands.
 */
export function descentOffsetScene(elapsedMs: number, reducedMotion: boolean): number {
  if (reducedMotion) return 0;
  const t = Math.max(0, elapsedMs % DESCENT_MS) / DESCENT_MS;
  return TRAVEL_SCENE_Y * (1 - easeInOut(t));
}

// ── The scene ──────────────────────────────────────────────────────────────

const TOKEN: Record<Exclude<TwinAppearance, "placed">, string> = {
  ghost: DESATURATE_TOKEN,
  target: "--signal",
  building: "--motion",
  rejected: DESATURATE_TOKEN,
};

const OPACITY: Record<TwinAppearance, number> = {
  ghost: GHOST_OPACITY,
  target: TARGET_OPACITY,
  building: BUILDING_OPACITY,
  placed: 1,
  rejected: GHOST_OPACITY,
};

function bannerOf(state: StateModel | null, progress: TwinProgress,
                  options: TwinOptions): TwinBanner {
  // LOCKED first, and deliberately: a locked session that has also lost its
  // socket is still a locked session, and that is the more expensive fact.
  if (state?.build_state === "LOCKED") return "locked";
  if (!state || !options.connected) return "stale";
  if (state.build_state === "RUNNING") return "running";
  // The banner reports the MACHINE, so it does not wait for the rejected block
  // to be one of this model's: the rig refused, and that is worth saying either
  // way. Only the block-level `rejected` appearance needs an identified block.
  if (state.last_result === "rejected") return "rejected";
  return "none";
}

export function twinScene(state: StateModel | null, model: Model, progress: TwinProgress,
                          options: TwinOptions): TwinScene {
  const banner = bannerOf(state, progress, options);
  const locked = banner === "locked";
  const confirmed = new Set(progress.confirmed);
  // After an abort there is no next block: the plan the target belonged to no
  // longer describes anything anybody knows.
  const target = locked ? null : targetBlock(state, model);
  const running = state?.build_state === "RUNNING";

  const blocks = model.blocks.map<TwinBlock>(block => {
    const appearance: TwinAppearance =
      confirmed.has(block.id) ? "placed"
      : locked ? "ghost"
      : block.id === progress.rejectedId && state?.last_result === "rejected" ? "rejected"
      : block.id !== target?.id ? "ghost"
      : running ? "building" : "target";
    return {
      id: block.id, mode: block.mode, col: block.col, row: block.row, level: block.level,
      appearance,
      token: appearance === "placed" ? `--block-${block.colour}` : TOKEN[appearance],
      mix: locked ? LOCKED_MIX : 0,
      opacity: OPACITY[appearance],
      label: appearance === "target" || appearance === "building"
        ? commandText({ op: "build", id: block.id, col: block.col, row: block.row, level: block.level })
        : null,
      reason: appearance === "rejected" ? progress.rejectedReason : null,
    };
  });

  const bannerText =
    banner === "locked" ? state?.locked_reason ?? null
    : banner === "rejected" ? progress.rejectedReason ?? state?.last_result_reason ?? null
    : banner === "stale" ? `${Math.max(0, Math.round(options.staleSeconds ?? 0))}s since the last update`
    : banner === "running" ? state?.command ?? null
    : null;

  return {
    blocks,
    banner,
    bannerText,
    animating: banner === "running" && !options.reducedMotion,
    desaturate: locked,
    mode: state?.mode ?? null,
    targetId: target?.id ?? null,
  };
}

/**
 * Everything the twin's picture depends on, as one string.
 *
 * The pipeline driver notifies on every camera frame, so `/api/events` delivers
 * a fresh state about twenty times a second and almost all of them differ only
 * in `camera_age_ms`. Redrawing a WebGL canvas twenty times a second beside a
 * live MJPEG stream, to draw exactly the same thing, is precisely the cost this
 * panel is not allowed to have. So the panel recomputes the scene only when
 * this signature changes — and WHAT the twin depends on is a rule, which is why
 * it is here and tested rather than inside a `useMemo` nobody can point at.
 */
export function twinSignature(state: StateModel | null, progress: TwinProgress,
                              options: TwinOptions): string {
  const stale = !state || !options.connected;
  return [
    state?.mode, state?.build_state, state?.selected?.join(","), state?.level,
    state?.last_result, state?.last_result_reason, state?.locked_reason, state?.command,
    options.connected, options.reducedMotion,
    // The age only shows while the socket is down, where it is the whole point.
    stale ? Math.round(options.staleSeconds ?? 0) : 0,
    progress.confirmed.join("|"), progress.rejectedId, progress.rejectedReason,
  ].join("~");
}

// ── Choosing what the twin shows ───────────────────────────────────────────

export interface TwinModelChoice { id: string; name: string; blocks: number }

/**
 * The examples first, then whatever is saved, exactly as the Studio's library
 * drawer orders them. Storage that is unavailable costs the saved models and
 * nothing else — the shipped examples are in the bundle and always load.
 */
export function twinModelChoices(options: LibraryOptions = {}): TwinModelChoice[] {
  const examples = EXAMPLES.map(model => ({
    id: model.id, name: model.name, blocks: model.blocks.length,
  }));
  const stored = listModels(options);
  if (!stored.ok) return examples;
  return [...examples, ...stored.value.map(card => ({
    id: card.id, name: card.name, blocks: card.blocks,
  }))];
}

export function loadTwinModel(id: string, options: LibraryOptions = {}): StudioModel | null {
  const example = exampleById(id);
  if (example) return example;
  const stored = readModel(id, options);
  return stored.ok ? stored.value : null;
}

/** The blocks a chosen document contributes to the twin. */
export function twinModelOf(document: StudioModel | null): Model {
  return document ? structureOf(document) : { blocks: [], order: [] };
}
