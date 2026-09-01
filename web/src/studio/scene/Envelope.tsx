/**
 * The travel cap: a thin wireframe box with centimetre rulers on two edges.
 *
 * This is the machine's real limit, so it is always visible and it is never
 * inferred from the lattice - it comes from `workspace` in config/rig.json by
 * way of `view.envelopeBoxScene()`. Nothing here computes a coordinate.
 */
import { useMemo } from "react";
import { Html } from "@react-three/drei";
import { BufferGeometry, EdgesGeometry, BoxGeometry, Float32BufferAttribute } from "three";
import { rulerTicks } from "../lattice";
import { boxCentre, envelopeBoxScene, type Box } from "../view";
import { tokenColor } from "./theme";

/** Tick length in scene units — 1 unit is 1 cm, so these are millimetres. */
const MINOR = 0.25;
const MAJOR = 0.6;

/** Both rulers as one line geometry: the X edge at machine Y=0, the Y edge at X=0. */
function useRulerGeometry(box: Box): BufferGeometry {
  return useMemo(() => {
    const points: number[] = [];
    for (const tick of rulerTicks(box.max.x - box.min.x)) {
      const length = tick.major ? MAJOR : MINOR;
      const x = box.min.x + tick.at;
      points.push(x, box.min.y, box.max.z, x, box.min.y, box.max.z + length);
    }
    for (const tick of rulerTicks(box.max.z - box.min.z)) {
      const length = tick.major ? MAJOR : MINOR;
      const z = box.max.z - tick.at;
      points.push(box.min.x, box.min.y, z, box.min.x - length, box.min.y, z);
    }
    const geometry = new BufferGeometry();
    geometry.setAttribute("position", new Float32BufferAttribute(points, 3));
    return geometry;
  }, [box]);
}

export function Envelope({ box = envelopeBoxScene() }: { box?: Box }) {
  const centre = boxCentre(box);
  const size = { x: box.max.x - box.min.x, y: box.max.y - box.min.y, z: box.max.z - box.min.z };
  const cage = useMemo(
    () => new EdgesGeometry(new BoxGeometry(size.x, size.y, size.z)),
    [size.x, size.y, size.z]);
  const rulers = useRulerGeometry(box);
  const line = tokenColor("--line-strong");
  const dim = tokenColor("--text-faint");

  return (
    <group>
      <lineSegments geometry={cage} position={[centre.x, centre.y, centre.z]}>
        <lineBasicMaterial color={line} transparent opacity={0.65} />
      </lineSegments>

      <lineSegments geometry={rulers}>
        <lineBasicMaterial color={dim} />
      </lineSegments>

      {rulerTicks(box.max.x - box.min.x).filter(tick => tick.major).map(tick => (
        <Html key={`x${tick.cm}`} center
              position={[box.min.x + tick.at, box.min.y, box.max.z + MAJOR + 0.6]}>
          <span className="studio-tick">{tick.cm}</span>
        </Html>
      ))}
      {rulerTicks(box.max.z - box.min.z).filter(tick => tick.major).map(tick => (
        <Html key={`y${tick.cm}`} center
              position={[box.min.x - MAJOR - 0.7, box.min.y, box.max.z - tick.at]}>
          <span className="studio-tick">{tick.cm}</span>
        </Html>
      ))}
    </group>
  );
}
