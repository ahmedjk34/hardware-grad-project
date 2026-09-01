/** Lucide-derived 24px line icons. Inline SVG, never emoji: the console is
 *  read at arm's length and emoji rasterise differently on every platform. */
const PATHS: Record<string, string> = {
  grid: "M3 3h18v18H3z M9 3v18 M15 3v18 M3 9h18 M3 15h18",
  detect: "M3 7V5a2 2 0 0 1 2-2h2 M17 3h2a2 2 0 0 1 2 2v2 M21 17v2a2 2 0 0 1-2 2h-2 M7 21H5a2 2 0 0 1-2-2v-2 M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z",
  sheet: "M4 4h16v16H4z M4 9h16 M9 4v16",
  overlay: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z",
  live: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z",
  stale: "M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z M12 9v4 M12 17h.01",
  waiting: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z M12 7v5l3 2",
  lock: "M5 11h14v10H5z M8 11V7a4 4 0 0 1 8 0v4",
  link: "M12 20h.01 M8.5 16.4a5 5 0 0 1 7 0 M5 12.9a10 10 0 0 1 14 0 M1.4 9.4a15 15 0 0 1 21.2 0",
  unlink: "M1 1l22 22 M16.7 16.7a5 5 0 0 0-7.4 0 M5 12.9a10 10 0 0 1 4-2.5 M1.4 9.4a15 15 0 0 1 5-3.3 M12 20h.01",
  clock: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z M12 6v6l4 2",
  layers: "M12 2 2 7l10 5 10-5-10-5z M2 17l10 5 10-5 M2 12l10 5 10-5",
  target: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z M12 12h.01",
  chevron: "M6 9l6 6 6-6",
  axes: "M8 3 4 7l4 4 M4 7h16 M16 21l4-4-4-4 M20 17H4",
  ruler: "M3 9h18v6H3z M7 9v3 M11 9v3 M15 9v3 M19 9v3",
  down: "M12 5v14 M19 12l-7 7-7-7",
  check: "M20 6 9 17l-5-5",
  power: "M12 3v9 M18.4 6.6a9 9 0 1 1-12.8 0",
};

export function Icon({ name, size = 16, className }: { name: keyof typeof PATHS | string; size?: number; className?: string }) {
  const path = PATHS[name];
  if (!path) return null;
  return (
    <svg
      className={`icon${className ? ` ${className}` : ""}`}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {path.split(" M").map((segment, index) => (
        <path key={index} d={index === 0 ? segment : `M${segment}`} />
      ))}
    </svg>
  );
}
