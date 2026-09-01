import { describe, expect, it, vi } from "vitest";
import {
  THUMBNAIL, encodeThumbnail, flipRows, thumbnailAspect,
} from "./thumbnail";

describe("thumbnail — the pixel plumbing", () => {
  it("flips the rows WebGL hands back bottom-up", () => {
    // Two rows of one RGBA pixel: red on the bottom row, blue on the top.
    const pixels = new Uint8Array([255, 0, 0, 255, 0, 0, 255, 255]);
    expect([...flipRows(pixels, 1, 2)]).toEqual([0, 0, 255, 255, 255, 0, 0, 255]);
  });

  it("leaves a single-row image alone and never mutates the source", () => {
    const pixels = new Uint8Array([1, 2, 3, 4]);
    expect([...flipRows(pixels, 1, 1)]).toEqual([1, 2, 3, 4]);
    const two = new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8]);
    flipRows(two, 1, 2);
    expect([...two]).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
  });

  it("keeps the card's 16:10 frame at both the render and the stored size", () => {
    expect(THUMBNAIL.renderWidth / THUMBNAIL.renderHeight).toBeCloseTo(1.6, 6);
    expect(THUMBNAIL.width / THUMBNAIL.height).toBeCloseTo(1.6, 6);
    expect(thumbnailAspect()).toBeCloseTo(1.6, 6);
    expect(THUMBNAIL.renderWidth).toBe(640);
    expect(THUMBNAIL.width).toBe(320);
    expect(THUMBNAIL.quality).toBe(0.7);
  });

  it("returns nothing instead of throwing where OffscreenCanvas does not exist", async () => {
    vi.stubGlobal("OffscreenCanvas", undefined);
    const encoded = await encodeThumbnail(new Uint8Array(4 * 640 * 400), 640, 400);
    expect(encoded).toBeUndefined();
    vi.unstubAllGlobals();
  });

  it("encodes to a WebP data URL when the browser can", async () => {
    const context = { putImageData: vi.fn(), drawImage: vi.fn() };
    class FakeOffscreen {
      constructor(public width: number, public height: number) {}
      getContext() { return context; }
      convertToBlob() { return Promise.resolve(new Blob([new Uint8Array([1, 2, 3])], { type: "image/webp" })); }
    }
    vi.stubGlobal("OffscreenCanvas", FakeOffscreen);
    vi.stubGlobal("ImageData", class { constructor(public data: unknown, public width: number, public height: number) {} });

    const encoded = await encodeThumbnail(new Uint8Array(4 * 640 * 400), 640, 400);
    expect(encoded).toMatch(/^data:image\/webp;base64,/);
    // Rendered at 640×400, stored at 320×200: the downscale is the size guard.
    expect(context.drawImage).toHaveBeenCalledWith(expect.anything(), 0, 0, 320, 200);
    vi.unstubAllGlobals();
  });
});
