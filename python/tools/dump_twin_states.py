#!/usr/bin/env python3
"""Record real `/api/events` state sequences for the Studio twin's tests.

Plan 4 §9's twin is a claim about the machine, and the browser's version of that
claim (`web/src/studio/twin.ts`) is only worth anything if it is fed what the
server ACTUALLY sends. So the sequences it is tested against are not invented in
TypeScript: they are recorded here, from `web.app` running against `MockBoard`,
one entry per state the console's WebSocket would have delivered.

Three sessions, which are the three outcomes the mock board can produce:

  placed     select, build, PLACED. Note that `selected` survives RUNNING and is
             cleared by `BuildController.build()` the moment the block lands -
             that clearing is how the twin knows which block a `placed` result
             belongs to.
  rejected   the board refuses; nothing moved and the selection is kept.
  aborted    the board aborts; the session locks and the machine's real state
             is unknown from that point on.

Written to `web/src/studio/twin.fixtures.json` and read by `twin.test.ts`.
Same bridge as `dump_grid_fixtures.py`: when the two disagree, this is right.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from fastapi.testclient import TestClient  # noqa: E402

from web.app import ConsoleAppOptions, create_app  # noqa: E402

OUT = ROOT / "web" / "src" / "studio" / "twin.fixtures.json"
CELL = (3, 2)


def centre(state, col, row):
    """The pixel a click on that cell would land on, as the console computes it."""
    cell = next(item for item in state["geometry"]["grid"]
                if item["col"] == col and item["row"] == row)
    xs = [point[0] for point in cell["polygon"]]
    ys = [point[1] for point in cell["polygon"]]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def session(client, app, *, level: int, fail: tuple[str, str] | None):
    """One select-and-build cycle, sampled the way the socket would sample it."""
    states: list[dict] = []

    def sample():
        states.append(client.get("/api/state").json())

    sample()
    x, y = centre(states[-1], *CELL)
    size = states[-1]["geometry"]["image_size"]
    client.post("/api/select", json={"x": x, "y": y, "img_w": size[0], "img_h": size[1]})
    client.post("/api/level", json={"value": level})
    sample()

    if fail is not None:
        app.state.mock_board.fail_next_build(fail[0], fail[1])

    command = f"B {CELL[0]} {CELL[1]} {level}"
    client.post("/api/build", json={"confirm": True, "command": command})
    # The build runs on BuildJob's worker; sample until it settles, exactly as
    # the driver task does at 20 Hz.
    for _ in range(200):
        sample()
        if states[-1]["build_state"] != "RUNNING":
            break
        time.sleep(0.05)
    app.state.job.join()
    sample()
    return {"command": command, "states": states}


def main() -> None:
    options = ConsoleAppOptions(mock=True, build_seconds=0.4)
    sessions = {}
    with TestClient(create_app(options)) as client:
        app = client.app
        sessions["placed"] = session(client, app, level=0, fail=None)
        sessions["rejected"] = session(client, app, level=1,
                                       fail=("REJECTED", "no block at the feeder"))
    # An abort locks the controller for good, so it gets its own application.
    with TestClient(create_app(options)) as client:
        sessions["aborted"] = session(client, app=client.app, level=0,
                                      fail=("ABORTED", "claw did not release"))

    OUT.write_text(json.dumps({"cell": list(CELL), "sessions": sessions}, indent=2) + "\n")
    total = sum(len(item["states"]) for item in sessions.values())
    print(f"{len(sessions)} sessions, {total} states -> {OUT}")


if __name__ == "__main__":
    main()
