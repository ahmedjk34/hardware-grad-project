/**
 * Building mode (`#/build`): the fullscreen camera + twin console.
 *
 * The runner, the twin and the guarded routes are covered by their own suites.
 * What is new here and worth asserting: the toast queue's dedupe/expiry rules,
 * that the runner emits operator-facing toasts through `onToast` without any
 * behaviour change, that the library selects (and only selects) a build, and
 * that the route wires all three together over the shared store.
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useBuildToasts } from "./components/buildmode/useBuildToasts";
import { ToastStack } from "./components/buildmode/ToastStack";
import { BuildLibrary } from "./components/buildmode/BuildLibrary";
import { BuildMode } from "./components/buildmode/BuildMode";
import { RunnerPanel } from "./components/RunnerPanel";
import type { RunnerApi } from "./studio/runner-driver";
import { store } from "./consoleStore";
import { testState } from "./test-state";
import type { StateModel } from "./types";
import { useEffect } from "react";

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

// ── the toast queue ────────────────────────────────────────────────────────

function ToastHarness({ script }: { script: Parameters<ReturnType<typeof useBuildToasts>["push"]>[0][] }) {
  const { toasts, push, dismiss } = useBuildToasts();
  useEffect(() => { script.forEach(push); }, [script, push]);
  return (
    <div>
      <span data-testid="count">{toasts.length}</span>
      <ul>{toasts.map(t => <li key={t.id}>{t.title}{t.detail ? ` — ${t.detail}` : ""}</li>)}</ul>
      <button type="button" onClick={() => dismiss("socket")}>drop socket</button>
    </div>
  );
}

describe("useBuildToasts", () => {
  it("ignores a repeat of the newest key but keeps a changed one", () => {
    render(<ToastHarness script={[
      { key: "rig:phase", kind: "info", title: "A" },
      { key: "rig:phase", kind: "info", title: "A" },
      { key: "rig:phase", kind: "info", title: "B" },
    ]} />);
    // The two identical A pushes collapse; B replaces (same key never stacks).
    expect(screen.getByTestId("count").textContent).toBe("1");
    expect(screen.getByText("B")).toBeInTheDocument();
  });

  it("caps the visible stack at four", () => {
    render(<ToastHarness script={Array.from({ length: 7 }, (_, i) => (
      { key: `k${i}`, kind: "info" as const, title: `T${i}` }
    ))} />);
    expect(screen.getByTestId("count").textContent).toBe("4");
    expect(screen.queryByText("T2")).not.toBeInTheDocument();
    expect(screen.getByText("T6")).toBeInTheDocument();
  });

  it("expires a non-sticky toast on the timer and keeps a sticky one", () => {
    vi.useFakeTimers();
    try {
      render(<ToastHarness script={[
        { key: "socket", kind: "warn", title: "SOCKET LOST", sticky: true },
        { key: "rig:result", kind: "success", title: "BLOCK PLACED" },
      ]} />);
      expect(screen.getByTestId("count").textContent).toBe("2");
      act(() => { vi.advanceTimersByTime(6500); });
      expect(screen.queryByText("BLOCK PLACED")).not.toBeInTheDocument();
      expect(screen.getByText("SOCKET LOST")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("dismisses a sticky toast by key on demand", () => {
    render(<ToastHarness script={[{ key: "socket", kind: "warn", title: "SOCKET LOST", sticky: true }]} />);
    fireEvent.click(screen.getByRole("button", { name: "drop socket" }));
    expect(screen.queryByText("SOCKET LOST")).not.toBeInTheDocument();
  });
});

describe("ToastStack", () => {
  it("renders a toast and dismisses by key", () => {
    const onDismiss = vi.fn();
    render(<ToastStack onDismiss={onDismiss} toasts={[
      { id: 1, key: "rig:result", kind: "warn", title: "BLOCK REJECTED", detail: "feeder empty" },
    ]} />);
    expect(screen.getByText("BLOCK REJECTED")).toBeInTheDocument();
    expect(screen.getByText("feeder empty")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(onDismiss).toHaveBeenCalledWith("rig:result");
  });
});

// ── the runner speaks through onToast, unchanged otherwise ──────────────────

describe("RunnerPanel onToast", () => {
  it("emits a feeder toast for the loaded model and a completion toast on a dry run", async () => {
    const onToast = vi.fn();
    render(<RunnerPanel state={readyState()} connected modelId="example-tower"
                        api={mockedApi()} delay={async () => {}} onToast={onToast} />);
    await waitFor(() => expect(onToast).toHaveBeenCalledWith(
      expect.objectContaining({ key: "runner:feed", title: "FEEDER · LOAD BLUE" })));

    fireEvent.click(screen.getByRole("button", { name: "DRY RUN" }));
    fireEvent.click(screen.getByRole("button", { name: "START DRY RUN" }));
    await waitFor(() => expect(onToast).toHaveBeenCalledWith(
      expect.objectContaining({ key: "runner:phase:done", kind: "success", title: "RUN COMPLETE" })));
  });

  it("does nothing extra when no onToast is given (console behaviour)", () => {
    // Same assertion the console relies on: the honest-stop line is present and
    // no cancel/retry affordance exists.
    render(<RunnerPanel state={readyState()} connected modelId="example-tower" api={mockedApi()} />);
    expect(screen.getByText(/the rig cannot be interrupted/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
  });
});

// ── the library selects a build and nothing else ───────────────────────────

describe("BuildLibrary", () => {
  it("lists the built-in examples with an estimate and only offers selection", () => {
    render(<BuildLibrary open mode="vertical" currentId="" onPick={() => {}} onClose={() => {}} />);
    expect(screen.getByText("Single tower")).toBeInTheDocument();
    // The estimate string the runner's own compiler produces.
    expect(screen.getAllByText(/~\d/).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: /delete/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /import/i })).not.toBeInTheDocument();
  });

  it("reports the pick and closes", () => {
    const onPick = vi.fn();
    const onClose = vi.fn();
    render(<BuildLibrary open mode="vertical" currentId="" onPick={onPick} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: /Single tower/ }));
    expect(onPick).toHaveBeenCalledWith(expect.any(String));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("is hidden when closed", () => {
    render(<BuildLibrary open={false} mode="vertical" currentId="" onPick={() => {}} onClose={() => {}} />);
    expect(screen.getByLabelText("Build library")).not.toBeVisible();
  });
});

// ── the route, over the shared store ───────────────────────────────────────

describe("BuildMode", () => {
  beforeEach(() => {
    store.applyEvent({ type: "state", event_id: 1, at: 1, state: readyState() });
  });
  afterEach(() => { window.location.hash = ""; });

  it("draws the camera, the twin and the runner dock, and opens the library", () => {
    render(<BuildMode />);
    expect(screen.getByText("BUILDING MODE")).toBeInTheDocument();
    expect(screen.getByLabelText("Camera stage")).toBeInTheDocument();
    expect(screen.getByLabelText("Program runner")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /LIBRARY/ }));
    expect(screen.getByLabelText("Build library")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /Single tower/ }));
    // Selecting a build names it in the bar.
    expect(screen.getByText("Single tower", { selector: ".bm-model" })).toBeInTheDocument();
  });

  it("raises a sticky toast when the socket drops and clears it when it returns", async () => {
    render(<BuildMode />);
    act(() => { store.disconnected(); });
    await waitFor(() => expect(screen.getByText("SOCKET LOST")).toBeInTheDocument());
    act(() => { store.connected(); });
    await waitFor(() => expect(screen.queryByText("SOCKET LOST")).not.toBeInTheDocument());
  });
});
