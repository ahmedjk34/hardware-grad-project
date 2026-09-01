import type { CellTarget } from "../pick";

/** A renderer hit translated into the cell-space facts the editor needs. */
export interface SurfacePointer {
  target: CellTarget;
  clientX: number;
  clientY: number;
  pointerId: number;
  altKey: boolean;
  shiftKey: boolean;
  blockId?: string;
}

export interface SurfaceHandlers {
  onSurfaceMove?: (hit: SurfacePointer) => void;
  onSurfaceDown?: (hit: SurfacePointer) => void;
  onSurfaceUp?: (hit: SurfacePointer) => void;
  onSurfaceLeave?: () => void;
}
