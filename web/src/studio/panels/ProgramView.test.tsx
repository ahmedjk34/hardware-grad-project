import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProgramView } from "./ProgramView";
import type { Op, Stats } from "../compile";

const program: Op[] = [
  { op: "build", id: "b1", col: 1, row: 1, level: 0, text: "B 1 1 0" },
  { op: "build", id: "b3", col: 3, row: 1, level: 0, text: "B 3 1 0" },
  { op: "mode", mode: "horizontal", cost: "homes X and Y", text: "RR" },
  { op: "build", id: "b4", col: 0, row: 2, level: 2, text: "B 0 2 2" },
];
const stats: Stats = { blocks: 3, latches: 1, modeSwitches: 1, levels: 2, estimateSeconds: 136 };

const writeText = vi.fn().mockResolvedValue(undefined);
beforeEach(() => vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } }));
afterEach(() => { vi.unstubAllGlobals(); writeText.mockClear(); });

describe("ProgramView — the compiled program as a serial log", () => {
  it("reads like serial: numbered build lines, the latch set apart, numbers continuing across it", () => {
    render(<ProgramView program={program} valid stats={stats} />);
    expect(screen.getByText("~2:16", { exact: false })).toHaveTextContent("3 blocks · 1 latch · ~2:16");

    const lines = screen.getAllByRole("button", { name: /^line \d/ });
    expect(lines.map(el => el.textContent)).toEqual([
      "01B 1 1 0b1", "02B 3 1 0b3", "03B 0 2 2b4",
    ]);

    const latch = screen.getByRole("separator", { name: /latch RR — homes X and Y/ });
    expect(latch).toHaveTextContent("RR");
    expect(latch).toHaveTextContent("homes X and Y");
  });

  it("selecting a line reports its block id and reflects the current selection", async () => {
    const onSelect = vi.fn();
    const { rerender } = render(
      <ProgramView program={program} valid stats={stats} onSelect={onSelect} />,
    );
    await userEvent.click(screen.getByRole("button", { name: /line 3: B 0 2 2/ }));
    expect(onSelect).toHaveBeenCalledWith("b4");

    rerender(<ProgramView program={program} valid stats={stats} selectedId="b4" onSelect={onSelect} />);
    expect(screen.getByRole("button", { name: /line 3: B 0 2 2/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /line 1: B 1 1 0/ })).toHaveAttribute("aria-pressed", "false");
  });

  it("copies the exact serial text — every op.text, one per line — to the clipboard", async () => {
    render(<ProgramView program={program} valid stats={stats} />);
    await userEvent.click(screen.getByRole("button", { name: "COPY" }));
    expect(writeText).toHaveBeenCalledWith("B 1 1 0\nB 3 1 0\nRR\nB 0 2 2");
  });

  it("emits no lines and a plain message when the model is invalid", () => {
    render(<ProgramView program={[]} valid={false}
                        stats={{ blocks: 0, latches: 0, modeSwitches: 0, levels: 0, estimateSeconds: 0 }} />);
    expect(screen.getByText("MODEL HAS ERRORS")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^line / })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "COPY" })).toBeDisabled();
  });
});
