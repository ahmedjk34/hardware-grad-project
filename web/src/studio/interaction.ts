/** Pointer and keyboard gestures expressed without React or three.js. */
import type { CellTarget } from "./pick";

export interface Point2 { x: number; y: number }
export const CLICK_SLOP_PX = 4;

export function pointerIsClick(start: Point2, end: Point2): boolean {
  return Math.hypot(end.x - start.x, end.y - start.y) <= CLICK_SLOP_PX;
}

/** Prevent a pointer stream inside one cell from rerendering the whole scene. */
export function sameTarget(a: CellTarget | null, b: CellTarget | null): boolean {
  return a === b || (!!a && !!b && a.col === b.col && a.row === b.row && a.level === b.level);
}

export type KeyboardAction = "undo" | "redo" | "release-level" | "toggle-mode"
  | { holdLevel: number };

interface ShortcutInput {
  key: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  shiftKey?: boolean;
  targetTag?: string;
  contentEditable?: boolean;
}

export function keyboardAction(input: ShortcutInput): KeyboardAction | null {
  const tag = input.targetTag?.toUpperCase();
  if (input.contentEditable || tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return null;
  const modifier = input.ctrlKey || input.metaKey;
  const key = input.key.toLowerCase();
  if (modifier && key === "z") return input.shiftKey ? "redo" : "undo";
  if (modifier && key === "y") return "redo";
  if (!modifier && input.key === "Escape") return "release-level";
  if (!modifier && key === "m") return "toggle-mode";
  if (!modifier && /^[0-9]$/.test(input.key)) return { holdLevel: Number(input.key) };
  return null;
}
