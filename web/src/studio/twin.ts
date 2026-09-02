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
 * WHAT THE TWIN NOW KNOWS. The firmware announces every build phase, so the
 * twin no longer has to guess at a 40-second silence. `twinScene` takes the
 * `BuildProgress` the store folded out of those events, and the visual state is
 * a pure mapping of the phase id the RIG reported. There is no descent timer
 * any more, and there must never be one again: a local clock that claims the
 * arm is half way down is inventing telemetry the machine never sent.
 *
 * What phase-level truth cannot do is say WHERE the arm is between phases. The
 * firmware reports "lowering to level", not a height, so the twin shows the
 * block at the height the phase implies — carried at travel height, or resting
 * in its cell — plus an activity indicator that says "this is in motion". The
 * indicator is honest about being an indicator; an interpolated height would
 * not be.
 *
 * ONE DEVIATION from the milestone prompt, recorded in docs/STUDIO.md: the
 * signature is `twinScene(state, model, progress, options)` rather than
 * `(state, model, confirmed)`. `progress` IS the confirmed set — plus the
 * rejection the server reported, which arrives by exactly the same route and
 * which the component would otherwise have to remember itself. Remembering is a
 * rule, and rules do not live in components.
 */
import { emptyProgress, type BuildProgress } from "../store";
import { commandText } from "./compile";
import { MM_PER_CM, SCENE_UNITS_PER_MM, type ModeName } from "./coords";
import { EXAMPLES, exampleById } from "./examples";
import { listModels, readModel, type LibraryOptions } from "./library";
import type { Model, ModelBlock } from "./model";
import { structureOf, type StudioModel } from "./rigmodel";
import { ENVELOPE_Z_CM } from "./view";
import type { StateModel } from "../types";

/** The five appearances of Plan 4 §9.2, and nothing between them. */
export type TwinAppearance = "ghost" | "target" | "building" | "placed" | "rejected";
export type TwinBanner = "none" | "running" | "rejected" | "locked" | "stale";

/**
 * What the machine is doing, as one word the scene can be drawn from.
 *
 * Every one of these except `idle`, `target`, `placed`, `rejected` and
 * `aborted` is a PHASE THE FIRMWARE REPORTED. The mapping is one-to-one with
 * `buildStep()`'s phase ids in `build_test_v1.ino`; when the two disagree the
 * sketch is right, and `twin.test.ts` checks every id in the table.
 */
export type TwinPhase =
  | "idle" | "target"
  | "raising-clearance" | "homing-feeder" | "neutralising-claw" | "opening-claw"
  | "lowering-to-ground" | "gripping" | "lifting" | "moving-to-target"
  | "rotating" | "lowering-to-level" | "releasing" | "parking"
  | "placed" | "rejected" | "aborted";

/** The firmware's phase id -> what the twin shows. The whole mapping. */
export const PHASE_BY_ID: Record<string, TwinPhase> = {
  raise_clear: "raising-clearance",
  home_feeder: "homing-feeder",
  neutralise_claw: "neutralising-claw",
  open_claw: "opening-claw",
  lower_to_ground: "lowering-to-ground",
  grip: "gripping",
  lift_block: "lifting",
  move_to_target: "moving-to-target",
  rotate_to_grid: "rotating",
  lower_to_level: "lowering-to-level",
  release: "releasing",
  park_clear: "parking",
  park_home: "parking",
  park_rotation: "parking",
};

/**
 * The phases during which a block is IN THE CLAW.
 *
 * It starts at `gripping` — the jaws closing on the block at the feeder — and
 * ends at `releasing`, which is the phase in which it is let go. Everything
 * before is an empty claw travelling to the feeder; everything after is the
 * rig parking with nothing in it.
 */
const CARRYING: ReadonlySet<TwinPhase> = new Set<TwinPhase>([
  "gripping", "lifting", "moving-to-target", "rotating", "lowering-to-level",
  "releasing",
]);

/**
 * The phases in which the block is above its cell rather than in it.
 *
 * `lowering-to-level` is in this set deliberately: the phase has BEGUN, and
 * the only thing the machine has told us is that it began. Drawing the block
 * part way down would be a claim about a height nobody measured. It drops when
 * the release event arrives, which is a fact.
 */
const ALOFT: ReadonlySet<TwinPhase> = new Set<TwinPhase>([
  "lifting", "moving-to-target", "rotating", "lowering-to-level",
]);

/** Phases that are motion, and so earn the activity indicator. */
const IN_MOTION: ReadonlySet<TwinPhase> = new Set<TwinPhase>([
  "raising-clearance", "homing-feeder", "neutralising-claw", "opening-claw",
  "lowering-to-ground", "gripping", "lifting", "moving-to-target", "rotating",
  "lowering-to-level", "releasing", "parking",
]);

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

  // ── What the rig said it is doing ───────────────────────────────────────
  /** The visual state, mapped from the phase the FIRMWARE reported. */
  phase: TwinPhase;
  /** The rig's own words for it, e.g. "Move XY to the target cell". */
  phaseLabel: string | null;
  /** `8 / 14`, from the wire. Null when no command is in flight. */
  phaseStep: number | null;
  phaseTotal: number | null;
  /** True while a block is in the claw. */
  carrying: boolean;
  /** True once phase 11 confirmed the release. Still not `placed`. */
  released: boolean;
  /** How far above its cell the block in flight sits. Two values only. */
  blockOffset: number;
  /**
   * Draw the activity indicator: the phase is motion and the socket is live.
   *
   * It is an INDICATOR, not a position. The firmware reports phases, not motor
   * counts, so this says "the rig is moving" and never "the rig is here".
   */
  indicator: boolean;
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

// ── Where the block is ─────────────────────────────────────────────────────

/** Travel height in scene units, from the firmware's own Z_TRAVEL_CM. */
export const TRAVEL_SCENE_Y = ENVELOPE_Z_CM * MM_PER_CM * SCENE_UNITS_PER_MM;

/**
 * How far above its cell the block in flight is drawn, in scene units.
 *
 * TWO VALUES, AND NOTHING BETWEEN THEM. The firmware knows two things about Z
 * during a carry: it is at the top switch, or it has been commanded to a level.
 * It reports neither as a number, so this reports neither as a number. A block
 * being carried is drawn at travel height; a block that has been RELEASED —
 * a fact, from phase 11's `status=done` — is drawn in its cell.
 *
 * The old version of this function interpolated a 1.6-second descent off
 * `performance.now()`. It is gone on purpose: it drew the arm at a height
 * nobody had measured, and it looped, so a build that took forty seconds
 * showed twenty-five descents that had never happened. If exact continuous
 * motion is ever wanted, it has to come from throttled firmware telemetry, not
 * from a clock in a browser.
 */
export function phaseOffsetScene(phase: TwinPhase): number {
  return ALOFT.has(phase) ? TRAVEL_SCENE_Y : 0;
}

/** Whether the machine is mid-motion in this phase, for the activity pulse. */
export function phaseIsMoving(phase: TwinPhase): boolean {
  return IN_MOTION.has(phase);
}

/** Whether a block is in the claw in this phase. */
export function phaseIsCarrying(phase: TwinPhase): boolean {
  return CARRYING.has(phase);
}

/**
 * The one function that decides what the machine is doing.
 *
 * Order matters and is the safety argument:
 *
 * 1. **locked/aborted first.** After an abort nothing else is known, so no
 *    phase from before it may be shown as if it were still happening.
 * 2. **the terminal result next**, because `placed` is earned by the OK and by
 *    nothing before it, and `rejected` means nothing moved.
 * 3. **the reported phase**, if there is one.
 * 4. **target**, when the server has a selection but no command in flight.
 * 5. **idle**.
 *
 * An unknown phase id — firmware newer than this browser — falls through to a
 * generic `moving-to-target` rather than to `idle`: "something is happening and
 * I do not know what" is closer to the truth than "nothing is happening".
 */
export function twinPhase(state: StateModel | null, progress: BuildProgress,
                          hasTarget: boolean): TwinPhase {
  if (state?.build_state === "LOCKED" || progress.status === "locked") return "aborted";
  if (progress.status === "aborted") return "aborted";
  if (progress.status === "placed") return "placed";
  if (progress.status === "rejected") return "rejected";
  if (progress.status === "running" || progress.status === "parking") {
    if (progress.phase === null) return "moving-to-target";
    // The release is confirmed the instant phase 11 says `done`, even though
    // the phase id is still `release` until phase 12 begins.
    if (progress.phase === "release" && progress.releaseConfirmed) return "parking";
    return PHASE_BY_ID[progress.phase] ?? "moving-to-target";
  }
  // `accepted` and `validating`: the command is out but the rig has not moved.
  // That is not a phase, and drawing one would be inventing motion.
  if (hasTarget) return "target";
  return "idle";
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
                          options: TwinOptions,
                          build: BuildProgress = emptyProgress()): TwinScene {
  const banner = bannerOf(state, progress, options);
  const locked = banner === "locked";
  const confirmed = new Set(progress.confirmed);
  // After an abort there is no next block: the plan the target belonged to no
  // longer describes anything anybody knows.
  const target = locked ? null : targetBlock(state, model);
  const running = state?.build_state === "RUNNING";
  const phase = twinPhase(state, build, target !== null);
  // A dead socket freezes everything. The last phase seen stays on screen —
  // it is the last thing anyone knows — but nothing moves, because a moving
  // indicator over a dead socket says "still going" and nobody can tell.
  const live = options.connected && !locked && phase !== "aborted";
  const moving = live && phaseIsMoving(phase) && !options.reducedMotion;

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
    // Kept as a field, and still false the instant a session locks: an abort
    // must stop the picture, not merely change its colour.
    animating: moving,
    desaturate: locked,
    mode: state?.mode ?? null,
    targetId: target?.id ?? null,
    phase,
    phaseLabel: phase === "idle" || phase === "target" ? null : build.label,
    phaseStep: build.step,
    phaseTotal: build.total,
    carrying: live && phaseIsCarrying(phase) && !build.releaseConfirmed,
    released: build.releaseConfirmed,
    blockOffset: locked || phase === "aborted" ? 0 : phaseOffsetScene(phase),
    indicator: moving,
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
                              options: TwinOptions,
                              build: BuildProgress = emptyProgress()): string {
  const stale = !state || !options.connected;
  return [
    state?.mode, state?.build_state, state?.selected?.join(","), state?.level,
    state?.last_result, state?.last_result_reason, state?.locked_reason, state?.command,
    options.connected, options.reducedMotion,
    // The age only shows while the socket is down, where it is the whole point.
    stale ? Math.round(options.staleSeconds ?? 0) : 0,
    progress.confirmed.join("|"), progress.rejectedId, progress.rejectedReason,
    // The phase is now part of the picture, so it has to be part of what says
    // the picture changed — otherwise the twin would sit on one frame for a
    // whole build. `eventId` alone would do it, but naming the fields keeps
    // this readable as a statement of what the twin depends on.
    build.phase, build.step, build.status, build.releaseConfirmed, build.eventId,
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
