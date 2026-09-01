import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BuildButton } from "./components/BuildButton";
import { BuildBanner } from "./components/BuildBanner";
import { ResultToast } from "./components/ResultToast";
import { ControlPanel } from "./components/ControlPanel";
import * as api from "./api";
import type { StateModel } from "./types";

const state = (overrides: Partial<StateModel> = {}): StateModel => ({ mode: "vertical", cols: 6, rows: 5, calibrated: false, selected: [3, 5], command: "B 3 5 0", level: 0, build_state: "READY", locked_reason: null, camera: "LIVE", camera_age_ms: 1, last_result: null, last_result_reason: null, views: {}, geometry: null, ...overrides });

describe("Step 9 confirmed build safety UI", () => {
  it("requires a second tap with the exact displayed command", () => { const build = vi.spyOn(api, "build").mockResolvedValue(state()); render(<BuildButton state={state()} connected />); fireEvent.click(screen.getByRole("button", { name: "BUILD" })); expect(screen.getByRole("button", { name: "CONFIRM B 3 5 0" })).toBeEnabled(); fireEvent.click(screen.getByRole("button", { name: "CONFIRM B 3 5 0" })); expect(build).toHaveBeenCalledWith("B 3 5 0"); });
  it("shows moving banner and disables every control", () => { render(<><BuildBanner state={state({ build_state: "RUNNING" })} connected /><ControlPanel state={state({ build_state: "RUNNING" })} connected onBuild={() => {}} /></>); expect(screen.getByText(/cannot be interrupted/)).toBeInTheDocument(); screen.getAllByRole("button").forEach(button => expect(button).toBeDisabled()); });
  it("shows terminal placed and rejected states correctly", () => { const { rerender } = render(<ResultToast state={state({ selected: null, last_result: "placed" })} />); expect(screen.getByText(/PLACED/)).toHaveClass("placed"); rerender(<ResultToast state={state({ last_result: "rejected", last_result_reason: "safe refusal" })} />); expect(screen.getByText(/safe refusal/)).toHaveClass("rejected"); });
  it("has no retry control when locked", () => { render(<><BuildBanner state={state({ build_state: "LOCKED", locked_reason: "held" })} connected /><ControlPanel state={state({ build_state: "LOCKED" })} connected onBuild={() => {}} /></>); expect(screen.getByText(/SESSION LOCKED/)).toBeInTheDocument(); expect(screen.queryByRole("button", { name: /retry/i })).toBeNull(); });
});
