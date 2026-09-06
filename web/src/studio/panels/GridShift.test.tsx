import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { GridShift } from "./GridShift";

describe("GridShift — the grid-shift / running-bond window", () => {
  it("names the run axis and increment and is usable with no level held", () => {
    render(<GridShift mode="vertical" onSetBond={vi.fn()} />);
    expect(screen.getByText(/Y · 3\.8 cm/)).toBeInTheDocument();
    // The stepper is present immediately — no "hold a level" gate.
    expect(screen.getByRole("group", { name: /Course 1 offset on Y/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /offset courses 1, 3, 5/ })).toBeEnabled();
  });

  it("steps the selected course by ±half a pitch on the run axis", async () => {
    const onSetBond = vi.fn();
    render(<GridShift mode="vertical" onSetBond={onSetBond} />);
    await userEvent.click(screen.getByLabelText("Half pitch away from home"));
    expect(onSetBond).toHaveBeenCalledWith(1, [0, 3.8]);
  });

  it("the ◀ ▶ course selector moves which level the stepper writes", async () => {
    const onSetBond = vi.fn();
    render(<GridShift mode="vertical" ceiling={6} onSetBond={onSetBond} />);
    await userEvent.click(screen.getByRole("button", { name: "Next course" }));
    await userEvent.click(screen.getByRole("button", { name: "Next course" }));
    await userEvent.click(screen.getByLabelText("Half pitch away from home"));
    expect(onSetBond).toHaveBeenCalledWith(3, [0, 3.8]);
  });

  it("clears a course back to flush", async () => {
    const onSetBond = vi.fn();
    render(<GridShift mode="vertical" bondShifts={{ vertical: { 1: [0, 3.8] } }} onSetBond={onSetBond} />);
    expect(screen.getByText("3.8 cm")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Clear this course offset"));
    expect(onSetBond).toHaveBeenCalledWith(1, null);
  });

  it("follows a level held on the scrubber", async () => {
    const onSetBond = vi.fn();
    render(<GridShift mode="vertical" level={4} ceiling={17} onSetBond={onSetBond} />);
    await userEvent.click(screen.getByLabelText("Half pitch away from home"));
    expect(onSetBond).toHaveBeenCalledWith(4, [0, 3.8]);
  });

  it("horizontal runs the offset on X", async () => {
    const onSetBond = vi.fn();
    render(<GridShift mode="horizontal" onSetBond={onSetBond} />);
    expect(screen.getByText(/X · 3\.8 cm/)).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Half pitch away from home"));
    expect(onSetBond).toHaveBeenCalledWith(1, [3.8, 0]);
  });

  it("the preset fills the alternating courses up to the tallest block", async () => {
    const onSetBond = vi.fn();
    render(<GridShift mode="vertical" maxLevel={4} onSetBond={onSetBond} />);
    await userEvent.click(screen.getByRole("button", { name: /offset courses 1, 3, 5/ }));
    expect(onSetBond.mock.calls).toEqual([
      [1, [0, 3.8]], [2, null], [3, [0, 3.8]], [4, null],
    ]);
  });

  it("warns when a course has orphaned blocks", () => {
    render(<GridShift mode="vertical" orphanCount={2} onSetBond={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("2 blocks pushed off the travel cap");
  });
});
