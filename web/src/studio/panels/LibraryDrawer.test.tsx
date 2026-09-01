import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LibraryDrawer, UNDO_MS, relativeTime } from "./LibraryDrawer";
import { BUDGET_BYTES, writeModel, type LibraryStorage } from "../library";
import { documentOf } from "../rigmodel";
import { DEFAULT_STUDIO_SETTINGS } from "../settings";
import type { Model, ModelBlock } from "../model";

const block = (id: string, level: number): ModelBlock =>
  ({ id, mode: "vertical", col: 3, row: 2, level, colour: "white" });
const tower = (n: number): Model => {
  const blocks = Array.from({ length: n }, (_, level) => block(`b${level}`, level));
  return { blocks, order: blocks.map(item => item.id) };
};

class FakeStorage implements LibraryStorage {
  data = new Map<string, string>();
  get length() { return this.data.size; }
  key(index: number) { return [...this.data.keys()][index] ?? null; }
  getItem(key: string) { return this.data.get(key) ?? null; }
  setItem(key: string, value: string) { this.data.set(key, value); }
  removeItem(key: string) { this.data.delete(key); }
}

let storage: FakeStorage;
const onOpenModel = vi.fn();
const onClose = vi.fn();
let captureCurrent = vi.fn();

const draw = (overrides: Partial<Parameters<typeof LibraryDrawer>[0]> = {}) => render(
  <LibraryDrawer open onClose={onClose} currentId={null} onOpenModel={onOpenModel}
                 settings={DEFAULT_STUDIO_SETTINGS} storage={storage}
                 captureCurrent={captureCurrent} {...overrides} />,
);

beforeEach(() => {
  storage = new FakeStorage();
  onOpenModel.mockClear();
  onClose.mockClear();
  captureCurrent = vi.fn().mockResolvedValue(documentOf(tower(2), { id: "live", name: "Live model" }));
});
afterEach(() => vi.useRealTimers());

const card = (name: string) => screen.getByRole("listitem", { name: new RegExp(name) });

describe("LibraryDrawer — the cards", () => {
  it("shows the three built-in examples so an empty library never looks broken", () => {
    draw();
    expect(screen.getByRole("listitem", { name: /Single tower/ })).toBeInTheDocument();
    expect(screen.getByRole("listitem", { name: /Two towers, one span/ })).toBeInTheDocument();
    expect(screen.getByRole("listitem", { name: /Stepped pyramid/ })).toBeInTheDocument();
    expect(screen.getByText(/no saved models yet/i)).toBeInTheDocument();
  });

  it("puts the block count, latch count, estimate and modified date on one meta line", () => {
    writeModel(documentOf(tower(12), { id: "m1", name: "Slab", modified: new Date(Date.now() - 2 * 86400_000).toISOString() }),
               { storage, settings: DEFAULT_STUDIO_SETTINGS });
    draw();
    expect(within(card("Slab")).getByTestId("meta")).toHaveTextContent("12 blocks · 0 latches · ~0:25 · 2d ago");
  });

  it("marks the open model as selected, and nothing else", () => {
    writeModel(documentOf(tower(2), { id: "m1", name: "Alpha" }), { storage, settings: DEFAULT_STUDIO_SETTINGS });
    writeModel(documentOf(tower(3), { id: "m2", name: "Beta" }), { storage, settings: DEFAULT_STUDIO_SETTINGS });
    draw({ currentId: "m2" });
    expect(card("Beta")).toHaveAttribute("aria-current", "true");
    expect(card("Alpha")).not.toHaveAttribute("aria-current", "true");
  });

  it("opens a stored model when its card is clicked", async () => {
    writeModel(documentOf(tower(2), { id: "m1", name: "Alpha" }), { storage, settings: DEFAULT_STUDIO_SETTINGS });
    draw();
    await userEvent.click(within(card("Alpha")).getByRole("button", { name: /open Alpha/i }));
    expect(onOpenModel).toHaveBeenCalledWith(expect.objectContaining({ id: "m1", name: "Alpha" }));
  });

  it("opens a built-in example as a fresh copy of the shipped document", async () => {
    draw();
    await userEvent.click(within(card("Two towers, one span")).getByRole("button", { name: /open Two towers/i }));
    expect(onOpenModel).toHaveBeenCalledWith(expect.objectContaining({ id: "example-bridge" }));
  });
});

describe("LibraryDrawer — rename, duplicate, delete with undo", () => {
  beforeEach(() => {
    writeModel(documentOf(tower(2), { id: "m1", name: "Alpha" }), { storage, settings: DEFAULT_STUDIO_SETTINGS });
  });

  it("renames inline on double-click, not in a modal", async () => {
    draw();
    await userEvent.dblClick(within(card("Alpha")).getByTestId("name"));
    const field = screen.getByRole("textbox", { name: /model name/i });
    await userEvent.clear(field);
    await userEvent.type(field, "Renamed by hand{Enter}");
    await waitFor(() => expect(screen.getByRole("listitem", { name: /Renamed by hand/ })).toBeInTheDocument());
    expect(screen.queryByRole("listitem", { name: /Alpha/ })).not.toBeInTheDocument();
  });

  it("duplicates into a new card without disturbing the original", async () => {
    draw();
    await userEvent.click(within(card("Alpha")).getByRole("button", { name: /duplicate/i }));
    await waitFor(() => expect(screen.getByRole("listitem", { name: /Alpha copy/ })).toBeInTheDocument());
    expect(screen.getByRole("listitem", { name: "Alpha" })).toBeInTheDocument();
  });

  it("deletes immediately and offers a six-second undo that really restores it", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    vi.useFakeTimers({ shouldAdvanceTime: true });
    draw();
    await user.click(within(card("Alpha")).getByRole("button", { name: /delete/i }));
    expect(screen.queryByRole("listitem", { name: /Alpha/ })).not.toBeInTheDocument();

    const toast = screen.getByRole("status");
    expect(toast).toHaveTextContent(/deleted Alpha/i);
    await user.click(within(toast).getByRole("button", { name: /undo/i }));
    await waitFor(() => expect(screen.getByRole("listitem", { name: /Alpha/ })).toBeInTheDocument());
  });

  it("lets the undo lapse after six seconds and the delete stands", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    draw();
    await user.click(within(card("Alpha")).getByRole("button", { name: /delete/i }));
    expect(screen.getByRole("status")).toBeInTheDocument();
    vi.advanceTimersByTime(UNDO_MS + 100);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    expect(screen.queryByRole("listitem", { name: /Alpha/ })).not.toBeInTheDocument();
    expect(UNDO_MS).toBe(6000);
  });
});

describe("LibraryDrawer — storage that cannot keep the work", () => {
  it("says so in a strip and still shows the examples", () => {
    draw({ storage: undefined });
    expect(screen.getByRole("alert")).toHaveTextContent(/storage unavailable — your work will not be kept/i);
    expect(screen.getByRole("listitem", { name: /Single tower/ })).toBeInTheDocument();
  });

  it("refuses an over-budget save, names the largest models, and offers a delete right there", async () => {
    writeModel(documentOf(tower(2), {
      id: "big", name: "Big", thumbnail: "z".repeat(BUDGET_BYTES - 4000),
    }), { storage, settings: DEFAULT_STUDIO_SETTINGS });
    captureCurrent = vi.fn().mockResolvedValue(
      documentOf(tower(2), { id: "live", name: "Live model", thumbnail: "y".repeat(20_000) }),
    );
    draw();

    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));
    const refusal = await screen.findByRole("alert");
    expect(refusal).toHaveTextContent(/over budget/i);
    expect(refusal).toHaveTextContent(/Big/);

    // Nothing was evicted to make room, and the delete control is in the strip.
    expect(screen.getByRole("listitem", { name: /Big/ })).toBeInTheDocument();
    await userEvent.click(within(refusal).getByRole("button", { name: /delete Big/i }));
    await waitFor(() => expect(screen.queryByRole("listitem", { name: /Big/ })).not.toBeInTheDocument());
  });

  it("saves the captured document and selects it when there is room", async () => {
    const onOpenSaved = vi.fn();
    draw({ onSaved: onOpenSaved });
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(screen.getByRole("listitem", { name: /Live model/ })).toBeInTheDocument());
    expect(onOpenSaved).toHaveBeenCalledWith(expect.objectContaining({ id: "live" }));
  });
});

describe("LibraryDrawer — import never lands silently", () => {
  const drop = async (name: string, text: string) => {
    const file = new File([text], name, { type: "application/json" });
    Object.defineProperty(file, "text", { value: () => Promise.resolve(text) });
    const event = new Event("drop", { bubbles: true, cancelable: true });
    Object.defineProperty(event, "dataTransfer", { value: { files: [file], types: ["Files"] } });
    window.dispatchEvent(event);
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
  };

  it("shows what is about to be added, with its block count, and waits for a confirm", async () => {
    draw();
    const incoming = documentOf(tower(4), { id: "dropped", name: "From a colleague" });
    await drop("model.rigmodel.json", JSON.stringify({ schema: "rigmodel/1", ...incoming }));

    const sheet = screen.getByRole("dialog");
    expect(sheet).toHaveTextContent("From a colleague");
    expect(sheet).toHaveTextContent("4 blocks");
    expect(screen.queryByRole("listitem", { name: /From a colleague/ })).not.toBeInTheDocument();

    await userEvent.click(within(sheet).getByRole("button", { name: /import/i }));
    await waitFor(() => expect(screen.getByRole("listitem", { name: /From a colleague/ })).toBeInTheDocument());
  });

  it("shows the drift warning on the model it is about to import", async () => {
    const incoming = documentOf(tower(2), { id: "drifted", name: "Old geometry" });
    incoming.rig.modes.vertical.cols = 9;
    draw();
    await drop("old.rigmodel.json", JSON.stringify({ schema: "rigmodel/1", ...incoming }));
    expect(screen.getByRole("dialog")).toHaveTextContent(/9 . 6 vertical grid/);
  });

  it("names the reason when the dropped file is not a .json at all", async () => {
    draw();
    const file = new File(["PK"], "library.zip", { type: "application/zip" });
    const event = new Event("drop", { bubbles: true, cancelable: true });
    Object.defineProperty(event, "dataTransfer", { value: { files: [file], types: ["Files"] } });
    window.dispatchEvent(event);
    const refusal = await screen.findByRole("alert");
    expect(refusal).toHaveTextContent(/library\.zip is not a \.json file/i);
  });

  it("catches a drop even while the drawer is closed", async () => {
    draw({ open: false });
    const incoming = documentOf(tower(2), { id: "dropped", name: "Arrived closed" });
    await drop("model.rigmodel.json", JSON.stringify({ schema: "rigmodel/1", ...incoming }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Arrived closed");
  });

  it("cancels without importing anything", async () => {
    draw();
    const incoming = documentOf(tower(2), { id: "dropped", name: "Not wanted" });
    await drop("model.rigmodel.json", JSON.stringify({ schema: "rigmodel/1", ...incoming }));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: /cancel/i }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.queryByRole("listitem", { name: /Not wanted/ })).not.toBeInTheDocument();
  });
});

describe("relativeTime — the last field of the meta line", () => {
  const now = new Date("2026-09-01T12:00:00.000Z");
  it("reads the way a person would say it", () => {
    expect(relativeTime("2026-09-01T11:59:30.000Z", now)).toBe("just now");
    expect(relativeTime("2026-09-01T11:20:00.000Z", now)).toBe("40m ago");
    expect(relativeTime("2026-09-01T04:00:00.000Z", now)).toBe("8h ago");
    expect(relativeTime("2026-08-30T12:00:00.000Z", now)).toBe("2d ago");
    expect(relativeTime("2026-01-01T12:00:00.000Z", now)).toBe("1 Jan");
    expect(relativeTime("nonsense", now)).toBe("unknown");
  });
});
