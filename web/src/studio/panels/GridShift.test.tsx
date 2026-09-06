import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { GridShift } from "./GridShift";

describe("GridShift — the running-bond course control", () => {
  it("names the run axis and increment, and needs a held level to edit", () => {
    render(<GridShift mode="vertical" level={null} onSetBond={vi.fn()} />);
    expect(screen.getByText(/Y · 3\.8 cm/)).toBeInTheDocument();
    expect(screen.getByText(/Hold a level ≥ 1/)).toBeInTheDocument();
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
  });

  it("steps the held level's course by ±half a pitch on the run axis", async () => {
    const onSetBond = vi.fn();
    render(<GridShift mode="vertical" level={1} onSetBond={onSetBond} />);
    await userEvent.click(screen.getByLabelText("Half pitch away from home"));
    expect(onSetBond).toHaveBeenCalledWith(1, [0, 3.8]);
  });

  it("clears a course back to flush", async () => {
    const onSetBond = vi.fn();
    render(<GridShift mode="vertical" level={1} bondShifts={{ vertical: { 1: [0, 3.8] } }}
                     onSetBond={onSetBond} />);
    expect(screen.getByText("3.8 cm")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Clear this course offset"));
    expect(onSetBond).toHaveBeenCalledWith(1, null);
  });

  it("horizontal runs the offset on X", async () => {
    const onSetBond = vi.fn();
    render(<GridShift mode="horizontal" level={1} onSetBond={onSetBond} />);
    expect(screen.getByText(/X · 3\.8 cm/)).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Half pitch away from home"));
    expect(onSetBond).toHaveBeenCalledWith(1, [3.8, 0]);
  });

  it("the preset fills the alternating courses up to the tallest block", async () => {
    const onSetBond = vi.fn();
    render(<GridShift mode="vertical" level={null} maxLevel={4} onSetBond={onSetBond} />);
    await userEvent.click(screen.getByRole("button", { name: /alternate 1,3,5/ }));
    expect(onSetBond.mock.calls).toEqual([
      [1, [0, 3.8]], [2, null], [3, [0, 3.8]], [4, null],
    ]);
  });

  it("warns when a course has orphaned blocks", () => {
    render(<GridShift mode="vertical" level={1} orphanCount={2} onSetBond={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("2 blocks pushed off the travel cap");
  });
});
