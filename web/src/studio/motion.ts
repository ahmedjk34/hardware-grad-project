/**
 * Block arrival timing without React or three.js.
 *
 * The fade explains spawning; the downward ease explains placement. A gesture
 * that creates several rows starts each distinct row in sequence, while every
 * block in one row lands together. Single placements never inherit a row-based
 * delay merely because their machine row number is high.
 */
export const ARRIVAL_DROP_SCENE = 0.8; // 8 mm.
export const ARRIVAL_SETTLE_MS = 220;
export const ARRIVAL_FADE_MS = 130;
export const ROW_STAGGER_MS = 34;

export interface ArrivalFrame {
  active: boolean;
  opacity: number;
  offsetScene: number;
}

const clamp01 = (value: number) => Math.max(0, Math.min(1, value));
const smoothstep = (value: number) => value * value * (3 - 2 * value);
const easeOutQuint = (value: number) => 1 - Math.pow(1 - value, 5);

export function arrivalFrame(elapsedMs: number, delayMs: number, reducedMotion: boolean): ArrivalFrame {
  if (reducedMotion) return { active: false, opacity: 1, offsetScene: 0 };
  const local = elapsedMs - delayMs;
  if (local <= 0) return { active: true, opacity: 0, offsetScene: ARRIVAL_DROP_SCENE };
  if (local >= ARRIVAL_SETTLE_MS) return { active: false, opacity: 1, offsetScene: 0 };
  const fade = smoothstep(clamp01(local / ARRIVAL_FADE_MS));
  const settle = easeOutQuint(clamp01(local / ARRIVAL_SETTLE_MS));
  return {
    active: true,
    opacity: fade,
    offsetScene: ARRIVAL_DROP_SCENE * (1 - settle),
  };
}

export function rowArrivalDelays(blocks: ReadonlyArray<{ id: string; row: number }>): Map<string, number> {
  const rowOrder = new Map<number, number>();
  const delays = new Map<string, number>();
  for (const block of blocks) {
    let order = rowOrder.get(block.row);
    if (order === undefined) {
      order = rowOrder.size;
      rowOrder.set(block.row, order);
    }
    delays.set(block.id, order * ROW_STAGGER_MS);
  }
  return delays;
}
