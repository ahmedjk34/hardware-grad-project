import { useState } from "react";
import type { CellGeometry, Point, StateModel, Supervision } from "../types";

function points(polygon: Point[]) {
  return polygon.map(point => point.join(",")).join(" ");
}

/** Corner ticks make the selection readable over any video content. */
function corners(polygon: Point[], fraction = 0.28): string[] {
  return polygon.map((point, index) => {
    const before = polygon[(index + polygon.length - 1) % polygon.length];
    const after = polygon[(index + 1) % polygon.length];
    const towards = (target: Point): Point => [
      point[0] + (target[0] - point[0]) * fraction,
      point[1] + (target[1] - point[1]) * fraction,
    ];
    return points([towards(before), point, towards(after)]);
  });
}

/** The cells one verdict names, as a lookup. The SERVER decided these; this
 *  only asks "is [col,row] in the list the server sent". Nothing is derived. */
function cellKeys(cells: Point[] | undefined): Set<string> {
  return new Set((cells ?? []).map(([col, row]) => `${col},${row}`));
}

/** §6.9: name the cell in the first four words, say what to do, and never say
 *  "error" for something the machine may have got right. Used for the SVG
 *  `<title>` on each marked cell — the overlay is not text, so every marked
 *  cell carries one, and the banner remains the authoritative sentence. */
export function cellTitle(verdict: string | null, col: number, row: number): string {
  if (verdict === "REMOVED") return `[${col},${row}] — a block the plan placed is gone`;
  if (verdict === "NOT_DETECTED") return `[${col},${row}] — the block just placed was not seen`;
  if (verdict === "MOVED") return `[${col},${row}] — the board no longer matches the plan here`;
  if (verdict === "DISPLACED") return `[${col},${row}] — a block was knocked off this cell into a gap`;
  if (verdict === "FOREIGN") return `[${col},${row}] — something is here the plan did not put here`;
  if (verdict === "DISAGREES") return `[${col},${row}] — this cell differs from the plan`;
  if (verdict === "VERIFIED") return `[${col},${row}] — seen in frame`;
  return `[${col},${row}]`;
}

function bounds(polygon: Point[]) {
  const xs = polygon.map(point => point[0]);
  const ys = polygon.map(point => point[1]);
  return { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) };
}

export function GridOverlay({ state, onSelect, onHover, selectable = true }: {
  state: StateModel;
  onSelect: (point: Point) => void;
  onHover?: (cell: CellGeometry | null) => void;
  selectable?: boolean;
}) {
  const [hover, setHoverCell] = useState<CellGeometry | null>(null);
  const setHover = (cell: CellGeometry | null) => { setHoverCell(cell); onHover?.(cell); };
  const geometry = state.geometry;
  if (!geometry) return null;

  const showGrid = state.views.grid !== false;
  const showDetections = state.views.detect !== false;
  const [width, height] = geometry.image_size;
  const stroke = Math.max(width, height) / 640;

  const toPoint = (event: React.PointerEvent<SVGSVGElement>): Point => {
    const svg = event.currentTarget;
    const rect = svg.getBoundingClientRect();
    return [
      (event.clientX - rect.left) * geometry.image_size[0] / (rect.width || geometry.image_size[0]),
      (event.clientY - rect.top) * geometry.image_size[1] / (rect.height || geometry.image_size[1]),
    ];
  };

  const contains = (point: Point) => geometry.grid.find(cell => {
    const box = bounds(cell.polygon);
    return point[0] >= box.minX && point[0] <= box.maxX && point[1] >= box.minY && point[1] <= box.maxY;
  });

  const move = (event: React.PointerEvent<SVGSVGElement>) => setHover(contains(toPoint(event)) ?? null);
  const down = (event: React.PointerEvent<SVGSVGElement>) => {
    const point = toPoint(event);
    if (contains(point)) onSelect(point);
  };

  // ONE server field. `supervision.cells` are the cells the server's verdict
  // names and `supervision.unjudged` the ones it refused; the browser filters
  // a list it already has and adds a class, exactly as `blocked` works today.
  const supervision: Supervision | undefined = state.supervision;
  const verdictCells = cellKeys(supervision?.verdict === "VERIFIED" ? [] : supervision?.cells);
  const unjudged = cellKeys(supervision?.unjudged);
  const severity = supervision?.severity ?? "none";
  const verdictName = supervision?.verdict ?? null;

  const selected = geometry.selected;
  const levelBox = selected ? bounds(selected.polygon) : null;

  return (
    <svg
      className={`grid-overlay${selectable ? " selectable" : ""}`}
      viewBox={`0 0 ${width} ${height}`}
      onPointerMove={move}
      onPointerLeave={() => setHover(null)}
      onPointerDown={down}
    >
      {/* Every stroke is drawn twice: a dark halo first, the colour on top. */}
      {showGrid && geometry.grid.map(cell => (
        <polygon
          key={`halo-${cell.col}-${cell.row}`}
          className="grid-halo"
          strokeWidth={1.5 * stroke + 3}
          points={points(cell.polygon)}
        />
      ))}
      {showGrid && geometry.grid.map(cell => (
        <polygon
          key={`${cell.col}-${cell.row}`}
          className={`grid-cell${geometry.calibrated ? "" : " approximate"}${cell.col === 0 && cell.row === 0 ? " feeder" : ""}`}
          strokeWidth={1.5 * stroke}
          points={points(cell.polygon)}
        />
      ))}
      {/* Supervision, drawn over the grid and under the detections. A cell a
          verdict names takes the state colour; a cell the verdict REFUSED to
          judge takes a 45° hatch and no colour at all, because an absence of
          state must not be dressed as a state (DESIGN.md §2). */}
      <defs>
        <pattern id="sv-hatch" width="8" height="8" patternUnits="userSpaceOnUse"
                 patternTransform="rotate(45)">
          <line className="sv-hatch-line" x1="0" y1="0" x2="0" y2="8" strokeWidth={2} />
        </pattern>
      </defs>
      {showGrid && geometry.grid.filter(cell => unjudged.has(`${cell.col},${cell.row}`)).map(cell => (
        <polygon
          key={`sv-unjudged-${cell.col}-${cell.row}`}
          className="sv-unjudged"
          points={points(cell.polygon)}
        >
          <title>not checked — this cell's expected top level is above the detection ceiling</title>
        </polygon>
      ))}
      {showGrid && geometry.grid.filter(cell => verdictCells.has(`${cell.col},${cell.row}`)).map(cell => (
        <polygon
          key={`sv-verdict-${cell.col}-${cell.row}`}
          className={`sv-verdict sv-${severity}`}
          strokeWidth={2.5 * stroke}
          points={points(cell.polygon)}
        >
          <title>{cellTitle(verdictName, cell.col, cell.row)}</title>
        </polygon>
      ))}
      {showGrid && geometry.grid.filter(cell => cell.col === 0 && cell.row === 0).map(cell => {
        const box = bounds(cell.polygon);
        return (
          <text
            key="feed-label"
            className="feeder-label"
            x={(box.minX + box.maxX) / 2}
            y={(box.minY + box.maxY) / 2}
            textAnchor="middle"
            dominantBaseline="middle"
            fontSize={12 * stroke}
          >PICKUP</text>
        );
      })}

      {showGrid && geometry.feeder?.offset_from_cell && (
        <>
          <polygon
            className="feeder-true"
            points={points(geometry.feeder.polygon)}
          />
          <text
            className="feeder-label feeder-true-label"
            x={geometry.feeder.center[0]}
            y={geometry.feeder.center[1]}
            textAnchor="middle"
            dominantBaseline="middle"
            fontSize={10 * stroke}
          >FEEDER</text>
        </>
      )}

      {hover && <polygon className="hover-cell" points={points(hover.polygon)} />}

      {selected && (
        <>
          <polygon className="grid-halo" strokeWidth={3 * stroke + 3} points={points(selected.polygon)} />
          <polygon className="selected" strokeWidth={3 * stroke} points={points(selected.polygon)} />
          {corners(selected.polygon).map((tick, index) => (
            <polyline key={index} className="selected-tick" strokeWidth={3 * stroke} points={tick} />
          ))}
        </>
      )}

      {levelBox && Array.from({ length: Math.min(state.level, 8) }, (_, index) => (
        <rect
          key={`pip-${index}`}
          className="level-pip"
          x={levelBox.maxX - 10 * stroke}
          y={levelBox.maxY - (6 + index * 8) * stroke}
          width={6 * stroke}
          height={6 * stroke}
        />
      ))}

      {showDetections && geometry.detections.map((detection, index) => (
        <g key={index} className={`detection ${detection.color}`}>
          <polygon className="grid-halo" strokeWidth={2 * stroke + 3} points={points(detection.box)} />
          <polygon strokeWidth={2 * stroke} points={points(detection.box)} />
          <circle cx={detection.center[0]} cy={detection.center[1]} r={3 * stroke} />
        </g>
      ))}
    </svg>
  );
}
