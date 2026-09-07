/**
 * The banner is the only one of supervision's four surfaces allowed to be an
 * alarm, and the rules it has to keep are the ones a console lives or dies on:
 * the good case is near-silent, "not looking" takes no state colour, and a red
 * verdict cannot be waved away by reflex.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SupervisionBanner } from "./SupervisionBanner";
import { GridOverlay } from "./GridOverlay";
import { testState } from "../test-state";
import type { StateModel, Supervision } from "../types";

const supervision = (over: Partial<Supervision> = {}): Supervision => ({
  state: "VERDICT", verdict: "REMOVED", severity: "amber", cells: [[3, 1]],
  mode: "vertical", expected: [[3, 1]], observed: [], unjudged: [],
  reason: null, judged_at_ms: 12, acknowledged: false, ...over,
});

const state = (over: Partial<Supervision> = {}): StateModel =>
  testState({ supervision: supervision(over) });

describe("the supervision banner", () => {
  it("gives VERIFIED no banner at all", () => {
    // 40 green bars a build trains the operator to ignore them, and then the
    // one amber bar that matters is ignored too.
    const { container } = render(
      <SupervisionBanner state={state({ verdict: "VERIFIED", severity: "none", cells: [] })}
                         onAcknowledge={() => {}} />);
    expect(container.querySelector(".banner")).toBeNull();
  });

  it("gives BUSY, QUIET and NO MEMORY no state colour", () => {
    // BUSY is the normal condition for a whole build. Colouring it amber
    // leaves the console amber most of the time and the palette means nothing.
    for (const phase of ["BUSY", "QUIET", "NO_MEMORY", "WARMING"] as const) {
      const { container, unmount } = render(
        <SupervisionBanner state={state({ state: phase, verdict: null, severity: "none", cells: [] })}
                           onAcknowledge={() => {}} />);
      expect(container.querySelector(".sv-amber")).toBeNull();
      expect(container.querySelector(".sv-red")).toBeNull();
      unmount();
    }
  });

  it("is polite for amber and an alert for red", () => {
    const { unmount } = render(<SupervisionBanner state={state()} onAcknowledge={() => {}} />);
    expect(screen.getByRole("status")).toHaveClass("sv-amber");
    unmount();
    render(<SupervisionBanner state={state({ verdict: "FOREIGN", severity: "red", cells: [[4, 2]] })}
                              onAcknowledge={() => {}} />);
    expect(screen.getByRole("alert")).toHaveClass("sv-red");
  });

  it("names the cell in the first four words and says what to do", () => {
    render(<SupervisionBanner state={state()} onAcknowledge={() => {}} />);
    const text = screen.getByRole("status").textContent ?? "";
    expect(text).toContain("[3,1]");
    expect(text).toContain("Put it back");
    // Never "error" — the machine may have got this right.
    expect(text.toLowerCase()).not.toContain("error");
  });

  it("names the cell on the dismiss control, not 'dismiss'", () => {
    const ack = vi.fn();
    render(<SupervisionBanner state={state()} onAcknowledge={ack} />);
    const button = screen.getByRole("button", { name: /column 3 row 1/ });
    fireEvent.click(button);
    expect(ack).toHaveBeenCalled();
  });

  it("carries a word AND a shape, never colour alone", () => {
    render(<SupervisionBanner state={state()} onAcknowledge={() => {}} />);
    expect(screen.getByRole("status").textContent).toContain("▲");
    expect(screen.getByRole("status").textContent).toContain("REMOVED");
  });

  it("shows both sets on DISAGREES, because no cause can be named", () => {
    render(<SupervisionBanner state={state({
      verdict: "DISAGREES", severity: "red", cells: [[1, 1], [4, 2]],
      expected: [[1, 1], [2, 1]], observed: [[2, 1], [4, 2]],
    })} onAcknowledge={() => {}} />);
    const text = screen.getByRole("alert").textContent ?? "";
    expect(text).toContain("expected [1,1] [2,1]");
    expect(text).toContain("observed [2,1] [4,2]");
  });

  it("states the unjudged count and reason rather than hiding it", () => {
    render(<SupervisionBanner state={state({ unjudged: [[1, 1], [2, 2], [3, 3]] })}
                              onAcknowledge={() => {}} />);
    expect(screen.getByRole("status").textContent).toContain("UNCHECKED 3 cells");
  });

  it("goes quiet once the operator has acknowledged it", () => {
    const { container } = render(
      <SupervisionBanner state={state({ acknowledged: true })} onAcknowledge={() => {}} />);
    expect(container.querySelector(".banner")).toBeNull();
  });
});

describe("the camera overlay — the surface the operator is looking at", () => {
  const withGeometry = (over: Partial<Supervision>): StateModel => testState({
    supervision: supervision(over),
    geometry: {
      image_size: [640, 480], calibrated: true, selected: null, detections: [],
      grid: [
        { col: 3, row: 1, polygon: [[0, 0], [10, 0], [10, 10], [0, 10]] },
        { col: 4, row: 1, polygon: [[20, 0], [30, 0], [30, 10], [20, 10]] },
      ],
    } as StateModel["geometry"],
    views: { grid: true, detect: true },
  });

  it("marks exactly the cells the server named, and no others", () => {
    const { container } = render(
      <GridOverlay state={withGeometry({ cells: [[3, 1]] })} onSelect={() => {}} />);
    const marked = container.querySelectorAll(".sv-verdict");
    expect(marked).toHaveLength(1);
    expect(marked[0]).toHaveClass("sv-amber");
    expect(marked[0].querySelector("title")?.textContent).toContain("[3,1]");
  });

  it("marks nothing for VERIFIED — the good case leaves no persistent mark", () => {
    const { container } = render(
      <GridOverlay state={withGeometry({ verdict: "VERIFIED", severity: "none", cells: [] })}
                   onSelect={() => {}} />);
    expect(container.querySelectorAll(".sv-verdict")).toHaveLength(0);
  });

  it("hatches an unjudged cell instead of colouring it", () => {
    const { container } = render(
      <GridOverlay state={withGeometry({ cells: [], unjudged: [[4, 1]] })} onSelect={() => {}} />);
    const hatched = container.querySelectorAll(".sv-unjudged");
    expect(hatched).toHaveLength(1);
    // An absence of state must not take a state colour.
    expect(hatched[0]).not.toHaveClass("sv-amber");
    expect(hatched[0]).not.toHaveClass("sv-red");
    expect(hatched[0].querySelector("title")?.textContent)
      .toContain("above the detection ceiling");
  });
});
