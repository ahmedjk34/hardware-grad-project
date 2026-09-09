/**
 * The active mode's grid: every addressable cell at its true footprint, with
 * the true gaps, the feeder hatched, and the cells a shift has clipped struck
 * through in amber exactly as the firmware would report them.
 *
 * Which cells those are is decided in `studio/lattice.ts` and tested there.
 * This file draws the list it is given and nothing else.
 */
import { Fragment, memo, useLayoutEffect, useMemo, useRef } from "react";
import type { ThreeEvent } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import {
  BufferGeometry, DoubleSide, Float32BufferAttribute, Matrix4, type InstancedMesh,
} from "three";
import { latticeCells, trueFeederMarker, type LatticeCell } from "../lattice";
import type { ModeName, Shift } from "../coords";
import { resolveGroundTarget } from "../pick";
import { hatchTexture, tokenColor } from "./theme";
import type { SurfaceHandlers, SurfacePointer } from "./surface";

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

function surfaceHit(event: ThreeEvent<PointerEvent>, mode: ModeName, shift?: Shift): SurfacePointer | null {
  const target = resolveGroundTarget(event.point, mode, shift);
  return target ? {
    target,
    clientX: event.nativeEvent.clientX, clientY: event.nativeEvent.clientY,
    pointerId: event.nativeEvent.pointerId,
    altKey: event.nativeEvent.altKey, shiftKey: event.nativeEvent.shiftKey,
  } : null;
}

function surfaceHandler(mode: ModeName, shift: Shift | undefined,
                        callback: SurfaceHandlers["onSurfaceMove"] | undefined) {
  return (event: ThreeEvent<PointerEvent>) => {
    const hit = surfaceHit(event, mode, shift);
    if (hit && callback) callback(hit);
  };
}

function CellFills({ cells, token, opacity, mode, shift, handlers }: {
  cells: LatticeCell[]; token: string; opacity: number; mode: ModeName; shift?: Shift;
  handlers: SurfaceHandlers;
}) {
  const mesh = useRef<InstancedMesh>(null);
  const colour = tokenColor(token);
  const size = cells[0];
  const matrix = useMemo(() => new Matrix4(), []);

  useLayoutEffect(() => {
    if (!mesh.current) return;
    cells.forEach((cell, index) => {
      matrix.makeRotationX(-Math.PI / 2);
      matrix.setPosition(cell.centre.x, GROUND_Y, cell.centre.z);
      mesh.current!.setMatrixAt(index, matrix);
    });
    mesh.current.count = cells.length;
    mesh.current.instanceMatrix.needsUpdate = true;
    mesh.current.computeBoundingSphere();
  }, [cells, matrix]);

  if (!size) return null;
  return (
    <instancedMesh ref={mesh} args={[undefined, undefined, cells.length]}
                   onPointerMove={surfaceHandler(mode, shift, handlers.onSurfaceMove)}
                   onPointerDown={surfaceHandler(mode, shift, handlers.onSurfaceDown)}
                   onPointerUp={surfaceHandler(mode, shift, handlers.onSurfaceUp)}
                   onPointerOut={handlers.onSurfaceLeave}>
      <planeGeometry args={[size.sizeX, size.sizeZ]} />
      <meshBasicMaterial color={colour} transparent opacity={opacity} side={DoubleSide} />
    </instancedMesh>
  );
}

export const Lattice = memo(function Lattice({ mode, shift, ...handlers }: {
  mode: ModeName; shift?: Shift;
} & SurfaceHandlers) {
  const cells = useMemo(() => latticeCells(mode, shift), [mode, shift]);
  const plain = cells.filter(cell => cell.kind === "cell");
  const clipped = cells.filter(cell => cell.kind === "clipped");
  const feeder = cells.find(cell => cell.kind === "feeder");
  // The physical feeder — vertical [0,0] / the home corner — when it is NOT the
  // drawn [0,0] cell (i.e. horizontal mode). A block is fed and camera-checked
  // there regardless of the active grid.
  const trueFeeder = useMemo(() => trueFeederMarker(mode), [mode]);
  const hatch = useMemo(() => {
    const texture = hatchTexture("--text-dim");
    // One repeat per centimetre of footprint, so the stripes stay square
    // whichever way round the feeder cell is in this mode.
    if (feeder) texture.repeat.set(Math.max(1, feeder.sizeX), Math.max(1, feeder.sizeZ));
    return texture;
  }, [feeder?.sizeX, feeder?.sizeZ]);
  const trueFeederHatch = useMemo(() => {
    const texture = hatchTexture("--motion");
    if (trueFeeder) {
      texture.repeat.set(Math.max(1, trueFeeder.sizeX), Math.max(1, trueFeeder.sizeZ));
    }
    return texture;
  }, [trueFeeder?.sizeX, trueFeeder?.sizeZ]);
  const outlines = useMemo(() => outlineGeometry(plain, false), [plain]);
  const clippedOutlines = useMemo(() => outlineGeometry(clipped, true), [clipped]);
  const trueFeederOutline = useMemo(() => trueFeeder
    ? outlineGeometry([{
        col: 0, row: 0, kind: "feeder" as const,
        centre: { x: trueFeeder.centre.x, y: 0, z: trueFeeder.centre.z },
        sizeX: trueFeeder.sizeX, sizeZ: trueFeeder.sizeZ,
      }], false)
    : null, [trueFeeder]);

  return (
    <group>
      <CellFills cells={plain} token="--signal" opacity={0.3} mode={mode} shift={shift} handlers={handlers} />
      <CellFills cells={clipped} token="--motion" opacity={0.22} mode={mode} shift={shift} handlers={handlers} />

      <lineSegments geometry={outlines}>
        <lineBasicMaterial color={tokenColor("--signal")} transparent opacity={0.65} />
      </lineSegments>
      <lineSegments geometry={clippedOutlines}>
        <lineBasicMaterial color={tokenColor("--motion")} />
      </lineSegments>
      {feeder && (
        <Fragment>
          <mesh rotation={[-Math.PI / 2, 0, 0]}
                position={[feeder.centre.x, GROUND_Y, feeder.centre.z]}
                onPointerMove={surfaceHandler(mode, shift, handlers.onSurfaceMove)}
                onPointerDown={surfaceHandler(mode, shift, handlers.onSurfaceDown)}
                onPointerUp={surfaceHandler(mode, shift, handlers.onSurfaceUp)}
                onPointerOut={handlers.onSurfaceLeave}>
            <planeGeometry args={[feeder.sizeX, feeder.sizeZ]} />
            <meshBasicMaterial map={hatch} transparent opacity={0.5} side={DoubleSide} />
          </mesh>
          <Html center position={[feeder.centre.x, GROUND_Y, feeder.centre.z]}>
            <span className="studio-tag">PICKUP</span>
          </Html>
        </Fragment>
      )}
      {trueFeeder && (
        <Fragment>
          <mesh rotation={[-Math.PI / 2, 0, 0]}
                position={[trueFeeder.centre.x, GROUND_Y, trueFeeder.centre.z]}>
            <planeGeometry args={[trueFeeder.sizeX, trueFeeder.sizeZ]} />
            <meshBasicMaterial map={trueFeederHatch} transparent opacity={0.4} side={DoubleSide} />
          </mesh>
          {trueFeederOutline && (
            <lineSegments geometry={trueFeederOutline}>
              <lineBasicMaterial color={tokenColor("--motion")} transparent opacity={0.85} />
            </lineSegments>
          )}
          <Html center position={[trueFeeder.centre.x, GROUND_Y, trueFeeder.centre.z]}>
            <span className="studio-tag is-true-feeder">FEEDER · VERTICAL [0,0]</span>
          </Html>
        </Fragment>
      )}
    </group>
  );
});
