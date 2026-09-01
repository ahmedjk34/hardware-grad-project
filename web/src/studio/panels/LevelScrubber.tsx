/**
 * An explicit level hold, not a hidden modifier.
 *
 * Holding a level deliberately overrides stack-derived height so unsupported
 * overhangs can be authored before M3 evaluates them. The rail remains DOM UI
 * for focus, labels and pointer-drag accessibility.
 */
export function LevelScrubber({ ceiling, heldLevel, onHold, onRelease }: {
  ceiling: number;
  heldLevel: number | null;
  onHold: (level: number) => void;
  onRelease?: () => void;
}) {
  const levels = Array.from({ length: ceiling + 1 }, (_, level) => ceiling - level);
  return (
    <div className="studio-levels" aria-label="Placement level">
      <span className="studio-levels-label">LEVEL</span>
      <div className="studio-levels-rail">
        {levels.map(level => (
          <button
            key={level}
            type="button"
            className="studio-level"
            aria-label={`Hold level ${level}`}
            aria-pressed={heldLevel === level}
            onPointerDown={event => { event.preventDefault(); onHold(level); }}
            onPointerEnter={event => { if (event.buttons === 1) onHold(level); }}
          >
            <span className="studio-level-tick" />
            <span className="studio-level-number">{level}</span>
          </button>
        ))}
      </div>
      {heldLevel !== null ? (
        <button type="button" className="studio-level-release"
                aria-label="Release held level" onClick={onRelease}>ESC</button>
      ) : null}
    </div>
  );
}
