import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ControlPanel } from "./components/ControlPanel";
import { CameraView } from "./components/CameraView";
import { LockedBanner } from "./components/LockedBanner";
import { createConsoleStore } from "./store";
import * as api from "./api";
import type { StateModel } from "./types";

const state = (overrides: Partial<StateModel> = {}): StateModel => ({
  mode: "vertical", cols: 6, rows: 5, calibrated: false, selected: null,
  command: null, level: 0, build_state: "READY", locked_reason: null,
  camera: "LIVE", camera_age_ms: 1, last_result: null,
  last_result_reason: null, views: { grid: true, detect: true, paper: false, overlay: true },
  geometry: { image_size: [640, 480], calibrated: false, grid: [], selected: null, detections: [], paper: null },
  ...overrides,
});

describe("Step 7 console shell", () => {
  it("updates the store from state messages and marks close disconnected", () => {
    const store = createConsoleStore();
    store.apply(state({ selected: [3, 5], command: "B 3 5 0" }));
    expect(store.snapshot.state?.selected).toEqual([3, 5]);
    store.disconnected();
    expect(store.snapshot.connected).toBe(false);
  });

  it("enables BUILD only for a selected live READY state", () => {
    const { rerender } = render(<ControlPanel state={state()} connected onBuild={() => {}} />);
    expect(screen.getByRole("button", { name: "BUILD" })).toBeDisabled();
    rerender(<ControlPanel state={state({ selected: [3, 5], command: "B 3 5 0" })} connected onBuild={() => {}} />);
    expect(screen.getByRole("button", { name: "BUILD" })).toBeEnabled();
  });

  it("shows a locked reason and disables BUILD", () => {
    render(<><LockedBanner state={state({ build_state: "LOCKED", locked_reason: "held block" })} /><ControlPanel state={state({ selected: [3, 5], build_state: "LOCKED", locked_reason: "held block" })} connected onBuild={() => {}} /></>);
    expect(screen.getByText("held block")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "BUILD" })).toBeDisabled();
  });

  it("greys disconnected video and disables controls", () => {
    render(<><CameraView state={state()} connected={false} /><ControlPanel state={state({ selected: [3, 5] })} connected={false} onBuild={() => {}} /></>);
    expect(screen.getByText("DISCONNECTED")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "BUILD" })).toBeDisabled();
  });

  it("sends level deltas", () => {
    const level = vi.spyOn(api, "level").mockResolvedValue(state());
    render(<ControlPanel state={state()} connected onBuild={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Level +" }));
    fireEvent.click(screen.getByRole("button", { name: "Level -" }));
    expect(level).toHaveBeenNthCalledWith(1, 1);
    expect(level).toHaveBeenNthCalledWith(2, -1);
  });
});
