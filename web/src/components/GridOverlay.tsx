import { useState } from "react";
import type { CellGeometry, Point, StateModel } from "../types";

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
          >FEED</text>
        );
      })}

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
