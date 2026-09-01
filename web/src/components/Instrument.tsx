/**
 * Real workspace and virtual workspace, in step — Plan 4 §9.1.
 *
 * On a desktop the camera and the twin are equal columns inside ONE stage
 * border, top-aligned, so they read as one instrument rather than two widgets.
 * On a phone there is not room for two, so they become a two-tab switcher that
 * DEFAULTS TO THE CAMERA: the twin is a claim, the camera is what checks it,
 * and the camera is what an operator must be watching while the rig moves.
 *
 * BUILD does not move. On a phone it lives in the sticky action sheet below
 * this, so switching tabs cannot push it down the page by a pixel.
 */
import { useState, type ReactNode } from "react";
import { usePhone } from "../media";

type Pane = "camera" | "twin";
const PANES: Pane[] = ["camera", "twin"];

export function Instrument({ camera, twin }: { camera: ReactNode; twin: ReactNode }) {
  const phone = usePhone();
  const [pane, setPane] = useState<Pane>("camera");

  if (!phone) {
    return (
      <div className="instrument">
        <section className="instrument-pane">{camera}</section>
        <section className="instrument-pane">{twin}</section>
      </div>
    );
  }

  return (
    <div className="instrument is-tabbed">
      <div className="instrument-tabs" role="tablist" aria-label="Workspace view">
        {PANES.map(name => (
          <button key={name} type="button" role="tab" className="chip toggle"
                  id={`instrument-tab-${name}`}
                  aria-selected={pane === name} aria-controls="instrument-pane"
                  onClick={() => setPane(name)}>
            {name.toUpperCase()}
          </button>
        ))}
      </div>
      <section className="instrument-pane" id="instrument-pane" role="tabpanel"
               aria-labelledby={`instrument-tab-${pane}`}>
        {pane === "camera" ? camera : twin}
      </section>
    </div>
  );
}
