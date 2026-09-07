/**
 * The colour tokens, measured rather than assumed.
 *
 * DESIGN.md §7 asks for body text at 4.5:1 and STATE text at 7:1, and warns
 * that "amber is the one that usually fails". It measured wrong: amber clears
 * the bar comfortably and RED does not. `--danger` is 5.89:1 on `--surface`,
 * which is why `--danger-text` exists and why a red SENTENCE is never painted
 * in `--danger`.
 *
 * This file exists so that a future palette edit cannot quietly break any of
 * that. It reads the real stylesheet — not a copy of the values — so the test
 * and the shipped colours cannot drift apart.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const CSS = readFileSync(join(process.cwd(), "src", "style.css"), "utf8");

function token(name: string): string {
  const match = CSS.match(new RegExp(`${name}\\s*:\\s*(#[0-9A-Fa-f]{6})`));
  if (!match) throw new Error(`token ${name} is not defined in style.css`);
  return match[1];
}

/** WCAG 2.1 relative luminance. */
function luminance(hex: string): number {
  const channels = [1, 3, 5].map(index => parseInt(hex.slice(index, index + 2), 16) / 255);
  const linear = channels.map(c => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function contrast(a: string, b: string): number {
  const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (high + 0.05) / (low + 0.05);
}

describe("the reserved state palette", () => {
  const surface = () => token("--surface");
  const voidToken = () => token("--void");

  it("keeps every colour supervision paints a WORD in above 7:1", () => {
    // These are the three that can carry state text: two state colours that
    // pass as they are, and the lightened red that exists because the third
    // does not.
    for (const name of ["--ready", "--motion", "--danger-text", "--text-dim"]) {
      expect(contrast(token(name), surface()),
             `${name} on --surface`).toBeGreaterThanOrEqual(7);
    }
  });

  it("records that --danger itself FAILS the state-text bar", () => {
    // Not a bug to fix by lightening it: LOCKED depends on this exact value,
    // and as an icon, an edge and a filled chip it is already clear. The rule
    // is that it never carries body copy. If this assertion ever starts
    // failing, someone has changed --danger and the reason for --danger-text
    // needs re-checking, not deleting.
    expect(contrast(token("--danger"), surface())).toBeLessThan(7);
    expect(contrast(token("--danger"), surface())).toBeGreaterThan(4.5);
  });

  it("keeps the filled chips legible, which is how state colour is carried", () => {
    // --void on a filled plate, at >= 18.66px bold, is WCAG "large text" and
    // clears 3:1 on all three.
    for (const name of ["--ready", "--motion", "--danger"]) {
      expect(contrast(voidToken(), token(name)),
             `--void on ${name}`).toBeGreaterThanOrEqual(3);
    }
  });

  it("keeps the body text token far above the body bar", () => {
    expect(contrast(token("--text"), surface())).toBeGreaterThanOrEqual(4.5);
  });
});
