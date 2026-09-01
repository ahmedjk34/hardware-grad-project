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
import { blockBoxScene } from "../studio/view";
import { applyEdit, emptyModel, type Edit, type Model, type ModelBlock } from "../studio/model";
import { createHistory, push, redo, undo } from "../studio/history";
import { keyboardAction, pointerIsClick, sameTarget, type Point2 } from "../studio/interaction";
import { runCells, type CellTarget } from "../studio/pick";
import type { SurfacePointer } from "../studio/scene/surface";
import { LevelScrubber } from "../studio/panels/LevelScrubber";
import { Diagnostics } from "../studio/panels/Diagnostics";
import { Settings } from "../studio/panels/Settings";
import {
  loadStudioSettings, saveStudioSettings, type StudioSettings,
} from "../studio/settings";
import {
  placementDiagnosticMessage, primaryDiagnostic, snapshotRigGeometry,
  validateModel, validatePlacement, type DiagnosticFix, type ValidationContext,
} from "../studio/validate";
import type { GhostStatus } from "../studio/scene/Ghost";

const VIEW_LABEL: Record<ViewName, string> = {
  top: "TOP", front: "FRONT", side: "SIDE", iso: "ISO",
};

/** The rail shows physical Z travel; the practical warning ceiling is a setting. */
const THEORETICAL_LEVEL_CEILING = 17;

/** A shift readout in the console's own register: signed, mono, two decimals. */
function signed(value: number): string {
  return `${value < 0 ? "−" : "+"}${Math.abs(value).toFixed(2)}`;
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
  const rigSnapshot = useRef(snapshotRigGeometry()).current;
  const nextId = useRef(1);
  const gesture = useRef<{
    start: Point2; anchor: CellTarget; mode: ModeName; pointerId: number;
    shift: boolean; alt: boolean; blockId?: string;
  } | null>(null);

  const model = history.present;
  const validationContext = useMemo<ValidationContext>(
    () => ({ mode, settings, rigSnapshot }),
    [mode, settings, rigSnapshot],
  );
  const diagnostics = useMemo(
    () => validateModel(model, validationContext),
    [model, validationContext],
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
        <Viewport mode={mode} view={view} nonce={nonce} model={model}
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
