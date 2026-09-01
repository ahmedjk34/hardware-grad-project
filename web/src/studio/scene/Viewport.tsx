/**
 * The 3D viewport: a dark space holding an accurate, to-scale render of the
 * machine. Surface meshes report raycast hits in cell space while the route
 * owns model edits, history and keyboard state.
 *
 * The camera maths lives in `studio/view.ts` and is tested there; this file
 * moves a three.js camera to the poses that module hands it. Per DESIGN.md
 * section 3.4 the frameloop is on demand, so an idle Studio renders nothing at
 * all rather than burning a phone's battery animating a still picture.
 */
import { useEffect, useLayoutEffect, useMemo, useRef } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { Vector3 } from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import type { ModeName, Shift } from "../coords";
import type { Model } from "../model";
import type { CellTarget } from "../pick";
import type { Diagnostic } from "../validate";
import {
  FOV_DEG, MAX_POLAR_ANGLE, boxCentre, clampAboveGround, envelopeBoxScene,
  cameraTransitionMs, frameBox, introMs, introPose, viewPose,
  type Box, type CameraPose, type ViewName,
} from "../view";
import { Envelope } from "./Envelope";
import { Lattice } from "./Lattice";
import { Blocks } from "./Blocks";
import { BlockShadows } from "./BlockShadows";
import { Ghost, type GhostStatus } from "./Ghost";
import { Capture, type CaptureHandle } from "./Capture";
import { DiagnosticMarkers } from "./DiagnosticMarkers";
import { tokenColor } from "./theme";
import type { SurfaceHandlers } from "./surface";
import { useReducedMotion } from "../../media";

const ease = (t: number) => 1 - Math.pow(1 - t, 3);

/**
 * Drives the camera. Three jobs, in order of how often they run:
 *
 *  1. The intro, once per mount: `view.introPose()` walks the camera from in
 *     close out to the framed pose, swinging round the machine as it goes. It is guarded by `phase`, a ref, NOT by React state - a resize, a
 *     browser zoom, a rerender or a reframe must never start a second one. That
 *     was the "zooms in, then zooms out again" bug: the effect below reruns on
 *     every size change, and without the guard each rerun restarted the move.
 *  2. Explicit view commands after that, tweened for `TWEEN_MS`.
 *  3. Everything else - a first pose under reduced motion, a size-only reframe -
 *     snaps on the next frame, because animating those is the bug, not a feature.
 *
 * The frameloop is on demand, so `invalidate()` is called only while something
 * is actually moving; the moment a move lands, the scene goes quiet again.
 */
function CameraRig({ view, nonce, reduced, focusBox }: {
  view: ViewName; nonce: number; reduced: boolean; focusBox: Box | null;
}) {
  const { camera, size, invalidate, controls } = useThree();
  const tween = useRef<{ from: { position: Vector3; target: Vector3; up: Vector3 };
                         to: { position: Vector3; target: Vector3; up: Vector3 };
                         start: number; duration: number } | null>(null);
  /** The one-time intro guard. "pending" only ever becomes "intro" once. */
  const phase = useRef<"pending" | "intro" | "live">("pending");
  const intro = useRef<{ pose: CameraPose; start: number; duration: number } | null>(null);
  const previousCommand = useRef<string | null>(null);

  const apply = (to: { position: Vector3; target: Vector3; up: Vector3 }) => {
    const orbit = controls as OrbitControlsImpl | null;
    camera.up.copy(to.up);
    camera.position.copy(to.position);
    if (orbit) { orbit.target.copy(to.target); orbit.update(); }
    camera.lookAt(to.target);
  };

  const vectors = (pose: CameraPose) => ({
    position: new Vector3(pose.position.x, pose.position.y, pose.position.z),
    target: new Vector3(pose.target.x, pose.target.y, pose.target.z),
    up: new Vector3(pose.up.x, pose.up.y, pose.up.z),
  });

  useLayoutEffect(() => {
    const aspect = size.width / Math.max(size.height, 1);
    const pose = focusBox ? frameBox(focusBox, aspect) : viewPose(view, aspect);
    const command = `${view}:${nonce}`;

    // A resize mid-intro moves the DESTINATION, never the clock: the operator
    // sees one continuous pull-back that happens to end correctly framed.
    if (phase.current === "intro" && intro.current) {
      intro.current.pose = pose;
      invalidate();
      return;
    }

    if (phase.current === "pending") {
      previousCommand.current = command;
      const duration = introMs(reduced);
      if (duration === 0) { phase.current = "live"; apply(vectors(pose)); invalidate(); return; }
      phase.current = "intro";
      intro.current = { pose, start: performance.now(), duration };
      apply(vectors(introPose(pose, 0)));
      invalidate();
      return;
    }

    const explicitCommand = previousCommand.current !== command;
    const duration = cameraTransitionMs(true, explicitCommand, reduced);
    previousCommand.current = command;
    if (duration === 0) {
      apply(vectors(pose));
      tween.current = null;
      invalidate();
      return;
    }
    const orbit = controls as OrbitControlsImpl | null;
    tween.current = {
      from: {
        position: camera.position.clone(),
        target: orbit ? orbit.target.clone() : new Vector3(),
        up: camera.up.clone(),
      },
      to: vectors(pose), start: performance.now(), duration,
    };
    invalidate();
    // `apply` and `vectors` close over camera/controls, which the deps below track.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, nonce, reduced, focusBox, size.width, size.height, camera, controls, invalidate]);

  // The operator wins: touching the controls during the intro lands it at once,
  // so the tool never feels like it is holding the camera hostage.
  useEffect(() => {
    const orbit = controls as OrbitControlsImpl | null;
    if (!orbit) return;
    const land = () => {
      if (phase.current !== "intro" || !intro.current) return;
      phase.current = "live";
      intro.current = null;
      invalidate();
    };
    orbit.addEventListener("start", land);
    return () => orbit.removeEventListener("start", land);
  }, [controls, invalidate]);

  useFrame(() => {
    const orbit = controls as OrbitControlsImpl | null;

    const opening = intro.current;
    if (opening) {
      const t = Math.min(1, (performance.now() - opening.start) / opening.duration);
      apply(vectors(introPose(opening.pose, t)));
      if (t >= 1) { intro.current = null; phase.current = "live"; } else invalidate();
      return;
    }

    const active = tween.current;
    if (active) {
      const t = Math.min(1, (performance.now() - active.start) / active.duration);
      const k = ease(t);
      camera.position.lerpVectors(active.from.position, active.to.position, k);
      camera.up.lerpVectors(active.from.up, active.to.up, k).normalize();
      if (orbit) orbit.target.lerpVectors(active.from.target, active.to.target, k);
      camera.lookAt(orbit ? orbit.target : active.to.target);
      if (t >= 1) tween.current = null; else invalidate();
      return;
    }
    // The orbit is capped at the horizon, but a pan can still drag the camera
    // under the floor; the constraint is arithmetic, so it is applied here.
    const clamped = clampAboveGround(camera.position);
    if (clamped.y !== camera.position.y) { camera.position.y = clamped.y; invalidate(); }
  });

  return null;
}

function Scene({ mode, shift, view, nonce, reduced, model, target, status, heldLevel,
                 diagnostics, emphasizedId, focusBox, captureHandle, ...handlers }: {
  mode: ModeName; shift?: Shift; view: ViewName; nonce: number; reduced: boolean;
  model: Model; target: CellTarget | null; status: GhostStatus | null; heldLevel: number | null;
  diagnostics: Diagnostic[]; emphasizedId?: string | null; focusBox: Box | null;
  captureHandle?: CaptureHandle;
} & SurfaceHandlers) {
  const box = useMemo(() => envelopeBoxScene(), []);
  const centre = boxCentre(box);
  return (
    <>
      {/* Section 8.2: one key with soft shadows, one dim fill, a faint hemisphere. */}
      <hemisphereLight intensity={0.35} groundColor={tokenColor("--void")} color={tokenColor("--line-strong")} />
      <directionalLight
        intensity={1.5}
        position={[centre.x + 18, centre.y + 34, centre.z + 22]}
      />
      <directionalLight intensity={0.35} position={[centre.x - 26, centre.y + 12, centre.z - 20]} />

      <Envelope box={box} />
      <Lattice mode={mode} shift={shift} {...handlers} />
      <BlockShadows blocks={model.blocks} />
      <Blocks blocks={model.blocks} activeMode={mode} shift={shift} heldLevel={heldLevel}
              reduced={reduced} {...handlers} />
      <DiagnosticMarkers blocks={model.blocks} diagnostics={diagnostics} emphasizedId={emphasizedId} />
      <Ghost mode={mode} shift={shift} target={target} status={status} />

      <OrbitControls
        makeDefault enableDamping={false}
        maxPolarAngle={MAX_POLAR_ANGLE}
        target={[centre.x, centre.y, centre.z]}
        minDistance={4} maxDistance={260}
        zoomSpeed={1.25} rotateSpeed={0.9} panSpeed={0.9}
      />
      <CameraRig view={view} nonce={nonce} reduced={reduced} focusBox={focusBox} />
      {captureHandle ? <Capture handle={captureHandle} /> : null}
    </>
  );
}

export interface ViewportProps {
  mode: ModeName;
  shift?: Shift;
  view: ViewName;
  /** Bumped by the caller to re-snap to the view that is already selected. */
  nonce?: number;
  model: Model;
  target: CellTarget | null;
  status: GhostStatus | null;
  heldLevel: number | null;
  diagnostics?: Diagnostic[];
  emphasizedId?: string | null;
  focusBox?: Box | null;
  /** Filled with a thumbnail capture while the canvas is mounted; see Capture. */
  captureHandle?: CaptureHandle;
}

export function Viewport({ mode, shift, view, nonce = 0, model, target, status, heldLevel,
                           diagnostics = [], emphasizedId, focusBox = null, captureHandle,
                           onSurfaceMove, onSurfaceDown, onSurfaceUp, onSurfaceLeave }: ViewportProps & SurfaceHandlers) {
  const reduced = useReducedMotion();
  return (
    <div className="studio-viewport" onPointerLeave={onSurfaceLeave}>
      <Canvas
        frameloop="demand"
        dpr={[1, 1.5]}
        gl={{ antialias: true, alpha: true, stencil: false, powerPreference: "high-performance" }}
        camera={{ fov: FOV_DEG, near: 0.5, far: 800 }}
      >
        <Scene mode={mode} shift={shift} view={view} nonce={nonce} reduced={reduced}
               model={model} target={target} status={status} heldLevel={heldLevel}
               diagnostics={diagnostics} emphasizedId={emphasizedId} focusBox={focusBox}
               captureHandle={captureHandle}
               onSurfaceMove={onSurfaceMove} onSurfaceDown={onSurfaceDown}
               onSurfaceUp={onSurfaceUp} onSurfaceLeave={onSurfaceLeave} />
      </Canvas>
    </div>
  );
}
