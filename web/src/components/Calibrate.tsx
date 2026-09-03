import { useEffect, useState } from "react";
import * as api from "../api";
import type { BlockCalibrationStatus } from "../api";
import { Icon } from "./Icon";

const NAMES = [
  "holder home [0,0]",
  "far-X/home-Y holder limit",
  "far-X/far-Y holder limit",
  "home-X/far-Y holder limit",
];

const cellName = (cell: [number, number]) => `[${cell[0]},${cell[1]}]`;

/**
 * Placed-block calibration: the rig puts a block on a cell it was told, and the
 * camera measures where it went. The correspondence is labelled at the source,
 * so unlike the corner and sheet routes there is nothing to infer and nothing
 * to assume about where a piece of paper sits relative to the firmware's cells.
 *
 * One step is a full pick-and-place, so the button stays busy for as long as
 * the rig is moving and the backend refuses a second step while one is in
 * flight. See python/vision/block_grid.py for what gates a save.
 */
function BlockRun({ status, setStatus, onDone }: {
  status: BlockCalibrationStatus;
  setStatus: (next: BlockCalibrationStatus) => void;
  onDone: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const done = status.observed.length;
  const total = status.planned.length;
  const next = status.remaining[0];

  const guard = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const step = () => guard(async () => setStatus(await api.calibration.block.step()));
  const undo = () => guard(async () => {
    const last = status.observed[status.observed.length - 1];
    if (last) setStatus(await api.calibration.block.undo(last));
  });
  const cancel = () => guard(async () => {
    await api.calibration.block.cancel();
    onDone();
  });
  const save = () => guard(async () => {
    await api.calibration.block.save();
    onDone();
  });

  return (
    <section className="panel calibration" aria-label="Calibration">
      <header>
        <h2><Icon name="ruler" size={13} />Calibration</h2>
        <span className="spacer" />
        <span className="wizard-progress">{done} of {total} blocks</span>
      </header>

      <ol className="wizard-steps">
        {status.planned.map((cell, index) => (
          <li
            key={cellName(cell)}
            className={index < done ? "done" : index === done ? "current" : ""}
            aria-label={`cell ${cellName(cell)}`}
          />
        ))}
      </ol>

      {status.finished_reason ? (
        <p className="wizard-prompt" role="alert">{status.finished_reason}</p>
      ) : next ? (
        <p className="wizard-prompt">
          Next: place a block on <strong>{cellName(next)}</strong>. Keep the
          feeder at [0,0] loaded.
        </p>
      ) : (
        <p className="wizard-prompt">{status.summary}</p>
      )}

      {status.report && (
        <p className="wizard-prompt">
          Residual {status.report.mean_residual_px.toFixed(2)} px mean,{" "}
          {status.report.max_residual_px.toFixed(2)} px max
          {status.report.worst_cell && ` at ${cellName(status.report.worst_cell)}`}.
        </p>
      )}

      {error && <p className="wizard-prompt" role="alert">{error}</p>}

      <div className="row">
        <button
          type="button"
          className="btn"
          aria-label="Place next block"
          disabled={busy || !next || Boolean(status.finished_reason)}
          onClick={step}
        >{busy ? "Placing…" : "Place next block"}</button>
        <button
          type="button"
          className="btn btn-ghost"
          aria-label="Undo last block"
          disabled={busy || !done}
          onClick={undo}
        >Undo</button>
      </div>
      <div className="row">
        <button type="button" className="btn btn-ghost" onClick={cancel} disabled={busy}>Cancel</button>
        <button
          type="button"
          className="btn"
          aria-label="Save calibration"
          disabled={busy || !status.ready}
          onClick={save}
        >Save calibration</button>
      </div>
    </section>
  );
}

export function Calibrate({ ready, onCollecting, onPointChange }: {
  ready: boolean;
  onCollecting?: (active: boolean) => void;
  onPointChange?: (handler: ((point: [number, number], imageSize: [number, number]) => void) | null) => void;
}) {
  const [points, setPoints] = useState(0);
  const [active, setActive] = useState(false);
  const [block, setBlock] = useState<BlockCalibrationStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  const startBlocks = async () => {
    setError(null);
    try {
      setBlock(await api.calibration.block.start());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  };

  if (block) return (
    <BlockRun status={block} setStatus={setBlock} onDone={() => setBlock(null)} />
  );

  if (!active) return (
    <section className="panel" aria-label="Calibration">
      <header><h2><Icon name="ruler" size={13} />Calibration</h2></header>
      {/* Placed blocks first: it is the only route that measures the machine
          rather than something an operator positioned by hand. */}
      <button
        type="button"
        className="btn btn-ghost choice"
        aria-label="Calibrate with blocks"
        disabled={!ready}
        onClick={() => void startBlocks()}
      >
        <span className="btn-title"><Icon name="target" size={15} />Calibrate with blocks</span>
        <span className="btn-sub">The rig places blocks on known cells and measures where they land. Clear the build area first.</span>
      </button>
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
      {error && <p className="wizard-prompt" role="alert">{error}</p>}
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
