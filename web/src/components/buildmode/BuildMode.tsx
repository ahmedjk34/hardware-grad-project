/**
 * Building mode — the `#/build` route.
 *
 * A deliberately spare screen for the moment the rig is actually working: the
 * live camera and the twin side by side and nothing else competing for the
 * operator's eye. Everything that would be a panel on the console is a toast
 * here — what the rig is doing, what it just did, what has to be loaded into
 * the feeder next — and the guarded runner sits in a thin dock along the
 * bottom.
 *
 * It owns NO machine authority. Every action still goes through the same
 * `RunnerPanel` / guarded-route path the console uses; this route only changes
 * what is on screen. It shares the module-singleton store (`consoleStore.ts`),
 * so opening it mid-build shows the build already in progress, and it shares
 * the twin's model key, so a build chosen here is the build the console shows.
 */
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { store } from "../../consoleStore";
import { twinModelChoices } from "../../studio/twin";
import { CameraChip } from "../CameraChip";
import { CameraView } from "../CameraView";
import { Icon } from "../Icon";
import { RunnerPanel } from "../RunnerPanel";
import { TwinPanel, rememberModelId, storedModelId } from "../TwinPanel";
import { BuildLibrary } from "./BuildLibrary";
import { ToastStack } from "./ToastStack";
import { useBuildToasts } from "./useBuildToasts";

export function BuildMode() {
  const snapshot = useSyncExternalStore(store.subscribe, () => store.snapshot);
  const [modelId, setModelId] = useState(storedModelId);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [controlsOpen, setControlsOpen] = useState(true);
  const [runnerActive, setRunnerActive] = useState(false);
  const { toasts, push, dismiss } = useBuildToasts();

  const state = snapshot.state;
  const progress = snapshot.progress;
  const result = snapshot.lastResult;

  const modelName = useMemo(() => {
    if (!modelId) return null;
    return twinModelChoices().find(choice => choice.id === modelId)?.name ?? "Unknown build";
  }, [modelId]);

  const pickModel = useCallback((id: string) => {
    setModelId(id);
    rememberModelId(id);
  }, []);

  // Esc closes the library first, then leaves building mode.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      setLibraryOpen(open => {
        if (open) return false;
        window.location.hash = "#/";
        return false;
      });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // ── toast: what the rig is doing, straight from the phase stream ──────────
  useEffect(() => {
    if ((progress.status === "running" || progress.status === "parking") && progress.label) {
      push({
        key: "rig:phase",
        kind: "info",
        title: "RIG",
        detail: progress.step !== null && progress.total !== null
          ? `${progress.step}/${progress.total} · ${progress.label}`
          : progress.label,
      });
    }
  }, [progress.eventId, progress.status, progress.label, progress.step, progress.total, push]);

  // ── toast: the settled result of the last command ───────────────────────
  useEffect(() => {
    if (!result) return;
    if (result.locked) {
      push({
        key: "rig:result", kind: "error", sticky: true, title: "SESSION LOCKED",
        detail: result.locked_reason ?? result.reason ?? "A human must inspect the rig and restart the service.",
      });
    } else if (result.result === "placed") {
      push({ key: "rig:result", kind: "success", title: "BLOCK PLACED" });
    } else if (result.result === "rejected") {
      push({
        key: "rig:result", kind: "warn", title: "BLOCK REJECTED",
        detail: result.reason ?? "The rig refused that cell.",
      });
    } else if (result.result === "aborted") {
      push({
        key: "rig:result", kind: "error", sticky: true, title: "BUILD ABORTED",
        detail: result.reason ?? "The rig stopped mid-command; its position is unknown.",
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result?.eventId]);

  // ── toast: the socket ──────────────────────────────────────────────────
  useEffect(() => {
    if (snapshot.connected) {
      dismiss("socket");
    } else {
      push({
        key: "socket", kind: "warn", sticky: true, title: "SOCKET LOST",
        detail: "Reconnecting. If a build was running, do not touch the rig.",
      });
    }
  }, [snapshot.connected, push, dismiss]);

  if (!state) return (
    <main className="boot"><Icon name="waiting" size={28} />Connecting to rig…</main>
  );

  const buildState = state.build_state;

  return (
    <div className="buildmode">
      {/* A deliberately thin bar: a way out, the library toggle, the loaded
          build's name, and a minimal safety strip. Everything else is a toast
          or the floating controls. */}
      <header className="bm-bar">
        <a className="bm-exit" href="#/" aria-label="Leave building mode">
          <span aria-hidden="true">‹</span> CONSOLE
        </a>
        <button type="button" className="bm-librarybtn" aria-expanded={libraryOpen}
                onClick={() => setLibraryOpen(open => !open)}>
          <Icon name="layers" size={14} />LIBRARY
        </button>
        <span className="bm-model" title={modelName ?? undefined}>
          {modelName ?? "No build selected"}
        </span>

        <span className="spacer" />

        <span className={`chip ${
          buildState === "RUNNING" ? "is-motion"
          : buildState === "LOCKED" ? "is-danger" : "is-ready"}`}>
          {buildState}
        </span>
        <CameraChip state={state} />
        <span className={`chip ${snapshot.connected ? "is-ready" : "is-danger"}`}
              aria-label="Socket">
          <Icon name={snapshot.connected ? "link" : "unlink"} size={13} />
        </span>
      </header>

      <div className="bm-split">
        <section className="bm-pane bm-pane-camera">
          <CameraView state={state} connected={snapshot.connected} />
        </section>
        <section className="bm-pane bm-pane-twin">
          <TwinPanel state={state} connected={snapshot.connected}
                     lastUpdateAt={snapshot.updatedAt}
                     build={snapshot.progress}
                     modelId={modelId}
                     onModelIdChange={pickModel}
                     modelSelectionDisabled={runnerActive} />
        </section>
      </div>

      {/* The controls float over the twin's dead space, bottom-right, and
          collapse to a tab when they are in the way. */}
      <div className={`bm-controls${controlsOpen ? "" : " is-collapsed"}`}>
        <button type="button" className="bm-controls-toggle"
                aria-expanded={controlsOpen}
                onClick={() => setControlsOpen(open => !open)}>
          {controlsOpen ? "▾ CONTROLS" : "▸ CONTROLS"}
        </button>
        {controlsOpen && (
          <RunnerPanel state={state} connected={snapshot.connected}
                       modelId={modelId} compact
                       onActiveChange={setRunnerActive}
                       onToast={push}
                       progress={snapshot.progress}
                       lastResult={snapshot.lastResult} />
        )}
      </div>

      <ToastStack toasts={toasts} onDismiss={dismiss} />
      <BuildLibrary open={libraryOpen} mode={state.mode} currentId={modelId}
                    onPick={pickModel} onClose={() => setLibraryOpen(false)} />
    </div>
  );
}
