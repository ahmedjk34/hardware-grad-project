import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { Settings } from "./Settings";
import { DEFAULT_STUDIO_SETTINGS } from "../settings";

describe("estimated validation settings", () => {
  it("labels every default and says what remains unmeasured", () => {
    render(<Settings value={DEFAULT_STUDIO_SETTINGS} onChange={() => {}} />);
    expect(screen.getByText("ESTIMATES — NOT MEASUREMENTS")).toBeInTheDocument();
    expect(screen.getByLabelText("Support ratio")).toHaveValue(0.55);
    expect(screen.getByLabelText("Claw clearance in millimetres")).toHaveValue(8);
    expect(screen.getByLabelText("Level ceiling")).toHaveValue(6);
    expect(screen.getByText(/Nobody has measured this rig/)).toBeInTheDocument();
    expect(screen.getByText(/Measure the claw and change this/)).toBeInTheDocument();
    expect(screen.getByText(/operator limit, not a physical one/)).toBeInTheDocument();
  });

  it("reports edits immediately", async () => {
    const change = vi.fn();
    function Harness() {
      const [value, setValue] = useState(DEFAULT_STUDIO_SETTINGS);
      return <Settings value={value} onChange={next => { setValue(next); change(next); }} />;
    }
    render(<Harness />);
    const input = screen.getByLabelText("Claw clearance in millimetres");
    await userEvent.clear(input);
    await userEvent.type(input, "12");
    expect(change).toHaveBeenLastCalledWith({ ...DEFAULT_STUDIO_SETTINGS, clawMarginMm: 12 });
  });
});
