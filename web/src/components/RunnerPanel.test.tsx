import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { StateModel } from "../types";
import type { RunnerApi } from "../studio/runner-driver";
import { RunnerPanel } from "./RunnerPanel";

const readyState = (changes: Partial<StateModel> = {}): StateModel => ({
  mode: "vertical", cols: 7, rows: 6, calibrated: true, selected: null,
  command: null, level: 0, build_state: "READY", locked_reason: null,
  camera: "LIVE", camera_age_ms: 10, last_result: null,
  last_result_reason: null, views: {}, geometry: {
    image_size: [640, 480], calibrated: true,
    grid: [{ col: 3, row: 2, polygon: [[300, 200], [340, 200], [340, 240], [300, 240]] }],
    selected: null, detections: [], paper: null,
  },
  ...changes,
});

function mockedApi(command = "B 3 2 0"): RunnerApi {
  return {
    setLevel: vi.fn(async value => readyState({ level: value })),
    select: vi.fn(async () => readyState({ selected: [3, 2], command })),
    selectAxis: vi.fn(async () => readyState({ selected: [3, 2], command })),
    build: vi.fn(async sent => readyState({ selected: [3, 2], command: sent, build_state: "RUNNING" })),
    mode: vi.fn(async next => readyState({ mode: next })),
  };
}

describe("RunnerPanel", () => {
  it("runs the complete tower through fake transport with no serial traffic", async () => {
    const api = mockedApi();
    render(<RunnerPanel state={readyState()} connected modelId="example-tower"
                        api={api} delay={async () => {}} />);
    expect(screen.getByText("FEED: BLUE")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "DRY RUN" }));
    fireEvent.click(screen.getByRole("button", { name: "START DRY RUN" }));

    await waitFor(() => expect(screen.getByText("RUN COMPLETE")).toBeInTheDocument());
    expect(screen.getByText("DRY RUN — no serial traffic")).toBeInTheDocument();
    expect(api.select).not.toHaveBeenCalled();
    expect(api.selectAxis).not.toHaveBeenCalled();
    expect(api.build).not.toHaveBeenCalled();
    expect(api.mode).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "EXPORT MARKDOWN" })).toBeEnabled();
  });

  it("stops and renders both commands verbatim when mocked selection disagrees", async () => {
    const api = mockedApi("B 3 2 9");
    render(<RunnerPanel state={readyState()} connected modelId="example-tower"
                        api={api} delay={async () => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "RUN" }));
    fireEvent.click(screen.getByRole("button", { name: "START RUN" }));

    await waitFor(() => expect(screen.getByText("COMMAND MISMATCH — RUN STOPPED")).toBeInTheDocument());
    expect(screen.getByText("program: B 3 2 0")).toBeInTheDocument();
    expect(screen.getByText("rig: B 3 2 9")).toBeInTheDocument();
    expect(api.build).not.toHaveBeenCalled();
  });

  it("states the honest stop semantics and exposes no cancel or retry control", () => {
    render(<RunnerPanel state={readyState()} connected modelId="example-tower" api={mockedApi()} />);
    expect(screen.getByText("the block in flight will finish — the rig cannot be interrupted")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /cancel/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
  });

  it("pauses on the server's REJECTED result at the same block", async () => {
    const api = mockedApi();
    const { rerender } = render(<RunnerPanel state={readyState()} connected modelId="example-tower" api={api} />);
    fireEvent.click(screen.getByRole("button", { name: "RUN" }));
    fireEvent.click(screen.getByRole("button", { name: "START RUN" }));
    await waitFor(() => expect(api.build).toHaveBeenCalledOnce());
    rerender(<RunnerPanel state={readyState({ build_state: "RUNNING", selected: [3, 2], command: "B 3 2 0" })}
                          connected modelId="example-tower" api={api} />);
    rerender(<RunnerPanel state={readyState({ last_result: "rejected", last_result_reason: "feeder empty",
                          selected: [3, 2], command: "B 3 2 0" })}
                          connected modelId="example-tower" api={api} />);
    await waitFor(() => expect(screen.getByText("REJECTED — RUN PAUSED")).toBeInTheDocument());
    expect(screen.getByText("feeder empty")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "CONTINUE" })).toBeEnabled();
    expect(api.build).toHaveBeenCalledOnce();
  });

  it("preserves an aborted program read-only with no recovery control", async () => {
    const api = mockedApi();
    const { rerender } = render(<RunnerPanel state={readyState()} connected modelId="example-tower" api={api} />);
    fireEvent.click(screen.getByRole("button", { name: "RUN" }));
    fireEvent.click(screen.getByRole("button", { name: "START RUN" }));
    await waitFor(() => expect(api.build).toHaveBeenCalledOnce());
    rerender(<RunnerPanel state={readyState({ build_state: "RUNNING", selected: [3, 2], command: "B 3 2 0" })}
                          connected modelId="example-tower" api={api} />);
    rerender(<RunnerPanel state={readyState({ build_state: "LOCKED", last_result: "aborted",
                          last_result_reason: "claw position unknown", locked_reason: "claw position unknown" })}
                          connected modelId="example-tower" api={api} />);
    await waitFor(() => expect(screen.getByText("SESSION LOCKED")).toBeInTheDocument());
    expect(screen.getByText("stopped at step 1 of 5")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "CONTINUE" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
  });
});
