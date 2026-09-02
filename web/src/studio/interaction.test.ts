import { describe, expect, it } from "vitest";
import { keyboardAction, pointerIsClick, sameTarget } from "./interaction";

describe("Studio input interpretation", () => {
  it("commits only when pointerup stays within four pixels", () => {
    expect(pointerIsClick({ x: 10, y: 10 }, { x: 13, y: 12 })).toBe(true);
    expect(pointerIsClick({ x: 10, y: 10 }, { x: 15, y: 10 })).toBe(false);
  });

  it("recognises both redo conventions", () => {
    expect(keyboardAction({ key: "z", ctrlKey: true, shiftKey: false })).toBe("undo");
    expect(keyboardAction({ key: "Z", ctrlKey: true, shiftKey: true })).toBe("redo");
    expect(keyboardAction({ key: "y", ctrlKey: true, shiftKey: false })).toBe("redo");
  });

  it("maps Ctrl/Cmd-S to save and swallows the browser default", () => {
    expect(keyboardAction({ key: "s", ctrlKey: true })).toBe("save");
    expect(keyboardAction({ key: "S", metaKey: true, shiftKey: true })).toBe("save");
    expect(keyboardAction({ key: "s", ctrlKey: true, targetTag: "INPUT" })).toBeNull();
  });

  it("maps escape and digits to level actions", () => {
    expect(keyboardAction({ key: "Escape" })).toBe("release-level");
    expect(keyboardAction({ key: "7" })).toEqual({ holdLevel: 7 });
    expect(keyboardAction({ key: "m" })).toBe("toggle-mode");
  });

  it("ignores shortcuts originating in editable controls", () => {
    expect(keyboardAction({ key: "z", ctrlKey: true, targetTag: "INPUT" })).toBeNull();
    expect(keyboardAction({ key: "3", contentEditable: true })).toBeNull();
  });

  it("identifies redundant hover updates without collapsing different levels", () => {
    expect(sameTarget({ col: 2, row: 3, level: 1 }, { col: 2, row: 3, level: 1 })).toBe(true);
    expect(sameTarget({ col: 2, row: 3, level: 1 }, { col: 2, row: 3, level: 2 })).toBe(false);
    expect(sameTarget(null, null)).toBe(true);
  });
});
