/**
 * The one console store, shared by every route.
 *
 * `App` (the `#/` console) and `BuildMode` (`#/build`) are separate route
 * components that mount and unmount as the hash changes, but they mirror the
 * SAME server. If each made its own store the socket would be torn down and
 * replayed on every route switch, and a build running while the operator opened
 * building mode would flicker through WAITING. So the store is a module
 * singleton and `routes/Root.tsx` owns the single `connectEvents` subscription
 * for the life of the page.
 */
import { createConsoleStore } from "./store";

export const store = createConsoleStore();
