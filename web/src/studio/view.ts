/**
 * Where the camera stands, and what it is looking at. No three.js in here.
 *
 * Plan 4 section 0.4 rules out testing camera angles by rendering them, but the
 * arithmetic that produces a snap is not a rendering question: it is "does the
 * whole travel envelope fit on this screen, and is machine +X still to the
 * right". Both are answerable headlessly, so both are tested (`view.test.ts`).
 *
 * Every distance here is in SCENE units, and every one of them comes out of
 * `coords.ts` - this module converts nothing itself.
 */
import { MM_PER_CM, machineToScene, rigConfig, type Block, type ModeName, type Shift, type Vec3 } from "./coords";
import { aabbOf } from "./geometry";

/** arduino/build_test_v1: Z_TRAVEL_CM. The cage's height, not a build ceiling. */
export const ENVELOPE_Z_CM = 26.5;

export type ViewName = "top" | "front" | "side" | "iso";
export const VIEWS: ViewName[] = ["top", "front", "side", "iso"];

export const FOV_DEG = 35;
/** A little air around the envelope so it never touches the viewport edge. */
export const FRAME_MARGIN = 1.12;
/** The orbit's floor: the camera may sit level with the ground, never under it. */
export const MIN_CAMERA_Y = 0.2;
export const MAX_POLAR_ANGLE = Math.PI / 2;
/** Explicit view changes stay legible without making the camera feel heavy. */
export const TWEEN_MS = 260;

/**
 * The opening move, once per Studio mount: the camera starts in close on the
 * machine and pulls back to the framed view while it swings round it, so
 * the first thing an operator sees is that this is a 3D object and not a
 * picture of one. Short enough that it never stands between them and the tool.
 */
export const INTRO_MS = 880;
/** How close the camera starts, as a fraction of the final framing distance. */
export const INTRO_START_DISTANCE_RATIO = 0.32;
/** How far round the machine the pull-back sweeps, in radians (~49 degrees). */
export const INTRO_SWEEP_RAD = 0.85;
/** The start elevation, as a fraction of the final one: it rises as it pulls back. */
export const INTRO_START_ELEVATION_RATIO = 0.45;

/** Mouse-wheel direction in the physical convention browsers report: positive
 *  delta is a wheel moving down, and must move the camera away from the rig. */
export function wheelZoomDirection(deltaY: number): "in" | "out" | null {
  return deltaY > 0 ? "out" : deltaY < 0 ? "in" : null;
}

/** The scale used by OrbitControls' public dolly methods for one wheel event. */
export function wheelDollyScale(zoomSpeed: number): number {
  return Math.pow(0.95, Math.max(0, zoomSpeed));
}

export interface Box { min: Vec3; max: Vec3 }
export interface CameraPose { position: Vec3; target: Vec3; up: Vec3 }

const add = (a: Vec3, b: Vec3): Vec3 => ({ x: a.x + b.x, y: a.y + b.y, z: a.z + b.z });
const scale = (v: Vec3, k: number): Vec3 => ({ x: v.x * k, y: v.y * k, z: v.z * k });
const cross = (a: Vec3, b: Vec3): Vec3 => ({
  x: a.y * b.z - a.z * b.y, y: a.z * b.x - a.x * b.z, z: a.x * b.y - a.y * b.x,
});
const lerp = (a: number, b: number, k: number) => a + (b - a) * k;
/** Ease-in-out cubic: no jump at either end, and no jerk in the middle. */
export const easeInOut = (t: number) =>
  t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
const norm = (v: Vec3): Vec3 => {
  const length = Math.hypot(v.x, v.y, v.z);
  return length === 0 ? v : scale(v, 1 / length);
};

/** The travel cap as a scene-space box: X and Y from the workspace, Z from the
 *  firmware's Z_TRAVEL_CM. This is the machine's real limit and is always drawn. */
export function envelopeBoxScene(): Box {
  const workspace = rigConfig().workspace;
  const home = machineToScene({ x: 0, y: 0, z: 0 });
  const far = machineToScene({
    x: workspace.width_cm * MM_PER_CM,
    y: workspace.height_cm * MM_PER_CM,
    z: ENVELOPE_Z_CM * MM_PER_CM,
  });
  return {
    min: { x: Math.min(home.x, far.x), y: Math.min(home.y, far.y), z: Math.min(home.z, far.z) },
    max: { x: Math.max(home.x, far.x), y: Math.max(home.y, far.y), z: Math.max(home.z, far.z) },
  };
}

/**
 * The rectangle the overhead camera actually frames: the envelope's ground
 * plane, with none of the cage's height.
 *
 * Plan 4 §9.3's SYNC VIEW is `viewPose("top", aspect, workspaceBoxScene())`.
 * Framing the full envelope instead would push the camera back by the cage's
 * 26.5 cm of Z travel and the twin would show a smaller workspace than the
 * video beside it - which is the one thing this toggle exists to prevent.
 */
export function workspaceBoxScene(): Box {
  const box = envelopeBoxScene();
  return { min: box.min, max: { x: box.max.x, y: box.min.y, z: box.max.z } };
}

export function boxCentre(box: Box): Vec3 {
  return {
    x: (box.min.x + box.max.x) / 2,
    y: (box.min.y + box.max.y) / 2,
    z: (box.min.z + box.max.z) / 2,
  };
}

/** A placed machine box converted at the same boundary as the whole scene. */
export function blockBoxScene(block: Block, shift?: Shift): Box {
  const machine = aabbOf(block, shift);
  const first = machineToScene(machine.min);
  const second = machineToScene(machine.max);
  return {
    min: {
      x: Math.min(first.x, second.x), y: Math.min(first.y, second.y), z: Math.min(first.z, second.z),
    },
    max: {
      x: Math.max(first.x, second.x), y: Math.max(first.y, second.y), z: Math.max(first.z, second.z),
    },
  };
}

/**
 * The box the blocks themselves occupy, or `null` for an empty model.
 *
 * A thumbnail framed on the envelope gives every card the same picture of the
 * same empty cage, which is worse than no thumbnail at all. Framed on this, a
 * tower looks like a tower. The envelope still renders behind it, for scale.
 */
export function modelBoxScene(blocks: Block[],
                              shifts?: Partial<Record<ModeName, Shift>>): Box | null {
  if (blocks.length === 0) return null;
  const boxes = blocks.map(block => blockBoxScene(block, shifts?.[block.mode]));
  const reduce = (pick: (values: number[]) => number, axis: "x" | "y" | "z", side: "min" | "max") =>
    pick(boxes.map(box => box[side][axis]));
  return {
    min: { x: reduce(v => Math.min(...v), "x", "min"), y: reduce(v => Math.min(...v), "y", "min"), z: reduce(v => Math.min(...v), "z", "min") },
    max: { x: reduce(v => Math.max(...v), "x", "max"), y: reduce(v => Math.max(...v), "y", "max"), z: reduce(v => Math.max(...v), "z", "max") },
  };
}

function halfExtents(box: Box): Vec3 {
  return {
    x: (box.max.x - box.min.x) / 2,
    y: (box.max.y - box.min.y) / 2,
    z: (box.max.z - box.min.z) / 2,
  };
}

/**
 * How far back a perspective camera must stand for a rectangle of the given
 * half-extents to fit. A portrait viewport is narrower than it is tall, so the
 * horizontal half-extent is usually what pushes the camera back on a phone.
 */
export function frameDistance(halfWidth: number, halfHeight: number,
                              fovDeg = FOV_DEG, aspect = 1, margin = FRAME_MARGIN): number {
  const tangent = Math.tan((fovDeg * Math.PI) / 180 / 2);
  return Math.max(halfHeight / tangent, halfWidth / (tangent * aspect)) * margin;
}

/** The pose's screen basis, built exactly as three.js builds a camera's. */
export function screenAxes(pose: CameraPose): { right: Vec3; up: Vec3 } {
  const backward = norm({
    x: pose.position.x - pose.target.x,
    y: pose.position.y - pose.target.y,
    z: pose.position.z - pose.target.z,
  });
  const right = norm(cross(pose.up, backward));
  return { right, up: cross(backward, right) };
}

/**
 * Where the camera stands for a snap view, framed to the travel envelope.
 *
 * `top` is the one that carries a requirement beyond taste: it must show the
 * workspace the way the overhead camera does - machine +X to the right, machine
 * +Y up the screen - because the twin is later laid against that image.
 */
export function viewPose(view: ViewName, aspect: number, box = envelopeBoxScene()): CameraPose {
  const target = boxCentre(box);
  const half = halfExtents(box);
  const up: Vec3 = view === "top" ? { x: 0, y: 0, z: -1 } : { x: 0, y: 1, z: 0 };

  // Screen width, screen height and depth half-extents, per view direction.
  const framing = {
    top:   { width: half.x, height: half.z, depth: half.y, from: { x: 0, y: 1, z: 0 } },
    front: { width: half.x, height: half.y, depth: half.z, from: { x: 0, y: 0, z: 1 } },
    side:  { width: half.z, height: half.y, depth: half.x, from: { x: 1, y: 0, z: 0 } },
    iso:   { width: 0, height: 0, depth: 0, from: norm({ x: 1, y: 0.9, z: 1 }) },
  }[view];

  if (view === "iso") {
    return frameBox(box, aspect);
  }

  const distance = frameDistance(framing.width, framing.height, FOV_DEG, aspect) + framing.depth;
  return { position: add(target, scale(framing.from, distance)), target, up };
}

/**
 * Frame an arbitrary scene-space box for diagnostic click-through. Off-axis
 * framing uses the bounding sphere, exactly as the ISO envelope view does, so
 * every corner stays visible and `frameDistance` remains the only perspective
 * calculation in the Studio.
 */
export function frameBox(box: Box, aspect: number): CameraPose {
  const target = boxCentre(box);
  const half = halfExtents(box);
  const radius = Math.hypot(half.x, half.y, half.z);
  const distance = frameDistance(radius, radius, FOV_DEG, aspect) + radius;
  const from = norm({ x: 1, y: 0.9, z: 1 });
  return {
    position: add(target, scale(from, distance)),
    target,
    up: { x: 0, y: 1, z: 0 },
  };
}

/** The orbit constraint, as arithmetic: the camera never drops below ground. */
export function clampAboveGround(position: Vec3, minY = MIN_CAMERA_Y): Vec3 {
  return position.y >= minY ? position : { x: position.x, y: minY, z: position.z };
}

/**
 * The intro as a function of progress, in the pose's own orbit frame: the
 * camera keeps looking at the same target throughout, and only its distance and
 * its two angles move. `t >= 1` returns `final` itself, so the intro cannot
 * leave the camera a rounding error away from the pose the snap buttons use.
 */
export function introPose(final: CameraPose, t: number): CameraPose {
  if (!(t > 0)) t = 0;
  if (t >= 1) return final;
  const k = easeInOut(t);

  const offset = {
    x: final.position.x - final.target.x,
    y: final.position.y - final.target.y,
    z: final.position.z - final.target.z,
  };
  const distance = Math.hypot(offset.x, offset.y, offset.z);
  if (distance === 0) return final;

  const elevation = Math.asin(Math.max(-1, Math.min(1, offset.y / distance)));
  const azimuth = Math.atan2(offset.x, offset.z);

  const d = lerp(distance * INTRO_START_DISTANCE_RATIO, distance, k);
  const e = lerp(elevation * INTRO_START_ELEVATION_RATIO, elevation, k);
  const a = azimuth - INTRO_SWEEP_RAD * (1 - k);

  const ground = Math.cos(e) * d;
  return {
    position: clampAboveGround(add(final.target, {
      x: ground * Math.sin(a), y: Math.sin(e) * d, z: ground * Math.cos(a),
    })),
    target: final.target,
    up: final.up,
  };
}

/** DESIGN.md section 3.4: a reduced-motion viewer gets the destination, not the trip. */
export function introMs(reducedMotion: boolean): number {
  return reducedMotion ? 0 : INTRO_MS;
}

/** DESIGN.md section 3.4: a reduced-motion viewer gets the destination, not the trip. */
export function tweenMs(reducedMotion: boolean): number {
  return reducedMotion ? 0 : TWEEN_MS;
}

/**
 * A camera transition is animation only when the operator explicitly asks for
 * one after initialization. The first pose belongs to the intro (`introPose`),
 * which runs once per mount; a size-only reframe must snap. Tweening either
 * would let a settling ResizeObserver restart a zoom several times, which is
 * exactly the "zooms in, then zooms out again" bug this guard exists to stop.
 */
export function cameraTransitionMs(initialized: boolean, explicitCommand: boolean,
                                   reducedMotion: boolean): number {
  return initialized && explicitCommand ? tweenMs(reducedMotion) : 0;
}
