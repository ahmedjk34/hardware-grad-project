/** Orbit controls with an explicit, reliable mouse-wheel contract.
 *
 * three-stdlib ignores wheel input while its internal pointer state is not
 * NONE/ROTATE. R3F placement surfaces also consume pointer events, so a lost
 * pointer-up can leave wheel-down unable to dolly out. Handle the wheel at the
 * canvas capture boundary and use OrbitControls' public dolly methods instead:
 * positive delta is always out, negative delta is always in.
 */
import { useEffect, useRef } from "react";
import { useThree } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { MAX_POLAR_ANGLE, wheelDollyScale, wheelZoomDirection } from "../view";

export function RigOrbitControls({
  target, enabled = true, minDistance, maxDistance, zoomSpeed = 1,
  rotateSpeed = 1, panSpeed = 1,
}: {
  target: [number, number, number];
  enabled?: boolean;
  minDistance: number;
  maxDistance: number;
  zoomSpeed?: number;
  rotateSpeed?: number;
  panSpeed?: number;
}) {
  const controls = useRef<OrbitControlsImpl>(null);
  const { gl, invalidate } = useThree();

  useEffect(() => {
    const element = gl.domElement;
    const onWheel = (event: WheelEvent) => {
      const direction = wheelZoomDirection(event.deltaY);
      const orbit = controls.current;
      if (!enabled || !direction || !orbit) return;

      event.preventDefault();
      // Stop three-stdlib's state-gated wheel listener on this same canvas.
      event.stopImmediatePropagation();
      orbit.dispatchEvent({ type: "start", target: orbit });
      const scale = wheelDollyScale(zoomSpeed);
      if (direction === "out") orbit.dollyOut(scale);
      else orbit.dollyIn(scale);
      orbit.dispatchEvent({ type: "end", target: orbit });
      invalidate();
    };

    element.addEventListener("wheel", onWheel, { capture: true, passive: false });
    return () => element.removeEventListener("wheel", onWheel, { capture: true });
  }, [enabled, gl, invalidate, zoomSpeed]);

  return (
    <OrbitControls
      ref={controls}
      makeDefault
      enableDamping={false}
      // Zoom is handled entirely by the wheel listener above via dollyIn/dollyOut;
      // three-stdlib's own state-gated wheel handler would otherwise race it on
      // the same canvas element regardless of listener registration order.
      enableZoom={false}
      enabled={enabled}
      maxPolarAngle={MAX_POLAR_ANGLE}
      target={target}
      minDistance={minDistance}
      maxDistance={maxDistance}
      zoomSpeed={zoomSpeed}
      rotateSpeed={rotateSpeed}
      panSpeed={panSpeed}
    />
  );
}
