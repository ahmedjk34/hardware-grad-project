import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BuildButton } from "./components/BuildButton";
import { CameraChip } from "./components/CameraChip";
import { CameraView } from "./components/CameraView";
import { Calibrate } from "./components/Calibrate";
import { LevelStepper } from "./components/LevelStepper";
import { ModeSwitch } from "./components/ModeSwitch";
import { RigLog } from "./components/RigLog";
import { Shortcuts } from "./components/Shortcuts";
import { createConsoleStore, LOG_CAP } from "./store";
import * as api from "./api";
import type { StateModel } from "./types";
import { testState } from "./test-state";

const state = (overrides: Partial<StateModel> = {}): StateModel => testState({
  mode: "vertical", cols: 6, rows: 5, calibrated: true, selected: [3, 5],
  command: "B 3 5 0", level: 1, camera_age_ms: 42,
  views: { grid: true, detect: true, paper: false, overlay: true },
  geometry: { image_size: [640, 480], calibrated: true, grid: [], selected: null, detections: [], paper: null },
  ...overrides,
});

const serial = (id: number, line: string, stream: "rig" | "error" = "rig") =>
  ({ type: "serial" as const, event_id: id, at: id, line, stream });

describe("rig log buffer", () => {
  it("appends each line once and caps the buffer", () => {
    const store = createConsoleStore();
    store.applyEvent(serial(1, "@0 READY"));
    store.applyEvent(serial(2, "@1 PLACED 3 5 0"));
    store.applyEvent(serial(3, "ERROR limit"));
    expect(store.snapshot.log.map(line => line.text))
      .toEqual(["@0 READY", "@1 PLACED 3 5 0", "ERROR limit"]);
    store.applyEvents(Array.from({ length: LOG_CAP + 50 },
      (_, index) => serial(index + 4, `line ${index}`)));
    expect(store.snapshot.log).toHaveLength(LOG_CAP);
    expect(store.snapshot.log.at(-1)?.text).toBe(`line ${LOG_CAP + 49}`);
  });

  it("keeps two identical lines, because the rig printed two", () => {
    // The old store deduplicated by text overlap and would have swallowed the
    // second of these. Two ids is two lines, whatever they say.
    const store = createConsoleStore();
    store.applyEvent(serial(1, "  AT ORIGIN. Position = X 0 / Y 0"));
    store.applyEvent(serial(2, "  AT ORIGIN. Position = X 0 / Y 0"));
    expect(store.snapshot.log).toHaveLength(2);
  });

  it("drops a repeat of an id it has already applied", () => {
    const store = createConsoleStore();
    store.applyEvent(serial(7, "@0 READY"));
    store.applyEvent(serial(7, "@0 READY"));
    store.applyEvent(serial(6, "an older line the replay overlapped"));
    expect(store.snapshot.log).toHaveLength(1);
  });

  it("colours lines by kind, marks phases, and can be collapsed", () => {
    const log = [
      { id: 0, text: "@2 ok", at: 0, kind: "ack" as const },
      { id: 1, text: "ERROR limit hit", at: 0, kind: "prose" as const },
      { id: 2, text: "PLACED 3 5 0", at: 0, kind: "prose" as const },
      { id: 3, text: "misc", at: 0, kind: "prose" as const },
      {
        id: 4, kind: "step" as const, at: 0,
        text: "@12 STEP step=8 total=14 phase=move_to_target action=move"
          + " text=Move_XY_to_the_target_cell status=begin",
      },
    ];
    render(<RigLog log={log} defaultOpen />);
    expect(screen.getByText("@2 ok").parentElement).toHaveClass("ack");
    expect(screen.getByText("ERROR limit hit").parentElement).toHaveClass("error");
    expect(screen.getByText("PLACED 3 5 0").parentElement).toHaveClass("placed");
    // The raw line survives verbatim; the summary is drawn beside it.
    expect(screen.getByText(/@12 STEP step=8/).parentElement).toHaveClass("step");
    expect(screen.getByText("8/14 Move XY to the target cell")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Collapse" }));
    expect(screen.queryByText("misc")).toBeNull();
  });

  it("says so when a reconnect could not be filled from the replay buffer", () => {
    render(<RigLog log={[]} defaultOpen gap />);
    expect(screen.getByText(/lines were missed/)).toBeInTheDocument();
  });
});

describe("overlay view toggles", () => {
  it("posts the inverted flag and stays available while the rig is moving", () => {
    const view = vi.spyOn(api, "view").mockResolvedValue(state());
    const { rerender } = render(<CameraView state={state()} connected />);
    fireEvent.click(screen.getByRole("button", { name: "Toggle detect overlay" }));
    expect(view).toHaveBeenCalledWith({ detect: false });
    rerender(<CameraView state={state({ build_state: "RUNNING" })} connected />);
    expect(screen.getByRole("button", { name: "Toggle grid overlay" })).toBeEnabled();
  });
});

describe("grid mode switch", () => {
  it("warns that the rig homes before it posts the new mode", () => {
    const mode = vi.spyOn(api, "mode").mockResolvedValue(state());
    render(<ModeSwitch state={state()} disabled={false} />);
    fireEvent.click(screen.getByRole("button", { name: "horizontal" }));
    expect(mode).not.toHaveBeenCalled();
    expect(screen.getByText(/homes the X and Y axes/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Home and switch" }));
    expect(mode).toHaveBeenCalledWith("horizontal");
  });
});

describe("camera freshness", () => {
  it("names the freshness and shows the frame age", () => {
    const { rerender } = render(<CameraChip state={state()} />);
    expect(screen.getByText(/LIVE/)).toHaveClass("is-ready");
    expect(screen.getByText("42ms")).toBeInTheDocument();
    rerender(<CameraChip state={state({ camera: "STALE", camera_age_ms: 2140 })} />);
    expect(screen.getByText(/STALE/)).toHaveClass("is-motion");
    expect(screen.getByText("2,140ms")).toBeInTheDocument();
    rerender(<CameraChip state={state({ camera: "WAITING", camera_age_ms: null })} />);
    expect(screen.getByText(/WAITING/)).toHaveClass("is-idle");
  });
});

describe("direct level entry", () => {
  it("sends an absolute level and refuses a negative one", () => {
    const setLevel = vi.spyOn(api, "setLevel").mockResolvedValue(state());
    render(<LevelStepper level={1} disabled={false} />);
    const input = screen.getByLabelText("Level");
    fireEvent.change(input, { target: { value: "4" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(setLevel).toHaveBeenCalledWith(4);
    fireEvent.change(input, { target: { value: "-2" } });
    fireEvent.blur(input);
    expect(setLevel).toHaveBeenCalledTimes(1);
  });
});

describe("build affordances", () => {
  it("renders the disabled reason as visible text, not only a tooltip", () => {
    render(<BuildButton state={state({ selected: null, command: null })} connected />);
    expect(screen.getByText("Select a cell first")).toBeInTheDocument();
  });

  it("shows a draining arm indicator once armed", () => {
    const { container } = render(<BuildButton state={state()} connected />);
    fireEvent.click(screen.getByRole("button", { name: "BUILD" }));
    expect(screen.getByRole("button", { name: "CONFIRM B 3 5 0" })).toBeEnabled();
    expect(container.querySelector(".arm-drain")).toBeTruthy();
  });
});

describe("keyboard help", () => {
  it("lists every shortcut in the overlay", () => {
    render(<Shortcuts onClose={() => {}} />);
    ["← ↑ → ↓", "+ / −", "Esc", "B", "Enter", "?"].forEach(key =>
      expect(screen.getByText(key)).toBeInTheDocument());
  });
});

describe("calibration wizard", () => {
  it("tracks which corner is being collected", async () => {
    vi.spyOn(api.calibration, "start").mockResolvedValue({} as never);
    render(<Calibrate ready />);
    fireEvent.click(screen.getByRole("button", { name: "Calibrate" }));
    expect(await screen.findByText("0 of 4 corners")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Place corner" }));
    expect(screen.getByText("1 of 4 corners")).toBeInTheDocument();
    expect(screen.getByText(/far-X\/home-Y/)).toBeInTheDocument();
  });
});
