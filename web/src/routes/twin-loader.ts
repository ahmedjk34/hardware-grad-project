import { createPreloader } from "./preload";

/** The twin's canvas, split out so the console's first paint never waits on
 *  three.js — the same treatment `studio-loader.ts` gives the Studio route. */
export const preloadTwin = createPreloader(() => import("../studio/scene/Twin"));
