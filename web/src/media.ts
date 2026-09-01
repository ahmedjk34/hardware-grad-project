/**
 * The two media questions this app asks, in one place.
 *
 * Both were written twice — the console's phone breakpoint in `App.tsx`, the
 * Studio's reduced-motion query in `scene/Viewport.tsx` — and Plan 4 §9 needs
 * both again in the twin. Two copies of a breakpoint is how a layout ends up
 * disagreeing with itself at 899px.
 */
import { useEffect, useState } from "react";

/** DESIGN.md §5: below this the rail stacks and the action sheet appears. */
export const PHONE_QUERY = "(max-width: 899px)";
export const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia?.(query).matches ?? false);
  useEffect(() => {
    const media = window.matchMedia?.(query);
    if (!media) return;
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener?.("change", update);
    return () => media.removeEventListener?.("change", update);
  }, [query]);
  return matches;
}

export const usePhone = (): boolean => useMediaQuery(PHONE_QUERY);
/** DESIGN.md §3.4: a reduced-motion viewer gets the destination, not the trip. */
export const useReducedMotion = (): boolean => useMediaQuery(REDUCED_MOTION_QUERY);

/**
 * Whether this tab is on screen at all. The twin stops rendering when it is
 * not: on a phone the camera is what matters, and a hidden 3D canvas that keeps
 * drawing is a dropped video frame for nothing.
 */
export function useDocumentVisible(): boolean {
  const [visible, setVisible] = useState(() => !document.hidden);
  useEffect(() => {
    const update = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);
  return visible;
}
