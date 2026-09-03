/**
 * The build picker for building mode — a slide-over list of every model the
 * twin can show (the three built-in examples first, then whatever is saved),
 * each with the numbers that matter before you commit the rig to it: block
 * count, latch count, and an estimated wall-clock the same compiler the runner
 * uses produces.
 *
 * It only SELECTS. There is no rename, delete, import or export here — those
 * live in the Studio's own library drawer, which is one hash away. A build-mode
 * operator is choosing what to run, not curating files.
 */
import { useMemo } from "react";
import { compile, estimateLabel } from "../../studio/compile";
import { fromFileRig, shiftsOf, structureOf } from "../../studio/rigmodel";
import { DEFAULT_STUDIO_SETTINGS } from "../../studio/settings";
import { loadTwinModel, twinModelChoices } from "../../studio/twin";
import type { ModeName } from "../../studio/coords";
import { Icon } from "../Icon";

interface Row {
  id: string;
  name: string;
  blocks: number;
  label: string;
  valid: boolean;
  thumbnail?: string;
}

function rowFor(id: string, name: string, mode: ModeName): Row {
  const document = loadTwinModel(id);
  if (!document) return { id, name, blocks: 0, label: "unavailable", valid: false };
  try {
    const program = compile(structureOf(document), {
      mode,
      settings: DEFAULT_STUDIO_SETTINGS,
      shifts: shiftsOf(document.rig),
      rigSnapshot: fromFileRig(document.rig),
    });
    return {
      id, name,
      blocks: document.blocks.length,
      label: program.valid ? estimateLabel(program.stats) : "has compiler errors",
      valid: program.valid,
      ...(document.thumbnail === undefined ? {} : { thumbnail: document.thumbnail }),
    };
  } catch {
    return { id, name, blocks: document.blocks.length, label: "could not compile", valid: false };
  }
}

export function BuildLibrary({ open, mode, currentId, onPick, onClose }: {
  open: boolean;
  mode: ModeName;
  currentId: string;
  onPick: (id: string) => void;
  onClose: () => void;
}) {
  const rows = useMemo(
    () => twinModelChoices().map(choice => rowFor(choice.id, choice.name, mode)),
    [mode],
  );

  return (
    <aside className="bm-library" hidden={!open} aria-label="Build library">
      <header className="bm-library-head">
        <span>SELECT A BUILD</span>
        <button type="button" className="bm-library-close" aria-label="Close the library"
                onClick={onClose}>×</button>
      </header>

      <ul className="bm-library-list">
        <li>
          <button type="button" className="bm-library-card"
                  aria-current={currentId === "" ? "true" : undefined}
                  onClick={() => { onPick(""); onClose(); }}>
            <span className="bm-library-thumb bm-library-thumb-empty" aria-hidden="true">—</span>
            <span className="bm-library-name">No build loaded</span>
            <span className="bm-library-meta">Clears the twin</span>
          </button>
        </li>
        {rows.map(row => (
          <li key={row.id}>
            <button type="button" className="bm-library-card"
                    aria-current={currentId === row.id ? "true" : undefined}
                    onClick={() => { onPick(row.id); onClose(); }}>
              <span className="bm-library-thumb">
                {row.thumbnail
                  ? <img src={row.thumbnail} alt="" width={320} height={200} />
                  : <span className="bm-library-thumb-empty" aria-hidden="true">NO PREVIEW</span>}
              </span>
              <span className="bm-library-name">
                {row.name}
                {!row.valid && <em className="bm-library-warn"> · {row.label}</em>}
              </span>
              <span className="bm-library-meta">
                {row.valid
                  ? <><Icon name="layers" size={12} />{row.label}</>
                  : `${row.blocks} block${row.blocks === 1 ? "" : "s"}`}
              </span>
            </button>
          </li>
        ))}
      </ul>

      <p className="bm-library-foot">
        Design a new build in the <a href="#/studio">3D Build Studio</a>.
      </p>
    </aside>
  );
}
