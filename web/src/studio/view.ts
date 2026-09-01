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
import { MM_PER_CM, machineToScene, rigConfig, type Vec3 } from "./coords";

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

export interface Box { min: Vec3; max: Vec3 }
export interface CameraPose { position: Vec3; target: Vec3; up: Vec3 }

const add = (a: Vec3, b: Vec3): Vec3 => ({ x: a.x + b.x, y: a.y + b.y, z: a.z + b.z });
const scale = (v: Vec3, k: number): Vec3 => ({ x: v.x * k, y: v.y * k, z: v.z * k });
const cross = (a: Vec3, b: Vec3): Vec3 => ({
  x: a.y * b.z - a.z * b.y, y: a.z * b.x - a.x * b.z, z: a.x * b.y - a.y * b.x,
});
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

export function boxCentre(box: Box): Vec3 {
  return {
    x: (box.min.x + box.max.x) / 2,
    y: (box.min.y + box.max.y) / 2,
    z: (box.min.z + box.max.z) / 2,
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
    // Off-axis, so frame the bounding sphere rather than a face: it holds for
    // every orbit angle and cannot clip a corner.
    const radius = Math.hypot(half.x, half.y, half.z);
    const distance = frameDistance(radius, radius, FOV_DEG, aspect) + radius;
    return { position: add(target, scale(framing.from, distance)), target, up };
  }

  const distance = frameDistance(framing.width, framing.height, FOV_DEG, aspect) + framing.depth;
  return { position: add(target, scale(framing.from, distance)), target, up };
}

/** The orbit constraint, as arithmetic: the camera never drops below ground. */
export function clampAboveGround(position: Vec3, minY = MIN_CAMERA_Y): Vec3 {
  return position.y >= minY ? position : { x: position.x, y: minY, z: position.z };
}

/** DESIGN.md section 3.4: a reduced-motion viewer gets the destination, not the trip. */
export function tweenMs(reducedMotion: boolean): number {
  return reducedMotion ? 0 : TWEEN_MS;
}

/**
 * A camera transition is animation only when the operator explicitly asks for
 * one after initialization. The first pose and a size-only reframe must snap:
 * tweening either makes the canvas visibly zoom from Three.js's default pose,
 * and a settling ResizeObserver can otherwise restart that zoom several times.
 */
export function cameraTransitionMs(initialized: boolean, explicitCommand: boolean,
                                   reducedMotion: boolean): number {
  return initialized && explicitCommand ? tweenMs(reducedMotion) : 0;
}
