import { describe, expect, it, vi } from "vitest";
import { captureCameraThumbnail, markdownReport } from "./run-report";
import type { RunState } from "./runner";

describe("run report", () => {
  it("captures a bounded WebP thumbnail from the live camera image", () => {
    const drawImage = vi.fn();
    const canvas = {
      width: 0, height: 0,
      getContext: vi.fn(() => ({ drawImage })),
      toDataURL: vi.fn(() => "data:image/webp;base64,camera"),
    } as unknown as HTMLCanvasElement;
    const image = { naturalWidth: 1280, naturalHeight: 720 } as HTMLImageElement;
    expect(captureCameraThumbnail(image, () => canvas)).toBe("data:image/webp;base64,camera");
    expect(canvas.width).toBe(320);
    expect(canvas.height).toBe(180);
    expect(drawImage).toHaveBeenCalledWith(image, 0, 0, 320, 180);
  });

  it("exports deterministic event-derived commands, outcomes, timings and evidence", () => {
    const state = {
      modelName: "Bridge | trial",
      style: "run",
      startedAt: 1_000,
      finishedAt: 4_500,
      phase: "stopped-mismatch",
      failure: "command mismatch",
      mismatch: { program: "B 3 2 1", rig: "B 3 2 0" },
      log: [
        { index: 0, kind: "mode", command: "RR", result: "switched", startedAt: 1_000, finishedAt: 1_600 },
        { index: 1, kind: "build", command: "B 2 2 0", result: "placed", startedAt: 1_600, finishedAt: 2_300,
          thumbnail: "data:image/webp;base64,abc", verification: "verified" },
      ],
    } as RunState;
    const report = markdownReport(state);
    expect(report).toContain("# Run report — Bridge \\| trial");
    expect(report).toContain("| 1 | `RR` | switched | 0.60 s | — |");
    expect(report).toContain("| 2 | `B 2 2 0` | placed | 0.70 s | verified |");
    expect(report).toContain("Total time: **3.50 s**");
    expect(report).toContain("program: `B 3 2 1`");
    expect(report).toContain("rig: `B 3 2 0`");
    expect(report).toContain("![Camera after step 2](data:image/webp;base64,abc)");
  });
});
