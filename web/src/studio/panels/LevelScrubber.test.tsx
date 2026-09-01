import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { LevelScrubber } from "./LevelScrubber";

describe("level scrubber", () => {
  it("exposes every level and marks the held one", async () => {
    const hold = vi.fn();
    render(<LevelScrubber ceiling={4} heldLevel={2} onHold={hold} />);

    expect(screen.getByRole("button", { name: "Hold level 2" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "Hold level 4" }));
    expect(hold).toHaveBeenCalledWith(4);
  });

  it("releases the held level from its explicit control", async () => {
    const release = vi.fn();
    render(<LevelScrubber ceiling={3} heldLevel={1} onHold={() => {}} onRelease={release} />);
    await userEvent.click(screen.getByRole("button", { name: "Release held level" }));
    expect(release).toHaveBeenCalledOnce();
  });
});
