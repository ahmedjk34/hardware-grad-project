#!/usr/bin/env python3
"""Generate browser projection golden cases from the authoritative Python map."""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rig.workspace import WorkspaceMap

OUT = Path(__file__).resolve().parents[2] / "web/src/lib/workspace.fixtures.json"

def main() -> None:
    size = (640, 480)
    workspace = WorkspaceMap.from_pixels(3, 2, ((80, 60), (560, 90), (540, 420), (70, 400)), size)
    points = ((100, 100), (300, 180), (500, 300), (20, 20), (620, 450))
    payload = {"maps": [{"cols": workspace.cols, "rows": workspace.rows,
                           "corners": workspace.corners, "image_size": list(size),
                           "cells": [{"point": list(point), "cell": list(workspace.cell_at(point, size)) if workspace.cell_at(point, size) is not None else None} for point in points],
                           "polygons": [{"col": col, "row": row, "polygon": [list(point) for point in workspace.target_polygon(col, row, size)]} for row in range(workspace.rows) for col in range(workspace.cols)]}]}
    OUT.write_text(json.dumps(payload, indent=2) + "\n")

if __name__ == "__main__": main()
