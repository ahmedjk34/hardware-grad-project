import { describe, expect, it, vi } from "vitest";
import { createPreloader } from "./preload";

describe("lazy route preloading", () => {
  it("starts a heavy import once and reuses it for hover, idle and navigation", async () => {
    const load = vi.fn(async () => ({ default: "studio" }));
    const preload = createPreloader(load);

    const first = preload();
    const second = preload();
    expect(first).toBe(second);
    expect(load).toHaveBeenCalledOnce();
    await expect(first).resolves.toEqual({ default: "studio" });
  });
});
