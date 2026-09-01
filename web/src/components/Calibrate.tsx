import { useEffect, useState } from "react";
import * as api from "../api";
import { Icon } from "./Icon";

const NAMES = [
  "holder home [0,0]",
  "far-X/home-Y holder limit",
  "far-X/far-Y holder limit",
  "home-X/far-Y holder limit",
];

export function Calibrate({ ready, onCollecting, onPointChange }: {
  ready: boolean;
  onCollecting?: (active: boolean) => void;
  onPointChange?: (handler: ((point: [number, number], imageSize: [number, number]) => void) | null) => void;
}) {
  const [points, setPoints] = useState(0);
  const [active, setActive] = useState(false);

  useEffect(() => {
    if (!active) return onPointChange?.(null);
    onPointChange?.((point, size) => {
      void api.calibration.corner(point[0], point[1], size[0], size[1])
        .then(reply => setPoints((reply as { count: number }).count));
    });
    return () => onPointChange?.(null);
  }, [active, onPointChange]);

  const enter = async () => {
    await api.calibration.start();
    setPoints(0);
    setActive(true);
    onCollecting?.(true);
  };
  const undo = async () => {
    await api.calibration.undo();
    setPoints(value => Math.max(0, value - 1));
  };
  const cancel = async () => {
    await api.calibration.cancel();
    setActive(false);
    onCollecting?.(false);
  };
  const place = () => setPoints(value => Math.min(4, value + 1));
  const save = async () => {
    await api.calibration.save();
    setActive(false);
    onCollecting?.(false);
  };

  if (!active) return (
    <section className="panel" aria-label="Calibration">
      <header><h2><Icon name="ruler" size={13} />Calibration</h2></header>
      <button
        type="button"
        className="btn btn-ghost choice"
        aria-label="Calibrate"
        disabled={!ready}
        onClick={() => void enter()}
      >
        <span className="btn-title"><Icon name="target" size={15} />Calibrate by corners</span>
        <span className="btn-sub">Click the four holder limits on the video, in order.</span>
      </button>
      <button
        type="button"
        className="btn btn-ghost choice"
        aria-label="Calibrate from sheet"
        disabled={!ready}
        onClick={() => void api.calibration.paper()}
      >
        <span className="btn-title"><Icon name="sheet" size={15} />Calibrate from sheet</span>
        <span className="btn-sub">Detect the printed calibration sheet in the current frame.</span>
      </button>
    </section>
  );

  return (
    <section className="panel calibration" aria-label="Calibration">
      <header>
        <h2><Icon name="ruler" size={13} />Calibration</h2>
        <span className="spacer" />
        <span className="wizard-progress">{Math.min(points, 4)} of 4 corners</span>
      </header>
      <ol className="wizard-steps">
        {NAMES.map((name, index) => (
          <li
            key={name}
            className={index < points ? "done" : index === points ? "current" : ""}
            aria-label={name}
          />
        ))}
      </ol>
      <p className="wizard-prompt">
        Click <strong>{NAMES[points] ?? "Save calibration"}</strong> on the video.
      </p>
      <div className="row">
        <button type="button" className="btn" onClick={place} aria-label="Place corner">Place corner</button>
        <button type="button" className="btn btn-ghost" onClick={() => void undo()} disabled={!points}>Undo</button>
      </div>
      <div className="row">
        <button type="button" className="btn btn-ghost" onClick={() => void cancel()}>Cancel</button>
        <button
          type="button"
          className="btn"
          aria-label="Save calibration"
          disabled={points !== 4}
          onClick={() => void save()}
        >Save calibration</button>
      </div>
    </section>
  );
}
