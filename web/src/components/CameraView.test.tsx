/**
 * The camera stage toolbar. The supervisor kill switch lives in this row,
 * directly after DETECT, and it is a plain toggle: one click flips it, it is
 * never disabled, and it talks to `/api/supervision/enabled` — not `/api/view`.
 */
import { render, screen, fireEvent, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({
  view: vi.fn(),
  select: vi.fn(),
  setSupervisionEnabled: vi.fn(),
}));

import * as api from "../api";
import { CameraView } from "./CameraView";
import { testState } from "../test-state";

describe("the camera stage toolbar", () => {
  it("puts the supervisor toggle immediately after the detect toggle", () => {
    render(<CameraView state={testState()} connected />);
    const group = screen.getByRole("group", { name: /overlay views/i });
    const labels = within(group).getAllByRole("button").map(b => b.getAttribute("aria-label"));
    const detect = labels.indexOf("Toggle detect overlay");
    const supervisor = labels.indexOf("Turn placement supervision off");
    expect(detect).toBeGreaterThanOrEqual(0);
    expect(supervisor).toBe(detect + 1);
  });

  it("reads pressed when supervision is on and toggles it off in one click", () => {
    render(<CameraView state={testState()} connected />);
    const toggle = screen.getByRole("button", { name: "Turn placement supervision off" });
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(toggle);
    expect(api.setSupervisionEnabled).toHaveBeenCalledWith(false);
  });

  it("offers to turn supervision back on when it is off", () => {
    render(<CameraView state={testState({ supervision_enabled: false })} connected />);
    const toggle = screen.getByRole("button", { name: "Turn placement supervision on" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(toggle);
    expect(api.setSupervisionEnabled).toHaveBeenCalledWith(true);
  });

  it("explains itself through an error when a crash disabled it", () => {
    render(<CameraView
      state={testState({ supervision_enabled: false,
                         supervision_fault: "RuntimeError: detector exploded" })}
      connected />);
    const toggle = screen.getByRole("button", { name: "Turn placement supervision on" });
    expect(toggle.getAttribute("title")).toContain("detector exploded");
  });
});
