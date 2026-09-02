/**
 * Plan 4 §9.2's table, one test per row, driven by fixture `/api/events`
 * payloads. The rendering needs no GPU test; this mapping is where the bugs
 * that matter live, so every claim the twin makes about the machine is made
 * here and asserted here.
 */
import { describe, expect, it } from "vitest";
import {
  BUILDING_OPACITY, DESATURATE_TOKEN, GHOST_OPACITY, LOCKED_MIX, PHASE_BY_ID,
  DESCENT_CLAMP, TARGET_OPACITY, TRAVEL_SCENE_Y, descentProgress,
  emptyTwinProgress, foldTwinProgress, loadTwinModel, phaseOffsetScene,
  targetBlock, twinModelChoices, twinPhase, twinScene, twinSignature,
  type TwinPhase, type TwinProgress,
} from "./twin";
import * as twinModule from "./twin";
import { createConsoleStore, emptyProgress, type BuildProgress } from "../store";
import type { ServerEvent } from "../types";
import { EXAMPLES } from "./examples";
import { structureOf } from "./rigmodel";
import type { Model } from "./model";
import type { StateModel } from "../types";
import fixtures from "./twin.fixtures.json";
import { testState } from "../test-state";

const TOWER = EXAMPLES[0];
const model: Model = structureOf(TOWER);
/** TOWER is one vertical cell, five levels: t1 at level 0 … t5 at level 4. */
const CELL: [number, number] = [TOWER.blocks[0].col, TOWER.blocks[0].row];

const state = (overrides: Partial<StateModel> = {}): StateModel => testState({
  mode: "vertical", cols: 7, rows: 6, calibrated: true, selected: null,
  ...overrides,
});

/** The server has selected TOWER's ground block and nothing has run yet. */
const armed = (overrides: Partial<StateModel> = {}) =>
  state({ selected: CELL, level: 0, command: `B ${CELL[0]} ${CELL[1]} 0`, ...overrides });

const live = { connected: true };
const progressWith = (overrides: Partial<TwinProgress> = {}): TwinProgress =>
  ({ ...emptyTwinProgress(), ...overrides });

const byId = <T extends { id: string }>(blocks: T[], id: string) => blocks.find(block => block.id === id)!;

/** A BuildProgress as the store would hold it after one `build_step`. */
const at = (overrides: Partial<BuildProgress> = {}): BuildProgress =>
  ({ ...emptyProgress(), status: "running", commandSeq: 1, step: 1, total: 14,
     eventId: 10, ...overrides });


describe("twinScene — Plan 4 §9.2, row by row", () => {
  it("a model is loaded: every remaining block is a ghost and nothing animates", () => {
    const scene = twinScene(state(), model, emptyTwinProgress(), live);
    expect(scene.blocks).toHaveLength(model.blocks.length);
    expect(scene.blocks.every(block => block.appearance === "ghost")).toBe(true);
    expect(scene.blocks.every(block => block.token === DESATURATE_TOKEN)).toBe(true);
    expect(scene.blocks.every(block => block.opacity === GHOST_OPACITY)).toBe(true);
    expect(scene.banner).toBe("none");
    expect(scene.animating).toBe(false);
    expect(scene.desaturate).toBe(false);
  });

  it("the next command is chosen: that block is the target, labelled with its command", () => {
    const scene = twinScene(armed(), model, emptyTwinProgress(), live);
    const target = byId(scene.blocks, "t1");
    expect(target.appearance).toBe("target");
    expect(target.label).toBe(`B ${CELL[0]} ${CELL[1]} 0`);
    expect(target.token).toBe("--signal");
    expect(target.opacity).toBe(TARGET_OPACITY);
    expect(scene.targetId).toBe("t1");
    // Everything else is still only a plan.
    expect(scene.blocks.filter(block => block.appearance === "ghost")).toHaveLength(4);
    // Idle, the target is static: the console owns the one licensed loop.
    expect(scene.animating).toBe(false);
  });

  it("RUNNING: the target turns --motion and the banner names the build", () => {
    const scene = twinScene(armed({ build_state: "RUNNING" }), model,
                            emptyTwinProgress(), live,
                            at({ phase: "move_to_target", step: 8 }));
    const target = byId(scene.blocks, "t1");
    expect(target.appearance).toBe("building");
    expect(target.token).toBe("--motion");
    expect(target.opacity).toBe(BUILDING_OPACITY);
    expect(scene.banner).toBe("running");
    expect(scene.animating).toBe(true);
    expect(scene.phase).toBe("moving-to-target");
  });

  it("RUNNING with no phase reported yet: building, but NOTHING moves", () => {
    // The command is out and the board has not announced a phase. Animating
    // here would be the twin inventing motion it has no evidence for.
    const scene = twinScene(armed({ build_state: "RUNNING" }), model,
                            emptyTwinProgress(), live);
    expect(byId(scene.blocks, "t1").appearance).toBe("building");
    expect(scene.animating).toBe(false);
    expect(scene.indicator).toBe(false);
    expect(scene.phaseLabel).toBeNull();
  });

  it("freezes on a dead socket rather than animating over one", () => {
    const scene = twinScene(armed({ build_state: "RUNNING" }), model,
                            emptyTwinProgress(), { connected: false },
                            at({ phase: "move_to_target", step: 8 }));
    // The last phase seen stays on screen — it is the last thing known — but
    // the indicator stops, because "still going" is exactly what nobody knows.
    expect(scene.phase).toBe("moving-to-target");
    expect(scene.animating).toBe(false);
    expect(scene.indicator).toBe(false);
  });

  it("RUNNING under reduced motion: still building, but nothing moves", () => {
    const scene = twinScene(armed({ build_state: "RUNNING" }), model, emptyTwinProgress(),
                            { connected: true, reducedMotion: true });
    expect(byId(scene.blocks, "t1").appearance).toBe("building");
    expect(scene.animating).toBe(false);
  });

  it("placed: the block snaps solid in its authored colour — and ONLY from the server's set", () => {
    const confirmed = twinScene(state({ last_result: "placed" }), model,
                                progressWith({ confirmed: ["t1"] }), live);
    const placed = byId(confirmed.blocks, "t1");
    expect(placed.appearance).toBe("placed");
    expect(placed.token).toBe(`--block-${TOWER.blocks[0].colour}`);
    expect(placed.opacity).toBe(1);

    // The same payload with nothing confirmed places nothing: no optimism.
    const optimistic = twinScene(armed({ build_state: "RUNNING" }), model, emptyTwinProgress(), live);
    expect(optimistic.blocks.some(block => block.appearance === "placed")).toBe(false);
  });

  it("rejected: the block returns to a ghost outlined --motion, carrying the reason", () => {
    const scene = twinScene(
      armed({ last_result: "rejected", last_result_reason: "cell occupied" }), model,
      progressWith({ rejectedId: "t1", rejectedReason: "cell occupied" }), live);
    const rejected = byId(scene.blocks, "t1");
    expect(rejected.appearance).toBe("rejected");
    expect(rejected.reason).toBe("cell occupied");
    expect(rejected.opacity).toBe(GHOST_OPACITY);
    expect(scene.banner).toBe("rejected");
    expect(scene.bannerText).toBe("cell occupied");
    expect(scene.animating).toBe(false);
  });

  it("rejected: the banner reports the machine even for a cell outside this model", () => {
    const scene = twinScene(
      state({ selected: [1, 1], last_result: "rejected", last_result_reason: "cell occupied" }),
      model, emptyTwinProgress(), live);
    expect(scene.banner).toBe("rejected");
    expect(scene.bannerText).toBe("cell occupied");
    // ...but nothing in the model is marked rejected, because nothing was.
    expect(scene.blocks.every(block => block.appearance === "ghost")).toBe(true);
  });

  it("LOCKED: every block desaturates toward --text-faint under a red plate", () => {
    const scene = twinScene(
      armed({ build_state: "LOCKED", locked_reason: "build aborted", last_result: "aborted" }),
      model, progressWith({ confirmed: ["t1"] }), live);
    expect(scene.banner).toBe("locked");
    expect(scene.bannerText).toBe("build aborted");
    expect(scene.desaturate).toBe(true);
    expect(scene.blocks.every(block => block.mix === LOCKED_MIX)).toBe(true);
  });

  it("LOCKED: the twin STOPS animating and claims nothing beyond what was confirmed", () => {
    const scene = twinScene(
      armed({ build_state: "LOCKED", locked_reason: "build aborted" }),
      model, progressWith({ confirmed: ["t1"] }), live);
    // The one assertion this milestone exists for.
    expect(scene.animating).toBe(false);
    // After an abort the machine's state is unknown: no target, nothing in
    // flight, and only the blocks the server already confirmed stay solid.
    expect(scene.targetId).toBeNull();
    expect(scene.blocks.map(block => block.appearance))
      .toEqual(["placed", "ghost", "ghost", "ghost", "ghost"]);
  });

  it("LOCKED beats a dropped socket: the more expensive fact wins the banner", () => {
    const scene = twinScene(armed({ build_state: "LOCKED", locked_reason: "held block" }),
                            model, emptyTwinProgress(), { connected: false, staleSeconds: 9 });
    expect(scene.banner).toBe("locked");
    expect(scene.animating).toBe(false);
  });
});

describe("twinScene — when the socket drops", () => {
  it("freezes exactly as it is, stops animating, and reports the age", () => {
    const running = armed({ build_state: "RUNNING" });
    const frozen = twinScene(running, model, emptyTwinProgress(),
                             { connected: false, staleSeconds: 12 });
    expect(frozen.banner).toBe("stale");
    expect(frozen.bannerText).toBe("12s since the last update");
    expect(frozen.animating).toBe(false);
    // Frozen, not cleared: the block in flight is still shown where it was.
    expect(byId(frozen.blocks, "t1").appearance).toBe("building");
    expect(frozen.blocks).toHaveLength(model.blocks.length);
    expect(frozen.desaturate).toBe(false);
  });

  it("no state at all is stale, not empty", () => {
    const scene = twinScene(null, model, emptyTwinProgress(), { connected: false });
    expect(scene.banner).toBe("stale");
    expect(scene.mode).toBeNull();
    expect(scene.blocks.every(block => block.appearance === "ghost")).toBe(true);
  });
});

describe("twinScene — the mode mirror", () => {
  it("mirrors state.mode and never a local one", () => {
    expect(twinScene(state({ mode: "horizontal" }), model, emptyTwinProgress(), live).mode)
      .toBe("horizontal");
  });

  it("a selection in the other mode is not this model's target", () => {
    const scene = twinScene(armed({ mode: "horizontal" }), model, emptyTwinProgress(), live);
    expect(scene.targetId).toBeNull();
    expect(scene.blocks.every(block => block.appearance === "ghost")).toBe(true);
  });

  it("an empty model renders nothing at all", () => {
    expect(twinScene(state(), { blocks: [], order: [] }, emptyTwinProgress(), live).blocks)
      .toEqual([]);
  });
});

describe("targetBlock", () => {
  it("matches mode, cell and level together", () => {
    expect(targetBlock(armed({ level: 2 }), model)?.id).toBe("t3");
    expect(targetBlock(armed({ level: 9 }), model)).toBeNull();
    expect(targetBlock(state(), model)).toBeNull();
  });
});

describe("foldTwinProgress — confirmation comes from the server or not at all", () => {
  it("confirms the block only once the server has cleared the selection", () => {
    let progress = emptyTwinProgress();
    progress = foldTwinProgress(progress, armed(), model);
    progress = foldTwinProgress(progress, armed({ build_state: "RUNNING" }), model);
    expect(progress.confirmed).toEqual([]);
    // BuildController clears `selected` on PLACED; that is how we know which
    // block the result belongs to.
    progress = foldTwinProgress(progress, state({ last_result: "placed" }), model);
    expect(progress.confirmed).toEqual(["t1"]);
  });

  it("is idempotent: the same state folded twice confirms once", () => {
    let progress = emptyTwinProgress();
    for (const payload of [armed(), armed({ build_state: "RUNNING" }),
                           state({ last_result: "placed" }), state({ last_result: "placed" })]) {
      progress = foldTwinProgress(progress, payload, model);
    }
    expect(progress.confirmed).toEqual(["t1"]);
  });

  it("confirms a second, different block after its own RUNNING pass", () => {
    let progress = emptyTwinProgress();
    const second = armed({ level: 1, command: `B ${CELL[0]} ${CELL[1]} 1` });
    for (const payload of [armed(), armed({ build_state: "RUNNING" }),
                           state({ last_result: "placed" }),
                           second, { ...second, build_state: "RUNNING" as const },
                           state({ last_result: "placed" })]) {
      progress = foldTwinProgress(progress, payload, model);
    }
    expect(progress.confirmed).toEqual(["t1", "t2"]);
  });

  it("never confirms a block a fresh page load merely finds selected", () => {
    // A `placed` result already on screen when the console connects belongs to
    // a build this session never saw; the selection proves it is not this one.
    const progress = foldTwinProgress(emptyTwinProgress(),
                                      armed({ last_result: "placed" }), model);
    expect(progress.confirmed).toEqual([]);
  });

  it("records a rejection against the selection the server kept", () => {
    let progress = foldTwinProgress(emptyTwinProgress(), armed(), model);
    progress = foldTwinProgress(progress, armed({ build_state: "RUNNING" }), model);
    progress = foldTwinProgress(progress,
      armed({ last_result: "rejected", last_result_reason: "no block detected" }), model);
    expect(progress.confirmed).toEqual([]);
    expect(progress.rejectedId).toBe("t1");
    expect(progress.rejectedReason).toBe("no block detected");
  });

  it("an abort confirms nothing — the machine's state is unknown", () => {
    let progress = foldTwinProgress(emptyTwinProgress(), armed(), model);
    progress = foldTwinProgress(progress, armed({ build_state: "RUNNING" }), model);
    progress = foldTwinProgress(progress, state({
      build_state: "LOCKED", locked_reason: "aborted", last_result: "aborted",
    }), model);
    expect(progress.confirmed).toEqual([]);
    expect(progress.pendingId).toBeNull();
  });

  it("a new selection clears the previous rejection", () => {
    let progress = progressWith({ rejectedId: "t1", rejectedReason: "no block detected" });
    progress = foldTwinProgress(progress, armed({ level: 1 }), model);
    expect(progress.rejectedId).toBeNull();
  });
});

describe("the phase mapping — every id the firmware can send", () => {
  // The keys of this table are the phase ids in `buildStep()`'s call sites in
  // build_test_v1.ino. If the sketch grows a phase, this list fails first.
  const EXPECTED: Record<string, TwinPhase> = {
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

  it("maps all fourteen firmware phases and invents none", () => {
    expect(PHASE_BY_ID).toEqual(EXPECTED);
  });

  it.each(Object.entries(EXPECTED))("%s becomes %s", (id, expected) => {
    expect(twinPhase(armed({ build_state: "RUNNING" }),
                     at({ phase: id }), true)).toBe(expected);
  });

  it("shows the release as parking once phase 11 confirms it", () => {
    // The phase id is still `release` until phase 12 begins, but the block has
    // left the claw and the twin must stop showing it there.
    expect(twinPhase(armed({ build_state: "RUNNING" }),
                     at({ phase: "release", releaseConfirmed: true }), true))
      .toBe("parking");
  });

  it("calls an unknown phase id motion, not idle", () => {
    // Firmware newer than this browser. "Something is happening and I do not
    // know what" beats "nothing is happening".
    expect(twinPhase(armed({ build_state: "RUNNING" }),
                     at({ phase: "polish_the_block" }), true))
      .toBe("moving-to-target");
  });

  it("never shows a phase for a command that has not moved yet", () => {
    for (const status of ["accepted", "validating"] as const) {
      expect(twinPhase(armed(), at({ status, phase: null }), true)).toBe("target");
    }
  });

  it("shows aborted over everything, whatever phase was last seen", () => {
    expect(twinPhase(state({ build_state: "LOCKED" }),
                     at({ phase: "move_to_target" }), true)).toBe("aborted");
    expect(twinPhase(armed(), at({ status: "locked", phase: "grip" }), true))
      .toBe("aborted");
    expect(twinPhase(armed(), at({ status: "aborted", phase: "grip" }), true))
      .toBe("aborted");
  });
});

describe("the block's height — two values, both reported", () => {
  it("carries at travel height and rests in the cell, and nothing between", () => {
    const carried: TwinPhase[] = ["lifting", "moving-to-target", "rotating",
                                  "lowering-to-level"];
    for (const phase of carried) expect(phaseOffsetScene(phase)).toBe(TRAVEL_SCENE_Y);
    const grounded: TwinPhase[] = ["idle", "target", "raising-clearance",
                                   "homing-feeder", "gripping", "releasing",
                                   "parking", "placed", "aborted"];
    for (const phase of grounded) expect(phaseOffsetScene(phase)).toBe(0);
  });

  it("no longer exports the invented descent it used to", () => {
    // The looping 1.6-second `descentOffsetScene(elapsed, reducedMotion)` had a
    // made-up duration and completed on its own. `descentProgress` replaced it
    // and is a different thing — see the block below for what makes it one.
    expect("descentOffsetScene" in twinModule).toBe(false);
    expect("DESCENT_MS" in twinModule).toBe(false);
  });
});

/**
 * The descent is the ONE place a clock says anything, so it gets its own
 * fence. The property that matters is not "it animates" — it is that it
 * CANNOT FINISH. Only the real release event puts the block in its cell.
 */
describe("the estimated descent — anchored, sized and clamped", () => {
  it("needs an estimate from the firmware, and does nothing without one", () => {
    expect(descentProgress(1000, null)).toBe(0);
    expect(descentProgress(1000, 0)).toBe(0);
    expect(descentProgress(1000, -5)).toBe(0);
  });

  it("runs from 0 toward the clamp over the firmware's own duration", () => {
    // 2570 ms is what the sketch computes for a full-travel Z descent:
    // 1350 steps x 1.9 ms/step + DIR_SETTLE_MS.
    expect(descentProgress(0, 2570)).toBe(0);
    expect(descentProgress(642, 2570)).toBeCloseTo(0.25, 2);
    expect(descentProgress(1285, 2570)).toBeCloseTo(0.5, 2);
    expect(descentProgress(2313, 2570)).toBeCloseTo(0.9, 2);
  });

  it("NEVER reaches the cell, however long it is left running", () => {
    // The estimate is a floor: the real move can only take longer. So running
    // out of time means the rig is slower than predicted, not that it landed.
    for (const elapsed of [2570, 3000, 10_000, 60_000, 1e9]) {
      expect(descentProgress(elapsed, 2570)).toBe(DESCENT_CLAMP);
      expect(descentProgress(elapsed, 2570)).toBeLessThan(1);
    }
    expect(DESCENT_CLAMP).toBeLessThan(1);
  });

  it("is offered only while lowering to the level, and only with an estimate", () => {
    const lowering = (overrides = {}) => twinScene(
      armed({ build_state: "RUNNING" }), model, emptyTwinProgress(), live,
      at({ phase: "lower_to_level", step: 10, etaMs: 2570,
           receivedAt: 1_000, ...overrides }));

    expect(lowering().descent).toEqual({ etaMs: 2570, since: 1_000 });
    // No estimate from the firmware: no animation, not a guessed duration.
    expect(lowering({ etaMs: null }).descent).toBeNull();
    // Every other phase carries no descent at all.
    for (const phase of ["move_to_target", "grip", "release", "park_home"]) {
      expect(lowering({ phase }).descent).toBeNull();
    }
  });

  it("stops offering a descent the moment the socket dies or the rig aborts", () => {
    const build = at({ phase: "lower_to_level", step: 10, etaMs: 2570,
                       receivedAt: 1_000 });
    expect(twinScene(armed({ build_state: "RUNNING" }), model, emptyTwinProgress(),
                     { connected: false }, build).descent).toBeNull();
    expect(twinScene(state({ build_state: "LOCKED" }), model, emptyTwinProgress(),
                     live, build).descent).toBeNull();
  });

  it("redraws for a new descent, because the signature notices one", () => {
    const sign = (build: Parameters<typeof twinSignature>[3]) =>
      twinSignature(armed({ build_state: "RUNNING" }), emptyTwinProgress(), live, build);
    const base = sign(at({ phase: "lower_to_level", step: 10 }));
    expect(sign(at({ phase: "lower_to_level", step: 10, etaMs: 2570 })))
      .not.toBe(base);
  });
});

describe("choosing what the twin shows", () => {
  it("lists the built-in examples even with no storage at all", () => {
    const choices = twinModelChoices({ storage: undefined });
    expect(choices.map(choice => choice.id)).toEqual(EXAMPLES.map(example => example.id));
  });

  it("loads an example by id and refuses an unknown one", () => {
    expect(loadTwinModel(TOWER.id, { storage: undefined })?.blocks).toHaveLength(5);
    expect(loadTwinModel("nope", { storage: undefined })).toBeNull();
  });
});

/**
 * The same mapping, fed what the SERVER actually sends: sequences recorded from
 * `web.app` against `MockBoard` by `python/tools/dump_twin_states.py`, one entry
 * per state the console's WebSocket would have delivered. Every claim above
 * about `selected`, `last_result` and the RUNNING window is checked here against
 * the real thing rather than against a payload this file invented.
 */
describe("against recorded /api/events sessions", () => {
  const session = (name: keyof typeof fixtures.sessions) =>
    fixtures.sessions[name].states as unknown as StateModel[];
  const events = (name: keyof typeof fixtures.sessions) =>
    fixtures.sessions[name].events as unknown as ServerEvent[];
  const play = (states: StateModel[], from = emptyTwinProgress()) =>
    states.reduce((progress, payload) => foldTwinProgress(progress, payload, model), from);

  /**
   * Replay a session's recorded events through the REAL store, stopping after
   * the nth `build_step`. What comes back is exactly the `BuildProgress` a
   * browser would be holding at that instant.
   */
  const replayTo = (name: keyof typeof fixtures.sessions, steps: number) => {
    const store = createConsoleStore();
    let seen = 0;
    for (const event of events(name)) {
      if (event.type === "build_step" && event.status === "begin") {
        if (seen >= steps) break;
        seen += 1;
      }
      store.applyEvent(event);
    }
    return store.snapshot;
  };
  const replayAll = (name: keyof typeof fixtures.sessions) => {
    const store = createConsoleStore();
    store.applyEvents(events(name));
    return store.snapshot;
  };

  it("the fixture cell is TOWER's, so levels 0 and 1 are t1 and t2", () => {
    expect(fixtures.cell).toEqual([...CELL]);
    expect(targetBlock(armed(), model)?.id).toBe("t1");
  });

  it("a PLACED session confirms exactly the block that was built", () => {
    expect(play(session("placed")).confirmed).toEqual(["t1"]);
  });

  it("the recorded descent carries the firmware's own predicted duration", () => {
    const lowering = events("placed").find(
      event => event.type === "build_step"
        && (event as { phase: string }).phase === "lower_to_level")!;
    // 1350 steps x 1.9 ms/step + DIR_SETTLE_MS, worked out by the board.
    expect((lowering as { eta_ms: number }).eta_ms).toBe(2570);

    // And it reaches the scene as a descent the component can animate.
    const states = session("placed");
    const running = states.find(payload => payload.build_state === "RUNNING")!;
    const scene = twinScene(running, model,
                            play(states.slice(0, states.indexOf(running) + 1)), live,
                            replayTo("placed", 10).progress);
    expect(scene.phase).toBe("lowering-to-level");
    expect(scene.descent?.etaMs).toBe(2570);
    // Still not placed, and it cannot become so on that timer.
    expect(scene.blocks.some(block => block.appearance === "placed")).toBe(false);
    expect(descentProgress(1e9, scene.descent!.etaMs)).toBeLessThan(1);
  });

  it("the recorded stream is the firmware's fourteen phases, in order, once", () => {
    const steps = events("placed").filter(event => event.type === "build_step");
    expect(steps.map(event => (event as { step: number }).step))
      .toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 11, 12, 13, 14]);
    // Exactly one `done`, and it is the release.
    const done = steps.filter(event => (event as { status: string }).status === "done");
    expect(done).toHaveLength(1);
    expect((done[0] as { phase: string }).phase).toBe("release");
  });

  it("walks the recorded phases and shows each one, carrying only when it is", () => {
    const states = session("placed");
    const running = states.find(payload => payload.build_state === "RUNNING")!;
    const progress = play(states.slice(0, states.indexOf(running) + 1));
    const sceneAfter = (steps: number) =>
      twinScene(running, model, progress, live, replayTo("placed", steps).progress);

    // Fetching the block: nothing is in the claw and nothing is placed.
    expect(sceneAfter(1).phase).toBe("raising-clearance");
    expect(sceneAfter(1).carrying).toBe(false);
    expect(sceneAfter(5).phase).toBe("lowering-to-ground");
    expect(sceneAfter(5).carrying).toBe(false);

    // The jaws close: from here the block is in the claw.
    expect(sceneAfter(6).phase).toBe("gripping");
    expect(sceneAfter(6).carrying).toBe(true);
    expect(sceneAfter(8).phase).toBe("moving-to-target");
    expect(sceneAfter(8).carrying).toBe(true);
    expect(sceneAfter(8).blockOffset).toBe(TRAVEL_SCENE_Y);
    expect(sceneAfter(9).phase).toBe("rotating");

    // Nothing anywhere in the carry says the block has been placed.
    for (let steps = 1; steps <= 11; steps += 1) {
      expect(sceneAfter(steps).phase).not.toBe("placed");
      expect(sceneAfter(steps).blocks.some(block => block.appearance === "placed"))
        .toBe(false);
    }
    expect(byId(sceneAfter(8).blocks, "t1").appearance).toBe("building");
    expect(sceneAfter(8).animating).toBe(true);
  });

  it("shows the release, then parking, and STILL does not say placed", () => {
    const states = session("placed");
    const running = states.find(payload => payload.build_state === "RUNNING")!;
    const progress = play(states.slice(0, states.indexOf(running) + 1));

    // Everything up to and including the release `done`.
    const store = createConsoleStore();
    for (const event of events("placed")) {
      store.applyEvent(event);
      if (event.type === "build_step" && event.status === "done") break;
    }
    const released = twinScene(running, model, progress, live, store.snapshot.progress);
    expect(released.released).toBe(true);
    expect(released.carrying).toBe(false);
    expect(released.blockOffset).toBe(0);
    expect(released.phase).toBe("parking");
    expect(released.blocks.some(block => block.appearance === "placed")).toBe(false);

    // Phases 12-14: still parking, still not placed.
    const parking = twinScene(running, model, progress, live,
                              replayTo("placed", 13).progress);
    expect(parking.phase).toBe("parking");
    expect(parking.blocks.some(block => block.appearance === "placed")).toBe(false);
  });

  it("only the terminal build_result turns the phase to placed", () => {
    const snapshot = replayAll("placed");
    expect(snapshot.lastResult?.result).toBe("placed");
    expect(snapshot.progress.status).toBe("placed");
    const final = session("placed").at(-1)!;
    expect(twinScene(final, model, play(session("placed")), live, snapshot.progress)
      .phase).toBe("placed");
    expect(play(session("placed")).confirmed).toEqual(["t1"]);
  });

  it("a REJECTED session keeps the earlier block placed and marks only the new one", () => {
    // The recorded rejected session opens with `last_result: placed` still on
    // screen from the previous build AND a fresh selection — the exact payload
    // that would make an optimistic twin place the wrong block.
    const states = session("rejected");
    expect(states[1].last_result).toBe("placed");
    expect(states[1].selected).not.toBeNull();

    const progress = play(states, play(session("placed")));
    expect(progress.confirmed).toEqual(["t1"]);
    expect(progress.rejectedId).toBe("t2");
    expect(progress.rejectedReason).toBe("no block at the feeder");

    const scene = twinScene(states.at(-1)!, model, progress, live,
                            replayAll("rejected").progress);
    expect(byId(scene.blocks, "t1").appearance).toBe("placed");
    expect(byId(scene.blocks, "t2").appearance).toBe("rejected");
    expect(byId(scene.blocks, "t2").reason).toBe("no block at the feeder");
    expect(scene.banner).toBe("rejected");
    expect(scene.animating).toBe(false);
    // A rejection announces NO phase: the firmware refuses it during
    // validation, before anything moves. The absence is the evidence.
    expect(events("rejected").filter(event => event.type === "build_step")).toEqual([]);
    expect(scene.phase).toBe("rejected");
    expect(scene.carrying).toBe(false);
  });

  it("an ABORTED session locks the twin, confirms nothing, and stops it dead", () => {
    const states = session("aborted");
    const progress = play(states);
    expect(progress.confirmed).toEqual([]);

    // It died at phase 8 — MID-CARRY, with the block in the claw. The twin
    // must stop, not carry on showing a block travelling to a cell it never
    // reached, and must never place it.
    const snapshot = replayAll("aborted");
    expect(snapshot.progress.step).toBe(8);
    expect(snapshot.progress.releaseConfirmed).toBe(false);
    expect(snapshot.lastResult?.locked).toBe(true);

    const scene = twinScene(states.at(-1)!, model, progress, live, snapshot.progress);
    expect(scene.phase).toBe("aborted");
    expect(scene.carrying).toBe(false);
    expect(scene.indicator).toBe(false);
    expect(scene.blockOffset).toBe(0);
    expect(scene.banner).toBe("locked");
    expect(scene.bannerText).toBe("could not reach the target cell");
    expect(scene.animating).toBe(false);
    expect(scene.desaturate).toBe(true);
    expect(scene.targetId).toBeNull();
    expect(scene.blocks.every(block => block.appearance === "ghost")).toBe(true);
    expect(scene.blocks.every(block => block.mix === LOCKED_MIX)).toBe(true);
  });

  it("replaying a whole session twice changes nothing", () => {
    const states = [...session("placed"), ...session("rejected")];
    expect(play([...states, ...states])).toEqual(play(states));
  });
});

describe("twinSignature — what the twin is actually allowed to redraw for", () => {
  const sign = (payload: StateModel | null, progress = emptyTwinProgress(),
                options: Parameters<typeof twinSignature>[2] = live) =>
    twinSignature(payload, progress, options);

  it("ignores the twenty-a-second churn: camera age, freshness and geometry", () => {
    expect(sign(armed({ camera_age_ms: 41 })))
      .toBe(sign(armed({ camera_age_ms: 980, camera: "STALE", calibrated: false })));
  });

  it("changes for everything the picture depends on", () => {
    const base = sign(armed());
    expect(sign(armed({ build_state: "RUNNING" }))).not.toBe(base);
    expect(sign(armed({ level: 1 }))).not.toBe(base);
    expect(sign(armed({ mode: "horizontal" }))).not.toBe(base);
    expect(sign(armed({ last_result: "rejected", last_result_reason: "no block" }))).not.toBe(base);
    expect(sign(armed(), progressWith({ confirmed: ["t1"] }))).not.toBe(base);
    expect(sign(armed(), emptyTwinProgress(), { connected: false })).not.toBe(base);
  });

  it("counts the stale age only while the socket is down", () => {
    expect(sign(armed(), emptyTwinProgress(), { connected: true, staleSeconds: 4 }))
      .toBe(sign(armed(), emptyTwinProgress(), { connected: true, staleSeconds: 19 }));
    expect(sign(armed(), emptyTwinProgress(), { connected: false, staleSeconds: 4 }))
      .not.toBe(sign(armed(), emptyTwinProgress(), { connected: false, staleSeconds: 19 }));
  });
});
