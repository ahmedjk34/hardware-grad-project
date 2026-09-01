/**
 * The 3D Build Studio.
 *
 * M1 is the viewport and its chrome: the machine to scale, from any angle, in
 * either mode. There is no placement, no library and no timeline yet — those
 * arrive in later milestones and the layout of section 8.1 grows around this.
 *
 * This route is loaded lazily (see `routes/Root.tsx`) so the operator console's
 * first paint never pays for three.js.
 */
import { useState } from "react";
import { Viewport } from "../studio/scene/Viewport";
import { activeMode, cellCount, modeGeometry, reachableCells, type ModeName } from "../studio/coords";
import { VIEWS, type ViewName } from "../studio/view";

const VIEW_LABEL: Record<ViewName, string> = {
  top: "TOP", front: "FRONT", side: "SIDE", iso: "ISO",
};

/** A shift readout in the console's own register: signed, mono, two decimals. */
function signed(value: number): string {
  return `${value < 0 ? "−" : "+"}${Math.abs(value).toFixed(2)}`;
}

export default function Studio() {
  const [mode, setMode] = useState<ModeName>(() => activeMode());
  const [view, setView] = useState<ViewName>("iso");
  const [nonce, setNonce] = useState(0);

  const geometry = modeGeometry(mode);
  const requested = cellCount(mode);
  const reachable = reachableCells(mode);
  const clipped = reachable.cols < requested.cols || reachable.rows < requested.rows;

  const snap = (next: ViewName) => { setView(next); setNonce(value => value + 1); };

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
      </header>

      <div className="studio-stage">
        <Viewport mode={mode} view={view} nonce={nonce} />

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
