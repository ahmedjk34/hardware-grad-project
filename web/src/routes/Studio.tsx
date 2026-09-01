/**
 * The 3D Build Studio.
 *
 * M2 makes that viewport an editor: surface hits become cell-space targets,
 * every completed gesture becomes one immutable history entry, and held-level
 * state remains explicit in both the rail and header.
 *
 * This route is loaded lazily (see `routes/Root.tsx`) so the operator console's
 * first paint never pays for three.js.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Viewport } from "../studio/scene/Viewport";
import { activeMode, cellCount, modeGeometry, reachableCells, type ModeName } from "../studio/coords";
import { VIEWS, type ViewName } from "../studio/view";
import { applyEdit, emptyModel, type Edit, type ModelBlock } from "../studio/model";
import { createHistory, push, redo, undo } from "../studio/history";
import { keyboardAction, pointerIsClick, sameTarget, type Point2 } from "../studio/interaction";
import { placementStatus } from "../studio/placement";
import { runCells, type CellTarget } from "../studio/pick";
import type { SurfacePointer } from "../studio/scene/surface";
import { LevelScrubber } from "../studio/panels/LevelScrubber";

const VIEW_LABEL: Record<ViewName, string> = {
  top: "TOP", front: "FRONT", side: "SIDE", iso: "ISO",
};

/** The current operator ceiling; M3 promotes this to a visible setting. */
const LEVEL_CEILING = 17;

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
  const nextId = useRef(1);
  const gesture = useRef<{
    start: Point2; anchor: CellTarget; mode: ModeName; pointerId: number;
    shift: boolean; alt: boolean; blockId?: string;
  } | null>(null);

  const model = history.present;
  const status = useMemo(
    () => target ? placementStatus(model, mode, target) : null,
    [model, mode, target],
  );

  const geometry = modeGeometry(mode);
  const requested = cellCount(mode);
  const reachable = reachableCells(mode);
  const clipped = reachable.cols < requested.cols || reachable.rows < requested.rows;

  const snap = (next: ViewName) => { setView(next); setNonce(value => value + 1); };
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

  const newBlock = (blockMode: ModeName, cell: CellTarget): ModelBlock => ({
    id: `b${nextId.current++}`, mode: blockMode,
    col: cell.col, row: cell.row, level: cell.level, colour: "white",
  });

  const surfaceUp = useCallback((raw: SurfacePointer) => {
    const start = gesture.current;
    gesture.current = null;
    if (!start || start.pointerId !== raw.pointerId) return;
    const hit = atHeldLevel(raw);
    const end = { x: hit.clientX, y: hit.clientY };

    if (start.shift) {
      const blocks = runCells(start.anchor, hit.target)
        .map(cell => ({ ...cell, level: start.anchor.level }))
        .filter(cell => placementStatus(model, start.mode, cell).legal)
        .map(cell => newBlock(start.mode, cell));
      if (blocks.length) {
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
    if (placementStatus(model, start.mode, hit.target).legal) {
      commit({ type: "place", block: newBlock(start.mode, hit.target) });
      setTarget(null);
    }
  }, [atHeldLevel, commit, model]);

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
      else if (action.holdLevel <= LEVEL_CEILING) setHeldLevel(action.holdLevel);
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
                  onSurfaceMove={surfaceMove} onSurfaceDown={surfaceDown}
                  onSurfaceUp={surfaceUp} onSurfaceLeave={surfaceLeave} />

        <LevelScrubber ceiling={LEVEL_CEILING} heldLevel={heldLevel}
                       onHold={setHeldLevel} onRelease={() => setHeldLevel(null)} />

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
