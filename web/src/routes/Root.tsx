/**
 * The whole of the routing: the console at `#/`, the Studio at `#/studio`.
 *
 * A hash route needs no server rewrite, which matters because the Pi serves
 * this as static files and the PWA shell has to keep working offline. The
 * Studio is a lazy import so three.js lands in its own chunk and the console's
 * first paint never downloads it.
 */
import { Suspense, lazy, useEffect, useState } from "react";
import { App } from "../App";
import { Icon } from "../components/Icon";
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
  if (!route.startsWith("/studio")) return <App />;
  return (
    <Suspense fallback={<main className="boot"><Icon name="waiting" size={28} />Loading the Studio…</main>}>
      <Studio />
    </Suspense>
  );
}
