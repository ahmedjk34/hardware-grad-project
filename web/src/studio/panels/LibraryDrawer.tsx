/**
 * The library, as a drawer over the viewport rather than a column beside it.
 *
 * The viewport is the point of this application and it should not be squeezed
 * to 288 px to list files, so this slides in at `--z-drawer` on top and slides
 * back out. Everything it knows about storage comes from `library.ts`, which
 * never throws; this file only draws, and every failure it can meet arrives as
 * a `Result` reason it can put on screen.
 *
 * Three deliberate interaction choices:
 *
 *  - **Rename is an inline edit on double-click.** A modal for renaming a local
 *    file is friction with no safety in it.
 *  - **Delete is immediate, with a six-second undo.** A confirm dialog asks
 *    somebody to be careful; an undo lets them be wrong. That undo is a
 *    requirement, not a nicety.
 *  - **Import never lands silently.** A dropped file is parsed, shown with its
 *    name, block count and any `GEOMETRY_DRIFT` warning, and waits for a
 *    confirm. A file that appeared in your library without being read is a file
 *    you cannot trust.
 *
 * The three built-in examples are listed above the saved models and are never
 * written to storage: they cost no budget, they cannot be deleted by accident,
 * and an empty library therefore never looks broken.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import {
  LIBRARY_FILE_EXTENSION, MODEL_FILE_EXTENSION, acceptsDroppedFile, duplicateModel,
  exportLibrary, exportModel, importLibrary, largestFirst, listModels, readModel,
  removeModel, renameModel, storageReport, writeModel,
  type LibraryStorage, type ModelCard, type StudioModel,
} from "../library";
import { EXAMPLES, isExampleId } from "../examples";
import { compile, formatDuration } from "../compile";
import { fromFileRig, structureOf, shiftsOf } from "../rigmodel";
import { describeDrift } from "../validate";
import type { StudioSettings } from "../settings";

/** Long enough to notice and reach, short enough not to be a pending state. */
export const UNDO_MS = 6000;

export interface LibraryDrawerProps {
  open: boolean;
  onClose: () => void;
  currentId: string | null;
  onOpenModel: (document: StudioModel) => void;
  /** Snapshot the editor as a saveable document — thumbnail included. The
   *  drawer owns the write so the budget refusal has somewhere to appear. */
  captureCurrent: () => Promise<StudioModel>;
  onSaved?: (document: StudioModel) => void;
  settings: StudioSettings;
  storage?: LibraryStorage;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** The last field of the meta line, in the register a person would use. */
export function relativeTime(iso: string, now: Date = new Date()): string {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "unknown";
  const seconds = Math.max(0, (now.getTime() - then.getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 86400 * 7) return `${Math.floor(seconds / 86400)}d ago`;
  return `${then.getUTCDate()} ${MONTHS[then.getUTCMonth()]}`;
}

function metaLine(card: ModelCard, now?: Date): string {
  const blocks = `${card.blocks} block${card.blocks === 1 ? "" : "s"}`;
  const latches = card.latches === 1 ? "1 latch" : `${card.latches} latches`;
  return `${blocks} · ${latches} · ~${formatDuration(card.estimateSeconds)} · ${relativeTime(card.modified, now)}`;
}

/** The examples have no stored body, so their card is derived on the spot from
 *  the same compiler the stored cards were written by. */
function cardFor(document: StudioModel, settings: StudioSettings): ModelCard {
  const program = compile(structureOf(document), {
    settings, shifts: shiftsOf(document.rig), rigSnapshot: fromFileRig(document.rig),
  });
  return {
    id: document.id, name: document.name, blocks: document.blocks.length,
    latches: program.stats.latches, estimateSeconds: program.stats.estimateSeconds,
    modified: document.modified, bytes: 0,
    ...(document.thumbnail === undefined ? {} : { thumbnail: document.thumbnail }),
  };
}

/** A download the operator's browser performs; no server is involved. */
function download(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

const safeFilename = (name: string) => name.replace(/[^\w. -]+/g, "_").trim() || "model";

export function LibraryDrawer({
  open, onClose, currentId, onOpenModel, captureCurrent, onSaved, settings, storage,
}: LibraryDrawerProps) {
  const options = { storage, settings };
  const [cards, setCards] = useState<ModelCard[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<StudioModel | null>(null);
  const [incoming, setIncoming] = useState<StudioModel[] | null>(null);
  const undoTimer = useRef<number | null>(null);

  const report = storageReport(options);

  const refresh = useCallback(() => {
    const listed = listModels({ storage, settings });
    setCards(listed.ok ? listed.value : []);
    if (!listed.ok) setNotice(null);
  }, [storage, settings]);

  useEffect(refresh, [refresh]);

  const complain = (result: { ok: boolean; reason?: string }) => {
    if (!result.ok && result.reason) setNotice(result.reason);
    refresh();
  };

  // ── delete, and the undo that makes it safe ───────────────────────────────

  const armUndo = (document: StudioModel) => {
    if (undoTimer.current !== null) window.clearTimeout(undoTimer.current);
    setPendingDelete(document);
    undoTimer.current = window.setTimeout(() => setPendingDelete(null), UNDO_MS);
  };

  const deleteCard = (id: string) => {
    const document = readModel(id, options);
    const removed = removeModel(id, options);
    if (!removed.ok) { complain(removed); return; }
    refresh();
    if (document.ok) armUndo(document.value);
  };

  const undoDelete = () => {
    if (!pendingDelete) return;
    if (undoTimer.current !== null) window.clearTimeout(undoTimer.current);
    complain(writeModel(pendingDelete, options));
    setPendingDelete(null);
  };

  useEffect(() => () => {
    if (undoTimer.current !== null) window.clearTimeout(undoTimer.current);
  }, []);

  // ── save ──────────────────────────────────────────────────────────────────

  const save = async () => {
    const document = await captureCurrent();
    const written = writeModel(document, options);
    if (!written.ok) { setNotice(written.reason); refresh(); return; }
    setNotice(null);
    refresh();
    onSaved?.(document);
  };

  // ── open ──────────────────────────────────────────────────────────────────

  const openStored = (id: string) => {
    const document = readModel(id, options);
    if (!document.ok) { setNotice(document.reason); return; }
    onOpenModel(document.value);
  };

  // ── drag and drop import ──────────────────────────────────────────────────

  useEffect(() => {
    const allow = (event: DragEvent) => {
      if (event.dataTransfer?.types?.includes("Files")) event.preventDefault();
    };
    const onDrop = (event: DragEvent) => {
      const file = event.dataTransfer?.files?.[0];
      if (!file) return;
      event.preventDefault();
      const accepted = acceptsDroppedFile(file.name);
      if (!accepted.ok) { setNotice(accepted.reason); return; }
      void file.text().then(text => {
        const parsed = importLibrary(text);
        if (!parsed.ok) { setNotice(parsed.reason); return; }
        setNotice(null);
        setIncoming(parsed.value);
      });
    };
    window.addEventListener("dragover", allow);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragover", allow);
      window.removeEventListener("drop", onDrop);
    };
  }, []);

  const confirmImport = () => {
    if (!incoming) return;
    for (const document of incoming) {
      const written = writeModel(document, options);
      if (!written.ok) { setNotice(written.reason); break; }
    }
    setIncoming(null);
    refresh();
  };

  // ── rendering ─────────────────────────────────────────────────────────────

  const renderCard = (card: ModelCard, document?: StudioModel) => {
    const example = document !== undefined;
    const selected = currentId === card.id;
    const commitRename = (value: string) => {
      setRenaming(null);
      if (value.trim() && value !== card.name) complain(renameModel(card.id, value, options));
    };
    const keyDown = (event: KeyboardEvent<HTMLInputElement>) => {
      if (event.key === "Enter") commitRename(event.currentTarget.value);
      if (event.key === "Escape") setRenaming(null);
    };
    return (
      <li key={card.id} className="studio-library-card" aria-label={card.name}
          {...(selected ? { "aria-current": "true" as const } : {})}>
        <button type="button" className="studio-library-open" aria-label={`Open ${card.name}`}
                onClick={() => example ? onOpenModel(document!) : openStored(card.id)}>
          <span className="studio-library-thumb">
            {card.thumbnail
              ? <img src={card.thumbnail} alt="" width={320} height={200} />
              : <span className="studio-library-thumb-empty" aria-hidden="true">NO PREVIEW</span>}
          </span>
        </button>
        {renaming === card.id ? (
          <input className="studio-library-rename" aria-label="Model name" autoFocus
                 defaultValue={card.name} onKeyDown={keyDown}
                 onBlur={event => commitRename(event.currentTarget.value)} />
        ) : (
          <span className="studio-library-name" data-testid="name"
                onDoubleClick={() => { if (!example) setRenaming(card.id); }}>
            {card.name}
          </span>
        )}
        <span className="studio-library-meta" data-testid="meta">{metaLine(card)}</span>
        <span className="studio-library-actions">
          {example ? null : (
            <>
              <button type="button" onClick={() => complain(duplicateModel(card.id, options))}>
                DUPLICATE
              </button>
              <button type="button" onClick={() => {
                const stored = readModel(card.id, options);
                if (stored.ok) download(`${safeFilename(card.name)}${MODEL_FILE_EXTENSION}`, exportModel(stored.value));
                else setNotice(stored.reason);
              }}>EXPORT</button>
              <button type="button" className="studio-library-delete"
                      onClick={() => deleteCard(card.id)}>DELETE</button>
            </>
          )}
        </span>
      </li>
    );
  };

  const strip = notice ?? report.message;

  return (
    <>
      <aside className="studio-library" hidden={!open} aria-label="Model library">
        <header className="studio-panel-header studio-library-head">
          <span>LIBRARY</span>
          <button type="button" onClick={() => void save()}>SAVE</button>
          <button type="button" onClick={() => {
            const text = exportLibrary(options);
            if (text.ok) download(`library${LIBRARY_FILE_EXTENSION}`, text.value);
            else setNotice(text.reason);
          }}>EXPORT ALL</button>
          <button type="button" className="studio-library-close" onClick={onClose}
                  aria-label="Close the library">&times;</button>
        </header>

        {strip ? (
          <div className="studio-library-strip" role="alert">
            <span>{strip}</span>
            {largestFirst(cards).slice(0, 3).map(card => (
              <button key={card.id} type="button" aria-label={`Delete ${card.name}`}
                      onClick={() => deleteCard(card.id)}>
                DELETE {card.name.toUpperCase()}
              </button>
            ))}
          </div>
        ) : null}

        <h3 className="studio-library-section">EXAMPLES</h3>
        <ul className="studio-library-list">
          {EXAMPLES.map(example => renderCard(cardFor(example, settings), example))}
        </ul>

        <h3 className="studio-library-section">SAVED</h3>
        {cards.length === 0 ? (
          <p className="studio-library-empty">No saved models yet — open an example, or press SAVE.</p>
        ) : (
          <ul className="studio-library-list">{cards.map(card => renderCard(card))}</ul>
        )}
      </aside>

      {pendingDelete ? (
        <div className="studio-library-toast" role="status">
          <span>Deleted {pendingDelete.name}</span>
          <button type="button" onClick={undoDelete}>UNDO</button>
        </div>
      ) : null}

      {incoming ? (
        <div className="studio-library-sheet" role="dialog" aria-modal="true"
             aria-label="Confirm import">
          <h3>IMPORT {incoming.length === 1 ? "1 MODEL" : `${incoming.length} MODELS`}</h3>
          <ul>
            {incoming.map(document => {
              const drift = describeDrift(fromFileRig(document.rig));
              return (
                <li key={document.id}>
                  <b>{document.name}</b>
                  <span className="studio-library-meta">
                    {document.blocks.length} block{document.blocks.length === 1 ? "" : "s"}
                    {isExampleId(document.id) ? " · replaces a built-in id" : ""}
                  </span>
                  {drift ? <span className="studio-library-drift">{drift}</span> : null}
                </li>
              );
            })}
          </ul>
          <div className="studio-library-sheet-actions">
            <button type="button" onClick={() => setIncoming(null)}>CANCEL</button>
            <button type="button" className="studio-library-primary" onClick={confirmImport}>IMPORT</button>
          </div>
        </div>
      ) : null}
    </>
  );
}
