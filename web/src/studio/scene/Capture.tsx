/**
 * The thumbnail capture, and the trap it exists to avoid.
 *
 * The Studio's frameloop is `demand` and the canvas is created without
 * `preserveDrawingBuffer`, so calling `toDataURL` on it in a save handler
 * returns a transparent rectangle: the backbuffer has already been cleared.
 * Turning `preserveDrawingBuffer` on globally would fix that at the cost of
 * every frame of the whole application, for a feature used once per save.
 *
 * So this renders the SAME scene into an off-screen `WebGLRenderTarget` at
 * 640 × 400 with a camera of its own, reads the pixels back, and hands them to
 * `thumbnail.ts` to become a 320 × 200 WebP. Nothing about the live canvas
 * changes, and the visible camera is never moved.
 *
 * The capture camera is posed with `view.viewPose("iso", aspect, box)` on the
 * MODEL's bounding box, not the envelope, so a card shows the structure rather
 * than the same empty cage every other card shows. The envelope is still in the
 * scene, so it renders faintly behind it for scale.
 */
import { useEffect } from "react";
import { useThree } from "@react-three/fiber";
import { PerspectiveCamera, Vector3, WebGLRenderTarget } from "three";
import { FOV_DEG, envelopeBoxScene, viewPose, type Box } from "../view";
import { THUMBNAIL, encodeThumbnail, thumbnailAspect } from "../thumbnail";

export type CaptureThumbnail = (box: Box | null) => Promise<string | undefined>;
export interface CaptureHandle { current: CaptureThumbnail | null }

export function Capture({ handle }: { handle: CaptureHandle }) {
  const { gl, scene } = useThree();

  useEffect(() => {
    handle.current = async (box: Box | null) => {
      const target = new WebGLRenderTarget(THUMBNAIL.renderWidth, THUMBNAIL.renderHeight);
      try {
        const aspect = thumbnailAspect();
        const pose = viewPose("iso", aspect, box ?? envelopeBoxScene());
        const camera = new PerspectiveCamera(FOV_DEG, aspect, 0.5, 800);
        camera.up.set(pose.up.x, pose.up.y, pose.up.z);
        camera.position.set(pose.position.x, pose.position.y, pose.position.z);
        camera.lookAt(new Vector3(pose.target.x, pose.target.y, pose.target.z));
        camera.updateProjectionMatrix();

        const previous = gl.getRenderTarget();
        gl.setRenderTarget(target);
        gl.render(scene, camera);
        const pixels = new Uint8Array(THUMBNAIL.renderWidth * THUMBNAIL.renderHeight * 4);
        gl.readRenderTargetPixels(target, 0, 0, THUMBNAIL.renderWidth, THUMBNAIL.renderHeight, pixels);
        gl.setRenderTarget(previous);
        return await encodeThumbnail(pixels, THUMBNAIL.renderWidth, THUMBNAIL.renderHeight);
      } catch {
        // A save must never fail because a thumbnail could not be drawn.
        return undefined;
      } finally {
        target.dispose();
      }
    };
    return () => { handle.current = null; };
  }, [gl, scene, handle]);

  return null;
}
