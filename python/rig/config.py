#!/usr/bin/env python3
"""The one hand-edited config file, loaded from anywhere.

Why this exists
---------------
The same numbers were living in four places: module constants in the viewers,
argparse defaults, config/lens_profile.json, and C++ constants in the firmware.
This collapses the Python half onto one file, config/rig.json.

    from rig.config import load
    cfg = load()
    port = cfg["serial"]["port"]

What does NOT belong here
-------------------------
config/lens_profile.json stays separate. The viewer WRITES that file with its
'save' command, so it is a generated artefact — a calibration run must never be
able to silently rewrite your serial port. rig.json is intent; lens_profile.json
is measurement.

The firmware also keeps its own copy of the machine numbers (step envelope, Z
levels, pin assignments) and stays the authority on them. The grid count is
Python-side intent and is pushed with 'S <cols> <rows>' on every connection.
The optional per-mode `shift_x_cm` / `shift_y_cm` (the firmware's shiftX /
shiftY, default 0.0) are Python-side intent too: `rig.link` pushes them after
the mode latch and before 'S' on every connection, since a port-open reset
clears them. They translate the whole placement lattice, [0,0] reference
included, but never the pick-up.
The `workspace` X/Y holder displacement, block footprint, 0.5 cm gaps and
signed trims are also consumed by the Pi's camera mapping. Python serial
clients prefer `/dev/ttyACM0` and fall back to `/dev/ttyACM1` if needed.
`tool_offsets` are the calibrated vector from the
gantry holder reference to the actual block-placement point. They are consumed
by the firmware only, but retained here as the editable counterpart to its
compiled constants. Their compiled firmware partners are listed in AGENTS.md
and must be changed with this file.

`observed_build_area` records the separately measured 24.3 x 43 cm physical
build displacement. It is deliberately not a control input while the extra
3 cm Y arm-holder relationship is being ignored.

Two grids, not one
------------------
`grid` holds `active_mode` plus a `modes` table with one self-contained entry
per block orientation: `vertical` (blocks standing, 9 x 5) and `horizontal`
(blocks lying, 3 x 15). Each entry declares BOTH `block_x_cm` and `block_y_cm`
outright. Nothing anywhere swaps a width for a length — a swap would have to be
performed identically in the firmware, in `MachineGrid` and in the camera
overlay, which is three chances to get an axis backwards. See
docs/dual-orientation-grid.md D12.

`workspace`, `observed_build_area`, `tool_offsets`, `serial`, `board` and
`frame` are NOT per mode: travel and claw geometry are physical facts, and a
block lying down does not move a limit switch.

Use :func:`grid_geometry` rather than reaching into `cfg["grid"]`. It also
migrates the pre-dual-orientation flat `grid` block (which had
`block_width_cm` / `block_length_cm` and no modes) into `modes.vertical`, so an
old checkout's config still loads.

`max_edge_overhang_*_cm` is how far past the holder-travel limit that mode
permits a placed block's own EDGE to sit. It is not a trim and it moves
nothing: it is the budget the geometry validator checks the far and near block
edges against, on both machines. Vertical allows half a block on each axis
(1.1 / 3.75 cm) because its last centre sits exactly on the travel limit and
the held block unavoidably overhangs — that is the shipped, physically
verified 9 x 5 grid. Horizontal allows zero, because its 15 rows are flush
with both walls and any overhang there means the trims are wrong. See
docs/dual-orientation-grid.md D20 and R2. A mode that omits the pair gets
half a block, which makes the edge check exactly as permissive as the
centre-only check that predates it — so a legacy config does not start failing.
"""

from __future__ import annotations

import json
from pathlib import Path

# python/rig/config.py -> python/rig -> python -> repo root
CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "rig.json"

_cache: dict | None = None

# The two block orientations. Vertical is the compiled firmware default and the
# state every USB open resets the board to; see docs/dual-orientation-grid.md D2.
GRID_MODES = ("vertical", "horizontal")
DEFAULT_GRID_MODE = "vertical"

# What the flat pre-dual-orientation `grid` block called the two block extents.
# It only ever described the vertical layout, so it migrates into that mode.
_LEGACY_BLOCK_KEYS = {"block_width_cm": "block_x_cm", "block_length_cm": "block_y_cm"}

# Every field a mode entry must declare for itself. Nothing is inherited from
# another mode or from a shared default: a missing key is a config bug, not a
# silent fallback to the other orientation's number.
GRID_MODE_FIELDS = (
    "cols", "rows",
    "block_x_cm", "block_y_cm",
    "gap_x_cm", "gap_y_cm",
    "trim_x_cm", "trim_y_cm",
)

# Deliberately NOT in GRID_MODE_FIELDS: a config written before D20 has no such
# key, and half a block is precisely the overhang a full-travel grid produces,
# so defaulting to it changes no existing behaviour.
def max_edge_overhang_cm(geometry: dict, axis: str) -> float:
    """The mode's permitted block-edge overhang past travel, in cm."""
    key = f"max_edge_overhang_{axis}_cm"
    if key in geometry:
        return float(geometry[key])
    return float(geometry[f"block_{axis}_cm"]) / 2.0


class UnknownGridMode(ValueError):
    """A grid mode was asked for that config/rig.json does not define.

    A distinct type because the caller usually can say something useful — the
    calibration UIs offer the modes that do exist rather than tracebacking.
    """


def migrate_grid(grid: dict) -> dict:
    """Return the `grid` block in the two-mode shape, whatever shape it is in.

    A file already carrying `modes` is passed through with only its
    `active_mode` defaulted. A legacy flat block becomes `modes.vertical`,
    because that is the only layout that existed before this table did.
    """
    if "modes" in grid:
        modes = grid["modes"]
        if not isinstance(modes, dict) or not modes:
            raise ValueError("config/rig.json: grid.modes must be a non-empty object")
        return {"active_mode": grid.get("active_mode", DEFAULT_GRID_MODE),
                "modes": modes}

    vertical = {key: value for key, value in grid.items()
                if key not in _LEGACY_BLOCK_KEYS}
    for legacy, current in _LEGACY_BLOCK_KEYS.items():
        if legacy in grid:
            vertical[current] = grid[legacy]
    return {"active_mode": DEFAULT_GRID_MODE, "modes": {DEFAULT_GRID_MODE: vertical}}


def grid_modes(cfg: dict | None = None) -> dict:
    """The `{name: geometry}` table, migrated if the file predates it."""
    cfg = cfg if cfg is not None else load()
    return migrate_grid(cfg["grid"])["modes"]


def active_grid_mode(cfg: dict | None = None) -> str:
    """Which mode the rig is meant to be in. Validated, so callers can trust it."""
    cfg = cfg if cfg is not None else load()
    migrated = migrate_grid(cfg["grid"])
    mode = migrated["active_mode"]
    if mode not in migrated["modes"]:
        raise UnknownGridMode(
            f"config/rig.json sets grid.active_mode to {mode!r}, which is not "
            f"one of the defined modes: {', '.join(sorted(migrated['modes']))}"
        )
    return mode


def grid_geometry(cfg: dict | None = None, mode: str | None = None) -> dict:
    """One mode's self-contained geometry. `mode=None` means the active one.

    Raises :class:`UnknownGridMode` — never a bare KeyError — because the mode
    name usually arrives from a UI selection or a saved calibration file, and
    "horizontal is not in this config" is a thing an operator can act on.
    """
    cfg = cfg if cfg is not None else load()
    migrated = migrate_grid(cfg["grid"])
    modes = migrated["modes"]
    name = active_grid_mode(cfg) if mode is None else str(mode)

    if name not in modes:
        available = ", ".join(sorted(modes))
        hint = ""
        if name in GRID_MODES and set(modes) == {DEFAULT_GRID_MODE}:
            # The single-mode shape is exactly what migrate_grid() produces from
            # a legacy flat block, so say that rather than "typo?".
            hint = (" This config only defines the vertical grid — it predates "
                    "docs/dual-orientation-grid.md and needs the modes table "
                    "from that plan's section 5.")
        raise UnknownGridMode(
            f"unknown grid mode {name!r}; config/rig.json defines: {available}.{hint}"
        )

    geometry = modes[name]
    missing = [field for field in GRID_MODE_FIELDS if field not in geometry]
    if missing:
        raise ValueError(
            f"config/rig.json: grid.modes.{name} is missing {', '.join(missing)}. "
            "Every mode declares its own geometry outright; nothing is inherited "
            "from the other orientation."
        )
    return geometry


def serial_port_candidates(preferred: str) -> tuple[str, ...]:
    """Return the preferred Mega port, with ACM0/ACM1 fallback support."""
    if preferred == "/dev/ttyACM0":
        return ("/dev/ttyACM0", "/dev/ttyACM1")
    if preferred == "/dev/ttyACM1":
        return ("/dev/ttyACM0", "/dev/ttyACM1")
    return (preferred,)


def load(path: Path = CONFIG_PATH, reload: bool = False) -> dict:
    """Read config/rig.json. Cached, because every caller wants the same one.

    Absolute path off __file__ rather than the cwd: the viewers are run from
    python/ so that `import vision` resolves, and a relative path would break
    the moment someone runs one from the repo root instead.
    """
    global _cache
    if _cache is not None and not reload:
        return _cache

    try:
        text = path.read_text()
    except FileNotFoundError:
        raise SystemExit(
            f"Config not found: {path}\n"
            "This file is committed to the repo — if it is missing, you are "
            "probably running from a different checkout."
        )

    try:
        _cache = json.loads(text)
    except json.JSONDecodeError as exc:
        # Say which line, because a stray trailing comma in JSON is otherwise a
        # miserable thing to find.
        raise SystemExit(f"{path} is not valid JSON: {exc}")

    return _cache
