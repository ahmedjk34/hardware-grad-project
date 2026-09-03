/**
 * The whole of the routing: the console at `#/`, building mode at `#/build`,
 * the Studio at `#/studio`.
 *
 * A hash route needs no server rewrite, which matters because the Pi serves
 * this as static files and the PWA shell has to keep working offline. The
 * Studio is a lazy import so three.js lands in its own chunk and the console's
 * first paint never downloads it. Building mode is NOT lazy — it reuses the
 * console's own components and the runner, none of which pull three directly;
 * the twin inside it still lazy-loads the 3D canvas the same way the console's
 * twin does.
 *
 * `connectEvents` is subscribed here, once, for the life of the page. Both the
 * console and building mode read the same module-singleton store, so moving
 * between them never tears the socket down.
 */
import { Suspense, lazy, useEffect, useState } from "react";
import { App } from "../App";
import { BuildMode } from "../components/buildmode/BuildMode";
import { Icon } from "../components/Icon";
import { store } from "../consoleStore";
import { connectEvents } from "../ws";
import { preloadStudio } from "./studio-loader";

const Studio = lazy(preloadStudio);

function useHashRoute(): string {
  const [route, setRoute] = useState(() => window.location.hash.replace(/^#/, "") || "/");
  useEffect(() => {
    const update = () => setRoute(window.location.hash.replace(/^#/, "") || "/");
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  return route;
}

export function Root() {
  const route = useHashRoute();
  useEffect(() => connectEvents(store), []);

  if (route.startsWith("/studio")) return (
    <Suspense fallback={<main className="boot"><Icon name="waiting" size={28} />Loading the Studio…</main>}>
      <Studio />
    </Suspense>
  );
  if (route.startsWith("/build")) return <BuildMode />;
  return <App />;
}
