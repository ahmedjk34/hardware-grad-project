/**
 * Three models shipped in the bundle, so an empty library never looks broken —
 * and so a geometry change in `config/rig.json` breaks a test rather than the
 * presentation. `examples.test.ts` asserts that each one loads, validates with
 * no errors, and compiles to a program the runner could send.
 *
 * They are also the fallback demo. Each one is authored so the timeline reads
 * sensibly top to bottom, because these are the programs that will be on screen
 * while somebody explains the project.
 *
 * THE BRIDGE CARRIES A GRID SHIFT, AND THAT IS THE POINT. Horizontal's +1.9 cm
 * registration lands a span block dead over the 1.6 cm gap between two vertical
 * stacks: it touches 73.3% of its footprint but its centroid sits over the gap
 * — over air — so M3 rejects it. A ±1.0 cm operator shift slides the span so
 * its centroid rides one tower (56.7% contact at +1.0 cm). Because the rig is
 * not applying that shift today, the bridge opens with a `GEOMETRY_DRIFT`
 * warning naming it. That warning is the feature: it is the difference between
 * an operator pushing `shiftX 1.0` before the build and watching a block fall
 * between two towers.
 */
import type { ModelBlock } from "./model";
import { documentOf, snapshotFileRig, type StudioModel } from "./rigmodel";

/**
 * Found, not guessed. The search sweeps `shiftX` in 1 mm steps through M3's
 * `validateModel` for the `v[2,2] v[3,2]` / `h[1,4]` fixture on the shipped
 * rig.json (horizontal registered +1.9 cm on both axes); the shifts with no
 * error are -1.0…-0.8 cm and +0.8…+1.1 cm. +1.0 is the round one, and puts the
 * span's centroid over the far tower v[3,2].
 */
export const BRIDGE_SHIFT_CM = 1;

const AUTHORED = "2026-09-01T12:00:00.000Z";

const block = (
  id: string, mode: ModelBlock["mode"], col: number, row: number, level: number,
  colour: ModelBlock["colour"],
): ModelBlock => ({ id, mode, col, row, level, colour });

function example(
  id: string, name: string, description: string, blocks: ModelBlock[],
  shift?: { mode: "vertical" | "horizontal"; xCm: number; yCm: number },
): StudioModel {
  const rig = snapshotFileRig();
  if (shift) rig.shift_cm[shift.mode] = [shift.xCm, shift.yCm];
  return documentOf({ blocks, order: blocks.map(item => item.id) }, {
    id, name, description, rig, created: AUTHORED, modified: AUTHORED,
  });
}

/** TOWER — one cell, five levels. Stacking, and a short program to rehearse. */
const TOWER = example(
  "example-tower",
  "Single tower",
  "One cell of the vertical grid, five blocks high. No mode latch, five B commands, about three minutes — the program to rehearse the runner with.",
  [0, 1, 2, 3, 4].map(level => block(`t${level + 1}`, "vertical", 3, 2, level, "blue")),
);

/** BRIDGE — the one that matters: Plan 4 §3 fact 6, and one forced latch. */
const BRIDGE = example(
  "example-bridge",
  "Two towers, one span",
  "Two vertical stacks two blocks high, with a horizontal block laid across both of them. The two grids are different lattices in the same physical space, so a 6.0 cm horizontal block can bridge a gap no vertical block can. Needs shiftX +1.00 cm on the horizontal grid — the model says so on open.",
  [
    block("l1", "vertical", 2, 2, 0, "blue"),
    block("r1", "vertical", 3, 2, 0, "blue"),
    block("l2", "vertical", 2, 2, 1, "blue"),
    block("r2", "vertical", 3, 2, 1, "blue"),
    block("s1", "horizontal", 1, 4, 2, "yellow"),
  ],
  { mode: "horizontal", xCm: BRIDGE_SHIFT_CM, yCm: 0 },
);

/**
 * PYRAMID — 5 / 3 / 1, every course resting fully on the one beneath.
 *
 * It opens with ISLAND warnings, and they are correct: within one mode the
 * 1.6 cm gaps mean no two cells ever touch, so five stacks side by side really
 * are five separate structures. That is Plan 4 §3 fact 6 stated from the other
 * direction, and it is why "Two towers, one span" exists.
 */
const PYRAMID = example(
  "example-pyramid",
  "Stepped pyramid",
  "Three courses on a five-wide base, each block resting fully on the one below. The ISLAND warnings are honest: inside one grid the 1.6 cm gaps mean the five stacks never touch — only a cross-mode span can tie them together.",
  [
    ...[1, 2, 3, 4, 5].map(col => block(`a${col}`, "vertical", col, 2, 0, "red")),
    ...[2, 3, 4].map(col => block(`b${col}`, "vertical", col, 2, 1, "orange")),
    block("c3", "vertical", 3, 2, 2, "yellow"),
  ],
);

export const EXAMPLES: StudioModel[] = [TOWER, BRIDGE, PYRAMID];

export const EXAMPLE_IDS: string[] = EXAMPLES.map(item => item.id);

export function isExampleId(id: string): boolean {
  return EXAMPLE_IDS.includes(id);
}

/** A fresh copy every time: the drawer hands these straight to the editor, and
 *  an editor that mutated the shipped constant would corrupt the demo. */
export function exampleById(id: string): StudioModel | undefined {
  const found = EXAMPLES.find(item => item.id === id);
  return found ? structuredClone(found) : undefined;
}
