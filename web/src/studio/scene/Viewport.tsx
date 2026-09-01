/**
 * The 3D viewport: a dark space holding an accurate, to-scale render of the
 * machine. Nothing in here is interactive yet beyond the camera — placement
 * arrives in M2.
 *
 * The camera maths lives in `studio/view.ts` and is tested there; this file
 * moves a three.js camera to the poses that module hands it. Per DESIGN.md
 * section 3.4 the frameloop is on demand, so an idle Studio renders nothing at
 * all rather than burning a phone's battery animating a still picture.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { ContactShadows, OrbitControls } from "@react-three/drei";
import { Vector3 } from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import type { ModeName, Shift } from "../coords";
import {
  FOV_DEG, MAX_POLAR_ANGLE, boxCentre, clampAboveGround, envelopeBoxScene,
  tweenMs, viewPose, type ViewName,
} from "../view";
import { Envelope } from "./Envelope";
import { Lattice } from "./Lattice";
import { tokenColor } from "./theme";

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => window.matchMedia?.(REDUCED_MOTION).matches ?? false);
  useEffect(() => {
    const query = window.matchMedia?.(REDUCED_MOTION);
    if (!query) return;
    const update = () => setReduced(query.matches);
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);
  return reduced;
}

const ease = (t: number) => 1 - Math.pow(1 - t, 3);

/**
 * Drives the camera to a snap pose. `view` changing starts a tween; a viewer
 * who has asked for reduced motion gets the destination on the next frame.
 */
function CameraRig({ view, nonce, reduced }: { view: ViewName; nonce: number; reduced: boolean }) {
  const { camera, size, invalidate, controls } = useThree();
  const tween = useRef<{ from: { position: Vector3; target: Vector3; up: Vector3 };
                         to: { position: Vector3; target: Vector3; up: Vector3 };
                         start: number; duration: number } | null>(null);

  useEffect(() => {
    const orbit = controls as OrbitControlsImpl | null;
    const pose = viewPose(view, size.width / Math.max(size.height, 1));
    const to = {
      position: new Vector3(pose.position.x, pose.position.y, pose.position.z),
      target: new Vector3(pose.target.x, pose.target.y, pose.target.z),
      up: new Vector3(pose.up.x, pose.up.y, pose.up.z),
    };
    const duration = tweenMs(reduced);
    if (duration === 0) {
      camera.up.copy(to.up);
      camera.position.copy(to.position);
      if (orbit) { orbit.target.copy(to.target); orbit.update(); }
      camera.lookAt(to.target);
      tween.current = null;
      invalidate();
      return;
    }
    tween.current = {
      from: {
        position: camera.position.clone(),
        target: orbit ? orbit.target.clone() : new Vector3(),
        up: camera.up.clone(),
      },
      to, start: performance.now(), duration,
    };
    invalidate();
  }, [view, nonce, reduced, size.width, size.height, camera, controls, invalidate]);

  useFrame(() => {
    const orbit = controls as OrbitControlsImpl | null;
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

function Scene({ mode, shift, view, nonce, reduced }: {
  mode: ModeName; shift?: Shift; view: ViewName; nonce: number; reduced: boolean;
}) {
  const box = useMemo(() => envelopeBoxScene(), []);
  const centre = boxCentre(box);

  return (
    <>
      {/* Section 8.2: one key with soft shadows, one dim fill, a faint hemisphere. */}
      <hemisphereLight intensity={0.35} groundColor={tokenColor("--void")} color={tokenColor("--line-strong")} />
      <directionalLight
        castShadow intensity={1.5}
        position={[centre.x + 18, centre.y + 34, centre.z + 22]}
        shadow-mapSize={[1024, 1024]}
        shadow-bias={-0.0005}
        shadow-camera-left={-40} shadow-camera-right={40}
        shadow-camera-top={40} shadow-camera-bottom={-40}
      />
      <directionalLight intensity={0.35} position={[centre.x - 26, centre.y + 12, centre.z - 20]} />

      {/* What later makes a block look placed rather than floating. */}
      <ContactShadows
        position={[centre.x, 0, centre.z]}
        scale={Math.max(box.max.x - box.min.x, box.max.z - box.min.z) * 1.6}
        resolution={1024} blur={2.4} opacity={0.55} far={12} frames={1}
      />

      <Envelope box={box} />
      <Lattice mode={mode} shift={shift} />

      <OrbitControls
        makeDefault enableDamping={false}
        maxPolarAngle={MAX_POLAR_ANGLE}
        target={[centre.x, centre.y, centre.z]}
        minDistance={4} maxDistance={260}
      />
      <CameraRig view={view} nonce={nonce} reduced={reduced} />
    </>
  );
}

export interface ViewportProps {
  mode: ModeName;
  shift?: Shift;
  view: ViewName;
  /** Bumped by the caller to re-snap to the view that is already selected. */
  nonce?: number;
}

export function Viewport({ mode, shift, view, nonce = 0 }: ViewportProps) {
  const reduced = useReducedMotion();
  return (
    <div className="studio-viewport">
      <Canvas
        frameloop="demand"
        shadows
        dpr={[1, 2]}
        gl={{ antialias: true, alpha: true }}
        camera={{ fov: FOV_DEG, near: 0.5, far: 800 }}
      >
        <Scene mode={mode} shift={shift} view={view} nonce={nonce} reduced={reduced} />
      </Canvas>
    </div>
  );
}
