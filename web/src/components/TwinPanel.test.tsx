/**
 * The twin's chrome. The 3D canvas is stubbed — Plan 4 §0.4 rules out testing
 * the rendering, and §9's rules are all in `studio/twin.ts` — so what is
 * asserted here is the chrome's own promises: a read-only mode label, a sync
 * toggle that admits it disables the orbit, and the console's locked copy.
 */
import { fireEvent, render, screen, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Instrument } from "./Instrument";
import { TwinPanel } from "./TwinPanel";
import * as api from "../api";
import { EXAMPLES } from "../studio/examples";
import type { StateModel } from "../types";
import { testState } from "../test-state";

vi.mock("../routes/twin-loader", () => ({
  preloadTwin: () => Promise.resolve({
    default: ({ synced }: { synced: boolean }) =>
      <div data-testid="twin-canvas" data-synced={String(synced)} />,
  }),
}));

const state = (overrides: Partial<StateModel> = {}): StateModel => testState({
  mode: "vertical", cols: 7, rows: 6, calibrated: true, selected: null,
  ...overrides,
});

const panel = (props: Partial<Parameters<typeof TwinPanel>[0]> = {}) =>
  render(<TwinPanel state={state()} connected lastUpdateAt={Date.now()} {...props} />);

/** jsdom always answers `false`; the tests that need a phone say so. */
function media(phone: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: phone && query.includes("max-width"),
    media: query, onchange: null,
    addEventListener: () => {}, removeEventListener: () => {},
    addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

beforeEach(() => media(false));
afterEach(() => vi.restoreAllMocks());

describe("the twin's mode indicator — the trap in this milestone", () => {
  it("mirrors state.mode as a plain label, with no control that could latch it", () => {
    const post = vi.spyOn(api, "mode").mockResolvedValue(state());
    const { rerender } = panel();
    const label = screen.getByLabelText("Rig grid mode");
    expect(label).toHaveTextContent("VERTICAL");
    expect(label.tagName).not.toBe("BUTTON");
    expect(label.querySelector("button")).toBeNull();
    rerender(<TwinPanel state={state({ mode: "horizontal" })} connected lastUpdateAt={Date.now()} />);
    expect(screen.getByLabelText("Rig grid mode")).toHaveTextContent("HORIZONTAL");
    expect(post).not.toHaveBeenCalled();
  });

  it("says where a mode change actually happens, and never offers one itself", () => {
    panel();
    expect(screen.getByText(/homes the rig/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /horizontal/i })).toBeNull();
  });
});

describe("SYNC VIEW", () => {
  it("presses, disables the orbit, and says so", () => {
    panel();
    const chip = screen.getByRole("button", { name: "SYNC VIEW" });
    expect(chip).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(chip);
    expect(chip).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("synced to camera")).toBeInTheDocument();
  });
});

describe("the twin's banners", () => {
  it("carries the console's locked copy and offers no retry", () => {
    panel({ state: state({ build_state: "LOCKED", locked_reason: "build aborted" }) });
    expect(screen.getByText("SESSION LOCKED")).toBeInTheDocument();
    expect(screen.getByText(/build aborted/)).toBeInTheDocument();
    expect(screen.getByText(/inspect the rig/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retry/i })).toBeNull();
  });

  it("names a rejection in the server's own words", () => {
    panel({ state: state({ last_result: "rejected", last_result_reason: "no block detected" }) });
    expect(screen.getByText(/no block detected/)).toBeInTheDocument();
  });

  it("shows STALE with the seconds since the last update when the socket drops", () => {
    panel({ connected: false, lastUpdateAt: Date.now() - 7_000 });
    expect(screen.getByText("STALE")).toBeInTheDocument();
    expect(screen.getByText(/7s since the last update/)).toBeInTheDocument();
  });
});

describe("choosing the model the twin shows", () => {
  it("offers the built-in examples and loads the one chosen", () => {
    panel();
    const picker = screen.getByLabelText("Model shown in the twin");
    EXAMPLES.forEach(example =>
      expect(screen.getByRole("option", { name: new RegExp(example.name) })).toBeInTheDocument());
    fireEvent.change(picker, { target: { value: EXAMPLES[0].id } });
    expect(screen.getByText(/5 blocks/)).toBeInTheDocument();
  });

  it("can be controlled by the runner so the twin and program cannot diverge", () => {
    const changed = vi.fn();
    panel({ modelId: EXAMPLES[1].id, onModelIdChange: changed, modelSelectionDisabled: true });
    const picker = screen.getByLabelText("Model shown in the twin");
    expect(picker).toHaveValue(EXAMPLES[1].id);
    expect(picker).toBeDisabled();
    expect(screen.getByText(/5 blocks/)).toBeInTheDocument();
  });
});

describe("the index layout — camera and twin, in step", () => {
  it("shows both, top-aligned in one instrument, on a desktop", () => {
    const { container } = render(
      <Instrument camera={<div data-testid="camera" />} twin={<div data-testid="twin" />} />);
    expect(screen.getByTestId("camera")).toBeInTheDocument();
    expect(screen.getByTestId("twin")).toBeInTheDocument();
    expect(container.querySelector(".instrument")).toBeTruthy();
    expect(screen.queryByRole("tab")).toBeNull();
  });

  it("becomes a two-tab switcher on a phone, DEFAULTING TO THE CAMERA", () => {
    media(true);
    render(<Instrument camera={<div data-testid="camera" />} twin={<div data-testid="twin" />} />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map(tab => tab.textContent)).toEqual(["CAMERA", "TWIN"]);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("camera")).toBeInTheDocument();
    expect(screen.queryByTestId("twin")).toBeNull();

    fireEvent.click(tabs[1]);
    expect(screen.getByTestId("twin")).toBeInTheDocument();
    expect(screen.queryByTestId("camera")).toBeNull();
  });
});
