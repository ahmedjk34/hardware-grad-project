import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Diagnostics } from "./Diagnostics";
import type { Diagnostic } from "../validate";

const diagnostics: Diagnostic[] = [
  { severity: "warning", code: "CLAW_CLEARANCE", blockId: "b7", message: "b7 has guessed claw clearance" },
  { severity: "error", code: "COLLISION", blockId: "b4", message: "b4 would collide with b2",
    fix: { label: "Drop to level 1", edit: { type: "move", id: "b4", level: 1 } } },
];

describe("Diagnostics panel", () => {
  it("groups errors before warnings and reports a clean model plainly", () => {
    const { rerender } = render(<Diagnostics diagnostics={diagnostics} />);
    // The count is split across <b> and <span>, so normalise whitespace.
    expect(screen.getByText(/ERROR/).closest(".studio-error-count")).toHaveTextContent("1 ERROR");
    expect(screen.getByText(/WARNING/).closest(".studio-warning-count")).toHaveTextContent("1 WARNING");
    const rows = screen.getAllByRole("button", { name: /b[47]/ });
    expect(rows[0]).toHaveTextContent("b4");
    expect(rows[1]).toHaveTextContent("b7");

    rerender(<Diagnostics diagnostics={[]} />);
    expect(screen.getByText("NO PROBLEMS")).toBeInTheDocument();
  });

  it("previews, selects, frames and applies a real fix", async () => {
    const hover = vi.fn();
    const select = vi.fn();
    const fix = vi.fn();
    render(<Diagnostics diagnostics={diagnostics} onHover={hover} onSelect={select} onFix={fix} />);
    const row = screen.getByRole("button", { name: /b4 would collide/ });
    await userEvent.hover(row);
    expect(hover).toHaveBeenCalledWith("b4");
    await userEvent.click(row);
    expect(select).toHaveBeenCalledWith("b4");
    await userEvent.click(screen.getByRole("button", { name: "Drop to level 1" }));
    expect(fix).toHaveBeenCalledWith(diagnostics[1].fix);
    expect(select).toHaveBeenCalledTimes(1);
  });
});
