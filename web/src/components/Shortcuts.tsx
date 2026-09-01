const KEYS: [string, string][] = [
  ["← ↑ → ↓", "Nudge the selected cell"],
  ["+ / −", "Change level"],
  ["Esc", "Deselect"],
  ["B", "Arm build"],
  ["Enter", "Confirm the armed build"],
  ["?", "Show or hide this list"],
];

export function Shortcuts({ onClose }: { onClose: () => void }) {
  return (
    <div className="shortcuts" role="dialog" aria-modal="true" aria-label="Keyboard shortcuts" onClick={onClose}>
      <div className="sheet-card" onClick={event => event.stopPropagation()}>
        <h2 className="label">Keyboard shortcuts</h2>
        <dl>
          {KEYS.map(([key, description]) => (
            <div key={key} style={{ display: "contents" }}>
              <dt>{key}</dt>
              <dd>{description}</dd>
            </div>
          ))}
        </dl>
        <button type="button" className="btn" onClick={onClose}>Close</button>
      </div>
    </div>
  );
}
