import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Calibrate } from "./components/Calibrate";
import * as api from "./api";
import type { BlockCalibrationStatus } from "./api";

function status(overrides: Partial<BlockCalibrationStatus> = {}): BlockCalibrationStatus {
  const planned: [number, number][] = [[1, 0], [6, 0], [6, 5], [0, 5], [3, 3], [0, 2]];
  return {
    mode: "vertical",
    planned,
    observed: [],
    remaining: planned,
    ready: false,
    reasons: ["0/5 placements recorded"],
    started: true,
    finished_reason: null,
    summary: "vertical placed-block calibration: 0/6 cells",
    report: null,
    ...overrides,
  };
}

describe("placed-block calibration", () => {
  it("walks the plan, reports the residual, and only saves once the fit is gated in", async () => {
    const planned = status().planned;
    const start = vi.spyOn(api.calibration.block, "start").mockResolvedValue(status());
    // Four placements fit a homography exactly, so the backend refuses to call
    // the run ready until five: the button must stay disabled until it does.
    const step = vi.spyOn(api.calibration.block, "step")
      .mockImplementation(async () => {
        const done = step.mock.calls.length;
        return status({
          observed: planned.slice(0, done),
          remaining: planned.slice(done),
          ready: done >= 5,
          report: done >= 5
            ? {
              observations: done, mean_residual_px: 0.42, max_residual_px: 1.03,
              worst_cell: [3, 3], short_pitch_px: 54, size_agreement: 0.99,
              max_bearing_error_deg: 1.2, residuals: {},
            }
            : null,
        });
      });
    const save = vi.spyOn(api.calibration.block, "save").mockResolvedValue({} as never);

    render(<Calibrate ready />);
    fireEvent.click(screen.getByRole("button", { name: "Calibrate with blocks" }));
    expect(start).toHaveBeenCalledOnce();

    // The panel names the cell the rig is about to place on, not a step number:
    // an operator watching the machine needs to know where to look.
    expect(await screen.findByText("[1,0]")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save calibration" })).toBeDisabled();

    for (let index = 0; index < 4; index++) {
      fireEvent.click(screen.getByRole("button", { name: "Place next block" }));
      await waitFor(() => expect(step).toHaveBeenCalledTimes(index + 1));
    }
    expect(screen.getByRole("button", { name: "Save calibration" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Place next block" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save calibration" })).toBeEnabled());
    expect(screen.getByText(/0\.42 px mean/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Save calibration" }));
    await waitFor(() => expect(save).toHaveBeenCalledOnce());
  });

  it("shows a refused step without losing the placements already made", async () => {
    const planned = status().planned;
    vi.spyOn(api.calibration.block, "start").mockResolvedValue(
      status({ observed: planned.slice(0, 2), remaining: planned.slice(2) }));
    vi.spyOn(api.calibration.block, "step").mockRejectedValue(
      new Error("[6,5] was placed but not seen: the only block in view is cut off by the frame edge"));

    render(<Calibrate ready />);
    fireEvent.click(screen.getByRole("button", { name: "Calibrate with blocks" }));
    fireEvent.click(await screen.findByRole("button", { name: "Place next block" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/cut off by the frame edge/);
    // Still on the same cell, still able to retry: a refused placement is not
    // a lost run.
    expect(screen.getByText("[6,5]")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Place next block" })).toBeEnabled();
  });

  it("stops offering steps once the rig has aborted", async () => {
    vi.spyOn(api.calibration.block, "start").mockResolvedValue(status({
      finished_reason: "the rig aborted while placing [6,0]. The claw may still "
        + "be holding a block - do not retry, go and look at the rig",
    }));

    render(<Calibrate ready />);
    fireEvent.click(screen.getByRole("button", { name: "Calibrate with blocks" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/go and look at the rig/);
    expect(screen.getByRole("button", { name: "Place next block" })).toBeDisabled();
  });

  it("surfaces a refusal to start at all", async () => {
    vi.spyOn(api.calibration.block, "start").mockRejectedValue(
      new Error("camera frame is stale; selection is unsafe"));

    render(<Calibrate ready />);
    fireEvent.click(screen.getByRole("button", { name: "Calibrate with blocks" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/camera frame is stale/);
    // The chooser stays put, so the other two routes are still reachable.
    expect(screen.getByRole("button", { name: "Calibrate from sheet" })).toBeInTheDocument();
  });
});
