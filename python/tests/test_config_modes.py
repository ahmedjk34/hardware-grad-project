#!/usr/bin/env python3
"""Step 1 of plans/dual-orientation-grid.md: the two-mode `grid` block.

    cd python
    ../.venv/bin/python tests/test_config_modes.py

Covers the step's acceptance criteria: both modes load, a legacy flat file
still loads as `vertical`, and an unknown mode name raises something a human
can act on rather than a KeyError.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rig.config import (  # noqa: E402
    GRID_MODES,
    UnknownGridMode,
    active_grid_mode,
    grid_geometry,
    grid_modes,
    load,
    migrate_grid,
)

PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print(f"{'ok  ' if condition else 'FAIL'}  {name:44} {detail}")


def raises(exc_type, call):
    try:
        call()
    except exc_type as exc:
        return str(exc)
    except Exception as exc:  # noqa: BLE001 - the wrong type is the failure
        return f"!! wrong exception type: {exc!r}"
    return "!! no exception"


config = load()

# ------------------------------------------------------------------
# The shipped file
# ------------------------------------------------------------------

modes = grid_modes(config)
check("rig.json defines both modes", set(modes) == set(GRID_MODES), str(sorted(modes)))
check("the build starts vertical (D2)", active_grid_mode(config) == "vertical",
      active_grid_mode(config))

vertical = grid_geometry(config, "vertical")
horizontal = grid_geometry(config, "horizontal")

# Counts, not highest indices: coordinate 0 is a real block, so vertical
# addresses 0..6 x 0..5 and horizontal 0..2 x 0..10. The firmware's S command
# speaks in highest indices; rig/link.py is the one place that converts.
check("vertical is 7 x 6 (D1)",
      (vertical["cols"], vertical["rows"]) == (7, 6))
check("horizontal is 3 x 10 (D1)",
      (horizontal["cols"], horizontal["rows"]) == (3, 10))

# D12: each mode states both block extents outright, and they are the swap of
# each other only as a matter of physical fact - no code performs that swap.
check("vertical block is 2.2 x 6.0 cm",
      (vertical["block_x_cm"], vertical["block_y_cm"]) == (2.2, 6.0))
check("horizontal block is 6.0 x 2.2 cm",
      (horizontal["block_x_cm"], horizontal["block_y_cm"]) == (6.0, 2.2))
# One gap, every axis, both modes. A vertical block reads 2.2 + 1.6 + 2.2 along
# its 6.0 cm length and consecutive blocks are also 1.6 apart, so the 2.2 cm
# sub-cells repeat at one unbroken 3.8 cm pitch. Measured off the printed sheet.
check("every axis of both modes uses the same 1.6 cm gap",
      (vertical["gap_x_cm"], vertical["gap_y_cm"]) == (1.6, 1.6)
      and (horizontal["gap_x_cm"], horizontal["gap_y_cm"]) == (1.6, 1.6))

# D14: vertical is anchored dead on the home corner. Horizontal carries the
# +1.9 cm pickup-cell registration on BOTH axes - the rotated 6.0 cm face
# overhangs the 2.2 cm vertical footprint by 6.0/2 - 2.2/2 = 1.9 cm per side.
# Horizontal must never simply inherit vertical's trims.
check("vertical seeds at trim 0.0 / 0.0, horizontal at +1.9 / +1.9 (D14)",
      (vertical["trim_x_cm"], vertical["trim_y_cm"]) == (0.0, 0.0)
      and (horizontal["trim_x_cm"], horizontal["trim_y_cm"]) == (1.9, 1.9))

check("no mode is asked to share the other's numbers",
      all(set(("cols", "rows", "block_x_cm", "block_y_cm", "gap_x_cm", "gap_y_cm",
               "trim_x_cm", "trim_y_cm", "error_offset_x_cm", "error_offset_y_cm"))
          <= set(mode) for mode in modes.values()))

# `grid_geometry` with no mode follows active_mode.
check("default mode is the active one",
      grid_geometry(config) == grid_geometry(config, active_grid_mode(config)))

# ------------------------------------------------------------------
# The rest of rig.json is NOT per mode
# ------------------------------------------------------------------

check("travel is mode-independent",
      (config["workspace"]["width_cm"], config["workspace"]["height_cm"])
      == (22.8, 38.0))
check("tool_offsets keeps neutral/cw/ccw (D15)",
      set(config["tool_offsets"]) == {"neutral", "cw", "ccw"})
# NEUTRAL is genuinely zero: the claw closes on the middle of the block and a
# vertical build never turns, so holder and block centre coincide.
#
# CW is NOT zero any more. The claw's grip point sits about (-0.3, +0.6) cm off
# the aux stepper's rotation axis, so the 90-degree pickup-rotate swings the
# block centre round that axis by X +0.9 / Y -0.3 cm. That swing was previously
# absorbed by grid.modes.horizontal.error_offset_* (+0.5, +0.3), which is a
# rotation-blind knob and had X's sign backwards - blocks landed 1.4 cm too far
# from the X home switch. It is claw geometry, so per D15 it belongs here.
#
# CCW stays zero: no grid or build route requests it, so it is unmeasured. The
# recorded (3.75, 1.40) CCW trial predates the centre-anchored lattice and must
# not be copied in.
check("neutral and ccw tool offsets stay at zero",
      all((config["tool_offsets"][k]["x_cm"],
           config["tool_offsets"][k]["y_cm"]) == (0.0, 0.0)
          for k in ("neutral", "ccw")))
check("cw carries the measured pickup-rotate swing (D15, not an error offset)",
      (config["tool_offsets"]["cw"]["x_cm"],
       config["tool_offsets"]["cw"]["y_cm"]) == (0.9, -0.3))
check("horizontal no longer hides the rotation swing in its error offset",
      (config["grid"]["modes"]["horizontal"]["error_offset_x_cm"],
       config["grid"]["modes"]["horizontal"]["error_offset_y_cm"]) == (0.0, 0.0))

# ------------------------------------------------------------------
# Legacy migration
# ------------------------------------------------------------------

LEGACY = {
    "cols": 9, "rows": 5,
    "block_width_cm": 2.2, "block_length_cm": 7.5,
    "gap_x_cm": 0.5, "gap_y_cm": 0.5,
    "trim_x_cm": 1.1, "trim_y_cm": 3.75,
    "error_offset_x_cm": 0.0, "error_offset_y_cm": 0.0,
}
legacy_cfg = {"grid": dict(LEGACY)}

check("a legacy flat grid migrates to modes.vertical",
      set(grid_modes(legacy_cfg)) == {"vertical"})
check("legacy migration renames the block extents",
      grid_geometry(legacy_cfg, "vertical")["block_x_cm"] == 2.2
      and grid_geometry(legacy_cfg, "vertical")["block_y_cm"] == 7.5)
check("legacy migration keeps every other field",
      grid_geometry(legacy_cfg)["trim_y_cm"] == 3.75
      and grid_geometry(legacy_cfg)["cols"] == 9)
check("legacy files are active in vertical", active_grid_mode(legacy_cfg) == "vertical")
check("migrate_grid does not mutate its input", legacy_cfg["grid"] == LEGACY)

# The whole point of the migration is that an old checkout still runs. Asking a
# legacy file for horizontal must say WHY it is not there.
message = raises(UnknownGridMode, lambda: grid_geometry(legacy_cfg, "horizontal"))
check("legacy file explains the missing horizontal mode",
      "predates" in message and "dual-orientation" in message, message)

# ------------------------------------------------------------------
# Readable errors, not KeyErrors
# ------------------------------------------------------------------

message = raises(UnknownGridMode, lambda: grid_geometry(config, "diagonal"))
check("unknown mode names itself and the alternatives",
      "diagonal" in message and "horizontal" in message and "vertical" in message,
      message)

message = raises(UnknownGridMode,
                 lambda: active_grid_mode({"grid": {"active_mode": "sideways",
                                                    "modes": {"vertical": vertical}}}))
check("a bad active_mode is caught too", "sideways" in message, message)

message = raises(ValueError, lambda: grid_geometry(
    {"grid": {"active_mode": "vertical",
              "modes": {"vertical": {"cols": 9, "rows": 5}}}}))
check("an incomplete mode lists what it is missing",
      "block_x_cm" in message and "trim_y_cm" in message, message)

message = raises(ValueError, lambda: migrate_grid({"modes": {}}))
check("an empty modes table is refused", "non-empty" in message, message)

# ------------------------------------------------------------------
# The file on disk really is loadable from a path, not just the cache
# ------------------------------------------------------------------

with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "rig.json"
    path.write_text(json.dumps({"grid": dict(LEGACY)}))
    check("a legacy-shaped file on disk loads",
          load(path, reload=True)["grid"]["block_width_cm"] == 2.2)
load(reload=True)  # put the module cache back to the real config

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("failed: " + ", ".join(FAILED))
sys.exit(1 if FAILED else 0)
