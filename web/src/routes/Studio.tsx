/**
 * The 3D Build Studio.
 *
 * The route owns editor state; the pure validator owns every machine decision.
 * The ghost and diagnostics panel enter the same RULES table, so an operator
 * cannot see one answer before a click and another after it.
 *
 * This route is loaded lazily (see `routes/Root.tsx`) so the operator console's
 * first paint never pays for three.js.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Viewport } from "../studio/scene/Viewport";
import { activeMode, cellCount, modeGeometry, reachableCells, type ModeName } from "../studio/coords";
import { VIEWS, type ViewName } from "../studio/view";
import { blockBoxScene, modelBoxScene } from "../studio/view";
import { applyEdit, emptyModel, type Edit, type Model, type ModelBlock } from "../studio/model";
import { createHistory, push, redo, undo } from "../studio/history";
import { keyboardAction, pointerIsClick, sameTarget, type Point2 } from "../studio/interaction";
import { runCells, type CellTarget } from "../studio/pick";
import type { SurfacePointer } from "../studio/scene/surface";
import { LevelScrubber } from "../studio/panels/LevelScrubber";
import { Diagnostics } from "../studio/panels/Diagnostics";
import { Settings } from "../studio/panels/Settings";
import { ProgramView } from "../studio/panels/ProgramView";
import { LibraryDrawer } from "../studio/panels/LibraryDrawer";
import { writeModel } from "../studio/library";
import { isExampleId } from "../studio/examples";
import { compile } from "../studio/compile";
import {
  loadStudioSettings, saveStudioSettings, type StudioSettings,
} from "../studio/settings";
import {
  placementDiagnosticMessage, primaryDiagnostic,
  validateModel, validatePlacement, type DiagnosticFix, type ValidationContext,
} from "../studio/validate";
import type { GhostStatus } from "../studio/scene/Ghost";
import type { CaptureHandle } from "../studio/scene/Capture";
import {
  documentOf, fromFileRig, newModelId, shiftsOf, structureOf, type StudioModel,
} from "../studio/rigmodel";

const VIEW_LABEL: Record<ViewName, string> = {
  top: "TOP", front: "FRONT", side: "SIDE", iso: "ISO",
};

/** The rail shows physical Z travel; the practical warning ceiling is a setting. */
const THEORETICAL_LEVEL_CEILING = 17;

/** A shift readout in the console's own register: signed, mono, two decimals. */
function signed(value: number): string {
  return `${value < 0 ? "−" : "+"}${Math.abs(value).toFixed(2)}`;
}

/** A cheap fingerprint of everything a save would persist about the geometry —
 *  used to tell a clean build from one with unsaved edits. */
function signatureOf(blocks: Model["blocks"], order: Model["order"], name: string): string {
  return JSON.stringify({ blocks, order, name });
}

export default function Studio() {
  const [mode, setMode] = useState<ModeName>(() => activeMode());
  const [view, setView] = useState<ViewName>("iso");
  const [nonce, setNonce] = useState(0);
  const [history, setHistory] = useState(() => createHistory(emptyModel()));
  const [target, setTarget] = useState<CellTarget | null>(null);
  const [heldLevel, setHeldLevel] = useState<number | null>(null);
  const [settings, setSettings] = useState<StudioSettings>(() => loadStudioSettings());
  const [hoveredDiagnosticId, setHoveredDiagnosticId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focusBox, setFocusBox] = useState<ReturnType<typeof blockBoxScene> | null>(null);
  /** The document the editor is currently inside: its identity, its name and
   *  the rig geometry it was authored against. Loading a model replaces this
   *  wholesale, which is what makes GEOMETRY_DRIFT reachable from the editor. */
  const [modelDocument, setModelDocument] = useState<StudioModel>(() => documentOf(emptyModel(), { name: "Untitled" }));
  const [libraryOpen, setLibraryOpen] = useState(false);
  /** The library id this editor is tracking — `null` means "never saved" (a
   *  blank build, or one opened from a built-in example), so the next save has
   *  to mint an id and ask for a name rather than overwrite anything. */
  const [savedId, setSavedId] = useState<string | null>(null);
  /** A cheap fingerprint of the geometry + name at the last save or open.
   *  Anything else means there is unsaved work. */
  const [savedSignature, setSavedSignature] = useState("");
  const [naming, setNaming] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [toast, setToast] = useState<{ kind: "ok" | "warn"; text: string } | null>(null);
  /** Bumped on every successful write so the library drawer re-reads storage
   *  even when the save came from the toolbar or Ctrl/⌘S rather than from it. */
  const [savedTick, setSavedTick] = useState(0);
  const capture = useRef(null) as CaptureHandle;
  const nextId = useRef(1);
  const gesture = useRef<{
    start: Point2; anchor: CellTarget; mode: ModeName; pointerId: number;
    shift: boolean; alt: boolean; blockId?: string;
  } | null>(null);

  const model = history.present;
  const currentSignature = useMemo(
    () => signatureOf(model.blocks, model.order, modelDocument.name),
    [model, modelDocument.name],
  );
  /** An empty, never-saved build is not "unsaved work" — there is nothing to
   *  lose yet. Anything placed, or any tracked model diverging, is. */
  const dirty = currentSignature !== savedSignature
    && (model.blocks.length > 0 || savedId !== null);

  // The model's own rig snapshot drives BOTH the shift the lattice is drawn
  // with and the snapshot GEOMETRY_DRIFT compares. A model that needs a shift
  // the rig is not applying therefore renders where it will really be built,
  // and says so, rather than looking right and building wrong.
  const shifts = useMemo(() => shiftsOf(modelDocument.rig), [modelDocument.rig]);
  const rigSnapshot = useMemo(() => fromFileRig(modelDocument.rig), [modelDocument.rig]);
  const validationContext = useMemo<ValidationContext>(
    () => ({ mode, settings, shifts, rigSnapshot }),
    [mode, settings, shifts, rigSnapshot],
  );
  const diagnostics = useMemo(
    () => validateModel(model, validationContext),
    [model, validationContext],
  );
  const program = useMemo(
    () => compile(model, { mode, settings, shifts, rigSnapshot }),
    [model, mode, settings, shifts, rigSnapshot],
  );
  const placementDiagnostics = useMemo(() => target ? validatePlacement(model, {
    id: "ghost", mode, col: target.col, row: target.row, level: target.level, colour: "white",
  }, validationContext) : [], [model, mode, target, validationContext]);
  const status = useMemo<GhostStatus | null>(() => {
    if (!target) return null;
    const errors = placementDiagnostics.filter(item => item.severity === "error");
    const primary = primaryDiagnostic(errors.length ? errors : placementDiagnostics);
    return {
      legal: errors.length === 0,
      reason: primary ? placementDiagnosticMessage(primary) : null,
      severity: primary?.severity ?? null,
    };
  }, [placementDiagnostics, target]);

  useEffect(() => saveStudioSettings(settings), [settings]);

  const geometry = modeGeometry(mode);
  const requested = cellCount(mode);
  const reachable = reachableCells(mode);
  const clipped = reachable.cols < requested.cols || reachable.rows < requested.rows;

  const snap = (next: ViewName) => {
    setView(next);
    setFocusBox(null);
    setNonce(value => value + 1);
  };
  const commit = useCallback((edit: Edit) => {
    setHistory(current => {
      const next = applyEdit(current.present, edit);
      return next === current.present ? current : push(current, next);
    });
  }, []);

  const atHeldLevel = useCallback((hit: SurfacePointer): SurfacePointer => heldLevel === null ? hit : ({
    ...hit, target: { ...hit.target, level: heldLevel },
  }), [heldLevel]);

  const surfaceMove = useCallback((raw: SurfacePointer) => {
    const next = atHeldLevel(raw).target;
    setTarget(current => sameTarget(current, next) ? current : next);
  }, [atHeldLevel]);

  const surfaceLeave = useCallback(() => {
    setTarget(current => current === null ? current : null);
  }, []);

  const surfaceDown = useCallback((raw: SurfacePointer) => {
    const hit = atHeldLevel(raw);
    gesture.current = {
      start: { x: hit.clientX, y: hit.clientY }, anchor: hit.target, mode,
      pointerId: hit.pointerId, shift: hit.shiftKey, alt: hit.altKey, blockId: hit.blockId,
    };
  }, [atHeldLevel, mode]);

  const legalPlacement = useCallback((candidateModel: Model, candidate: ModelBlock) =>
    !validatePlacement(candidateModel, candidate, validationContext)
      .some(item => item.severity === "error"), [validationContext]);

  const surfaceUp = useCallback((raw: SurfacePointer) => {
    const start = gesture.current;
    gesture.current = null;
    if (!start || start.pointerId !== raw.pointerId) return;
    const hit = atHeldLevel(raw);
    const end = { x: hit.clientX, y: hit.clientY };

    if (start.shift) {
      const blocks: ModelBlock[] = [];
      let preview = model;
      for (const cell of runCells(start.anchor, hit.target)
        .map(item => ({ ...item, level: start.anchor.level }))) {
        const candidate: ModelBlock = {
          id: `b${nextId.current + blocks.length}`, mode: start.mode,
          col: cell.col, row: cell.row, level: cell.level, colour: "white",
        };
        if (!legalPlacement(preview, candidate)) continue;
        blocks.push(candidate);
        preview = applyEdit(preview, { type: "place", block: candidate });
      }
      if (blocks.length) {
        nextId.current += blocks.length;
        commit({ type: "placeRun", blocks });
        setTarget(null);
      }
      return;
    }
    if (!pointerIsClick(start.start, end)) return;
    if (start.alt || hit.altKey) {
      const id = hit.blockId ?? start.blockId;
      if (id) {
        commit({ type: "remove", id });
        setTarget(null);
      }
      return;
    }
    const candidate = {
      id: `b${nextId.current}`, mode: start.mode,
      col: hit.target.col, row: hit.target.row, level: hit.target.level, colour: "white" as const,
    };
    if (legalPlacement(model, candidate)) {
      nextId.current += 1;
      commit({ type: "place", block: candidate });
      setTarget(null);
    }
  }, [atHeldLevel, commit, legalPlacement, model]);

  const selectDiagnostic = useCallback((id: string) => {
    const block = model.blocks.find(item => item.id === id);
    if (!block) return;
    setSelectedId(id);
    setFocusBox(blockBoxScene(block));
    setNonce(value => value + 1);
  }, [model.blocks]);

  const applyFix = useCallback((fix: DiagnosticFix) => {
    const edit = fix.edit;
    if (edit.type === "reorder" && typeof edit.id === "string" && typeof edit.toIndex === "number") {
      commit({ type: "reorder", id: edit.id, toIndex: edit.toIndex });
      return;
    }
    if (edit.type === "move" && typeof edit.id === "string" && typeof edit.level === "number") {
      const block = model.blocks.find(item => item.id === edit.id);
      if (block) commit({
        type: "move", id: block.id, mode: block.mode, col: block.col, row: block.row, level: edit.level,
      });
    }
  }, [commit, model.blocks]);

  /**
   * Snapshot the editor as a saveable document. The thumbnail is rendered off
   * screen from the model's own bounding box (see `scene/Capture.tsx`); if the
   * GPU cannot produce one the save still goes ahead with a plain card.
   */
  const captureCurrent = useCallback(async (): Promise<StudioModel> => {
    const thumbnail = await capture.current?.(modelBoxScene(model.blocks, shifts));
    return {
      ...modelDocument,
      blocks: model.blocks,
      order: model.order,
      modified: new Date().toISOString(),
      ...(thumbnail === undefined ? {} : { thumbnail }),
    };
  }, [model, modelDocument, shifts]);

  /**
   * Write the current build to the library. A never-saved build (`savedId ===
   * null`) is minted a fresh id and keeps the name it was just given; a tracked
   * build overwrites itself in place. A refusal — storage full, over budget —
   * becomes a warning toast and opens the library, where the full remedy with
   * its delete controls already lives.
   */
  const performSave = useCallback(async (name?: string): Promise<void> => {
    try {
      const base = await captureCurrent();
      const document: StudioModel = savedId === null
        ? { ...base, id: newModelId(), name: (name ?? base.name).trim() || "Untitled" }
        : { ...base, id: savedId };
      const written = writeModel(document, { settings });
      if (!written.ok) {
        setToast({ kind: "warn", text: written.reason });
        setLibraryOpen(true);
        return;
      }
      setModelDocument(document);
      setSavedId(document.id);
      setSavedSignature(signatureOf(document.blocks, document.order, document.name));
      setSavedTick(tick => tick + 1);
      setToast({ kind: "ok", text: `Saved “${document.name}”` });
    } catch (error) {
      const reason = error instanceof Error ? error.message : "save failed unexpectedly";
      setToast({ kind: "warn", text: reason });
    }
  }, [captureCurrent, savedId, settings]);

  /** The one entry point for SAVE and Ctrl/Cmd-S: name a build the first time,
   *  overwrite silently after that. */
  const requestSave = useCallback(() => {
    if (savedId === null) {
      setNameDraft(modelDocument.name === "Untitled" ? "" : modelDocument.name);
      setNaming(true);
      return;
    }
    void performSave();
  }, [savedId, modelDocument.name, performSave]);

  const confirmName = useCallback(() => {
    setNaming(false);
    void performSave(nameDraft);
  }, [nameDraft, performSave]);

  // The keydown listener is bound once; this ref keeps Ctrl/Cmd-S pointed at
  // the current save closure without re-subscribing on every edit.
  const requestSaveRef = useRef(requestSave);
  requestSaveRef.current = requestSave;

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), toast.kind === "ok" ? 2400 : 5200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  // A page unload with unsaved work gets the browser's own confirm. This is the
  // only place the Studio leans on `beforeunload`; it is armed only while dirty.
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  /** Load a document: its structure, its identity AND its geometry snapshot.
   *  `nextId` moves past whatever the file used so a new block cannot collide
   *  with an imported one. */
  const openDocument = useCallback((incoming: StudioModel) => {
    setModelDocument(incoming);
    setHistory(createHistory(structureOf(incoming)));
    setSelectedId(null);
    setFocusBox(null);
    setTarget(null);
    setHeldLevel(null);
    // An example is a starting point, not a saved slot: the next save forks it.
    setSavedId(isExampleId(incoming.id) ? null : incoming.id);
    setSavedSignature(signatureOf(incoming.blocks, incoming.order, incoming.name));
    nextId.current = incoming.blocks.reduce(
      (highest, block) => Math.max(highest, Number(/\d+$/.exec(block.id)?.[0] ?? 0) + 1), 1,
    );
    setLibraryOpen(false);
    setNonce(value => value + 1);
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const element = event.target instanceof HTMLElement ? event.target : null;
      const action = keyboardAction({
        key: event.key, ctrlKey: event.ctrlKey, metaKey: event.metaKey, shiftKey: event.shiftKey,
        targetTag: element?.tagName, contentEditable: element?.isContentEditable,
      });
      if (!action) return;
      event.preventDefault();
      if (action === "undo") setHistory(current => undo(current));
      else if (action === "redo") setHistory(current => redo(current));
      else if (action === "save") requestSaveRef.current();
      else if (action === "release-level") setHeldLevel(null);
      else if (action === "toggle-mode") setMode(current => current === "vertical" ? "horizontal" : "vertical");
      else if (action.holdLevel <= THEORETICAL_LEVEL_CEILING) setHeldLevel(action.holdLevel);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <div className="studio">
      <header className="studio-bar">
        <a className="studio-back" href="#/">&#9664; CONSOLE</a>
        <span className="studio-title">BUILD STUDIO</span>
        <button type="button" className="studio-back studio-library-toggle"
                aria-expanded={libraryOpen} onClick={() => setLibraryOpen(open => !open)}>
          LIBRARY
        </button>
        <button type="button" className="studio-back studio-save"
                data-dirty={dirty || undefined}
                title="Save this build  (Ctrl/⌘ S)"
                onClick={requestSave}>
          SAVE{dirty ? <span className="studio-save-dot" aria-hidden="true" /> : null}
        </button>
        <span className="studio-readout studio-model-name">
          {modelDocument.name}
          {dirty ? <span className="studio-unsaved" title="unsaved changes"> — unsaved</span> : null}
        </span>
        <span className="studio-readout">
          <b>{mode.toUpperCase()}</b> {requested.cols}&times;{requested.rows}
          {clipped && <em className="studio-clipped"> clipped to {reachable.cols}&times;{reachable.rows}</em>}
        </span>
        <span className="studio-readout">
          shiftX {signed(geometry.shift_x_cm ?? 0)} &nbsp; shiftY {signed(geometry.shift_y_cm ?? 0)} cm
        </span>
        <span className="studio-readout studio-block-count">{model.blocks.length} BLOCKS</span>
        {heldLevel !== null ? <span className="studio-held">LEVEL {heldLevel} HELD</span> : null}
      </header>

      <div className="studio-stage">
        <Viewport mode={mode} shift={shifts[mode]} view={view} nonce={nonce} model={model}
                  captureHandle={capture}
                  target={target} status={status} heldLevel={heldLevel}
                  diagnostics={diagnostics}
                  emphasizedId={hoveredDiagnosticId ?? selectedId}
                  focusBox={focusBox}
                  onSurfaceMove={surfaceMove} onSurfaceDown={surfaceDown}
                  onSurfaceUp={surfaceUp} onSurfaceLeave={surfaceLeave} />

        <LevelScrubber ceiling={THEORETICAL_LEVEL_CEILING} heldLevel={heldLevel}
                       onHold={setHeldLevel} onRelease={() => setHeldLevel(null)} />

        <div className="studio-sidepanels">
          <Diagnostics diagnostics={diagnostics} onHover={setHoveredDiagnosticId}
                       onSelect={selectDiagnostic} onFix={applyFix} />
          <ProgramView program={program.program} valid={program.valid} stats={program.stats}
                       selectedId={selectedId} onSelect={selectDiagnostic} />
          <Settings value={settings} onChange={setSettings} />
        </div>

        <div className="studio-views" role="group" aria-label="View">
          {VIEWS.map(name => (
            <button key={name} type="button" className="studio-view"
                    aria-pressed={view === name} onClick={() => snap(name)}>
              {VIEW_LABEL[name]}
            </button>
          ))}
        </div>

        <LibraryDrawer open={libraryOpen} onClose={() => setLibraryOpen(false)}
                       currentId={savedId} onOpenModel={openDocument}
                       captureCurrent={captureCurrent}
                       onSave={requestSave} dirty={dirty} savedTick={savedTick}
                       onSaved={saved => setModelDocument(saved)}
                       settings={settings} />

        {naming ? (
          <div className="studio-library-sheet studio-name-sheet" role="dialog"
               aria-modal="true" aria-label="Name this build">
            <h3>NAME THIS BUILD</h3>
            <input className="studio-library-rename" autoFocus aria-label="Build name"
                   placeholder="e.g. Demo tower" value={nameDraft}
                   onChange={event => setNameDraft(event.target.value)}
                   onKeyDown={event => {
                     if (event.key === "Enter") confirmName();
                     if (event.key === "Escape") setNaming(false);
                   }} />
            <div className="studio-library-sheet-actions">
              <button type="button" onClick={() => setNaming(false)}>CANCEL</button>
              <button type="button" className="studio-library-primary" onClick={confirmName}>
                SAVE
              </button>
            </div>
          </div>
        ) : null}

        {toast ? (
          <div className={`studio-toast studio-toast--${toast.kind}`} role="status">
            {toast.text}
          </div>
        ) : null}

        <div className="studio-modes" role="group" aria-label="Grid mode">
          {(["vertical", "horizontal"] as ModeName[]).map(name => (
            <button key={name} type="button" className="studio-mode"
                    aria-pressed={mode === name} onClick={() => setMode(name)}>
              {name === "vertical" ? "V" : "H"}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
