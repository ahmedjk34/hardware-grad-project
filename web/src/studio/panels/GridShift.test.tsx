import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { GridShift } from "./GridShift";

describe("GridShift — incrementer, live preview, apply", () => {
  it("shows the increment in cm on the step buttons and the axis it moves", () => {
    render(<GridShift mode="vertical" onSetBond={vi.fn()} />);
    expect(screen.getByText("Y axis")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Increase by 3.8 cm" })).toHaveTextContent("+3.8");
    expect(screen.getByRole("button", { name: "Decrease by 3.8 cm" })).toHaveTextContent("−3.8");
    expect(screen.getByText("0.0 cm")).toBeInTheDocument();
  });

  it("increments the pending amount and previews it live, without committing", async () => {
    const onPreview = vi.fn();
    const onSetBond = vi.fn();
    render(<GridShift mode="vertical" onPreview={onPreview} onSetBond={onSetBond} />);
    await userEvent.click(screen.getByRole("button", { name: "Increase by 3.8 cm" }));
    expect(screen.getByText("+3.8 cm")).toBeInTheDocument();
    expect(onPreview).toHaveBeenLastCalledWith(1, 3.8);
    expect(onSetBond).not.toHaveBeenCalled();
  });

  it("Apply commits the pending offset and clears the preview", async () => {
    const onSetBond = vi.fn();
    render(<GridShift mode="vertical" onSetBond={onSetBond} />);
    expect(screen.getByRole("button", { name: "APPLY" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Increase by 3.8 cm" }));
    await userEvent.click(screen.getByRole("button", { name: "APPLY" }));
    expect(onSetBond).toHaveBeenCalledWith(1, [0, 3.8]);
  });

  it("Apply with the amount back at zero clears the course", async () => {
    const onSetBond = vi.fn();
    render(<GridShift mode="vertical" bondShifts={{ vertical: { 1: [0, 3.8] } }} onSetBond={onSetBond} />);
    expect(screen.getByText("+3.8 cm")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Decrease by 3.8 cm" }));
    await userEvent.click(screen.getByRole("button", { name: "APPLY" }));
    expect(onSetBond).toHaveBeenCalledWith(1, null);
  });

  it("reset drops the pending change", async () => {
    render(<GridShift mode="vertical" onSetBond={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Increase by 3.8 cm" }));
    await userEvent.click(screen.getByRole("button", { name: "reset" }));
    expect(screen.getByText("0.0 cm")).toBeInTheDocument();
  });

  it("the course selector picks which level Apply writes", async () => {
    const onSetBond = vi.fn();
    render(<GridShift mode="vertical" ceiling={6} onSetBond={onSetBond} />);
    await userEvent.click(screen.getByRole("button", { name: "Next course" }));
    await userEvent.click(screen.getByRole("button", { name: "Next course" }));
    await userEvent.click(screen.getByRole("button", { name: "Increase by 3.8 cm" }));
    await userEvent.click(screen.getByRole("button", { name: "APPLY" }));
    expect(onSetBond).toHaveBeenCalledWith(3, [0, 3.8]);
  });

  it("horizontal moves the X axis", async () => {
    const onSetBond = vi.fn();
    render(<GridShift mode="horizontal" onSetBond={onSetBond} />);
    expect(screen.getByText("X axis")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Increase by 3.8 cm" }));
    await userEvent.click(screen.getByRole("button", { name: "APPLY" }));
    expect(onSetBond).toHaveBeenCalledWith(1, [3.8, 0]);
  });

  it("running bond fills the alternating courses up to the tallest block", async () => {
    const onSetBond = vi.fn();
    render(<GridShift mode="vertical" maxLevel={4} onSetBond={onSetBond} />);
    await userEvent.click(screen.getByRole("button", { name: /running bond/ }));
    expect(onSetBond.mock.calls).toEqual([[1, [0, 3.8]], [2, null], [3, [0, 3.8]], [4, null]]);
  });

  it("warns about orphaned blocks", () => {
    render(<GridShift mode="vertical" orphanCount={2} onSetBond={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("2 blocks pushed off the travel cap");
  });
});
