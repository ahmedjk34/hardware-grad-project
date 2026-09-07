/**
 * The detector-activity panel is the surface `#/build` acts on: it hosts the
 * CORRECTION control for a MOVED / DISPLACED verdict (the console also has it in
 * the banner). Same rules as everywhere: shown only when the SERVER says
 * `correctable`, never fires on one click, and the browser derives nothing.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SupervisionActivity } from "./SupervisionActivity";
import { testState } from "../test-state";
import type { StateModel, Supervision } from "../types";

const sv = (over: Partial<Supervision> = {}): Supervision => ({
  state: "VERDICT", verdict: "DISPLACED", severity: "amber", cells: [[2, 1]],
  mode: "vertical", expected: [[2, 1]], observed: [], unjudged: [],
  reason: null, judged_at_ms: 20, acknowledged: false,
  correctable: true, correction_cell: [2, 1], correction_level: 0,
  correction_reason: "the block is 1.15 cm off [2, 1]; the claw can pick it up",
  ...over,
});
const st = (over: Partial<Supervision> = {}): StateModel =>
  testState({ supervision: sv(over) });

describe("SupervisionActivity — the CORRECTION control for #/build", () => {
  it("shows no correction control without an onCorrect handler", () => {
    render(<SupervisionActivity state={st()} defaultOpen />);
    expect(screen.queryByRole("button", { name: /Return the block/ })).toBeNull();
  });

  it("offers RETURN BLOCK TO CELL for a correctable DISPLACED verdict", () => {
    render(<SupervisionActivity state={st()} onCorrect={() => {}} defaultOpen />);
    expect(screen.getByRole("button", { name: /Return the block to column 2 row 1/ })).toBeTruthy();
  });

  it("confirms before it moves anything, and only then calls onCorrect", () => {
    const onCorrect = vi.fn();
    render(<SupervisionActivity state={st()} onCorrect={onCorrect} defaultOpen />);
    fireEvent.click(screen.getByRole("button", { name: /Return the block/ }));
    expect(onCorrect).not.toHaveBeenCalled();
    expect(screen.getByText(/Watch the rig/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "RUN" }));
    expect(onCorrect).toHaveBeenCalledTimes(1);
  });

  it("shows the reason instead of a button when the pick is not safe", () => {
    const { container } = render(<SupervisionActivity
      state={st({ correctable: false,
        correction_reason: "the block is 1.90 cm off its cell — beyond the 1.2 cm limit" })}
      onCorrect={() => {}} defaultOpen />);
    expect(screen.queryByRole("button", { name: /Return the block/ })).toBeNull();
    expect(container.textContent).toContain("beyond the 1.2 cm limit");
  });

  it("offers nothing for REMOVED / FOREIGN, or once acknowledged", () => {
    for (const over of [
      { verdict: "REMOVED" as const },
      { verdict: "FOREIGN" as const, severity: "red" as const },
      { acknowledged: true },
    ]) {
      const { unmount } = render(
        <SupervisionActivity state={st(over)} onCorrect={() => {}} defaultOpen />);
      expect(screen.queryByRole("button", { name: /Return the block/ })).toBeNull();
      unmount();
    }
  });
});
