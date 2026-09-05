import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { StateModel } from "../types";
import type { RunnerApi } from "../studio/runner-driver";
import { RunnerPanel } from "./RunnerPanel";
import { emptyProgress, type BuildProgress, type ConsoleSnapshot } from "../store";

/** The phase the rig has just announced, as the store would hold it. */
const phaseAt = (step: number, phase: string, label: string,
                 overrides: Partial<BuildProgress> = {}): BuildProgress => ({
  ...emptyProgress(), status: "running", commandSeq: 1, step, total: 14,
  phase, label, action: "move", eventId: 100 + step, ...overrides,
});

/** A settled build, as the server's `build_result` event reported it. */
const settled = (result: "placed" | "rejected" | "aborted", reason: string | null,
                 locked = false): ConsoleSnapshot["lastResult"] => ({
  command_seq: 1, result, reason, locked, locked_reason: locked ? reason : null,
  from_prose: false, eventId: 900,
});
import { testState } from "../test-state";

const readyState = (changes: Partial<StateModel> = {}): StateModel => testState({
  mode: "vertical", cols: 7, rows: 6, calibrated: true, selected: null,
  geometry: {
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
                          connected modelId="example-tower" api={api}
                          lastResult={settled("rejected", "feeder empty")} />);
    await waitFor(() => expect(screen.getByText("REJECTED — RUN PAUSED")).toBeInTheDocument());
    expect(screen.getByText("feeder empty")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "CONTINUE" })).toBeEnabled();
    expect(api.build).toHaveBeenCalledOnce();
  });

  it("continues RUN when placed arrives before its READY state snapshot", async () => {
    const api = mockedApi();
    let selection = 0;
    api.select = vi.fn(async () => readyState({
      selected: [3, 2], command: `B 3 2 ${selection++}`,
    }));
    const { rerender } = render(<RunnerPanel state={readyState()} connected modelId="example-tower" api={api} />);
    fireEvent.click(screen.getByRole("button", { name: "RUN" }));
    fireEvent.click(screen.getByRole("button", { name: "START RUN" }));
    await waitFor(() => expect(api.build).toHaveBeenCalledWith("B 3 2 0"));

    // This is the production WebSocket order: the durable placed result is
    // delivered before the coalesced READY snapshot.
    rerender(<RunnerPanel state={readyState({ build_state: "RUNNING", selected: [3, 2], command: "B 3 2 0" })}
                          connected modelId="example-tower" api={api}
                          lastResult={settled("placed", null)} />);

    await waitFor(() => expect(api.build).toHaveBeenCalledWith("B 3 2 1"));
    expect(api.setLevel).toHaveBeenCalledWith(1);
    expect(screen.queryByText("RUN PAUSED")).not.toBeInTheDocument();
  });

  it("does not replay a SETTLED command's last phase onto the next command", async () => {
    // The server keeps `build_step`/`build_phase` across `on_result` — for a
    // failed build, where it stopped is the last thing anyone knows — and
    // stamps the following snapshot with the RESULT's event id. That id is
    // higher than any of that command's steps, so replaying it as a phase
    // pins the readout to "14/14 · Return the claw to neutral" over whatever
    // the rig does next.
    const api = mockedApi();
    let selection = 0;
    api.select = vi.fn(async () => readyState({
      selected: [3, 2], command: `B 3 2 ${selection++}`,
    }));
    const running = readyState({ build_state: "RUNNING", selected: [3, 2], command: "B 3 2 0" });
    const { rerender } = render(<RunnerPanel state={readyState()} connected modelId="example-tower" api={api} />);
    fireEvent.click(screen.getByRole("button", { name: "RUN" }));
    fireEvent.click(screen.getByRole("button", { name: "START RUN" }));
    await waitFor(() => expect(api.build).toHaveBeenCalledWith("B 3 2 0"));

    rerender(<RunnerPanel state={running} connected modelId="example-tower" api={api}
                          progress={phaseAt(14, "park_rotation", "Return the claw to neutral",
                                            { action: "park", status: "parking" })} />);
    await waitFor(() =>
      expect(screen.getByText("14/14 · Return the claw to neutral")).toBeInTheDocument());

    // The durable result settles the build and the next one goes out.
    rerender(<RunnerPanel state={running} connected modelId="example-tower" api={api}
                          progress={phaseAt(14, "park_rotation", "Return the claw to neutral",
                                            { action: "park", status: "parking" })}
                          lastResult={settled("placed", null)} />);
    await waitFor(() => expect(api.build).toHaveBeenCalledWith("B 3 2 1"));

    // The snapshot that follows the result: the SAME phase, now stamped
    // `placed` and carrying the result's (higher) event id. Block 2 is in
    // flight and the rig has not announced anything about it.
    rerender(<RunnerPanel state={running} connected modelId="example-tower" api={api}
                          progress={phaseAt(14, "park_rotation", "Return the claw to neutral",
                                            { action: "park", status: "placed", eventId: 900 })}
                          lastResult={settled("placed", null)} />);

    await waitFor(() => expect(screen.getByText("WAITING FOR THE RIG")).toBeInTheDocument());
    expect(screen.queryByText("14/14 · Return the claw to neutral")).not.toBeInTheDocument();
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
                          connected modelId="example-tower" api={api}
                          lastResult={settled("aborted", "claw position unknown", true)} />);
    await waitFor(() => expect(screen.getByText("SESSION LOCKED")).toBeInTheDocument());
    expect(screen.getByText("stopped at step 1 of 5")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "CONTINUE" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
  });

  it("shows the rig's own phase, and says so when the rig has said nothing", async () => {
    const api = mockedApi();
    const running = readyState({ build_state: "RUNNING", selected: [3, 2], command: "B 3 2 0" });
    const { rerender } = render(<RunnerPanel state={readyState()} connected modelId="example-tower" api={api} />);
    fireEvent.click(screen.getByRole("button", { name: "RUN" }));
    fireEvent.click(screen.getByRole("button", { name: "START RUN" }));
    await waitFor(() => expect(api.build).toHaveBeenCalledOnce());

    // The command is out and the board has not announced a phase yet. The
    // panel must say that, not invent a first step.
    rerender(<RunnerPanel state={running} connected modelId="example-tower" api={api} />);
    await waitFor(() => expect(screen.getByText("WAITING FOR THE RIG")).toBeInTheDocument());
    expect(screen.getByText(/has not announced a phase yet/)).toBeInTheDocument();

    rerender(<RunnerPanel state={running} connected modelId="example-tower" api={api}
                          progress={phaseAt(8, "move_to_target", "Move XY to the target cell")} />);
    await waitFor(() =>
      expect(screen.getByText("8/14 · Move XY to the target cell")).toBeInTheDocument());
    expect(screen.getByLabelText("Phase 8 of 14")).toHaveValue(8);
  });

  it("does not advance to the next block on a phase, only on the terminal OK", async () => {
    const api = mockedApi();
    const running = readyState({ build_state: "RUNNING", selected: [3, 2], command: "B 3 2 0" });
    const { rerender } = render(<RunnerPanel state={readyState()} connected modelId="example-tower" api={api} />);
    fireEvent.click(screen.getByRole("button", { name: "RUN" }));
    fireEvent.click(screen.getByRole("button", { name: "START RUN" }));
    await waitFor(() => expect(api.build).toHaveBeenCalledOnce());

    // Every phase of the build, INCLUDING the confirmed release and parking.
    for (const [step, phase, label] of [
      [6, "grip", "Close the claw and grip"],
      [11, "release", "Open the claw and release"],
      [14, "park_rotation", "Return the claw to neutral"],
    ] as const) {
      rerender(<RunnerPanel state={running} connected modelId="example-tower" api={api}
                            progress={phaseAt(step, phase, label,
                              step >= 11 ? { releaseConfirmed: true } : {})} />);
    }
    await waitFor(() =>
      expect(screen.getByText("14/14 · Return the claw to neutral")).toBeInTheDocument());
    // Fourteen phases later, the runner has still sent exactly one command.
    expect(api.build).toHaveBeenCalledOnce();
    expect(api.select).toHaveBeenCalledOnce();
    expect(screen.getByText("1 / 5")).toBeInTheDocument();
  });

  it("goes stale on a lost socket and assumes no progress from it", async () => {
    const api = mockedApi();
    const running = readyState({ build_state: "RUNNING", selected: [3, 2], command: "B 3 2 0" });
    const progress = phaseAt(8, "move_to_target", "Move XY to the target cell");
    const { rerender } = render(<RunnerPanel state={readyState()} connected modelId="example-tower" api={api} />);
    fireEvent.click(screen.getByRole("button", { name: "RUN" }));
    fireEvent.click(screen.getByRole("button", { name: "START RUN" }));
    await waitFor(() => expect(api.build).toHaveBeenCalledOnce());
    rerender(<RunnerPanel state={running} connected modelId="example-tower" api={api}
                          progress={progress} />);
    await waitFor(() => expect(screen.getByText(/reported by the rig/)).toBeInTheDocument());

    rerender(<RunnerPanel state={running} connected={false} modelId="example-tower" api={api}
                          progress={progress} />);
    await waitFor(() => expect(screen.getByText("STALE — RUN PAUSED")).toBeInTheDocument());
    // The last phase stays on screen, honestly labelled as the last one heard.
    expect(screen.getByText("8/14 · Move XY to the target cell")).toBeInTheDocument();
    expect(screen.getByText(/socket lost/)).toBeInTheDocument();
    expect(api.build).toHaveBeenCalledOnce();

    // A later phase proves the socket is back, and the run picks itself up.
    rerender(<RunnerPanel state={running} connected modelId="example-tower" api={api}
                          progress={phaseAt(10, "lower_to_level", "Lower Z to the target level")} />);
    await waitFor(() =>
      expect(screen.getByText("10/14 · Lower Z to the target level")).toBeInTheDocument());
    expect(screen.queryByText("STALE — RUN PAUSED")).not.toBeInTheDocument();
  });
});
