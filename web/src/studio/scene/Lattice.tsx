/**
 * The active mode's grid: every addressable cell at its true footprint, with
 * the true gaps, the feeder hatched, and the cells a shift has clipped struck
 * through in amber exactly as the firmware would report them.
 *
 * Which cells those are is decided in `studio/lattice.ts` and tested there.
 * This file draws the list it is given and nothing else.
 */
import { Fragment, useMemo } from "react";
import { Html } from "@react-three/drei";
import { BufferGeometry, DoubleSide, Float32BufferAttribute } from "three";
import { latticeCells, type LatticeCell } from "../lattice";
import type { ModeName, Shift } from "../coords";
import { hatchTexture, tokenColor } from "./theme";

/** Just clear of the ground so the fills never z-fight the contact shadow. */
const GROUND_Y = 0.01;
const OUTLINE_Y = 0.02;

function outlineGeometry(cells: LatticeCell[], withCross: boolean): BufferGeometry {
  const points: number[] = [];
  for (const cell of cells) {
    const x0 = cell.centre.x - cell.sizeX / 2, x1 = cell.centre.x + cell.sizeX / 2;
    const z0 = cell.centre.z - cell.sizeZ / 2, z1 = cell.centre.z + cell.sizeZ / 2;
    points.push(
      x0, OUTLINE_Y, z0, x1, OUTLINE_Y, z0,
      x1, OUTLINE_Y, z0, x1, OUTLINE_Y, z1,
      x1, OUTLINE_Y, z1, x0, OUTLINE_Y, z1,
      x0, OUTLINE_Y, z1, x0, OUTLINE_Y, z0);
    // A clipped cell is crossed through: it is still addressable, the shift has
    // simply put it past the travel cap.
    if (withCross) points.push(x0, OUTLINE_Y, z0, x1, OUTLINE_Y, z1, x1, OUTLINE_Y, z0, x0, OUTLINE_Y, z1);
  }
  const geometry = new BufferGeometry();
  geometry.setAttribute("position", new Float32BufferAttribute(points, 3));
  return geometry;
}

function CellFills({ cells, token, opacity }: { cells: LatticeCell[]; token: string; opacity: number }) {
  const colour = tokenColor(token);
  return (
    <Fragment>
      {cells.map(cell => (
        <mesh key={`${cell.col},${cell.row}`} rotation={[-Math.PI / 2, 0, 0]}
              position={[cell.centre.x, GROUND_Y, cell.centre.z]}>
          <planeGeometry args={[cell.sizeX, cell.sizeZ]} />
          <meshBasicMaterial color={colour} transparent opacity={opacity} side={DoubleSide} />
        </mesh>
      ))}
    </Fragment>
  );
}

export function Lattice({ mode, shift }: { mode: ModeName; shift?: Shift }) {
  const cells = useMemo(() => latticeCells(mode, shift), [mode, shift]);
  const plain = cells.filter(cell => cell.kind === "cell");
  const clipped = cells.filter(cell => cell.kind === "clipped");
  const feeder = cells.find(cell => cell.kind === "feeder");
  const hatch = useMemo(() => {
    const texture = hatchTexture("--text-dim");
    // One repeat per centimetre of footprint, so the stripes stay square
    // whichever way round the feeder cell is in this mode.
    if (feeder) texture.repeat.set(Math.max(1, feeder.sizeX), Math.max(1, feeder.sizeZ));
    return texture;
  }, [feeder?.sizeX, feeder?.sizeZ]);

  const outlines = useMemo(() => outlineGeometry(plain, false), [plain]);
  const clippedOutlines = useMemo(() => outlineGeometry(clipped, true), [clipped]);

  return (
    <group>
      <CellFills cells={plain} token="--signal" opacity={0.3} />
      <CellFills cells={clipped} token="--motion" opacity={0.22} />

      <lineSegments geometry={outlines}>
        <lineBasicMaterial color={tokenColor("--signal")} transparent opacity={0.65} />
      </lineSegments>
      <lineSegments geometry={clippedOutlines}>
        <lineBasicMaterial color={tokenColor("--motion")} />
      </lineSegments>

      {feeder && (
        <Fragment>
          <mesh rotation={[-Math.PI / 2, 0, 0]}
                position={[feeder.centre.x, GROUND_Y, feeder.centre.z]}>
            <planeGeometry args={[feeder.sizeX, feeder.sizeZ]} />
            <meshBasicMaterial map={hatch} transparent opacity={0.5} side={DoubleSide} />
          </mesh>
          <Html center position={[feeder.centre.x, GROUND_Y, feeder.centre.z]}>
            <span className="studio-tag">FEED</span>
          </Html>
        </Fragment>
      )}
    </group>
  );
}
