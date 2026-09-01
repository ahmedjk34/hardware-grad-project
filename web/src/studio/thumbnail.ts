/**
 * A card's picture, and the one trap that costs an hour.
 *
 * The Studio's frameloop is `demand` and the canvas has no
 * `preserveDrawingBuffer`, so by the time a save handler calls `toDataURL` the
 * backbuffer has already been cleared and you get a transparent rectangle.
 * Turning `preserveDrawingBuffer` on globally would fix it at the cost of every
 * frame of the whole application, for a feature used once per save. So the
 * capture renders to an off-screen `WebGLRenderTarget` instead
 * (`scene/capture.ts`) and hands the raw pixels here.
 *
 * WebGL reads a framebuffer bottom-up; images are top-down. `flipRows` is that
 * one line, and it is pure, so the part that is easy to get silently wrong is
 * the part with a test.
 *
 * Rendered at 640 × 400 and stored at 320 × 200, WebP quality 0.7: about
 * 10–20 kB each, which is what makes the library's 4 MB budget hold ~200
 * models rather than ~20.
 */
export const THUMBNAIL = Object.freeze({
  renderWidth: 640,
  renderHeight: 400,
  width: 320,
  height: 200,
  quality: 0.7,
  type: "image/webp",
});

/** 16:10 — the card's frame, and the aspect the capture camera is posed for. */
export function thumbnailAspect(): number {
  return THUMBNAIL.width / THUMBNAIL.height;
}

/** Bottom-up RGBA to top-down RGBA. Returns a new buffer; never mutates. */
export function flipRows(pixels: Uint8Array, width: number, height: number): Uint8Array {
  const stride = width * 4;
  const flipped = new Uint8Array(pixels.length);
  for (let row = 0; row < height; row++) {
    flipped.set(pixels.subarray(row * stride, (row + 1) * stride), (height - 1 - row) * stride);
  }
  return flipped;
}

function base64(bytes: Uint8Array): string {
  let binary = "";
  for (let index = 0; index < bytes.length; index++) binary += String.fromCharCode(bytes[index]);
  return btoa(binary);
}

/**
 * Raw render-target pixels to a `data:image/webp` URL, or `undefined` where the
 * browser cannot do it. A missing thumbnail is a plain card; a thrown one would
 * be a save the operator cannot complete, which is much worse.
 */
export async function encodeThumbnail(
  pixels: Uint8Array, width: number, height: number,
): Promise<string | undefined> {
  try {
    const Offscreen = globalThis.OffscreenCanvas;
    if (typeof Offscreen !== "function" || typeof ImageData !== "function") return undefined;

    const full = new Offscreen(width, height);
    const fullContext = full.getContext("2d") as OffscreenCanvasRenderingContext2D | null;
    if (!fullContext) return undefined;
    fullContext.putImageData(new ImageData(new Uint8ClampedArray(flipRows(pixels, width, height)), width, height), 0, 0);

    const small = new Offscreen(THUMBNAIL.width, THUMBNAIL.height);
    const smallContext = small.getContext("2d") as OffscreenCanvasRenderingContext2D | null;
    if (!smallContext) return undefined;
    smallContext.drawImage(full as unknown as CanvasImageSource, 0, 0, THUMBNAIL.width, THUMBNAIL.height);

    const blob = await small.convertToBlob({ type: THUMBNAIL.type, quality: THUMBNAIL.quality });
    return `data:${THUMBNAIL.type};base64,${base64(new Uint8Array(await blob.arrayBuffer()))}`;
  } catch {
    return undefined;
  }
}
