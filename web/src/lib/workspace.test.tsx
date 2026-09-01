import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import fixtures from "./workspace.fixtures.json";
import { WorkspaceProjection, type ProjectionFixture } from "./workspace";
import { GridOverlay } from "../components/GridOverlay";
import type { StateModel } from "../types";

describe("Step 8 workspace projection", () => {
  it("matches every Python cell and target polygon fixture", () => {
    for (const fixture of fixtures.maps) {
      const projection = new WorkspaceProjection(fixture as unknown as ProjectionFixture);
      for (const item of fixture.cells) expect(projection.cellAt(item.point as [number, number], fixture.image_size as [number, number])).toEqual(item.cell);
      for (const item of fixture.polygons) projection.targetPolygon(item.col, item.row, fixture.image_size as [number, number]).forEach((point, index) => expect(point[0]).toBeCloseTo(item.polygon[index][0], 6));
    }
  });

  it("does not optimistically select outside a cell", () => {
    const state = overlayState(); const select = vi.fn();
    const { container } = render(<GridOverlay state={state} onSelect={select} />);
    fireEvent.pointerDown(container.querySelector("svg")!, { clientX: -1, clientY: -1 });
    expect(select).not.toHaveBeenCalled();
  });

  it("draws grid and selected polygons, amber when approximate", () => {
    const { container } = render(<GridOverlay state={overlayState()} onSelect={() => {}} />);
    expect(container.querySelectorAll("polygon.grid-cell")).toHaveLength(2);
    expect(container.querySelector("polygon.selected")).toBeTruthy();
    expect(container.querySelector("polygon.grid-cell")?.getAttribute("class")).toContain("approximate");
  });
});

function overlayState(): StateModel { return { mode: "vertical", cols: 2, rows: 1, calibrated: false, selected: [1, 0], command: "B 1 0 0", level: 0, build_state: "READY", locked_reason: null, camera: "LIVE", camera_age_ms: 1, last_result: null, last_result_reason: null, views: {}, geometry: { image_size: [100, 100], calibrated: false, grid: [{ col: 0, row: 0, polygon: [[0, 0], [50, 0], [50, 100], [0, 100]] }, { col: 1, row: 0, polygon: [[50, 0], [100, 0], [100, 100], [50, 100]] }], selected: { col: 1, row: 0, polygon: [[50, 0], [100, 0], [100, 100], [50, 100]] }, detections: [], paper: null } }; }
