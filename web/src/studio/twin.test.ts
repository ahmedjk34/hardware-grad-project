/**
 * Plan 4 §9.2's table, one test per row, driven by fixture `/api/events`
 * payloads. The rendering needs no GPU test; this mapping is where the bugs
 * that matter live, so every claim the twin makes about the machine is made
 * here and asserted here.
 */
import { describe, expect, it } from "vitest";
import {
  BUILDING_OPACITY, DESATURATE_TOKEN, GHOST_OPACITY, LOCKED_MIX, TARGET_OPACITY,
  descentOffsetScene, emptyTwinProgress, foldTwinProgress, loadTwinModel,
  targetBlock, twinModelChoices, twinScene, twinSignature, type TwinProgress,
} from "./twin";
import { EXAMPLES } from "./examples";
import { structureOf } from "./rigmodel";
import type { Model } from "./model";
import type { StateModel } from "../types";
import fixtures from "./twin.fixtures.json";

const TOWER = EXAMPLES[0];
const model: Model = structureOf(TOWER);
/** TOWER is one vertical cell, five levels: t1 at level 0 … t5 at level 4. */
const CELL: [number, number] = [TOWER.blocks[0].col, TOWER.blocks[0].row];

const state = (overrides: Partial<StateModel> = {}): StateModel => ({
  mode: "vertical", cols: 7, rows: 6, calibrated: true, selected: null,
  command: null, level: 0, build_state: "READY", locked_reason: null,
  camera: "LIVE", camera_age_ms: 40, last_result: null, last_result_reason: null,
  views: {}, geometry: null, ...overrides,
});

/** The server has selected TOWER's ground block and nothing has run yet. */
const armed = (overrides: Partial<StateModel> = {}) =>
  state({ selected: CELL, level: 0, command: `B ${CELL[0]} ${CELL[1]} 0`, ...overrides });

const live = { connected: true };
const progressWith = (overrides: Partial<TwinProgress> = {}): TwinProgress =>
  ({ ...emptyTwinProgress(), ...overrides });

const byId = <T extends { id: string }>(blocks: T[], id: string) => blocks.find(block => block.id === id)!;

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

  it("RUNNING: the target turns --motion, descends, and the banner names the build", () => {
    const scene = twinScene(armed({ build_state: "RUNNING" }), model, emptyTwinProgress(), live);
    const target = byId(scene.blocks, "t1");
    expect(target.appearance).toBe("building");
    expect(target.token).toBe("--motion");
    expect(target.opacity).toBe(BUILDING_OPACITY);
    expect(scene.banner).toBe("running");
    expect(scene.animating).toBe(true);
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

describe("descentOffsetScene — an illustration, not a telemetry read-out", () => {
  it("starts at travel height, arrives at the cell, and repeats", () => {
    expect(descentOffsetScene(0, false)).toBeGreaterThan(0);
    expect(descentOffsetScene(1e9, false)).toBeGreaterThanOrEqual(0);
    const early = descentOffsetScene(100, false);
    const later = descentOffsetScene(900, false);
    expect(later).toBeLessThan(early);
  });

  it("is exactly zero under reduced motion", () => {
    expect(descentOffsetScene(0, true)).toBe(0);
    expect(descentOffsetScene(400, true)).toBe(0);
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
  const play = (states: StateModel[], from = emptyTwinProgress()) =>
    states.reduce((progress, payload) => foldTwinProgress(progress, payload, model), from);

  it("the fixture cell is TOWER's, so levels 0 and 1 are t1 and t2", () => {
    expect(fixtures.cell).toEqual([...CELL]);
    expect(targetBlock(armed(), model)?.id).toBe("t1");
  });

  it("a PLACED session confirms exactly the block that was built", () => {
    expect(play(session("placed")).confirmed).toEqual(["t1"]);
  });

  it("mid-build, the recorded RUNNING states animate a descent and place nothing", () => {
    const states = session("placed");
    const running = states.find(payload => payload.build_state === "RUNNING")!;
    const scene = twinScene(running, model, play(states.slice(0, states.indexOf(running) + 1)),
                            live);
    expect(scene.animating).toBe(true);
    expect(byId(scene.blocks, "t1").appearance).toBe("building");
    expect(scene.blocks.some(block => block.appearance === "placed")).toBe(false);
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

    const scene = twinScene(states.at(-1)!, model, progress, live);
    expect(byId(scene.blocks, "t1").appearance).toBe("placed");
    expect(byId(scene.blocks, "t2").appearance).toBe("rejected");
    expect(byId(scene.blocks, "t2").reason).toBe("no block at the feeder");
    expect(scene.banner).toBe("rejected");
    expect(scene.animating).toBe(false);
  });

  it("an ABORTED session locks the twin, confirms nothing, and stops it dead", () => {
    const states = session("aborted");
    const progress = play(states);
    expect(progress.confirmed).toEqual([]);

    const scene = twinScene(states.at(-1)!, model, progress, live);
    expect(scene.banner).toBe("locked");
    expect(scene.bannerText).toBe("claw did not release");
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
