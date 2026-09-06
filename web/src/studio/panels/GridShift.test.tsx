import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { GridShift } from "./GridShift";

describe("GridShift — incrementer, live preview, apply (horizontal grid)", () => {
  it("is inert in the vertical grid and says the shift is horizontal-only", () => {
    render(<GridShift mode="vertical" onSetBond={vi.fn()} />);
    expect(screen.getByText("horizontal only")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "APPLY" })).not.toBeInTheDocument();
  });

  it("shows the increment in cm on the step buttons and the axis it moves", () => {
    render(<GridShift mode="horizontal" onSetBond={vi.fn()} />);
    expect(screen.getByText("X axis")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Increase by 3.8 cm" })).toHaveTextContent("+3.8");
    expect(screen.getByRole("button", { name: "Decrease by 3.8 cm" })).toHaveTextContent("−3.8");
    expect(screen.getByText("0.0 cm")).toBeInTheDocument();
  });

  it("increments the pending amount and previews it live, without committing", async () => {
    const onPreview = vi.fn();
    const onSetBond = vi.fn();
    render(<GridShift mode="horizontal" onPreview={onPreview} onSetBond={onSetBond} />);
    await userEvent.click(screen.getByRole("button", { name: "Increase by 3.8 cm" }));
    expect(screen.getByText("+3.8 cm")).toBeInTheDocument();
    expect(onPreview).toHaveBeenLastCalledWith(1, 3.8);
    expect(onSetBond).not.toHaveBeenCalled();
  });

  it("Apply commits the pending offset on the X axis and clears the preview", async () => {
    const onSetBond = vi.fn();
    render(<GridShift mode="horizontal" onSetBond={onSetBond} />);
    expect(screen.getByRole("button", { name: "APPLY" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Increase by 3.8 cm" }));
    await userEvent.click(screen.getByRole("button", { name: "APPLY" }));
    expect(onSetBond).toHaveBeenCalledWith(1, [3.8, 0]);
  });

  it("Apply with the amount back at zero clears the course", async () => {
    const onSetBond = vi.fn();
    render(<GridShift mode="horizontal" bondShifts={{ horizontal: { 1: [3.8, 0] } }} onSetBond={onSetBond} />);
    expect(screen.getByText("+3.8 cm")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Decrease by 3.8 cm" }));
    await userEvent.click(screen.getByRole("button", { name: "APPLY" }));
    expect(onSetBond).toHaveBeenCalledWith(1, null);
  });

  it("reset drops the pending change", async () => {
    render(<GridShift mode="horizontal" onSetBond={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Increase by 3.8 cm" }));
    await userEvent.click(screen.getByRole("button", { name: "reset" }));
    expect(screen.getByText("0.0 cm")).toBeInTheDocument();
  });

  it("the course selector picks which level Apply writes", async () => {
    const onSetBond = vi.fn();
    render(<GridShift mode="horizontal" ceiling={6} onSetBond={onSetBond} />);
    await userEvent.click(screen.getByRole("button", { name: "Next course" }));
    await userEvent.click(screen.getByRole("button", { name: "Next course" }));
    await userEvent.click(screen.getByRole("button", { name: "Increase by 3.8 cm" }));
    await userEvent.click(screen.getByRole("button", { name: "APPLY" }));
    expect(onSetBond).toHaveBeenCalledWith(3, [3.8, 0]);
  });

  it("running bond fills the alternating courses up to the tallest block", async () => {
    const onSetBond = vi.fn();
    render(<GridShift mode="horizontal" maxLevel={4} onSetBond={onSetBond} />);
    await userEvent.click(screen.getByRole("button", { name: /running bond/ }));
    expect(onSetBond.mock.calls).toEqual([[1, [3.8, 0]], [2, null], [3, [3.8, 0]], [4, null]]);
  });

  it("warns about orphaned blocks", () => {
    render(<GridShift mode="horizontal" orphanCount={2} onSetBond={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("2 blocks pushed off the travel cap");
  });
});
