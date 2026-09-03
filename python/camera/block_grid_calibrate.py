#!/usr/bin/env python3
"""Run a placed-block calibration from the terminal, and prove it landed.

The rig puts a block on a cell it was told, the camera measures where it went,
and six of those fit the workspace map. Unlike the four-click and printed-sheet
routes this measures the machine itself, so what it writes is where the blocks
actually go rather than where a piece of paper says they should.

    # dry run against the mock camera and mock board - no hardware at all
    python/camera/block_grid_calibrate.py --mock

    # the real thing, six cells, writing config/workspace_map.json
    python/camera/block_grid_calibrate.py --save

    # a tightly framed camera that cuts off the outermost row of blocks
    python/camera/block_grid_calibrate.py --inset 1 --save

Load the feeder at [0,0] first and **clear the build area**: the first frame is
the baseline every later capture is differenced against, so a block already on
the table is invisible to the difference and can only be found by shape.

Nothing is written unless ``--save`` is passed, and even then the fit has to
clear every gate in :func:`vision.block_grid.fit_block_grid` first. An
annotated frame is saved per step with ``--trace``, which is the fastest way to
see *why* a run was refused.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
import sys
import tempfile
import time

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera.camera_feed import CAPTURE_DIR, SETTINGS_PATH  # noqa: E402
from rig.block_calibration import (  # noqa: E402
    BlockCalibrationAborted,
    BlockCalibrationError,
    BlockCalibrationRun,
)
from rig.config import (CONFIG_PATH, GRID_MODES, active_grid_mode,  # noqa: E402
                        load as load_rig_config)
from rig.console_pipeline import ConsolePipeline  # noqa: E402
from rig.workspace import WORKSPACE_MAP_PATH  # noqa: E402
from vision.block_grid import (  # noqa: E402
    DEFAULT_OBSERVATIONS,
    MIN_OBSERVATIONS,
    BlockGridError,
)
from vision.color_grid_overlay import draw_color_grid, draw_workspace_corners  # noqa: E402


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Calibrate the workspace from blocks the rig places itself")
    parser.add_argument("--mode", choices=GRID_MODES,
                        help="grid mode to calibrate (default: the active one)")
    parser.add_argument("--count", type=int, default=DEFAULT_OBSERVATIONS,
                        help=f"cells to place on (minimum {MIN_OBSERVATIONS}, "
                             f"default {DEFAULT_OBSERVATIONS})")
    parser.add_argument("--supply", type=int, default=None,
                        help="how many blocks you physically have; fills the "
                             "grid densely from the home corner with that many "
                             "and synthesises every cell they cannot reach. "
                             "25+ on the vertical grid also measures the real "
                             "pitch and picks a lattice model")
    parser.add_argument("--inset", type=int, default=0,
                        help="drop this many outermost rings of cells; use 1 "
                             "when the camera cuts off the outer row of blocks")
    parser.add_argument("--cells", help="explicit plan, e.g. '1,0 6,0 6,5 0,5 3,3 2,2'")
    parser.add_argument("--save", action="store_true",
                        help=f"write the map to {WORKSPACE_MAP_PATH}")
    parser.add_argument("--trace", action="store_true",
                        help="save an annotated frame after every placement")
    parser.add_argument("--mock", action="store_true",
                        help="use the mock camera and mock board; no hardware")
    parser.add_argument("--settle", type=float, default=None,
                        help="seconds to wait after the rig parks (default 1.5)")
    parser.add_argument("--settings", type=Path, default=SETTINGS_PATH)
    parser.add_argument("--rig-config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--map", type=Path, default=WORKSPACE_MAP_PATH)
    return parser.parse_args(argv)


def mock_settings(source: Path) -> Path:
    """The real camera settings with the framing and lens correction removed.

    The saved zoom, pan and crop are tuned for the rig's actual camera, and
    applying them to the mock camera's synthetic 1296x972 render crops away
    most of the workspace - blocks then sit half outside the frame and are
    rightly refused. A dry run wants the whole mock scene, so ``--mock``
    borrows everything except the framing. Same trick as tests/web_command_test.py.
    """
    data = json.loads(Path(source).read_text())
    data.setdefault("capture", {}).update({"width": 1296, "height": 972})
    data.setdefault("correction", {})["enabled"] = False
    data["framing"] = {"crops": [], "zoom": 1.0, "pan": [0.5, 0.5]}
    handle = tempfile.NamedTemporaryFile(
        "w", suffix="_mock_camera_settings.json", delete=False)
    with handle:
        json.dump(data, handle)
    return Path(handle.name)


def parse_cells(text):
    if not text:
        return None
    cells = []
    # Two-number groups, so "1,0 6,5" and "1 0 6 5" both work.
    numbers = [int(value) for value in text.replace(",", " ").split()]
    if len(numbers) % 2:
        raise SystemExit("--cells needs an even number of coordinates")
    for index in range(0, len(numbers), 2):
        cells.append((numbers[index], numbers[index + 1]))
    return cells


class _MockRig:
    """A mock board that also draws its placements into the mock camera.

    ``--mock`` is only a useful dry run if the two mocks are connected: the
    board on its own acknowledges a build without anything appearing in front
    of the camera, so every step would fail with "placed but not seen". This
    wrapper is the missing wire, and it exists only on the ``--mock`` path.
    """

    def __init__(self, rig, camera):
        self._rig = rig
        self._camera = camera
        self._placed = []
        camera.set_blocks(())

    def __getattr__(self, name):
        return getattr(self._rig, name)

    def build(self, col, row, level, timeout=None):
        result = self._rig.build(col, row, level, timeout=timeout)
        if str(result) == "placed":
            self._placed.append((int(col), int(row), "orange"))
            self._camera.set_blocks(self._placed)
        return result


def prompt(message, *, default=""):
    """Ask, unless nothing is attached to answer - then take the default.

    Piping into this tool is how the dry run gets exercised; blocking on a
    prompt nobody can answer turns that into an EOFError traceback.
    """
    if not sys.stdin or not sys.stdin.isatty():
        print(f"{message}{default} (not a terminal)")
        return default
    try:
        return input(message)
    except EOFError:
        return default


def open_rig(args, grid, pipeline):
    """The real serial rig, or the wired-up mocks when ``--mock`` is set."""
    from rig.link import Rig                       # imported late: opens a port

    if args.mock:
        from rig.mock_board import MockBoard
        board = MockBoard(build_seconds=0.05)
        rig = Rig(serial_factory=lambda *rest: board)
    else:
        rig = Rig()
    rig.connect(home_before_configure=(grid.mode == "horizontal"))
    # --mode selects the grid the pipeline calibrates; the rig has to be put in
    # the same one or it will lay every block along the other axis.
    if grid.mode is not None and rig.grid.mode != grid.mode:
        print(f"switching the rig from {rig.grid.mode} to {grid.mode} ...")
        rig.set_mode(grid.mode)
    if args.mock and hasattr(pipeline.camera, "set_blocks"):
        return _MockRig(rig, pipeline.camera)
    return rig


def annotate(frame, run):
    """Draw the fit so far, if there is one worth drawing."""
    view = frame.copy()
    try:
        calibration = run.session.calibration(strict=False)
    except BlockGridError:
        return view
    draw_color_grid(view, calibration, labels=True, shade=0.25)
    try:
        draw_workspace_corners(view, calibration.workspace_corners(run.grid))
    except (BlockGridError, ValueError):
        pass
    return view


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.count < MIN_OBSERVATIONS:
        raise SystemExit(f"--count must be at least {MIN_OBSERVATIONS}: four "
                         f"placements fit a homography exactly and prove nothing")

    if args.mock and args.mode is not None:
        # MockCamera renders whichever mode config/rig.json calls active, and
        # ConsolePipeline gives it no way to be told otherwise - so a dry run
        # of the other mode would place blocks the mock scene cannot draw.
        # tests/test_block_calibration.py covers both modes properly by
        # building the mock camera directly.
        active = active_grid_mode(load_rig_config(args.rig_config))
        if args.mode != active:
            raise SystemExit(
                f"--mock can only dry-run the mode config/rig.json calls "
                f"active ({active}); the mock camera has no way to be told "
                f"about {args.mode}. Set grid.active_mode, or run without "
                f"--mock against the rig.")

    settings_path = mock_settings(args.settings) if args.mock else args.settings
    pipeline = ConsolePipeline(
        camera_backend="mock" if args.mock else None,
        settings_path=settings_path, rig_config_path=args.rig_config,
        workspace_map_path=args.map, mode=args.mode)
    pipeline.start()
    grid = pipeline.grid
    print(f"calibrating the {grid.mode} grid "
          f"({grid.cols}x{grid.rows} cells, block "
          f"{grid.block_x_cm:g}x{grid.block_y_cm:g} cm)")

    rig = None
    try:
        rig = open_rig(args, grid, pipeline)

        def capture():
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                frame = pipeline.process_once()
                if frame is not None and not frame.stale:
                    return frame.view
                time.sleep(0.05)
            raise BlockCalibrationError(
                "no fresh camera frame in five seconds; the calibration cannot "
                "see where the blocks went")

        kwargs = {} if args.settle is None else {"settle": args.settle}
        run = BlockCalibrationRun(rig, capture, grid=grid,
                                  cells=parse_cells(args.cells),
                                  count=args.count, inset=args.inset,
                                  supply=args.supply, **kwargs)
        print(f"plan: {' '.join(f'[{c},{r}]' for c, r in run.session.planned)}")
        prompt("clear the build area and load the feeder at [0,0], "
               "then press Enter")

        run.start()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        while run.session.remaining:
            cell = run.session.remaining[0]
            print(f"  placing [{cell[0]},{cell[1]}] ...", end="", flush=True)
            try:
                outcome = run.step()
            except BlockCalibrationAborted as exc:
                print(f"\n\nABORTED: {exc}")
                return 2
            except BlockCalibrationError as exc:
                print(f"\n  ! {exc}")
                reply = prompt("  [r]etry this cell, [s]kip it, or [q]uit? ",
                               default="q")
                if reply.strip().lower().startswith("q"):
                    return 1
                if reply.strip().lower().startswith("s"):
                    run.session.planned = tuple(
                        item for item in run.session.planned if item != cell)
                continue
            print(f" ok, {outcome.residual_px:.2f} px"
                  if outcome.residual_px is not None else " ok")
            if args.trace:
                path = CAPTURE_DIR / (f"{stamp}_blockcal_"
                                      f"{cell[0]}-{cell[1]}.png")
                cv2.imwrite(str(path), annotate(capture(), run))
                print(f"        traced to {path}")

        status = run.status()
        print()
        print(status.describe())
        if not status.ready:
            print("\nnot saved. Fix what the line above says and run again.")
            return 1
        if not args.save:
            print("\nlooks good. Re-run with --save to write "
                  f"{args.map}")
            return 0

        frame = pipeline.process_once()
        workspace = run.workspace_map(frame.image_size, pipeline.projection)
        workspace.save(args.map)
        pipeline.set_workspace(workspace)
        print(f"\nsaved {args.map}")
        return 0
    except (BlockGridError, BlockCalibrationError) as exc:
        print(f"\n{exc}")
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted; nothing was written")
        return 1
    finally:
        if rig is not None:
            rig.close()
        pipeline.stop()


if __name__ == "__main__":
    raise SystemExit(main())
