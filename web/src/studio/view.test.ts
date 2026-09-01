import { describe, expect, it, afterEach } from "vitest";
import { machineToScene, rigConfig, setRigConfig, type Vec3 } from "./coords";
import {
  INTRO_MS, INTRO_START_DISTANCE_RATIO, MAX_POLAR_ANGLE, MIN_CAMERA_Y, TWEEN_MS,
  VIEWS, cameraTransitionMs, clampAboveGround, easeInOut, envelopeBoxScene,
  blockBoxScene, frameBox, frameDistance, introMs, introPose, modelBoxScene, screenAxes,
  tweenMs, viewPose, workspaceBoxScene,
  type CameraPose,
} from "./view";

const shipped = rigConfig();
afterEach(() => setRigConfig(shipped));

const FOV = 35;
const sub = (a: Vec3, b: Vec3): Vec3 => ({ x: a.x - b.x, y: a.y - b.y, z: a.z - b.z });
const dot = (a: Vec3, b: Vec3) => a.x * b.x + a.y * b.y + a.z * b.z;
/** A machine-space direction as a unit vector in scene space. */
const dir = (v: Vec3): Vec3 => {
  const s = machineToScene(v);
  const length = Math.hypot(s.x, s.y, s.z);
  return { x: s.x / length, y: s.y / length, z: s.z / length };
};
const near = (a: Vec3, b: Vec3) => {
  expect(a.x).toBeCloseTo(b.x, 6);
  expect(a.y).toBeCloseTo(b.y, 6);
  expect(a.z).toBeCloseTo(b.z, 6);
};

function corners(box: { min: Vec3; max: Vec3 }): Vec3[] {
  const out: Vec3[] = [];
  for (const x of [box.min.x, box.max.x])
    for (const y of [box.min.y, box.max.y])
      for (const z of [box.min.z, box.max.z]) out.push({ x, y, z });
  return out;
}

/** Independent perspective check: is every corner inside this pose's frustum? */
function framesBox(pose: CameraPose, box: { min: Vec3; max: Vec3 }, aspect: number): boolean {
  const axes = screenAxes(pose);
  const forward = sub(pose.target, pose.position);
  const length = Math.hypot(forward.x, forward.y, forward.z);
  const unit = { x: forward.x / length, y: forward.y / length, z: forward.z / length };
  const halfHeight = Math.tan((FOV * Math.PI) / 180 / 2);
  return corners(box).every(corner => {
    const v = sub(corner, pose.position);
    const depth = dot(v, unit);
    if (depth <= 0) return false;
    return Math.abs(dot(v, axes.right)) <= depth * halfHeight * aspect + 1e-9
      && Math.abs(dot(v, axes.up)) <= depth * halfHeight + 1e-9;
  });
}

describe("the travel envelope in scene space", () => {
  it("spans the whole travel cap, converted only by coords.ts", () => {
    const box = envelopeBoxScene();
    const origin = machineToScene({ x: 0, y: 0, z: 0 });
    const far = machineToScene({ x: 228, y: 380, z: 265 });
    expect(box.min.x).toBeCloseTo(Math.min(origin.x, far.x), 6);
    expect(box.max.x).toBeCloseTo(Math.max(origin.x, far.x), 6);
    expect(box.min.y).toBeCloseTo(Math.min(origin.y, far.y), 6);
    expect(box.max.y).toBeCloseTo(Math.max(origin.y, far.y), 6);
    expect(box.min.z).toBeCloseTo(Math.min(origin.z, far.z), 6);
    expect(box.max.z).toBeCloseTo(Math.max(origin.z, far.z), 6);
  });

  it("follows the workspace when the config changes", () => {
    const wider = JSON.parse(JSON.stringify(rigConfig()));
    wider.workspace.width_cm = 40;
    setRigConfig(wider);
    expect(envelopeBoxScene().max.x).toBeCloseTo(machineToScene({ x: 400, y: 0, z: 0 }).x, 6);
  });
});

describe("view snaps", () => {
  const box = envelopeBoxScene();
  const centre: Vec3 = {
    x: (box.min.x + box.max.x) / 2,
    y: (box.min.y + box.max.y) / 2,
    z: (box.min.z + box.max.z) / 2,
  };

  it("names exactly top, front, side and iso", () => {
    expect(VIEWS).toEqual(["top", "front", "side", "iso"]);
  });

  it("every snap aims at the centre of the envelope and stays above ground", () => {
    for (const view of VIEWS) {
      const pose = viewPose(view, 16 / 9);
      near(pose.target, centre);
      expect(pose.position.y).toBeGreaterThanOrEqual(MIN_CAMERA_Y);
    }
  });

  it("every snap frames the whole envelope, on a phone as on a desktop", () => {
    for (const aspect of [16 / 9, 4 / 3, 0.5]) {
      for (const view of VIEWS) {
        expect(framesBox(viewPose(view, aspect), box, aspect)).toBe(true);
      }
    }
  });

  it("top looks straight down with machine +X to the right and +Y up the screen — the overhead camera's own framing", () => {
    const pose = viewPose("top", 16 / 9);
    expect(pose.position.x).toBeCloseTo(centre.x, 6);
    expect(pose.position.z).toBeCloseTo(centre.z, 6);
    expect(pose.position.y).toBeGreaterThan(box.max.y);
    const axes = screenAxes(pose);
    near(axes.right, dir({ x: 1, y: 0, z: 0 }));
    near(axes.up, dir({ x: 0, y: 1, z: 0 }));
  });

  it("front looks along machine +Y, side along machine -X, both with Z up the screen", () => {
    const front = screenAxes(viewPose("front", 16 / 9));
    near(front.right, dir({ x: 1, y: 0, z: 0 }));
    near(front.up, dir({ x: 0, y: 0, z: 1 }));

    const side = screenAxes(viewPose("side", 16 / 9));
    near(side.right, dir({ x: 0, y: 1, z: 0 }));
    near(side.up, dir({ x: 0, y: 0, z: 1 }));
  });

  it("iso is off-axis on both ground axes and above the model", () => {
    const pose = viewPose("iso", 16 / 9);
    expect(Math.abs(pose.position.x - centre.x)).toBeGreaterThan(1);
    expect(Math.abs(pose.position.z - centre.z)).toBeGreaterThan(1);
    expect(pose.position.y).toBeGreaterThan(centre.y);
  });

  it("a portrait viewport pulls the camera further back than a landscape one", () => {
    expect(frameDistance(10, 4, FOV, 0.5)).toBeGreaterThan(frameDistance(10, 4, FOV, 2));
  });

  it("frames whichever half-extent is binding", () => {
    const half = Math.tan((FOV * Math.PI) / 180 / 2);
    const tall = frameDistance(1, 10, FOV, 1);
    expect(tall * half).toBeGreaterThanOrEqual(10);
    const wide = frameDistance(10, 1, FOV, 1);
    expect(wide * half).toBeGreaterThanOrEqual(10);
  });

  it("frames an arbitrary selected box by reusing the perspective distance", () => {
    const selected = {
      min: { x: 3, y: 0, z: -8 },
      max: { x: 7, y: 2, z: -2 },
    };
    const pose = frameBox(selected, 16 / 9);
    expect(pose.target).toEqual({ x: 5, y: 1, z: -5 });
    expect(framesBox(pose, selected, 16 / 9)).toBe(true);
    const envelope = viewPose("iso", 16 / 9);
    const envelopeDistance = Math.hypot(
      envelope.position.x - envelope.target.x,
      envelope.position.y - envelope.target.y,
      envelope.position.z - envelope.target.z,
    );
    const selectedDistance = Math.hypot(
      pose.position.x - pose.target.x, pose.position.y - pose.target.y, pose.position.z - pose.target.z,
    );
    expect(selectedDistance).toBeLessThan(envelopeDistance);
  });

  it("converts a selected block box through the one coordinate boundary", () => {
    const box = blockBoxScene({ mode: "vertical", col: 1, row: 1, level: 0 });
    const expected = [
      machineToScene({ x: 27, y: 46, z: 0 }),
      machineToScene({ x: 49, y: 106, z: 15 }),
    ];
    expect(box.min).toEqual({
      x: Math.min(expected[0].x, expected[1].x),
      y: Math.min(expected[0].y, expected[1].y),
      z: Math.min(expected[0].z, expected[1].z),
    });
    expect(box.max).toEqual({
      x: Math.max(expected[0].x, expected[1].x),
      y: Math.max(expected[0].y, expected[1].y),
      z: Math.max(expected[0].z, expected[1].z),
    });
  });
});

describe("the orbit never goes below the ground plane", () => {
  it("caps the polar angle at the horizon", () => {
    expect(MAX_POLAR_ANGLE).toBeGreaterThan(0);
    expect(MAX_POLAR_ANGLE).toBeLessThanOrEqual(Math.PI / 2);
  });

  it("lifts a camera that has dropped under the ground and leaves a legal one alone", () => {
    expect(clampAboveGround({ x: 3, y: -20, z: 4 })).toEqual({ x: 3, y: MIN_CAMERA_Y, z: 4 });
    expect(clampAboveGround({ x: 3, y: 0, z: 4 }).y).toBe(MIN_CAMERA_Y);
    const high = { x: 3, y: 40, z: 4 };
    expect(clampAboveGround(high)).toEqual(high);
  });
});

describe("motion", () => {
  it("tweens by default and cuts instantly under prefers-reduced-motion", () => {
    expect(tweenMs(false)).toBeGreaterThan(0);
    expect(tweenMs(true)).toBe(0);
  });

  it("leaves the first pose to the intro rather than tweening from the Three.js default", () => {
    expect(cameraTransitionMs(false, false, false)).toBe(0);
  });

  it("reframes immediately when only the viewport size settles", () => {
    expect(cameraTransitionMs(true, false, false)).toBe(0);
  });

  it("animates only an explicit view command after initialization", () => {
    expect(cameraTransitionMs(true, true, false)).toBe(TWEEN_MS);
  });

  it("keeps explicit view commands instant under reduced motion", () => {
    expect(cameraTransitionMs(true, true, true)).toBe(0);
  });
});

describe("the opening move", () => {
  const final = viewPose("iso", 16 / 9);
  const radius = (pose: CameraPose) => Math.hypot(
    pose.position.x - final.target.x,
    pose.position.y - final.target.y,
    pose.position.z - final.target.z,
  );

  it("lasts long enough to read and short enough to stay out of the way", () => {
    expect(INTRO_MS).toBeGreaterThanOrEqual(700);
    expect(INTRO_MS).toBeLessThanOrEqual(1000);
  });

  it("is skipped entirely under prefers-reduced-motion", () => {
    expect(introMs(false)).toBe(INTRO_MS);
    expect(introMs(true)).toBe(0);
  });

  it("starts close to the rig and ends on the framed pose itself", () => {
    expect(radius(introPose(final, 0))).toBeCloseTo(radius(final) * INTRO_START_DISTANCE_RATIO, 6);
    expect(introPose(final, 1)).toBe(final);
    expect(introPose(final, 1.4)).toBe(final);
  });

  it("pulls back monotonically — it never zooms out and back in", () => {
    let previous = -Infinity;
    for (let i = 0; i <= 60; i++) {
      const r = radius(introPose(final, i / 60));
      expect(r).toBeGreaterThan(previous);
      previous = r;
    }
  });

  it("orbits the machine on the way out, then arrives on the final heading", () => {
    const azimuth = (pose: CameraPose) =>
      Math.atan2(pose.position.x - final.target.x, pose.position.z - final.target.z);
    expect(Math.abs(azimuth(introPose(final, 0)) - azimuth(final))).toBeGreaterThan(0.4);
    expect(azimuth(introPose(final, 0.999))).toBeCloseTo(azimuth(final), 3);
  });

  it("keeps looking at the same point and never dips under the floor", () => {
    for (let i = 0; i <= 60; i++) {
      const pose = introPose(final, i / 60);
      near(pose.target, final.target);
      expect(pose.position.y).toBeGreaterThanOrEqual(MIN_CAMERA_Y);
    }
  });

  it("eases in and out with no snap at either end and no jerk in the middle", () => {
    expect(easeInOut(0)).toBe(0);
    expect(easeInOut(1)).toBe(1);
    expect(easeInOut(0.5)).toBeCloseTo(0.5, 6);
    // Symmetric, and slow at both ends: the derivative is largest at the centre.
    expect(easeInOut(0.25) + easeInOut(0.75)).toBeCloseTo(1, 6);
    const step = (a: number, b: number) => easeInOut(b) - easeInOut(a);
    expect(step(0.45, 0.55)).toBeGreaterThan(step(0, 0.1));
    expect(step(0.45, 0.55)).toBeGreaterThan(step(0.9, 1));
  });

  it("frames the whole envelope the moment it finishes, at any aspect", () => {
    for (const aspect of [16 / 9, 4 / 3, 0.5]) {
      const pose = viewPose("iso", aspect);
      expect(framesBox(introPose(pose, 1), envelopeBoxScene(), aspect)).toBe(true);
    }
  });
});

describe("modelBoxScene — what a thumbnail is framed on", () => {
  const block = (mode: "vertical" | "horizontal", col: number, row: number, level: number) =>
    ({ mode, col, row, level });

  it("is null for an empty model, so the caller can fall back to the envelope", () => {
    expect(modelBoxScene([])).toBeNull();
  });

  it("is exactly one block's box for one block", () => {
    expect(modelBoxScene([block("vertical", 2, 2, 0)]))
      .toEqual(blockBoxScene(block("vertical", 2, 2, 0)));
  });

  it("unions across modes and levels, and stays inside the envelope", () => {
    const blocks = [block("vertical", 2, 2, 0), block("vertical", 3, 2, 1), block("horizontal", 1, 4, 2)];
    const box = modelBoxScene(blocks)!;
    const envelope = envelopeBoxScene();
    for (const one of blocks) {
      const single = blockBoxScene(one);
      expect(box.min.x).toBeLessThanOrEqual(single.min.x);
      expect(box.max.y).toBeGreaterThanOrEqual(single.max.y);
    }
    expect(box.max.y).toBeLessThanOrEqual(envelope.max.y);
    expect(box.max.y).toBeGreaterThan(box.min.y);
  });
});

/**
 * SYNC VIEW (Plan 4 §9.3) is `viewPose("top", aspect, workspaceBoxScene())`.
 * M1 chose the top view's up vector so that this would line up with the
 * overhead camera; this is the framing half of the same claim.
 */
describe("the workspace rectangle the camera frames", () => {
  it("is the envelope's ground plane: the same footprint, no height at all", () => {
    const envelope = envelopeBoxScene();
    const ground = workspaceBoxScene();
    expect(ground.min.x).toBeCloseTo(envelope.min.x, 6);
    expect(ground.max.x).toBeCloseTo(envelope.max.x, 6);
    expect(ground.min.z).toBeCloseTo(envelope.min.z, 6);
    expect(ground.max.z).toBeCloseTo(envelope.max.z, 6);
    expect(ground.min.y).toBeCloseTo(envelope.min.y, 6);
    expect(ground.max.y).toBeCloseTo(envelope.min.y, 6);
  });

  it("frames tighter than the envelope does, because the cage's height is not on the bench", () => {
    const aspect = 16 / 9;
    const synced = viewPose("top", aspect, workspaceBoxScene());
    const whole = viewPose("top", aspect);
    expect(synced.position.y).toBeLessThan(whole.position.y);
    expect(framesBox(synced, workspaceBoxScene(), aspect)).toBe(true);
  });

  it("keeps machine +X to the right and +Y up the screen, so the two panels agree", () => {
    for (const aspect of [16 / 9, 4 / 3, 0.5]) {
      const axes = screenAxes(viewPose("top", aspect, workspaceBoxScene()));
      near(axes.right, dir({ x: 1, y: 0, z: 0 }));
      near(axes.up, dir({ x: 0, y: 1, z: 0 }));
    }
  });
});
