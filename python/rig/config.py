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
The `workspace` X/Y holder displacement, block footprint, 0.5 cm gaps and
signed trims are also consumed by the Pi's camera mapping. `tool_offsets` are the calibrated vector from the
gantry holder reference to the actual block-placement point. They are consumed
by the firmware only, but retained here as the editable counterpart to its
compiled constants. Their compiled firmware partners are listed in AGENTS.md
and must be changed with this file.

`observed_build_area` records the separately measured 24.3 x 43 cm physical
build displacement. It is deliberately not a control input while the extra
3 cm Y arm-holder relationship is being ignored.
"""

from __future__ import annotations

import json
from pathlib import Path

# python/rig/config.py -> python/rig -> python -> repo root
CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "rig.json"

_cache: dict | None = None


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
