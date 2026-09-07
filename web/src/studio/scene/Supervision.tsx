/**
 * The board's verdict, drawn over the twin's lattice.
 *
 * A separate overlay LAYER, keyed by cell — never a sixth `TwinAppearance`.
 * The twin's five appearances say what the RIG is doing with a block; a
 * verdict says what the BOARD looks like, from a different instrument. Folding
 * one into the other would let either overwrite the other's meaning.
 *
 * This is the QUIETEST of supervision's four surfaces. The camera overlay is
 * the spatial answer, the banner is the alarm, the runner is the history, and
 * this is the plan-space echo — an outline, no fill, no motion. It draws the
 * list it is given and decides nothing.
 */
import { memo, useMemo } from "react";
import { BufferGeometry, Float32BufferAttribute } from "three";
import { latticeCells } from "../lattice";
import type { ModeName, Shift } from "../coords";
import { hatchTexture, tokenColor } from "./theme";

/** Above the lattice's own outlines so a marked cell reads on top of them. */
const MARK_Y = 0.05;

function ringGeometry(cells: { centre: { x: number; z: number }; sizeX: number; sizeZ: number }[]) {
  const points: number[] = [];
  for (const cell of cells) {
    const x0 = cell.centre.x - cell.sizeX / 2, x1 = cell.centre.x + cell.sizeX / 2;
    const z0 = cell.centre.z - cell.sizeZ / 2, z1 = cell.centre.z + cell.sizeZ / 2;
    points.push(
      x0, MARK_Y, z0, x1, MARK_Y, z0,
      x1, MARK_Y, z0, x1, MARK_Y, z1,
      x1, MARK_Y, z1, x0, MARK_Y, z1,
      x0, MARK_Y, z1, x0, MARK_Y, z0);
  }
  const geometry = new BufferGeometry();
  geometry.setAttribute("position", new Float32BufferAttribute(points, 3));
  return geometry;
}

export const SupervisionLayer = memo(function SupervisionLayer({
  mode, shift, cells, unjudged, severity,
}: {
  mode: ModeName;
  shift?: Shift;
  cells: [number, number][];
  unjudged: [number, number][];
  severity: "none" | "amber" | "red";
}) {
  const lattice = useMemo(() => latticeCells(mode, shift), [mode, shift]);
  const key = (col: number, row: number) => `${col},${row}`;
  const marked = useMemo(() => {
    const wanted = new Set(cells.map(([col, row]) => key(col, row)));
    return lattice.filter(cell => wanted.has(key(cell.col, cell.row)));
  }, [lattice, cells]);
  const refused = useMemo(() => {
    const wanted = new Set(unjudged.map(([col, row]) => key(col, row)));
    return lattice.filter(cell => wanted.has(key(cell.col, cell.row)));
  }, [lattice, unjudged]);

  const geometry = useMemo(() => ringGeometry(marked), [marked]);
  // A HATCH, never a colour: a cell nobody could judge has no machine state,
  // and dressing an absence of state in a state colour spends the reserved
  // palette on nothing.
  const hatch = useMemo(() => hatchTexture("--text-faint"), []);
  const size = refused[0];

  return (
    <>
      {marked.length > 0 && severity !== "none" && (
        <lineSegments geometry={geometry}>
          <lineBasicMaterial
            color={tokenColor(severity === "red" ? "--danger" : "--motion")}
            transparent
            opacity={0.95}
          />
        </lineSegments>
      )}
      {size && refused.map(cell => (
        <mesh key={`sv-unjudged-${cell.col}-${cell.row}`}
              position={[cell.centre.x, MARK_Y, cell.centre.z]}
              rotation={[-Math.PI / 2, 0, 0]}>
          <planeGeometry args={[cell.sizeX, cell.sizeZ]} />
          <meshBasicMaterial map={hatch} transparent opacity={0.35} />
        </mesh>
      ))}
    </>
  );
});
