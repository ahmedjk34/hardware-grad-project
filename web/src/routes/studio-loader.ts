import { createPreloader } from "./preload";

export const preloadStudio = createPreloader(() => import("./Studio"));
