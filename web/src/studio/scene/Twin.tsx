/**
 * The read-only twin: the same engine as the Studio, drawn beside the camera.
 *
 * IT HOLDS NO LOGIC. Every decision about what appears and how — the five
 * appearances, the desaturation, whether anything moves at all — is made in
 * `studio/twin.ts` and arrives here as a `TwinScene`. That is what makes Plan 4
 * §9's claims testable without a GPU, and it is why this file is allowed to be
 * judged by eye.
 *
 * IT IS DELIBERATELY CHEAP, because it shares a phone with a live MJPEG stream
 * and the camera is the thing the operator must be watching:
 *
 *  - no shadow maps and no post-processing; `BlockShadows`' instanced ellipses
 *    are the whole grounding cue, as they are in the Studio,
 *  - `dpr={[1, 1.5]}`, `frameloop="demand"`, and `invalidate()` only on a state
 *    change or while a descent is genuinely in flight,
 *  - one instanced batch per (mode, appearance) through `Blocks.tsx`'s own
 *    `BlockBatch` at `quality="twin"`, which drops the arrival pass, the shadow
 *    receiver, the custom shader and every pointer handler,
 *  - `frameloop="never"` the moment the panel is off screen — a phone tab
 *    switched to the camera, or a backgrounded document.
 */
import { memo, useLayoutEffect, useMemo, useRef } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import { Color, Mesh, MeshLambertMaterial } from "three";
import { blockSceneSize, cellToScene, type ModeName } from "../coords";
import {
  DESATURATE_TOKEN, descentProgress, type TwinBlock, type TwinScene,
} from "../twin";
import {
  FOV_DEG, boxCentre, envelopeBoxScene, viewPose, workspaceBoxScene,
} from "../view";
import { BlockBatch } from "./Blocks";
import { BlockShadows } from "./BlockShadows";
import { Envelope } from "./Envelope";
import { Lattice } from "./Lattice";
import { tokenColor } from "./theme";
import { RigOrbitControls } from "./RigOrbitControls";

const MODES: ModeName[] = ["vertical", "horizontal"];
/** Batched separately because each carries its own material and opacity. */
const BATCHED = ["ghost", "placed", "target", "rejected"] as const;
const NO_ANIMATION = new Set<string>();
const NO_HANDLERS = {};

/** A block's token, lerped toward `--text-faint` by the amount the MAPPING
 *  decided. The lerp is `twin.ts`'s call; reading the tokens is this file's. */
function appearanceColour(block: TwinBlock): Color {
  const colour = tokenColor(block.token).clone();
  return block.mix > 0 ? colour.lerp(tokenColor(DESATURATE_TOKEN), block.mix) : colour;
}

/** How fast the activity pulse breathes, in milliseconds per cycle. */
const PULSE_MS = 1400;
/** How far the pulse dips the block's opacity. Visible, not distracting. */
const PULSE_DEPTH = 0.35;

/**
 * The one block in flight. A single mesh rather than an instanced batch:
 * there is never more than one, and the machine builds one at a time.
 *
 * TWO THINGS MOVE HERE, AND NEITHER IS INVENTED.
 *
 * **The descent.** During `lowering_to_level` the block travels from
 * `offset` down toward its cell, over the duration the FIRMWARE predicted and
 * sent as `ms=` on the STEP line. `descentProgress` clamps it short, so the
 * block always stops fractionally above the cell and only settles when the
 * real release event arrives and `offset` becomes 0. That clamp is the whole
 * safety argument: if Z jams, the twin glides down, stops just short, and sits
 * there visibly not landing — which is the truth, and the `HELD` ack is about
 * to lock everything anyway.
 *
 * This is NOT the looping 1.6-second descent this component used to draw. That
 * one had a made-up duration, ran on a loop, and completed on its own.
 *
 * **The pulse.** Opacity, while `indicator` is true. It says "this phase is in
 * motion" and deliberately says nothing about where.
 */
function Building({ block, offset, indicator, descent }: {
  block: TwinBlock;
  offset: number;
  indicator: boolean;
  descent: TwinScene["descent"];
}) {
  const mesh = useRef<Mesh>(null);
  const material = useRef<MeshLambertMaterial>(null);
  const started = useRef(performance.now());
  const { invalidate } = useThree();
  const size = useMemo(() => blockSceneSize(block.mode), [block.mode]);
  const rest = useMemo(
    () => cellToScene(block.mode, block.col, block.row, block.level),
    [block.mode, block.col, block.row, block.level],
  );

  /** The block's height right now: the phase's resting height, less however
   *  much of the estimated descent has elapsed. */
  const heightNow = () => {
    if (!descent) return offset;
    // `Date.now()` and not `performance.now()`: `descent.since` is when this
    // browser was told about the phase, stamped on the same clock.
    return offset * (1 - descentProgress(Date.now() - descent.since, descent.etaMs));
  };

  useLayoutEffect(() => {
    started.current = performance.now();
    if (mesh.current) mesh.current.position.set(rest.x, rest.y + heightNow(), rest.z);
    if (material.current) material.current.opacity = block.opacity;
    invalidate();
  });

  useFrame(() => {
    if (mesh.current && descent) {
      mesh.current.position.y = rest.y + heightNow();
      invalidate();
    }
    if (!indicator || !material.current) return;
    const t = ((performance.now() - started.current) % PULSE_MS) / PULSE_MS;
    material.current.opacity =
      block.opacity * (1 - PULSE_DEPTH * (0.5 - 0.5 * Math.cos(t * Math.PI * 2)));
    invalidate();
  });

  return (
    <mesh ref={mesh} position={[rest.x, rest.y + offset, rest.z]}>
      <boxGeometry args={[size.x, size.y, size.z]} />
      <meshLambertMaterial ref={material} color={appearanceColour(block)}
                           transparent opacity={block.opacity} />
    </mesh>
  );
}

/** `NEXT · B 3 2 1`, beside the block it names. Mono, per DESIGN.md §2. */
function TargetLabel({ block }: { block: TwinBlock }) {
  const at = cellToScene(block.mode, block.col, block.row, block.level);
  const size = blockSceneSize(block.mode);
  return (
    <Html position={[at.x, at.y + size.y, at.z]} center distanceFactor={40}
          zIndexRange={[5, 0]} pointerEvents="none">
      <span className="twin-label"><b>NEXT</b>{block.label}</span>
    </Html>
  );
}

/**
 * Two poses and no tweens.
 *
 * SYNC VIEW (Plan 4 §9.3) is `viewPose("top", aspect, workspaceBoxScene())` —
 * the ground rectangle the overhead camera frames, from straight above, with
 * machine +X to the right and +Y up the screen. M1 chose the top view's up
 * vector for exactly this, and `view.test.ts` holds it there. While it is on the
 * orbit is disabled and the panel says so: an orbit that silently breaks the
 * sync is a control that lies.
 *
 * Unsynced, the twin frames the whole envelope once and then LEAVES THE CAMERA
 * ALONE — a resize must never yank a view the operator has orbited to.
 */
function TwinCamera({ synced }: { synced: boolean }) {
  const { camera, size, controls, invalidate } = useThree();
  const previous = useRef<string | null>(null);
  useLayoutEffect(() => {
    const command = synced ? "top" : "iso";
    const changed = previous.current !== command;
    previous.current = command;
    // Synced reframes on every resize, because matching the camera's framing is
    // the entire point of it; unsynced frames once and never again.
    if (!changed && !synced) return;
    const aspect = size.width / Math.max(size.height, 1);
    const pose = synced ? viewPose("top", aspect, workspaceBoxScene())
                        : viewPose("iso", aspect);
    camera.up.set(pose.up.x, pose.up.y, pose.up.z);
    camera.position.set(pose.position.x, pose.position.y, pose.position.z);
    const orbit = controls as
      { target?: { set(x: number, y: number, z: number): void }; update?(): void } | null;
    orbit?.target?.set(pose.target.x, pose.target.y, pose.target.z);
    orbit?.update?.();
    camera.lookAt(pose.target.x, pose.target.y, pose.target.z);
    invalidate();
  }, [synced, size.width, size.height, camera, controls, invalidate]);
  return null;
}

/** Redraws once whenever the mapping's answer changes, and not otherwise. */
function OnSceneChange({ scene }: { scene: TwinScene }) {
  const { invalidate } = useThree();
  useLayoutEffect(() => { invalidate(); }, [scene, invalidate]);
  return null;
}

function TwinScene3D({ scene, synced, mode }: {
  scene: TwinScene; synced: boolean; mode: ModeName;
}) {
  const box = useMemo(() => envelopeBoxScene(), []);
  const centre = boxCentre(box);
  const groups = useMemo(() => {
    const result = {} as Record<typeof BATCHED[number], Record<ModeName, TwinBlock[]>>;
    for (const appearance of BATCHED) result[appearance] = { vertical: [], horizontal: [] };
    for (const block of scene.blocks) {
      if (block.appearance !== "building") result[block.appearance][block.mode].push(block);
    }
    return result;
  }, [scene.blocks]);
  const building = scene.blocks.find(block => block.appearance === "building") ?? null;
  const target = scene.blocks.find(block => block.label !== null) ?? null;
  const placed = useMemo(
    () => scene.blocks.filter(block => block.appearance === "placed"),
    [scene.blocks],
  );

  return (
    <>
      {/* No key light and no shadow map: two cheap lights and the tokens. */}
      <hemisphereLight intensity={0.62} groundColor={tokenColor("--void")}
                       color={tokenColor("--line-strong")} />
      <directionalLight intensity={1.4} position={[centre.x + 18, centre.y + 34, centre.z + 22]} />

      <Envelope box={box} />
      <Lattice mode={mode} />
      <BlockShadows blocks={placed} />
      {BATCHED.flatMap(appearance => MODES.map(blockMode => {
        const blocks = groups[appearance][blockMode];
        if (blocks.length === 0) return null;
        return (
          <BlockBatch key={`${appearance}-${blockMode}`} blocks={blocks} mode={blockMode}
                      activeMode={blockMode} animateIds={NO_ANIMATION} reduced
                      opacity={blocks[0].opacity} handlers={NO_HANDLERS} quality="twin"
                      colourOf={appearanceColour} />
        );
      }))}
      {building ? <Building block={building} offset={scene.blockOffset}
                            indicator={scene.indicator} descent={scene.descent} /> : null}
      {target ? <TargetLabel block={target} /> : null}

      <RigOrbitControls enabled={!synced}
                     target={[centre.x, centre.y, centre.z]}
                     minDistance={6} maxDistance={700} />
      <TwinCamera synced={synced} />
      <OnSceneChange scene={scene} />
    </>
  );
}

export interface TwinProps {
  scene: TwinScene;
  synced: boolean;
  /** False when the panel is off screen; the canvas then draws nothing at all. */
  active: boolean;
  /** The lattice to draw: a read-only mirror of `state.mode`. */
  mode: ModeName;
}

export default memo(function Twin({ scene, synced, active, mode }: TwinProps) {
  return (
    <Canvas
      frameloop={active ? "demand" : "never"}
      dpr={[1, 1.5]}
      gl={{ antialias: false, alpha: true, stencil: false, depth: true,
            powerPreference: "low-power" }}
      camera={{ fov: FOV_DEG, near: 0.5, far: 800, position: [34, 30, 34] }}
    >
      <TwinScene3D scene={scene} synced={synced} mode={mode} />
    </Canvas>
  );
});
