import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Calibrate } from "./components/Calibrate";
import * as api from "./api";

describe("Step 10 calibration collection", () => {
  it("advances prompts, undoes, and only saves with four corners", async () => {
    vi.spyOn(api.calibration, "start").mockResolvedValue({} as never);
    vi.spyOn(api.calibration, "undo").mockResolvedValue({} as never);
    const save = vi.spyOn(api.calibration, "save").mockResolvedValue({} as never);
    render(<Calibrate ready />);
    fireEvent.click(screen.getByRole("button", { name: "Calibrate" }));
    expect(await screen.findByText(/holder home/)).toBeInTheDocument();
    for (let index = 0; index < 3; index++) fireEvent.click(screen.getByRole("button", { name: "Place corner" }));
    expect(screen.getByRole("button", { name: "Save calibration" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    fireEvent.click(screen.getByRole("button", { name: "Place corner" }));
    fireEvent.click(screen.getByRole("button", { name: "Place corner" }));
    fireEvent.click(screen.getByRole("button", { name: "Save calibration" }));
    expect(save).toHaveBeenCalledOnce();
  });
});
