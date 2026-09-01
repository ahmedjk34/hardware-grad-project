/**
 * Placed blocks, batched by their own mode and by the held-level x-ray split.
 *
 * A vertical and horizontal block are different physical boxes, not one box
 * rotated. Each block resolves through `coords.ts` using the mode stored on the
 * block, so changing the active lattice never moves existing geometry.
 */
import { memo, useLayoutEffect, useMemo, useRef, type RefObject } from "react";
import { useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { DynamicDrawUsage, InstancedBufferAttribute, Matrix4, type InstancedMesh } from "three";
import { RoundedBoxGeometry } from "three-stdlib";
import {
  blockSceneSize, cellToScene, type ModeName, type Shift,
} from "../coords";
import type { ModelBlock } from "../model";
import { resolveTopTarget } from "../pick";
import { arrivalFrame, rowArrivalDelays } from "../motion";
import { tokenColor } from "./theme";
import type { SurfaceHandlers, SurfacePointer } from "./surface";

const CAPACITY = 512;
const CORNER_RADIUS_SCENE = 0.06; // 0.6 mm at 10 mm per scene unit.
const configureArrivalShader = (shader: { vertexShader: string; fragmentShader: string }) => {
  shader.vertexShader = shader.vertexShader
    .replace("#include <common>", "#include <common>\nattribute float instanceOpacity;\nvarying float vInstanceOpacity;")
    .replace("#include <color_vertex>", "#include <color_vertex>\nvInstanceOpacity = instanceOpacity;");
  shader.fragmentShader = shader.fragmentShader
    .replace("#include <common>", "#include <common>\nvarying float vInstanceOpacity;")
    .replace("#include <color_fragment>", "#include <color_fragment>\ndiffuseColor.a *= vInstanceOpacity;");
};

const arrivalShaderKey = () => "rig-arrival-opacity-v1";

function nativeHit(event: ThreeEvent<PointerEvent>, target: SurfacePointer["target"], blockId: string): SurfacePointer {
  return {
    target, blockId,
    clientX: event.nativeEvent.clientX, clientY: event.nativeEvent.clientY,
    pointerId: event.nativeEvent.pointerId,
    altKey: event.nativeEvent.altKey, shiftKey: event.nativeEvent.shiftKey,
  };
}

function BlockBatch({ blocks, animateIds, mode, activeMode, shift, opacity, reduced, handlers }: {
  blocks: ModelBlock[];
  animateIds: Set<string>;
  mode: ModeName;
  activeMode: ModeName;
  shift?: Shift;
  opacity: number;
  reduced: boolean;
  handlers: SurfaceHandlers;
}) {
  const settledMesh = useRef<InstancedMesh>(null);
  const arrivingMesh = useRef<InstancedMesh>(null);
  const settledBlocks = useRef<ModelBlock[]>([]);
  const arrivingBlocks = useRef<ModelBlock[]>([]);
  const { invalidate } = useThree();
  const settling = useRef(new Map<string, { started: number; delay: number }>());
  const matrix = useMemo(() => new Matrix4(), []);
  const size = useMemo(() => blockSceneSize(mode), [mode]);
  const geometry = useMemo(
    () => new RoundedBoxGeometry(size.x, size.y, size.z, 1, CORNER_RADIUS_SCENE),
    [size.x, size.y, size.z],
  );
  const instanceOpacity = useMemo(
    () => new InstancedBufferAttribute(new Float32Array(CAPACITY), 1),
    [],
  );

  useLayoutEffect(() => {
    geometry.setAttribute("instanceOpacity", instanceOpacity);
    instanceOpacity.setUsage(DynamicDrawUsage);
  }, [geometry, instanceOpacity]);

  useLayoutEffect(() => {
    arrivingMesh.current?.instanceMatrix.setUsage(DynamicDrawUsage);
  }, []);

  const writeInstances = (now: number) => {
    const settled = settledMesh.current;
    const arriving = arrivingMesh.current;
    if (!settled || !arriving) return false;
    const settledHadColour = settled.instanceColor !== null;
    const arrivingHadColour = arriving.instanceColor !== null;
    let active = false;
    let settledIndex = 0;
    let arrivingIndex = 0;
    settledBlocks.current = [];
    arrivingBlocks.current = [];
    blocks.forEach(block => {
      // The block keeps the shift of its own stored mode. `shift` above is the
      // active lattice preview and must not drag already-authored geometry.
      const rest = cellToScene(block.mode, block.col, block.row, block.level);
      const arrival = settling.current.get(block.id);
      let y = rest.y;
      let isArriving = false;
      let arrivalOpacity = 1;
      if (arrival) {
        const frame = arrivalFrame(now - arrival.started, arrival.delay, reduced);
        y += frame.offsetScene;
        arrivalOpacity = frame.opacity;
        if (frame.active) {
          active = true;
          isArriving = true;
        } else settling.current.delete(block.id);
      }
      matrix.makeTranslation(rest.x, y, rest.z);
      const target = isArriving ? arriving : settled;
      const index = isArriving ? arrivingIndex++ : settledIndex++;
      target.setMatrixAt(index, matrix);
      target.setColorAt(index, tokenColor(`--block-${block.colour}`));
      if (isArriving) instanceOpacity.setX(index, arrivalOpacity);
      (isArriving ? arrivingBlocks : settledBlocks).current.push(block);
    });
    settled.count = settledIndex;
    arriving.count = arrivingIndex;
    settled.instanceMatrix.needsUpdate = true;
    arriving.instanceMatrix.needsUpdate = true;
    if (settled.instanceColor) settled.instanceColor.needsUpdate = true;
    if (arriving.instanceColor) arriving.instanceColor.needsUpdate = true;
    if (!settledHadColour && settled.instanceColor && !Array.isArray(settled.material)) {
      settled.material.needsUpdate = true;
    }
    if (!arrivingHadColour && arriving.instanceColor && !Array.isArray(arriving.material)) {
      arriving.material.needsUpdate = true;
    }
    instanceOpacity.needsUpdate = arrivingIndex > 0;
    return active;
  };

  useLayoutEffect(() => {
    const now = performance.now();
    const next = new Set(blocks.map(block => block.id));
    for (const id of settling.current.keys()) if (!next.has(id)) settling.current.delete(id);
    const newBlocks = blocks.filter(block => animateIds.has(block.id));
    const delays = rowArrivalDelays(newBlocks);
    for (const block of newBlocks) {
      if (!settling.current.has(block.id)) {
        settling.current.set(block.id, { started: now, delay: delays.get(block.id) ?? 0 });
      }
    }
    writeInstances(now);
    invalidate();
  }, [blocks, animateIds, reduced, invalidate]);

  useFrame(() => {
    if (settling.current.size === 0) return;
    if (writeInstances(performance.now())) invalidate();
  });

  const blockAt = (event: ThreeEvent<PointerEvent>, rendered: RefObject<ModelBlock[]>) => {
    if (event.instanceId === undefined) return null;
    const block = rendered.current[event.instanceId];
    return block ?? null;
  };

  const topHit = (event: ThreeEvent<PointerEvent>, rendered: RefObject<ModelBlock[]>): SurfacePointer | null => {
    if (!event.face || event.face.normal.y < 0.45) return null;
    const block = blockAt(event, rendered);
    if (!block) return null;
    const target = resolveTopTarget(block, event.point, activeMode, shift);
    return target ? nativeHit(event, target, block.id) : null;
  };

  const handle = (rendered: RefObject<ModelBlock[]>,
                  callback: SurfaceHandlers["onSurfaceMove"] | undefined, removeFromAnyFace = false) =>
    (event: ThreeEvent<PointerEvent>) => {
      const block = blockAt(event, rendered);
      const hit = topHit(event, rendered) ?? (removeFromAnyFace && event.nativeEvent.altKey && block
        ? nativeHit(event, { col: block.col, row: block.row, level: block.level }, block.id)
        : null);
      if (!hit || !callback) return;
      event.stopPropagation();
      callback(hit);
    };

  return (
    <>
      <instancedMesh
        ref={settledMesh}
        args={[geometry, undefined, CAPACITY]}
        receiveShadow
        onPointerMove={handle(settledBlocks, handlers.onSurfaceMove)}
        onPointerDown={handle(settledBlocks, handlers.onSurfaceDown, true)}
        onPointerUp={handle(settledBlocks, handlers.onSurfaceUp, true)}
        onPointerOut={handlers.onSurfaceLeave}
      >
        <meshStandardMaterial
          vertexColors roughness={0.5} metalness={0}
          emissive={tokenColor("--block-white")} emissiveIntensity={0.22}
          transparent={opacity < 1} opacity={opacity} depthWrite={opacity >= 1}
        />
      </instancedMesh>
      <instancedMesh
        ref={arrivingMesh}
        args={[geometry, undefined, CAPACITY]}
        receiveShadow
        onPointerMove={handle(arrivingBlocks, handlers.onSurfaceMove)}
        onPointerDown={handle(arrivingBlocks, handlers.onSurfaceDown, true)}
        onPointerUp={handle(arrivingBlocks, handlers.onSurfaceUp, true)}
        onPointerOut={handlers.onSurfaceLeave}
      >
        <meshStandardMaterial vertexColors roughness={0.5} metalness={0}
                              emissive={tokenColor("--block-white")} emissiveIntensity={0.22}
                              transparent opacity={opacity} depthWrite={false}
                              onBeforeCompile={configureArrivalShader}
                              customProgramCacheKey={arrivalShaderKey} />
      </instancedMesh>
    </>
  );
}

export const Blocks = memo(function Blocks({ blocks, activeMode, shift, heldLevel, reduced, ...handlers }: {
  blocks: ModelBlock[];
  activeMode: ModeName;
  shift?: Shift;
  heldLevel: number | null;
  reduced: boolean;
} & SurfaceHandlers) {
  const knownIds = useRef(new Set<string>());
  const animateIds = new Set(blocks.filter(block => !knownIds.current.has(block.id)).map(block => block.id));
  useLayoutEffect(() => {
    knownIds.current = new Set(blocks.map(block => block.id));
  }, [blocks]);
  const groups = useMemo(() => {
    const result: Record<ModeName, { solid: ModelBlock[]; xray: ModelBlock[] }> = {
      vertical: { solid: [], xray: [] }, horizontal: { solid: [], xray: [] },
    };
    for (const block of blocks) {
      const bucket = heldLevel !== null && block.level > heldLevel ? "xray" : "solid";
      result[block.mode][bucket].push(block);
    }
    return result;
  }, [blocks, heldLevel]);
  const surfaceHandlers = useMemo(() => ({ ...handlers }), [
    handlers.onSurfaceMove, handlers.onSurfaceDown, handlers.onSurfaceUp, handlers.onSurfaceLeave,
  ]);

  return (
    <>
      {(["vertical", "horizontal"] as ModeName[]).flatMap(mode => [
        <BlockBatch key={`${mode}-solid`} blocks={groups[mode].solid} animateIds={animateIds} mode={mode}
          activeMode={activeMode} shift={shift} opacity={1} reduced={reduced} handlers={surfaceHandlers} />,
        <BlockBatch key={`${mode}-xray`} blocks={groups[mode].xray} animateIds={animateIds} mode={mode}
          activeMode={activeMode} shift={shift} opacity={0.15} reduced={reduced} handlers={surfaceHandlers} />,
      ])}
    </>
  );
});
