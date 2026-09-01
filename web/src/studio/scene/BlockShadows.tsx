/**
 * A deliberately cheap grounding cue for placed blocks.
 *
 * Drei's ContactShadows renders and blurs an offscreen depth texture. Even at
 * one frame that creates a noticeable first-use GPU stall, especially on the
 * Pi. These two instanced ellipse batches need no framebuffer, blur pass or
 * shadow-map compilation and add at most two ordinary draw calls.
 */
import { memo, useLayoutEffect, useMemo, useRef } from "react";
import { CircleGeometry, Matrix4, type InstancedMesh } from "three";
import { blockSceneSize, cellToScene, type ModeName } from "../coords";
import type { ModelBlock } from "../model";
import { tokenColor } from "./theme";

const MODES: ModeName[] = ["vertical", "horizontal"];

function ShadowBatch({ blocks, mode }: { blocks: ModelBlock[]; mode: ModeName }) {
  const mesh = useRef<InstancedMesh>(null);
  const matrix = useMemo(() => new Matrix4(), []);
  const size = useMemo(() => blockSceneSize(mode), [mode]);
  const geometry = useMemo(() => {
    const circle = new CircleGeometry(1, 16);
    circle.scale(size.x * 0.44, size.z * 0.44, 1);
    circle.rotateX(-Math.PI / 2);
    return circle;
  }, [size.x, size.z]);

  useLayoutEffect(() => {
    if (!mesh.current) return;
    blocks.forEach((block, index) => {
      const position = cellToScene(block.mode, block.col, block.row, block.level);
      matrix.makeTranslation(position.x, 0.024, position.z);
      mesh.current?.setMatrixAt(index, matrix);
    });
    mesh.current.count = blocks.length;
    mesh.current.instanceMatrix.needsUpdate = true;
  }, [blocks, matrix]);

  if (blocks.length === 0) return null;
  return (
    <instancedMesh ref={mesh} args={[geometry, undefined, blocks.length]} renderOrder={-1}>
      <meshBasicMaterial color={tokenColor("--void")} transparent opacity={0.28}
                         depthWrite={false} toneMapped={false} />
    </instancedMesh>
  );
}

export const BlockShadows = memo(function BlockShadows({ blocks }: { blocks: ModelBlock[] }) {
  const groups = useMemo(() => ({
    vertical: blocks.filter(block => block.mode === "vertical"),
    horizontal: blocks.filter(block => block.mode === "horizontal"),
  }), [blocks]);
  return <>{MODES.map(mode => <ShadowBatch key={mode} mode={mode} blocks={groups[mode]} />)}</>;
});
