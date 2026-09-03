#!/usr/bin/env python3
"""Live camera + fisheye tuning bench, with a Tk control centre and JSON save.

This is undistorted_viewer.py opened all the way up. Everything that decides
what the picture looks like — the lens correction, the sensor's own controls,
zoom, crop, flip — is adjustable while you watch, from the terminal or from the
window, and `save` writes the whole state to one JSON file.

    python camera_studio.py
    python camera_studio.py --hq                    # sharpest: full sensor in
    python camera_studio.py --backend v4l2 --device /dev/video0
    python camera_studio.py --settings ../config/my_camera.json --autosave
    python camera_studio.py --fresh                 # ignore the settings file

Where the settings come from
----------------------------
It reads config/camera_settings.json at startup and `save` writes it back, so
the tool picks up where it left off and opens exactly like camera_feed.py from
that file. `--fresh` and `reset` deliberately return to the uncropped built-in
defaults shared with undistorted_viewer.py.

Four layers, each overriding the one before:

  1. the built-in defaults (undistorted_viewer.py's);
  2. config/lens_profile.json, the lens parameters the OTHER tools read;
  3. config/camera_settings.json, or whatever --settings names;
  4. the command-line flags.

Two windows, one process
------------------------
Tk is the control centre: real text entries, read-only dropdowns, buttons,
status labels and an arbitrary command entry. OpenCV presents the clean camera
image directly, without a per-frame Tk PhotoImage conversion. Click an entry,
type a value and press Enter; Up/Down step it. Choosing a dropdown applies
immediately. Drag a rectangle on the OpenCV preview to crop.

`--window WxH` and `--display-scale` affect display only. The processing size
is derived from the saved lens/ROI exactly as camera_feed.py derives it, so
desktop geometry cannot silently turn the canonical 384x440 feed into a much
larger render.

It opens rendering exactly the same corrected/framed image as camera_feed.py
from the selected settings file. A smaller desktop may downscale that image for
display; the underlying render and remap remain identical.

Zoom and crop are not what they usually are
-------------------------------------------
They are folded into the correction's lookup table rather than applied to the
finished image, so a 2x zoom re-renders that part of the field straight from the
sensor frame instead of enlarging pixels that were already interpolated once.
The SAMPLE line reports the real cost: at zoom 2 you should see `centre` roughly
halve, and if it drops well under 1.00 the answer is `--hq`, not a sharper
interpolation kernel.

Four ways to drive it
---------------------
Tk sends keyboard input to the focused widget. Single-key shortcuts belong to
the window, but are suspended while an entry or dropdown has focus so typing
`158` cannot also change k1, centre X and centre Y. Every input path echoes its
result into the log:

  1. TYPE IN THE TERMINAL. Commands typed into the shell that launched this tool
     are read from stdin and applied. This needs no window focus at all and is
     the one that always works. Try `help`.
  2. TYPE IN THE WINDOW. Use the command entry at the bottom and press Enter.
  3. CLICK AND TYPE. Continuous fields are entries: Enter commits, Up/Down
     steps, and Esc or leaving the field reverts an unfinished edit. Fixed-set
     fields are read-only dropdowns and apply immediately.
  4. CLICK AND DRAG. Use the buttons, or drag on the image to crop a rectangle.

Plus the single-key shortcuts below, which work whenever no field has focus.

Keys
----
  :  focus command box   ?  help window     q / Esc  quit
  u  view: corrected / raw / both           n  correction on / off
  [ ]  lens FOV -/+ 2 deg                   m  cycle projection model
  - =  output FOV -/+ 5 deg                 i  cycle interpolation kernel
  , .  output scale -/+ 0.1                 g  grid overlay (a straightness ruler)
  1 2  k1 -/+ 0.01                          3 4  k2 -/+ 0.01
  5 6  optical centre X -/+ 2 px            7 8  optical centre Y -/+ 2 px
  z x  zoom out / in                        arrows  pan
  0  reset zoom and pan                     c  crop to the current zoom rect
  Backspace  undo the last crop             f  refit (render the crop 1:1)
  v  fit / native sizing                    r  reset everything
  s  save the JSON                          p  snapshot PNGs

Colour commands: `colour` on/off, `wb`, `colourcal`, `tunetoraw`, `colourmode`,
`rgain`, `ggain`, `bgain`, `roff`, `goff`, `boff`, `gamma`, `csat`, `nomix`,
`colourinfo`, `colourreset`. See "Fixing the colour" below.

Reading the machine grid off the board
--------------------------------------
`blockcal` (the BLOCK CALIBRATION button) finds the wooden blocks currently on
the board, works out the lattice they sit on, and draws the WHOLE machine grid
over the corrected view: the cells a block is actually on are tinted, and every
cell the block supply did not reach is outlined from the same fitted lattice.
`vision/block_grid.py` does the work and AGENTS.md 3d-bis explains the method
and its limits.

Three things worth knowing before trusting what it draws:

  * The blocks alone cannot say where cell [0,0] is - a regular lattice looks
    identical shifted by one cell - so the anchor corner is an assertion, not a
    measurement. It defaults to `bottom-left`; `blockcal top-right` and friends
    pick another. A wrong anchor renumbers the whole board and nothing here
    can tell.
  * Wooden things that are not blocks (the holder's offcuts beside [0,0]) are
    discarded for not landing on the lattice, not for looking wrong.
  * `blockcal` writes NOTHING. The window's SAVE JSON button and its autosave
    write `camera_settings.json`, which is a different file for a different
    purpose - if you pressed those, no calibration was saved. `blockcalsave`
    is the one that writes `config/workspace_map.json`, and it says so.
  * A workspace map is stored PER GRID MODE, and `blockcal` uses whichever
    `config/rig.json` calls active. Saving the vertical grid leaves the
    horizontal entry untouched and vice versa.
  * An app that is already running has read the map once, at startup. Saving a
    new one does not reach it: press `L` in `rig_build_v1`, or POST
    `/api/calibration/reload` in the web console, or restart.
  * Nothing else is written. `blockcalsave` writes `config/workspace_map.json`;
    `blockcaloff` clears the overlay. Calibrating is a deliberate act, and this
    window is the camera-settings editor rather than the runtime pipeline.
  * The saved map is stamped with THIS window's lens, flip/rotate, correction
    state and framing. Those are editor state until SAVE JSON writes them, and
    the app renders from the FILE - so `blockcalsave` refuses outright when the
    two disagree, naming what drifted. Press SAVE JSON first. The file it then
    writes is byte-identical to what the printed-sheet route produces.
  * `blockcalsave` reports how far the saved map's cells land from the measured
    ones. `workspace_map.json` carries four envelope corners, not a per-cell
    table, so a consumer spaces cells evenly between them and any curvature the
    fit found is flattened. The corners stay exact and the error peaks in the
    middle of the grid.

Prefer `camera/block_grid_calibrate.py` when the rig is available: there the
machine places each block on a cell it was TOLD, so the labelling is recorded
rather than inferred and the anchor problem does not arise.

While an entry or dropdown has focus it takes the keyboard instead. That focus
guard is load-bearing: without it, digits typed into a field would also fire the
numeric lens shortcuts.

Commands
--------
`help` lists them all with their ranges. The numeric ones take an absolute value
or a signed step, so `fov 158` and `fov +2` both work; the choice ones take any
unambiguous prefix, so `interp lan` is enough; and every sensor control also
takes `auto` to hand it back to the camera's own loop. Every field, dropdown
entry and button is one of these commands, so the ways in cannot drift apart.

Fixing the colour
-----------------
The rig's camera does not agree with anyone's eyes. Its cast has been strong
enough to turn the printed sheet's green ink cyan, which makes half of that
sheet invisible to `vision/color_grid.py` and degrades `block_detector.py` too.
The COLOUR section fixes it once, here, and every tool that reads
`camera_settings.json` inherits the fix.

Two ways, both needing the printed calibration sheet in shot:

  1. `wb` — one press. Neutralises the cast against the sheet's own white
     paper. No reference photograph, nothing to line up. Start here.
  2. `colourcal <image>` — match this camera to a photograph of the SAME sheet
     taken with something you trust, typically a phone. Both images are reduced
     to three measured colours (green ink, magenta ink, white paper) and the
     transform between them is solved. The two shots need not be framed alike.
  3. `tunetoraw` — apply the profile that `vision/tune_color_to_raw_phone.py`
     already solved offline from the pair in `captures/color_correction/`. That
     script matches the whole colour DISTRIBUTION of a live view to a phone
     photo (gains, offsets, mixing, then gamma and saturation) and validates the
     result; this button only loads and applies its `.json`, showing the
     similarity score it reached. It does NOT re-tune.

`colourmode` picks what the fit solves. `gain` is the default and is almost
always the answer:

  gain    per-channel gain through the origin. Cannot crush blacks.
  affine  gain plus offset. Also corrects brightness, but the sheet is all
          mid-to-bright so the line down to black is extrapolated.
  matrix  full linear 3x3. Nine numbers from three colours: exactly determined,
          so it fits them perfectly whether or not it is right anywhere else.

**Read the warnings, not the residual.** On real rig data the residual ranks
these backwards — `matrix` scored a perfect 0.00 while turning the wall behind
the rig bright pink, and `gain` scored the worst 19.7 and was the only one that
looked right. `colourinfo` prints the matrix and everything implausible about
it; `nomix` walks a matrix fit back to its white balance.

Every fit also reports the `redgain`/`bluegain` that would do the same job in
the SENSOR section. Prefer those when the backend has them: they act before the
camera has thrown away headroom in the channel it under-exposed. The software
correction is the fallback, and what the V4L2 path usually has to use.

The COLOUR fields are the full manual control over whatever a fit produced:
per-channel gain and offset, gamma, and a software saturation that is separate
from the sensor's own.

Fixing the fisheye, in order
---------------------------
Point the camera at something with a long straight edge, put it near the frame
EDGE (the centre is nearly straight whatever you do), and turn on the grid with
'g' to have something to judge against.

  1. `fov` first. It scales every radius at once and is by far the biggest
     effect. Edges still bowing OUTWARD -> press ']'. Bowing INWARD, i.e.
     over-corrected -> press '['. Nothing else is worth touching until this is
     as close as it gets.
  2. `model` second, with 'm'. Four ideal curves; one of them will sit closer
     than the others. Cheap to try, so try all four.
  3. `k1` then `k2` — the broad residual. If the edge is straight in the middle
     but bends near the edge, these fix the shape `fov` cannot. Use `k3` and
     `k4` only for distortion confined to the extreme edge/corners; fitting a
     high-order coefficient too early makes a wavy correction that only looks
     right on one line.
  4. `cx` / `cy` next, and only if the bowing is ASYMMETRIC — straight along the
     left edge but curved along the right. That means the sensor is not centred
     behind the lens, and no amount of k1 will fix it.
  5. `fx scale` / `fy scale` only if horizontal and vertical lines need different
     correction strengths. Keep one at 1.000 while adjusting the other.
  6. `p1` / `p2` last for diagonal, one-sided decentring residuals. `skew` is a
     final shear correction and should almost always remain zero. Use TUNE VIEW
     to compare raw/corrected at full frame, and TUNE RESET to zero only these
     manual trims without losing sensor, colour, crop or output settings.

None of this is a calibration. It is straight to the eye, not metric, and the
panel says ESTIMATED in amber to keep that in view. A real ChArUco calibration
writes camera_matrix / dist_coeffs into the profile and the tools switch to it
automatically.
"""

import argparse
import json
import math
import sys
import threading
import time
import tkinter as tk
from dataclasses import asdict, dataclass
from pathlib import Path
from tkinter import ttk

import cv2
import numpy as np

# This tool lives one folder down, so python/ is not on the import path when it
# is run directly. Put it there before the shared libraries below are imported —
# without this, `python camera/camera_studio.py` dies on `import vision`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vision.camera_source import (
    AUTO,
    DEFAULT_SIZE,
    FULL_RES_SIZE,
    LatestFramePump,
    SENSOR_CONTROLS,
    build_controls,
    describe_sensor_modes,
    open_camera,
)
from vision.color_correction import (
    CHANNELS,
    DEFAULT_FIT_MODE as DEFAULT_COLOUR_FIT,
    FIT_MODES as COLOUR_FIT_MODES,
    ColorCorrection,
    ColorCorrectionError,
    equivalent_sensor_gains,
    neutral_matrix,
    pair_samples,
    solve_matrix,
)
from rig.config import load as load_rig_config
from rig.grid import MachineGrid
from rig.workspace import WORKSPACE_MAP_PATH
from camera.camera_feed import framing_roi, load_settings, profile_from_settings
from camera.gridded_camera_feed import projection_metadata
from vision.block_grid import (
    DEFAULT_LATTICE_ANCHOR,
    LATTICE_ANCHORS,
    BlockGridError,
    block_workspace_map,
    detect_block_lattice,
    workspace_map_error,
)
from vision.color_grid import ColorGridError, sample_ink_colors
from vision.color_grid_overlay import draw_color_grid
from vision.latest_worker import LatestValueWorker
from vision.performance import RateMeter
from vision.commands import (
    CommandError,
    CommandSet,
    MessageLog,
    need_args,
    parse_choice,
    parse_number,
)
from vision.fisheye import (
    DEFAULT_INTERPOLATION,
    INTERPOLATIONS,
    MODEL_NAMES,
    PROFILE_PATH,
    LensProfile,
    build_maps,
    sampling_stats,
    undistort,
)
from vision.overlays import (
    FONT,
    LABEL_COLOR,
    draw_grid,
)
from camera.snapshot_worker import SnapshotWorker

MANUAL_TUNING_DEFAULTS = {
    "k1": 0.0, "k2": 0.0, "k3": 0.0, "k4": 0.0,
    "centre_dx": 0.0, "centre_dy": 0.0,
    "focal_x_scale": 1.0, "focal_y_scale": 1.0,
    "skew": 0.0, "p1": 0.0, "p2": 0.0,
}

CAPTURE_DIR = Path(__file__).resolve().parents[1] / "captures"
SETTINGS_PATH = Path(__file__).resolve().parents[1] / "config" / "camera_settings.json"

# The tuned colour profile that `vision/tune_color_to_raw_phone.py` writes and
# the TUNE TO RAW PHONE IMAGE button applies. Same `colour` block as the
# settings file; carries a similarity score alongside it. The button loads this
# and applies it — it never runs the tuning.
RAW_PHONE_PROFILE_PATH = SETTINGS_PATH.parent / "color_profile_raw_phone.json"

INTERP_NAMES = list(INTERPOLATIONS)
VIEWS = ("corrected", "raw", "both")
FIT_MODES = ("fit", "native")     # crop sizing; the COLOUR section's fit modes
                                  # are COLOUR_FIT_MODES, imported above
FLIPS = ("none", "h", "v", "both")
ROTATIONS = (0, 90, 180, 270)

# Where `colourcal` looks for a reference photograph when given no path. The
# same printed sheet the grid calibration uses, shot with something trusted.
REFERENCE_DIR = CAPTURE_DIR / "grid_training"

LOG_LINES = 4

# Smallest drag that counts as a crop rather than a click, in image pixels. A
# click is how you dismiss a half-started drag, so it must not crop to a speck.
MIN_CROP_PX = 12


def full_output_size(profile, capture_size):
    """(w, h) the corrected image would be with no crop and no zoom.

    The crop rectangle and the pan centre are normalised against THIS, not
    against whatever is currently on screen, so that zooming in and back out
    lands exactly where it started.
    """
    w, h = capture_size
    return (max(2, int(round(w * profile.output_scale))),
            max(2, int(round(h * profile.output_scale))))


class Studio:
    """Every mutable setting, in one place.

    Commands, keys, buttons and panel fields all funnel through the same
    setters, so each parameter has exactly one definition and one place that
    decides the remap tables have gone stale.
    """

    def __init__(self, args, profile):
        self.args = args
        self.profile = profile
        # These are the BUILT-IN defaults, chosen to match undistorted_viewer.py
        # exactly. The settings file is loaded over the top of them at startup,
        # and the CLI flags over the top of that — see apply_overrides() for the
        # whole chain. Reading argparse defaults straight into here is what would
        # break that ordering, because argparse cannot tell a flag that was not
        # given from one that was given its default value.
        self.interp = DEFAULT_INTERPOLATION
        self.mip = True
        self.correct = True

        # Sensor controls start at "auto" across the board: the camera's own
        # loops are a better starting point than any number written here, and
        # "auto" is a value the JSON can honestly record.
        self.sensor = {name: AUTO for name in SENSOR_CONTROLS}
        self.sensor_status = "not applied yet"

        # Crops compose: each entry is a rectangle in the coordinates of the
        # crop before it. Keeping the stack rather than one flattened rectangle
        # is what makes 'uncrop' an undo instead of a reset.
        self.crops = []
        self.zoom = 1.0
        self.pan = (0.5, 0.5)          # zoom centre, normalised to the full output
        self.fit_mode = "fit"
        self.view_size = None          # resolved once the camera size is known
        self.viewport = None           # canonical corrected size; not a UI size
        self.preview_size = None       # optional display-only --window box

        self.flip = "none"
        self.rotate = 0
        self.swap_rb = False

        # Software colour correction. Starts as a disabled identity: a fresh
        # studio must render exactly what camera_feed.py renders, and that means
        # touching nothing until someone asks for it. See the COLOUR section.
        self.colour = ColorCorrection()
        self.colour_mode = DEFAULT_COLOUR_FIT
        self.colour_status = "not calibrated"
        # Set only by the TUNE TO RAW PHONE IMAGE profile, which carries the
        # score its offline tuning reached. None for every other colour source.
        self.colour_similarity = None
        self.last_capture = None       # newest frame BEFORE colour correction

        self.view = "corrected"
        self.show_grid = False
        # The last placed-block calibration, or None. Held here rather than
        # written straight out: the Studio edits camera settings, and turning a
        # workspace map into a saved file is a separate, deliberate act.
        self.block_lattice = None
        self.block_lattice_note = ""
        self.block_anchor = DEFAULT_LATTICE_ANCHOR
        self.show_keys = False
        self.autosave = bool(args.autosave)
        self.settings_path = args.settings

        self.capture_size = None       # filled in by main() once the camera opens
        self.camera_name = ""
        self.maps = None
        self.last_raw = None           # kept so 'snap' writes clean images,
        self.last_corrected = None     # i.e. without the grid drawn on them
        self.snapshot_submitter = None

        self.drag = None               # (start, current) in image coords, mid-crop
        self.pending = []              # command lines queued by the stdin thread

        self.dirty = True              # rebuild the remap tables before next frame
        self.sensor_dirty = True       # push sensor controls before next frame
        self.running = True
        self.log = MessageLog()
        self.commands = self._build_commands()

    # --- lens parameters ---------------------------------------------------
    # Each setter reports what changed, in the words the log and the panel show.
    # Returning the message rather than printing it is what lets one function
    # serve a keypress, a typed command, a button and a panel field.

    def _lens(self, attr, value, label, fmt="{:.0f}", unit=""):
        old = getattr(self.profile, attr)
        setattr(self.profile, attr, value)
        self.profile.clamp()
        new = getattr(self.profile, attr)
        self.dirty = True
        clipped = " (clamped)" if abs(new - value) > 1e-6 else ""
        return (f"{label} {fmt.format(old)} -> {fmt.format(new)}{unit}{clipped}")

    def set_lens_fov(self, v):
        return self._lens("lens_fov_deg", v, "lens FOV", unit=" deg")

    def set_output_fov(self, v):
        msg = self._lens("output_fov_deg", v, "output FOV", unit=" deg")
        if self.profile.output_fov_deg < v - 1e-6:
            # Silently clamping here is how you end up believing you rendered a
            # 170-degree view that the lens never saw.
            msg += f" — cannot exceed the {self.profile.lens_fov_deg:.0f} deg lens"
        return msg

    def set_output_scale(self, v):
        return self._lens("output_scale", v, "output scale", fmt="{:.2f}")

    def set_k1(self, v):
        return self._lens("k1", v, "k1 radial trim", fmt="{:+.3f}")

    def set_k2(self, v):
        return self._lens("k2", v, "k2 radial trim", fmt="{:+.3f}")

    def set_k3(self, v):
        return self._lens("k3", v, "k3 radial trim", fmt="{:+.3f}")

    def set_k4(self, v):
        return self._lens("k4", v, "k4 radial trim", fmt="{:+.3f}")

    def set_centre_dx(self, v):
        return self._lens("centre_dx", v, "optical centre X", fmt="{:+.1f}", unit=" px")

    def set_centre_dy(self, v):
        return self._lens("centre_dy", v, "optical centre Y", fmt="{:+.1f}", unit=" px")

    def set_focal_x_scale(self, v):
        return self._lens("focal_x_scale", v, "source focal X scale", fmt="{:.3f}")

    def set_focal_y_scale(self, v):
        return self._lens("focal_y_scale", v, "source focal Y scale", fmt="{:.3f}")

    def set_skew(self, v):
        return self._lens("skew", v, "source skew", fmt="{:+.4f}")

    def set_p1(self, v):
        return self._lens("p1", v, "p1 tangential trim", fmt="{:+.4f}")

    def set_p2(self, v):
        return self._lens("p2", v, "p2 tangential trim", fmt="{:+.4f}")

    def set_model(self, name):
        self.profile.model = name
        self.dirty = True
        return f"projection model {name}"

    def set_fov_reference(self, name):
        self.profile.fov_reference = name
        self.dirty = True
        return f"lens FOV is now read as the {name} FOV"

    def set_interp(self, name):
        self.interp = name
        self.dirty = True
        return f"interpolation {name}"

    # --- zoom and crop -----------------------------------------------------

    def crop_rect(self):
        """Compose the crop stack into one rectangle of the full output.

        Each entry is relative to the one before it, so cropping twice zooms
        into a piece of a piece — and popping one restores exactly the previous
        framing rather than jumping back to the whole frame.
        """
        x0, y0, x1, y1 = 0.0, 0.0, 1.0, 1.0
        for a, b, c, d in self.crops:
            w, h = x1 - x0, y1 - y0
            x0, y0, x1, y1 = x0 + a * w, y0 + b * h, x0 + c * w, y0 + d * h
        return x0, y0, x1, y1

    def roi(self):
        """The rectangle actually rendered: the crop, narrowed by the zoom.

        Zoom is kept separate from the crop stack on purpose. A crop is a
        decision you are recording in the JSON; zoom is how you are looking at
        it right now, and you want to be able to zoom back out without losing
        the crop. 'c' promotes the current zoom rectangle into a real crop when
        you decide you meant it.
        """
        x0, y0, x1, y1 = self.crop_rect()
        zw, zh = (x1 - x0) / self.zoom, (y1 - y0) / self.zoom
        # Clamp the centre so the zoom window can never leave the crop.
        cx = min(max(self.pan[0], x0 + zw / 2), x1 - zw / 2)
        cy = min(max(self.pan[1], y0 + zh / 2), y1 - zh / 2)
        return (cx - zw / 2, cy - zh / 2, cx + zw / 2, cy + zh / 2)

    def render_size(self):
        """(w, h) to render the ROI at, or None to render it 1:1.

        fit     the ROI is scaled to fill an explicitly selected processing
                view box. With no view box, the canonical feed's natural ROI
                size is used. Display-window dimensions never enter this path.
        native  the ROI is rendered at its natural size, so zoom and crop never
                interpolate anything. The OpenCV window scales that result only
                for presentation when a display-only bound was requested.
        """
        if self.fit_mode == "native" or self.view_size is None:
            return None
        ow, oh = full_output_size(self.profile, self.capture_size)
        x0, y0, x1, y1 = self.roi()
        pw, ph = max(1e-6, (x1 - x0) * ow), max(1e-6, (y1 - y0) * oh)
        s = min(self.view_size[0] / pw, self.view_size[1] / ph)
        # A view box within a pixel of the ROI's own size is someone asking for
        # 1:1 — that is exactly what 'refit' sets up. Snapping to it stops a
        # rounding remainder from turning a straight copy into a 0.999x
        # resample, which costs real sharpness for no reason at all.
        if abs(s - 1.0) * max(pw, ph) < 1.0:
            s = 1.0
        return (max(2, int(round(pw * s))), max(2, int(round(ph * s))))

    def set_zoom(self, value):
        old = self.zoom
        # Below 1 there is nothing to show: the ROI would leave the crop.
        self.zoom = float(min(max(value, 1.0), 40.0))
        self.dirty = True
        return f"zoom {old:.2f}x -> {self.zoom:.2f}x"

    def set_pan(self, cx, cy):
        self.pan = (float(min(max(cx, 0.0), 1.0)), float(min(max(cy, 0.0), 1.0)))
        self.dirty = True
        return f"pan centre {self.pan[0]:.3f}, {self.pan[1]:.3f}"

    def nudge_pan(self, dx, dy):
        """Move by a fraction of what is currently VISIBLE, not of the frame.

        So one arrow press is the same visual distance at every zoom level —
        at 10x it is a small step, not a jump clear across the crop.
        """
        x0, y0, x1, y1 = self.roi()
        return self.set_pan(self.pan[0] + dx * (x1 - x0),
                            self.pan[1] + dy * (y1 - y0))

    def push_crop(self, rect):
        """Add a crop, expressed in the coordinates of the CURRENT view.

        This is what a mouse drag produces: the rectangle arrives relative to
        what is on screen, which already includes the zoom, so it has to be
        composed onto the visible ROI. Dragging a box while zoomed in would
        otherwise crop to the wrong part of the frame.
        """
        a, b, c, d = rect
        vx0, vy0, vx1, vy1 = self.roi()
        vw, vh = vx1 - vx0, vy1 - vy0
        return self.push_absolute_crop((vx0 + a * vw, vy0 + b * vh,
                                        vx0 + c * vw, vy0 + d * vh))

    def push_absolute_crop(self, rect):
        """Add a crop given in FULL-OUTPUT coordinates, whatever is on screen.

        This is the form the crop field displays and the `crop x0 y0 x1 y1`
        command takes, and it is the reason those two agree: typing back the
        numbers the field is showing is a no-op rather than a second crop.

        The rectangle is still stored relative to the crop below it — that is
        what makes the stack an undo — but the arithmetic here inverts the
        composition, so any absolute rectangle can be expressed, including one
        that reaches back outside the current crop.
        """
        ax0, ay0, ax1, ay1 = rect
        cx0, cy0, cx1, cy1 = self.crop_rect()
        cw, ch = max(1e-9, cx1 - cx0), max(1e-9, cy1 - cy0)
        self.crops.append(((ax0 - cx0) / cw, (ay0 - cy0) / ch,
                           (ax1 - cx0) / cw, (ay1 - cy0) / ch))
        # The crop has taken over the framing, so the zoom that helped choose it
        # has done its job. Leaving it on would double-apply the magnification.
        self.zoom = 1.0
        self.pan = ((ax0 + ax1) / 2, (ay0 + ay1) / 2)
        self.dirty = True
        return (f"cropped to {ax0:.3f},{ay0:.3f} - {ax1:.3f},{ay1:.3f} "
                f"(crop {len(self.crops)}; Backspace or 'uncrop' undoes it)")

    def pop_crop(self):
        if not self.crops:
            raise CommandError("no crop to undo — the whole frame is showing")
        self.crops.pop()
        x0, y0, x1, y1 = self.crop_rect()
        self.pan = ((x0 + x1) / 2, (y0 + y1) / 2)
        self.zoom = 1.0
        self.dirty = True
        return (f"crop undone — {len(self.crops)} left"
                if self.crops else "crop undone — showing the whole frame")

    def clear_crops(self):
        n, self.crops = len(self.crops), []
        self.zoom, self.pan = 1.0, (0.5, 0.5)
        self.dirty = True
        return f"dropped {n} crop(s) — showing the whole frame"

    # --- sensor ------------------------------------------------------------

    def set_sensor(self, name, raw):
        """Set one sensor control from its text argument, or hand it back to auto.

        Values are validated against SENSOR_CONTROLS here rather than at the
        backend, so a typo is rejected with the range quoted instead of being
        silently swallowed by a driver that returns success for everything.
        """
        spec = SENSOR_CONTROLS[name]
        text = raw.strip().lower()
        note = ""

        # Checked before the choice branch so that "auto" works for every
        # control, including the choice ones — it means "do not send this at
        # all", which is a valid state for all of them and the state they all
        # start in. A field showing "auto" must be committable unchanged.
        if text in (AUTO, "a"):
            value = AUTO
        elif spec.kind == "choice":
            value = parse_choice(text, spec.choices)
        else:
            current = self.sensor[name]
            base = float(current) if current not in (AUTO, None) else 0.0
            value = parse_number(text, base, float)
            # Clamped, not rejected — otherwise stepping a field down from its
            # minimum is an error rather than a no-op, which is a miserable way
            # for a Down arrow to behave. The note keeps it from being silent.
            clamped = min(max(value, spec.lo), spec.hi)
            if abs(clamped - value) > 1e-9:
                note = f"  (clamped from {value:g}; range is {spec.range_text})"
            value = int(round(clamped)) if spec.kind == "int" else clamped

        self.sensor[name] = value
        self.sensor_dirty = True
        return f"{name} {value}{note}"

    def all_auto(self):
        for name in SENSOR_CONTROLS:
            self.sensor[name] = AUTO
        self.sensor_dirty = True
        return "every sensor control handed back to the camera (auto)"

    def apply_sensor(self, camera):
        """Push the sensor settings at the camera and record what it took.

        The result is kept as a string on the panel rather than only logged,
        because "the driver ignored that control" is a standing fact about this
        camera, not a one-off event that should scroll away.
        """
        self.sensor_dirty = False
        if not hasattr(camera, "apply"):
            self.sensor_status = "backend has no live controls"
            return self.sensor_status
        applied, skipped = camera.apply(dict(self.sensor))
        self.sensor_status = f"{len(applied)} applied"
        if skipped:
            self.sensor_status += f", {len(skipped)} unavailable: {'; '.join(skipped[:2])}"
            for note in skipped:
                self.log.add(False, f"sensor: {note}")
        return self.sensor_status

    # --- colour ------------------------------------------------------------
    #
    # A software correction, separate from the sensor's own redgain/bluegain
    # above. The sensor controls are better when the backend has them, because
    # they act before the camera has already lost headroom in the channel it
    # under-exposed — so every calibration here also reports the sensor gains
    # that would do the same job, and `colourinfo` prints them. This exists
    # because the V4L2 path often has no such control, and because a solved
    # matrix can do things a pair of gains cannot.

    def _need_capture(self):
        if self.last_capture is None:
            raise CommandError("no camera frame yet; wait for the preview")
        return self.last_capture

    def _sample_sheet(self, frame, what):
        try:
            return sample_ink_colors(frame)
        except ColorGridError as exc:
            raise CommandError(f"{what}: {exc}")

    def set_colour_enabled(self, on: bool):
        self.colour.enabled = bool(on)
        return f"colour correction {'on' if self.colour.enabled else 'off'}"

    def set_colour_gain(self, channel: int, value: float):
        applied = self.colour.set_gain(channel, value)
        return f"{CHANNELS[channel]} gain {applied:.3f}"

    def set_colour_offset(self, channel: int, value: float):
        applied = self.colour.set_offset(channel, value)
        return f"{CHANNELS[channel]} offset {applied:+.1f}"

    def set_colour_gamma(self, value: float):
        return f"gamma {self.colour.set_gamma(value):.3f}"

    def set_colour_saturation(self, value: float):
        return f"colour saturation {self.colour.set_saturation(value):.3f}"

    def set_colour_mode(self, mode: str):
        self.colour_mode = mode
        return f"colour fit mode {mode}"

    def white_balance_now(self):
        """Neutralise the cast using the printed sheet's own white paper.

        The zero-effort calibration: no reference photograph, nothing to line
        up, just the sheet in shot. The paper is the right white reference
        because it is lit by exactly the same light as everything else on the
        bench — unlike a wall, a bench top, or the brightest pixel in frame.
        """
        frame = self._need_capture()
        samples = self._sample_sheet(frame, "white balance")
        if "paper" not in samples.colors:
            raise CommandError(
                "found the ink but not the sheet's white margins; move the "
                "sheet fully into view")
        try:
            self.colour.set_matrix(neutral_matrix(samples.colors["paper"]),
                                   "white balance from the sheet's paper")
        except ColorCorrectionError as exc:
            raise CommandError(str(exc))
        self.colour.enabled = True
        self.colour_similarity = None
        red, blue = equivalent_sensor_gains(self.colour.matrix,
                                            samples.colors["paper"])
        self.colour_status = (f"paper white balance | equivalent sensor "
                              f"redgain {red:.2f} bluegain {blue:.2f}")
        return f"{self.colour.describe()} — {self.colour_status}"

    def calibrate_colour(self, reference_path, mode=None):
        """Match this camera to a reference photograph of the same printed sheet.

        Both images are reduced to three measured colours — green ink, magenta
        ink, white paper — and the transform between those pairs is what gets
        solved. The two photographs do not have to be framed alike, or even show
        the same part of the sheet: green is green in both.

        Every warning the fit produces is surfaced rather than logged quietly.
        On real rig data the residual ranks the fits backwards — see
        :func:`vision.color_correction.solve_matrix` — so the warnings are the
        part worth reading. With no explicit ``mode`` the strongest fit that
        does not look implausible is chosen automatically.
        """
        explicit_mode = mode                       # None => auto-pick a mode
        path = Path(reference_path)
        if not path.exists() and not path.is_absolute():
            path = REFERENCE_DIR / path
        reference = cv2.imread(str(path))
        if reference is None:
            raise CommandError(f"cannot read a reference image at {path}")

        frame = self._need_capture()
        camera_samples = self._sample_sheet(frame, "this camera")
        reference_samples = self._sample_sheet(reference, str(path.name))
        try:
            camera_colors, reference_colors, names = pair_samples(
                camera_samples, reference_samples)
        except ColorCorrectionError as exc:
            raise CommandError(str(exc))

        # Try the requested fit, or - when none was named - matrix, affine, gain
        # in order and take the first that does not look implausible. On a rig
        # frame where the camera has crushed the green channel, the full 3x3
        # scores a perfect residual while turning into a negative-gain, heavy
        # cross-mix transform; the constrained gain fit is then the honest
        # answer, and this picks it automatically instead of silently applying
        # the garbage matrix.
        order = ([explicit_mode] if explicit_mode
                 else [m for m in ("matrix", "affine", "gain")])
        attempts, chosen = [], None
        for candidate in order:
            try:
                m, residual, notes = solve_matrix(
                    camera_colors, reference_colors, mode=candidate)
            except ColorCorrectionError as exc:
                attempts.append((candidate, str(exc)))
                continue
            probe = ColorCorrection()
            probe.set_matrix(m)
            problems = probe.implausibilities()
            attempts.append((candidate, problems or "ok"))
            if chosen is None or (not problems and chosen[3]):
                chosen = (candidate, m, residual, bool(problems), notes)
            if not problems:
                break
        if chosen is None:
            detail = "; ".join(f"{c}: {why}" for c, why in attempts)
            raise CommandError(f"no colour fit succeeded ({detail})")

        mode, matrix, residual, implausible, notes = chosen
        self.colour.set_matrix(matrix, f"{mode} fit against {path.name}")
        self.colour.enabled = True
        self.colour_similarity = None
        self.colour_mode = mode
        red, blue = equivalent_sensor_gains(matrix, camera_samples.colors["paper"]) \
            if "paper" in camera_samples.colors else (float("nan"), float("nan"))
        self.colour_status = (f"{mode} fit vs {path.name}: residual "
                              f"{residual:.1f} levels over {', '.join(names)}")
        if math.isfinite(red):
            self.colour_status += (f" | equivalent sensor redgain {red:.2f} "
                                   f"bluegain {blue:.2f}")
        if not explicit_mode and mode != "matrix":
            self.colour_status += (
                f" | matrix/affine looked implausible on this frame, used "
                f"{mode}; fix the light/sensor so the green ink is not grey "
                f"for a full correction")
        for note in notes:
            self.log.add(False, f"colour: {note}")
        if implausible:
            self.colour_status += " | STILL implausible, see colourinfo"
        elif notes:
            self.colour_status += f" | {len(notes)} warning(s), see the log"
        return f"{self.colour.describe()} — {self.colour_status}"

    def apply_raw_phone_profile(self, path=None):
        """Apply the pre-tuned TUNE-TO-RAW-PHONE colour profile to the live view.

        Loads the profile ``vision/tune_color_to_raw_phone.py`` wrote and applies
        it, nothing more: it does not run the tuning, ask for images, or optimise
        anything. The profile is the same ``colour`` block the settings file
        carries, so once applied it saves, edits and toggles through the ordinary
        COLOUR workflow. The similarity score the offline tuning reached is kept
        for the panel.
        """
        path = Path(path) if path is not None else RAW_PHONE_PROFILE_PATH
        if not path.exists():
            raise CommandError(
                f"no tuned profile at {path.name} — run "
                f"vision/tune_color_to_raw_phone.py to create it first")
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"cannot read {path.name}: {exc}")
        try:
            self.colour = ColorCorrection.from_settings(data)
        except RuntimeError as exc:
            raise CommandError(str(exc))

        self.colour.enabled = True
        self.colour_similarity = data.get("similarity")
        # The offline tuner solves the full distribution transfer, so the panel's
        # fit selector should say so when the loaded matrix actually carries mix.
        self.colour_mode = ("matrix" if not self.colour.is_diagonal
                            else DEFAULT_COLOUR_FIT)
        source = self.colour.source or "tuned to the raw phone image"
        self.colour.source = source
        if self.colour_similarity is not None:
            match = f"{self.colour_similarity * 100:.1f}% colour similarity"
            if data.get("target_met") is False:
                match += " (best safe result)"
        else:
            match = "similarity not recorded"
        strength = data.get("strength")
        if strength is not None and strength < 0.999:
            match += (f", softened to {strength * 100:.0f}% strength to protect "
                      f"shadows")
        self.colour_status = (f"{source}, {match} — loaded from {path.name}, "
                              f"not re-tuned")
        for note in data.get("notes", []):
            self.log.add(False, f"colour: {note}")
        return f"{self.colour.describe()} — {self.colour_status}"

    def colour_report(self):
        lines = [self.colour.describe(), f"  {self.colour_status}"]
        if self.colour_similarity is not None:
            lines.append(f"  colour similarity to the raw phone image: "
                         f"{self.colour_similarity * 100:.1f}%")
        if self.colour.source:
            lines.append(f"  from: {self.colour.source}")
        lines.append("  matrix (BGR affine, row = output channel):")
        for index, row in enumerate(self.colour.matrix):
            lines.append(f"    {CHANNELS[index]:>5}  " +
                         "  ".join(f"{v:8.4f}" for v in row))
        for problem in self.colour.implausibilities():
            lines.append(f"  WARNING: {problem}")
        return "\n".join(lines)

    def reset_colour(self):
        self.colour.reset()
        self.colour.enabled = False
        self.colour_mode = DEFAULT_COLOUR_FIT
        self.colour_status = "not calibrated"
        self.colour_similarity = None
        return "colour correction reset to identity and switched off"

    # --- frame orientation -------------------------------------------------

    def orient(self, frame):
        """Flip and rotate the CAPTURED frame, before the correction sees it.

        Doing it here rather than to the finished image keeps one coordinate
        system for everything downstream: the maps, the crop rectangle and the
        mouse all agree. The correction itself is unharmed because it is radially
        symmetric about the image centre.

        The one thing to know: centre_dx/dy are measured in this oriented frame,
        so set the flip first and tune the optical centre afterwards.
        """
        if self.flip in ("h", "both"):
            frame = cv2.flip(frame, 1)
        if self.flip in ("v", "both"):
            frame = cv2.flip(frame, 0)
        if self.rotate:
            frame = cv2.rotate(frame, {
                90: cv2.ROTATE_90_CLOCKWISE,
                180: cv2.ROTATE_180,
                270: cv2.ROTATE_90_COUNTERCLOCKWISE,
            }[self.rotate])
        return frame

    # --- rebuild -----------------------------------------------------------

    def rebuild(self, input_size):
        self.capture_size = input_size
        self.maps = build_maps(self.profile, input_size, self.interp, mip=self.mip,
                               roi=self.roi(), view_size=self.render_size())
        if self.view_size is None:
            # The canonical viewport is the feed's natural corrected ROI. It
            # is deliberately derived from the maps, never from a Tk window.
            self.viewport = tuple(self.maps.out_size)
        self.dirty = False
        return self.maps

    def drain_pending(self):
        """Take everything the stdin thread has queued since the last frame.

        Swapping the list out in one statement is the whole of the thread safety
        here: the reader only ever appends, so nothing can be lost between the
        read and the rebind.
        """
        lines, self.pending = self.pending, []
        return lines

    # --- commands ----------------------------------------------------------

    def _build_commands(self):
        cmds = CommandSet()

        def numeric(setter, getter, usage, kind=float):
            def handler(args):
                need_args(args, 1, usage)
                return setter(parse_number(args[0], getter(), kind))
            return handler

        def choice(setter, options, usage):
            def handler(args):
                need_args(args, 1, usage)
                return setter(parse_choice(args[0], options))
            return handler

        # --- the correction ---
        cmds.add("undistort", self._cmd_undistort, "[on|off]",
                 "the fisheye correction itself", aliases=("un",))
        cmds.add("fov", numeric(self.set_lens_fov,
                                lambda: self.profile.lens_fov_deg, "fov <deg|+N|-N>"),
                 "<deg|+N|-N>", "quoted lens FOV — tune this FIRST (20..220)",
                 aliases=("lensfov",))
        cmds.add("ref", choice(self.set_fov_reference, ("diagonal", "horizontal"),
                               "ref <diagonal|horizontal>"),
                 "<diagonal|horizontal>", "which FOV the lens number refers to")
        cmds.add("model", choice(self.set_model, MODEL_NAMES, "model <name>"),
                 "<name>", f"projection curve: {', '.join(MODEL_NAMES)}")
        cmds.add("k1", numeric(self.set_k1, lambda: self.profile.k1, "k1 <v|+v|-v>"),
                 "<v|+v|-v>", "radial trim, edge-weighted (-0.5..0.5, try 0.01 steps)")
        cmds.add("k2", numeric(self.set_k2, lambda: self.profile.k2, "k2 <v|+v|-v>"),
                 "<v|+v|-v>", "radial trim, corner-weighted (-0.5..0.5)")
        cmds.add("k3", numeric(self.set_k3, lambda: self.profile.k3, "k3 <v|+v|-v>"),
                 "<v|+v|-v>", "radial trim, extreme-edge weighted (-0.5..0.5)")
        cmds.add("k4", numeric(self.set_k4, lambda: self.profile.k4, "k4 <v|+v|-v>"),
                 "<v|+v|-v>", "radial trim, extreme-corner weighted (-0.5..0.5)")
        cmds.add("cx", numeric(self.set_centre_dx,
                               lambda: self.profile.centre_dx, "cx <px|+px|-px>"),
                 "<px|+px|-px>", "optical axis offset X — for ASYMMETRIC bowing")
        cmds.add("cy", numeric(self.set_centre_dy,
                               lambda: self.profile.centre_dy, "cy <px|+px|-px>"),
                 "<px|+px|-px>", "optical axis offset Y")
        cmds.add("fxscale", numeric(self.set_focal_x_scale,
                                     lambda: self.profile.focal_x_scale,
                                     "fxscale <v|+v|-v>"),
                 "<v|+v|-v>", "source X focal multiplier (0.5..1.5; identity 1)")
        cmds.add("fyscale", numeric(self.set_focal_y_scale,
                                     lambda: self.profile.focal_y_scale,
                                     "fyscale <v|+v|-v>"),
                 "<v|+v|-v>", "source Y focal multiplier (0.5..1.5; identity 1)")
        cmds.add("skew", numeric(self.set_skew, lambda: self.profile.skew,
                                  "skew <v|+v|-v>"),
                 "<v|+v|-v>", "source X shear (-0.25..0.25; normally zero)")
        cmds.add("p1", numeric(self.set_p1, lambda: self.profile.p1,
                                "p1 <v|+v|-v>"),
                 "<v|+v|-v>", "tangential/decentring trim (-0.25..0.25)")
        cmds.add("p2", numeric(self.set_p2, lambda: self.profile.p2,
                                "p2 <v|+v|-v>"),
                 "<v|+v|-v>", "tangential/decentring trim (-0.25..0.25)")
        cmds.add("out", numeric(self.set_output_fov,
                                lambda: self.profile.output_fov_deg, "out <deg|+N|-N>"),
                 "<deg|+N|-N>", "how much of the lens cone to render (10..170)",
                 aliases=("outfov",))
        cmds.add("scale", numeric(self.set_output_scale,
                                  lambda: self.profile.output_scale, "scale <f|+f|-f>"),
                 "<f|+f|-f>", "render resolution of the correction (0.1..4)")
        cmds.add("interp", choice(self.set_interp, INTERP_NAMES, "interp <name>"),
                 "<name>", f"resampling kernel: {', '.join(INTERP_NAMES)}")
        cmds.add("mip", self._cmd_mip, "[on|off]",
                 "pyramid filtering of the regions the correction shrinks")
        cmds.add("straight", self._cmd_straight, "",
                 "print the recipe for straightening edges")
        cmds.add("tuneview", self._cmd_tuneview, "",
                 "full-frame raw/corrected comparison with grid enabled")
        cmds.add("tunereset", self._cmd_tunereset, "",
                 "reset manual lens trims only; preserve every other setting")

        # --- zoom and crop ---
        cmds.add("zoom", self._cmd_zoom, "<x|+x|-x>", "digital zoom, 1..40x",
                 aliases=("z",))
        cmds.add("pan", self._cmd_pan, "<dx> <dy> | centre",
                 "move the zoom window; steps are fractions of the visible area")
        cmds.add("crop", self._cmd_crop, "[x0 y0 x1 y1]",
                 "crop to a 0..1 rectangle, or to the current zoom if given none")
        cmds.add("uncrop", lambda a: self.pop_crop(), "", "UNDO the last crop",
                 aliases=("u",))
        cmds.add("nocrop", lambda a: self.clear_crops(), "", "drop every crop")
        cmds.add("fitmode", choice(lambda v: self._set_attr("fit_mode", v, "sizing",
                                                            dirty=True),
                                   FIT_MODES, "fitmode <fit|native>"),
                 "<fit|native>", "fit: fill the viewport. native: render the crop 1:1")
        cmds.add("viewbox", self._cmd_viewbox, "<w> <h>",
                 "size the correction renders at; 'fill' resets it to the viewport")
        cmds.add("refit", self._cmd_refit, "",
                 "resize the view box so the crop renders 1:1 (no interpolation)")
        cmds.add("fill", self._cmd_fill, "",
                 "view box back to the viewport — undoes 'refit'")

        # --- frame ---
        cmds.add("view", choice(lambda v: self._set_attr("view", v, "view"), VIEWS,
                                "view <corrected|raw|both>"),
                 "<corrected|raw|both>", "which image to show")
        cmds.add("flip", choice(lambda v: self._set_attr("flip", v, "flip", dirty=True),
                                FLIPS, "flip <none|h|v|both>"),
                 "<none|h|v|both>", "mirror the captured frame")
        cmds.add("rotate", self._cmd_rotate, "<0|90|180|270>",
                 "rotate the captured frame")
        cmds.add("swaprb", self._cmd_swaprb, "[on|off]",
                 "fix inverted red/blue channels")
        cmds.add("grid", self._cmd_grid, "[on|off]",
                 "8x8 overlay — the ruler you judge straightness against")
        cmds.add("blockcal", self._cmd_blockcal, "[anchor]",
                 "read the machine grid off the blocks on the board: measure "
                 "the ones that are there, fill in the ones that are not",
                 aliases=("blocks",))
        cmds.add("blockcalsave", self._cmd_blockcalsave, "",
                 "write the last blockcal result to config/workspace_map.json")
        cmds.add("blockcaloff", self._cmd_blockcaloff, "",
                 "clear the block-calibration overlay")

        # --- colour: the software correction, separate from the sensor's own ---
        cmds.add("colour", self._cmd_colour, "[on|off]",
                 "the software colour correction itself", aliases=("color",))
        cmds.add("wb", self._cmd_wb, "",
                 "WHITE BALANCE NOW from the printed sheet's white paper")
        cmds.add("colourcal", self._cmd_colourcal, "[image] [gain|affine|matrix]",
                 "match this camera to a reference photo of the same sheet",
                 aliases=("colorcal", "ccal"))
        cmds.add("colourmode", choice(self.set_colour_mode, COLOUR_FIT_MODES,
                                      "colourmode <gain|affine|matrix>"),
                 "<gain|affine|matrix>",
                 f"what a calibration fits: {', '.join(COLOUR_FIT_MODES)}")
        for index, name in enumerate(CHANNELS):
            cmds.add(f"{name[0]}gain",
                     numeric(lambda v, i=index: self.set_colour_gain(i, v),
                             lambda i=index: self.colour.gain[i],
                             f"{name[0]}gain <v|+v|-v>"),
                     "<v|+v|-v>", f"colour {name} gain (0.05..8)")
            cmds.add(f"{name[0]}off",
                     numeric(lambda v, i=index: self.set_colour_offset(i, v),
                             lambda i=index: self.colour.offset[i],
                             f"{name[0]}off <v|+v|-v>"),
                     "<v|+v|-v>", f"colour {name} offset (-128..128)")
        cmds.add("gamma", numeric(self.set_colour_gamma,
                                  lambda: self.colour.gamma, "gamma <v|+v|-v>"),
                 "<v|+v|-v>", "colour gamma (0.2..5)")
        cmds.add("csat", numeric(self.set_colour_saturation,
                                 lambda: self.colour.saturation, "csat <v|+v|-v>"),
                 "<v|+v|-v>", "SOFTWARE saturation (0..3) — not the sensor's")
        cmds.add("nomix", self._cmd_nomix, "",
                 "drop a fit's cross-channel terms, keeping its white balance")
        cmds.add("colourinfo", self._cmd_colourinfo, "",
                 "print the colour matrix and what is wrong with it",
                 aliases=("colorinfo",))
        cmds.add("colourreset", lambda a: self.reset_colour(), "",
                 "colour correction back to identity, and off",
                 aliases=("colorreset",))
        cmds.add("tunetoraw", lambda a: self.apply_raw_phone_profile(), "",
                 "apply the saved TUNE-TO-RAW-PHONE profile (loads it, does not "
                 "re-tune)", aliases=("rawphone",))

        # --- sensor: one command per control, generated from the table ---
        for name, spec in SENSOR_CONTROLS.items():
            cmds.add(name, self._sensor_handler(name), f"<{spec.range_text}>",
                     spec.help)
        cmds.add("sensor", self._cmd_sensor, "",
                 "print every sensor control and what the camera did with it")
        cmds.add("autoall", lambda a: self.all_auto(), "",
                 "hand every sensor control back to the camera")

        # --- files ---
        cmds.add("save", self._cmd_save, "[path]",
                 "WRITE THE JSON — everything above, in one file", aliases=("w",))
        cmds.add("autosave", self._cmd_autosave, "[on|off]",
                 "save the newest JSON after changes settle for 500 ms")
        cmds.add("load", self._cmd_load, "[path]", "read a settings JSON back in")
        cmds.add("lens", self._cmd_lens, "[path]",
                 f"also write the lens half to {PROFILE_PATH.name}, for the other tools")
        cmds.add("snap", self._cmd_snap, "", "save raw + corrected PNGs")
        cmds.add("params", self._cmd_params, "", "print every current value")
        cmds.add("reset", self._cmd_reset, "", "back to defaults, everything")
        cmds.add("help", self._cmd_help, "", "list these commands", aliases=("h", "?"))
        cmds.add("quit", self._cmd_quit, "", "exit", aliases=("q", "exit"))
        return cmds

    def _sensor_handler(self, name):
        def handler(args):
            spec = SENSOR_CONTROLS[name]
            need_args(args, 1, f"{name} <{spec.range_text}>")
            return self.set_sensor(name, args[0])
        return handler

    def _set_attr(self, attr, value, label, dirty=False):
        setattr(self, attr, value)
        if dirty:
            self.dirty = True
        return f"{label} {value}"

    def _flag(self, args, current):
        """Shared parsing for the on/off commands, where a bare word toggles."""
        if not args:
            return not current
        return parse_choice(args[0], ("on", "off")) == "on"

    def _cmd_colour(self, args):
        return self.set_colour_enabled(self._flag(args, self.colour.enabled))

    def _cmd_wb(self, args):
        return self.white_balance_now()

    def _cmd_colourcal(self, args):
        reference, mode = None, None
        for token in args:
            if token.lower() in COLOUR_FIT_MODES:
                mode = token.lower()
            else:
                reference = token
        if reference is None:
            candidates = sorted(REFERENCE_DIR.glob("*.jpeg")) + \
                sorted(REFERENCE_DIR.glob("*.jpg")) + \
                sorted(REFERENCE_DIR.glob("*.png"))
            if not candidates:
                raise CommandError(
                    f"give a reference image; none found in {REFERENCE_DIR}")
            if len(candidates) > 1:
                raise CommandError(
                    f"{len(candidates)} reference images in {REFERENCE_DIR}; "
                    f"name one: {', '.join(c.name for c in candidates[:4])}")
            reference = candidates[0]
        return self.calibrate_colour(reference, mode)

    def _cmd_colourinfo(self, args):
        for line in self.colour_report().splitlines():
            self.log.add(True, line)
            print(line)
        return self.colour.describe()

    def _cmd_nomix(self, args):
        removed = self.colour.drop_mix()
        if removed <= 0:
            return "the colour matrix was already diagonal"
        return f"dropped {removed:.3f} of cross-channel mixing; {self.colour.describe()}"

    def _cmd_undistort(self, args):
        self.correct = self._flag(args, self.correct)
        return f"fisheye correction {'ON' if self.correct else 'OFF (raw geometry)'}"

    def _cmd_mip(self, args):
        self.mip = self._flag(args, self.mip)
        self.dirty = True
        return f"mip filtering {'on' if self.mip else 'off'}"

    def _cmd_grid(self, args):
        self.show_grid = self._flag(args, self.show_grid)
        return f"grid {'on' if self.show_grid else 'off'}"

    def _cmd_blockcal(self, args):
        """Read the grid off the blocks currently on the board.

        Physical blocks are measured; every cell the block supply did not reach
        is filled in from the lattice they define, so the overlay always shows
        the whole grid. Nothing is written - ``blockcalsave`` does that.
        """
        anchor = self.block_anchor
        if args:
            wanted = str(args[0]).lower()
            matches = [name for name in LATTICE_ANCHORS if name.startswith(wanted)]
            if len(matches) != 1:
                raise CommandError(
                    f"anchor must be one of {', '.join(LATTICE_ANCHORS)}")
            anchor = matches[0]
        frame = self.last_corrected
        if frame is None:
            raise CommandError("no corrected frame yet")
        try:
            grid = MachineGrid.from_config(load_rig_config(reload=True))
        except (OSError, ValueError, KeyError) as exc:
            raise CommandError(f"cannot read the rig grid: {exc}")
        try:
            calibration, diagnostics = detect_block_lattice(
                frame, grid, anchor=anchor,
                max_processing_width=frame.shape[1])
        except BlockGridError as exc:
            self.block_lattice = None
            self.block_lattice_note = str(exc)
            raise CommandError(str(exc))

        self.block_anchor = anchor
        self.block_lattice = calibration
        physical = len(calibration.found_cells)
        virtual = len(calibration.virtual_cells)
        report = calibration.block_report
        note = (f"{physical} blocks measured, {virtual} cells filled in, "
                f"residual {report.mean_residual_px:.2f} px")
        if report.dense is not None:
            note += f", {report.dense.chosen}"
            for warning in report.dense.warnings:
                self.log.add(True, warning)
        if diagnostics["off_lattice"]:
            note += (f", {len(diagnostics['off_lattice'])} off-lattice object(s) "
                     f"ignored")
        self.block_lattice_note = note
        return f"block calibration ({anchor}): {note}"

    def projection(self):
        """The geometry identity a saved workspace map is only valid under.

        Every consumer of ``workspace_map.json`` compares this against its own
        and refuses a map whose lens, orientation or framing does not match -
        see ``gridded_camera_feed.load_workspace``. A map saved without it is
        written successfully and then silently ignored by everything, which is
        the least useful possible outcome, so this is not optional.
        """
        return projection_metadata(self.profile, {"flip": self.flip,
                                                  "rotate": self.rotate},
                                   self.correct, self.roi())

    def saved_projection(self):
        """The projection the APP will compute, from the settings file on disk.

        This window is an editor: its live lens, flip, crop, zoom and
        correction switch are whatever is being tuned right now, and they only
        become what the rest of the project sees once SAVE JSON writes them.
        Every consumer of ``workspace_map.json`` builds its projection from
        that FILE, so a calibration stamped with unsaved editor state is
        refused by all of them - and correctly so, because the frame it was
        fitted to is not the frame the app renders.

        Returns None when the file cannot be read; the caller then has nothing
        to compare against and should not block the save on it.
        """
        try:
            settings = load_settings(self.settings_path)
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        correction = settings.get("correction") or {}
        return projection_metadata(
            profile_from_settings(settings), settings.get("capture") or {},
            bool(correction.get("enabled", True)), framing_roi(settings))

    def _cmd_blockcalsave(self, args):
        """Write the last block calibration to config/workspace_map.json.

        Reports how far the saved map's cells land from the ones that were
        actually measured. ``WorkspaceMap`` carries four envelope corners and
        the grid geometry, not a per-cell table, so a consumer spaces cells
        evenly between those corners - and any curvature the fit bought is
        flattened on the way out. The corners themselves stay exact; the error
        peaks in the middle of the grid, which is the signature of exactly
        that. Saying the number is better than pretending it is zero.
        """
        if self.block_lattice is None:
            raise CommandError("run blockcal first")
        frame = self.last_corrected
        if frame is None:
            raise CommandError("no corrected frame yet")
        size = frame.shape[1::-1]

        # The paper route runs INSIDE the app, so its projection matches the
        # app's by construction. This one does not, and an editor's live
        # geometry is exactly the thing that drifts from the file. Catch it
        # here with a sentence an operator can act on, rather than letting the
        # app refuse the map later with "camera lens/orientation/framing
        # changed" and no clue which knob did it.
        live = self.projection()
        on_disk = self.saved_projection()
        if on_disk is not None and live != on_disk:
            differs = [name for name in ("view", "lens", "orientation", "roi")
                       if live.get(name) != on_disk.get(name)]
            raise CommandError(
                f"this window's {', '.join(differs)} does not match "
                f"{self.settings_path.name}, which is what the app renders "
                f"from. A calibration saved now would be refused by every "
                f"tool that loads it. Press SAVE JSON first, then save the "
                f"calibration again")
        try:
            grid = MachineGrid.from_config(load_rig_config(reload=True))
            workspace = block_workspace_map(
                self.block_lattice, grid, size, projection=live)
            workspace.save(WORKSPACE_MAP_PATH)
        except (BlockGridError, OSError, ValueError) as exc:
            raise CommandError(str(exc))

        # Name the file AND the mode. This window's other SAVE writes
        # camera_settings.json, so "saved" on its own is genuinely ambiguous -
        # and a workspace map is stored per grid mode, so which one it landed
        # in is the thing an operator actually needs told.
        note = (f"CALIBRATION SAVED: {grid.mode} grid "
                f"({grid.cols}x{grid.rows}) -> {WORKSPACE_MAP_PATH}. "
                f"Reload it in the app: press L in rig_build_v1, or POST "
                f"/api/calibration/reload in the web console")
        try:
            mean_px, max_px, worst = workspace_map_error(
                self.block_lattice, workspace, grid, size)
        except (BlockGridError, ValueError):
            return note
        pitch = self.block_lattice.block_report.dense
        per_cm = pitch.pitch_x.px_per_cm if pitch and pitch.pitch_x else 0.0
        detail = (f" | saved cells land {mean_px:.2f} px mean / {max_px:.2f} px "
                  f"max from the measured ones, worst at "
                  f"[{worst[0]},{worst[1]}]")
        if per_cm:
            detail += f" ({max_px / per_cm:.2f} cm)"
        if max_px > 4.0:
            self.log.add(False, "the four-corner map cannot reproduce this "
                                "lattice closely" + detail)
        return note + detail

    def _cmd_blockcaloff(self, args):
        self.block_lattice = None
        self.block_lattice_note = ""
        return "block calibration overlay cleared"

    def _cmd_swaprb(self, args):
        self.swap_rb = self._flag(args, self.swap_rb)
        return f"red/blue swap {'on' if self.swap_rb else 'off'}"

    def _cmd_autosave(self, args):
        self.autosave = self._flag(args, self.autosave)
        if self.autosave:
            self.write_settings(self.settings_path)
            return f"autosave ON — {self.settings_path} uses a 500 ms debounce"
        return "autosave off"

    def _cmd_rotate(self, args):
        need_args(args, 1, "rotate <0|90|180|270>")
        try:
            value = int(args[0])
        except ValueError:
            raise CommandError(f"'{args[0]}' is not a number")
        if value not in ROTATIONS:
            raise CommandError(f"rotation must be one of {ROTATIONS}")
        self.rotate = value
        self.dirty = True   # 90/270 swap width and height, so the maps change
        return f"rotate {value} deg"

    def _cmd_zoom(self, args):
        need_args(args, 1, "zoom <x|+x|-x>")
        return self.set_zoom(parse_number(args[0], self.zoom, float))

    def _cmd_pan(self, args):
        if len(args) == 1 and args[0].lower() in ("centre", "center", "c"):
            x0, y0, x1, y1 = self.crop_rect()
            return self.set_pan((x0 + x1) / 2, (y0 + y1) / 2)
        need_args(args, 2, "pan <dx> <dy>  |  pan centre")
        try:
            dx, dy = float(args[0]), float(args[1])
        except ValueError:
            raise CommandError("pan takes two numbers, e.g. 'pan 0.1 -0.1'")
        return self.nudge_pan(dx, dy)

    def _cmd_crop(self, args):
        if not args:
            if self.zoom <= 1.0:
                raise CommandError(
                    "nothing to crop to — zoom in first ('x' or 'zoom 2'), "
                    "drag a rectangle on the image, or give 'crop x0 y0 x1 y1'")
            return self.push_crop((0.0, 0.0, 1.0, 1.0))
        need_args(args, 4, "crop <x0> <y0> <x1> <y1>   (0..1, or none for the zoom rect)")
        try:
            x0, y0, x1, y1 = (float(a) for a in args)
        except ValueError:
            raise CommandError("all four corners must be numbers between 0 and 1")
        x0, x1 = sorted((min(max(x0, 0.0), 1.0), min(max(x1, 0.0), 1.0)))
        y0, y1 = sorted((min(max(y0, 0.0), 1.0), min(max(y1, 0.0), 1.0)))
        if x1 - x0 < 0.01 or y1 - y0 < 0.01:
            raise CommandError("that rectangle is empty — it must be at least 1% wide")
        # Absolute, matching what the crop field shows. Re-entering the numbers
        # already on display therefore changes nothing, which is the behaviour
        # anyone editing a text field expects.
        if abs(x0 - self.crop_rect()[0]) < 1e-9 and abs(y0 - self.crop_rect()[1]) < 1e-9 \
                and abs(x1 - self.crop_rect()[2]) < 1e-9 \
                and abs(y1 - self.crop_rect()[3]) < 1e-9:
            return "crop unchanged"
        return self.push_absolute_crop((x0, y0, x1, y1))

    def _cmd_viewbox(self, args):
        need_args(args, 2, "viewbox <w> <h>")
        try:
            w, h = int(args[0]), int(args[1])
        except ValueError:
            raise CommandError("viewbox takes two whole numbers of pixels")
        self.view_size = (max(64, w), max(64, h))
        self.dirty = True
        note = ""
        if self.viewport and (w > self.viewport[0] or h > self.viewport[1]):
            note = " — larger than the canonical feed output"
        return f"view box {self.view_size[0]}x{self.view_size[1]}{note}"

    def _cmd_fill(self, args):
        self.view_size = None
        self.fit_mode = "fit"
        self.dirty = True
        return "view box back to the canonical feed's natural corrected size"

    def _cmd_refit(self, args):
        if self.capture_size is None:
            raise CommandError("no frame captured yet")
        ow, oh = full_output_size(self.profile, self.capture_size)
        x0, y0, x1, y1 = self.roi()
        self.view_size = (max(64, int(round((x1 - x0) * ow))),
                          max(64, int(round((y1 - y0) * oh))))
        self.fit_mode = "fit"
        self.dirty = True
        what = "crop" if self.crops or self.zoom > 1.0 else "view"
        return (f"view box {self.view_size[0]}x{self.view_size[1]} — the {what} "
                "now renders 1:1, with nothing scaled after the correction")

    def _cmd_straight(self, args):
        body = __doc__.split("Fixing the fisheye, in order\n")[1] \
                      .split("None of this is a calibration")[0]
        for line in body.strip().splitlines()[1:]:      # [1:] drops the ---- rule
            self.log.add(True, line.strip() or " ")
            print(line)
        return "recipe above (and in the terminal)"

    def _cmd_tuneview(self, args):
        """Put the preview in a reproducible geometry-tuning state."""
        self.correct = True
        self.show_grid = True
        self.view = "both"
        self.crops, self.zoom, self.pan = [], 1.0, (0.5, 0.5)
        self.view_size = None
        self.fit_mode = "fit"
        self.dirty = True
        return ("TUNING VIEW: full-frame raw + corrected, grid on, crop/zoom cleared; "
                "sensor and colour settings preserved")

    def _cmd_tunereset(self, args):
        """Reset only manual estimated-model trims, not the whole camera setup."""
        for name, value in MANUAL_TUNING_DEFAULTS.items():
            setattr(self.profile, name, value)
        self.profile.clamp()
        self.dirty = True
        return ("manual fisheye trims reset (k1-k4, centre, X/Y focal scale, "
                "skew, p1/p2); FOV/model/output/framing/colour preserved")

    def _cmd_sensor(self, args):
        for line in self.sensor_lines():
            self.log.add(True, line)
        return f"camera reports: {self.sensor_status}"

    def _cmd_save(self, args):
        path = Path(args[0]).expanduser() if args else self.settings_path
        self.settings_path = path
        return f"SAVED {self.write_settings(path)}"

    def _cmd_load(self, args):
        path = Path(args[0]).expanduser() if args else self.settings_path
        return self.read_settings(path)

    def _cmd_lens(self, args):
        path = Path(args[0]).expanduser() if args else self.args.profile
        return f"wrote the lens profile to {self.profile.save(path)}"

    def _cmd_snap(self, args):
        if self.last_raw is None:
            raise CommandError("no frame captured yet")
        if self.snapshot_submitter is not None:
            if self.snapshot_submitter():
                return "saving raw + corrected PNGs in the background"
            raise CommandError("snapshot writer busy — try again shortly")
        return save_snapshot(self.last_raw, self.last_corrected, self.profile)

    def _cmd_params(self, args):
        for line in self.status_lines() + self.sensor_lines():
            self.log.add(True, line)
        for line in self.colour_report().splitlines():
            self.log.add(True, line)
            print(line)
        return "current settings above"

    def _cmd_reset(self, args):
        """Back to the built-in defaults, then the CLI flags — i.e. --fresh.

        Deliberately NOT a re-read of the settings file: `reset` is what you
        press when the tuning has gone somewhere strange and you want the known
        starting point back. `load` is the one that re-reads the file, and the
        file is not touched by either.
        """
        self.profile = LensProfile()
        self.interp = DEFAULT_INTERPOLATION
        self.mip = True
        self.correct = True
        self.crops, self.zoom, self.pan = [], 1.0, (0.5, 0.5)
        self.view_size = None          # rebuild() uses the canonical natural ROI
        self.fit_mode = "fit"
        self.flip, self.rotate, self.swap_rb = "none", 0, False
        self.reset_colour()
        self.all_auto()
        apply_overrides(self, self.args)
        return ("back to the undistorted_viewer.py defaults"
                " (the settings file is untouched — 'load' re-reads it)")

    def _cmd_help(self, args):
        # The command layer cannot create widgets: terminal input may arrive on
        # its reader thread. The Tk tick notices this flag on the UI thread and
        # opens (or raises) the help window there.
        self.show_keys = True
        for line in self.commands.help_lines():
            self.log.add(True, line)
        print("\n".join(self.commands.help_lines()))
        return "help opened (commands also listed in the terminal)"

    def _cmd_quit(self, args):
        self.running = False
        return "quitting"

    # --- the JSON ----------------------------------------------------------

    def settings_dict(self):
        """Everything, as the JSON records it.

        Split into what you SET and what that produced: `derived` is recomputed
        on load and exists so whatever reads this file next does not have to
        redo the geometry to find out where the crop landed or how much detail
        survived. `load` ignores it.
        """
        stats = sampling_stats(self.maps) if self.maps else {}
        return {
            "_about": "Written by camera/camera_studio.py. 'derived' is output, "
                      "not input — editing it does nothing.",
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "camera": self.camera_name,
            "capture": {
                "backend": self.args.backend,
                "device": self.args.device,
                "width": self.capture_size[0] if self.capture_size else None,
                "height": self.capture_size[1] if self.capture_size else None,
                "swap_rb": self.swap_rb,
                "flip": self.flip,
                "rotate": self.rotate,
            },
            "lens": asdict(self.profile),
            "correction": {
                "enabled": self.correct,
                "interp": self.interp,
                "mip": self.mip,
            },
            "framing": {
                "crops": [list(c) for c in self.crops],
                "zoom": round(self.zoom, 4),
                "pan": [round(self.pan[0], 5), round(self.pan[1], 5)],
                "fit_mode": self.fit_mode,
                # Recorded for reference only. Normal startup intentionally
                # resolves the saved lens/ROI to Camera Feed's natural output;
                # an explicit live `viewbox` remains a Studio inspection tool.
                "view_size": list(self.view_size) if self.view_size else None,
            },
            "sensor": dict(self.sensor),
            "colour": self.colour.to_settings(),
            # Only present when the colour came from TUNE TO RAW PHONE IMAGE, so
            # a save-then-load keeps the score the panel shows. `camera_feed.py`
            # ignores it; only the colour block drives the runtime feed.
            **({"similarity": round(self.colour_similarity, 5)}
               if self.colour_similarity is not None else {}),
            "derived": {
                "roi": [round(v, 6) for v in self.roi()],
                "output_size": list(self.maps.out_size) if self.maps else None,
                "full_output_size": list(full_output_size(self.profile,
                                                          self.capture_size))
                                    if self.capture_size else None,
                "source_focal_px": round(self.maps.source_focal_px, 2)
                                   if self.maps else None,
                "output_camera_matrix": self.maps.output_camera_matrix.tolist()
                                        if self.maps else None,
                "sampling": {k: (round(v, 4) if isinstance(v, float) else v)
                             for k, v in stats.items()},
            },
        }

    def write_settings(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.settings_dict(), indent=2) + "\n")
        return str(path)

    def read_settings(self, path):
        """Load a settings JSON back. Tolerant of missing sections by design.

        A file written by an older version, or one hand-edited down to just the
        lens block, should still load — so every section is optional and unknown
        keys are ignored rather than fatal.
        """
        path = Path(path)
        try:
            data = json.loads(path.read_text())
        except FileNotFoundError:
            raise CommandError(f"{path} does not exist")
        except json.JSONDecodeError as exc:
            raise CommandError(f"{path} is not valid JSON: {exc}")

        lens = data.get("lens") or {}
        known = {f: lens[f] for f in LensProfile.__dataclass_fields__ if f in lens}
        self.profile = LensProfile(**known)
        self.profile.clamp()

        corr = data.get("correction") or {}
        self.correct = bool(corr.get("enabled", self.correct))
        if corr.get("interp") in INTERPOLATIONS:
            self.interp = corr["interp"]
        self.mip = bool(corr.get("mip", self.mip))

        fr = data.get("framing") or {}
        self.crops = [tuple(c) for c in fr.get("crops", [])]
        self.zoom = float(fr.get("zoom", 1.0))
        self.pan = tuple(fr.get("pan", (0.5, 0.5)))
        if fr.get("fit_mode") in FIT_MODES:
            self.fit_mode = fr["fit_mode"]
        # Deliberately NOT restored: a normal launch must resolve these saved
        # lens/ROI settings to Camera Feed's natural corrected size. `viewbox`
        # and `refit` are explicit Studio inspection choices, never UI-window
        # dimensions and never part of the canonical runtime geometry.

        cap = data.get("capture") or {}
        self.swap_rb = bool(cap.get("swap_rb", self.swap_rb))
        if cap.get("flip") in FLIPS:
            self.flip = cap["flip"]
        if cap.get("rotate") in ROTATIONS:
            self.rotate = cap["rotate"]

        for name, value in (data.get("sensor") or {}).items():
            if name in SENSOR_CONTROLS:
                self.sensor[name] = value

        try:
            self.colour = ColorCorrection.from_settings(data)
        except RuntimeError as exc:
            raise CommandError(str(exc))
        # A settings file may carry the tuned score next to its colour block
        # (e.g. one saved straight after the button), but a plain calibration
        # will not — so this is None unless the file actually recorded it.
        self.colour_similarity = data.get("similarity")
        self.colour_status = self.colour.source or (
            "loaded" if not self.colour.is_identity else "not calibrated")

        self.settings_path = path
        self.dirty = self.sensor_dirty = True

        note = ""
        want = (cap.get("width"), cap.get("height"))
        if all(want) and self.capture_size and tuple(want) != tuple(self.capture_size):
            # Not applied, because changing it means reconfiguring the sensor.
            note = (f" — NOTE it was saved at {want[0]}x{want[1]}, this session is "
                    f"{self.capture_size[0]}x{self.capture_size[1]}; relaunch with "
                    f"--width {want[0]} --height {want[1]} to match")
        return f"loaded {path}{note}"

    # --- reporting ---------------------------------------------------------

    def derived_line(self, fps=0.0):
        """The one line in the panel that is NOT a field: what the settings cost.

        Everything else down there can be typed into. These numbers are results
        — the size actually being rendered and how much real detail survived the
        correction — so they get read, not edited.
        """
        stats = sampling_stats(self.maps) if self.maps else {}
        out = self.maps.out_size if self.maps else (0, 0)
        return (f"{'CALIBRATED' if self.profile.calibrated else 'ESTIMATED (uncalibrated)'}"
                f"   rendering {out[0]}x{out[1]}"
                f"   SAMPLE src px/out px: centre {stats.get('centre', 0):.2f}"
                f"  edge {stats.get('edge', 0):.2f}"
                f"  ({stats.get('upscaled_fraction', 0) * 100:.0f}% magnified)"
                f"  mip x{stats.get('mip_levels', 1)}"
                f"   {fps:5.1f} fps")

    def status_lines(self):
        """The parameter dump, for `params`, the panel and the startup banner."""
        p = self.profile
        stats = sampling_stats(self.maps) if self.maps else {}
        x0, y0, x1, y1 = self.roi()
        out = self.maps.out_size if self.maps else (0, 0)
        return [
            f"LENS   fov {p.lens_fov_deg:.0f} deg ({p.fov_reference})  model {p.model}"
            f"  centre {p.centre_dx:+.0f},{p.centre_dy:+.0f} px",
            f"TUNE   radial {p.k1:+.3f} {p.k2:+.3f} {p.k3:+.3f} {p.k4:+.3f}"
            f"  focal XY {p.focal_x_scale:.3f},{p.focal_y_scale:.3f}"
            f"  skew {p.skew:+.4f}  tangent {p.p1:+.4f},{p.p2:+.4f}",
            f"OUT    fov {p.output_fov_deg:.0f} deg  scale {p.output_scale:.2f}"
            f"  {self.interp}  mip {'on' if self.mip else 'off'}"
            f"  correction {'ON' if self.correct else 'OFF'}",
            f"FRAME  zoom {self.zoom:.2f}x  roi {x0:.3f},{y0:.3f}-{x1:.3f},{y1:.3f}"
            f"  crops {len(self.crops)}  {self.fit_mode}  {out[0]}x{out[1]}"
            f"  flip {self.flip}  rot {self.rotate}",
            f"SAMPLE src px/out px: centre {stats.get('centre', 0):.2f}"
            f"  edge {stats.get('edge', 0):.2f}"
            f"  ({stats.get('upscaled_fraction', 0) * 100:.0f}% magnified)"
            f"  mip x{stats.get('mip_levels', 1)}",
        ]

    def colour_line(self):
        state = "ON " if self.colour.enabled else "off"
        line = f"COLOUR {state} {self.colour.describe()[7:]} | {self.colour_status}"
        if self.colour_similarity is not None:
            line += f" | {self.colour_similarity * 100:.1f}% match to raw phone"
        return line

    def sensor_lines(self):
        """One line per sensor control, three to a row to fit the panel."""
        cells = [f"{n} {self.sensor[n]}" for n in SENSOR_CONTROLS]
        rows = [cells[i:i + 4] for i in range(0, len(cells), 4)]
        lines = ["  ".join(f"{c:<20}" for c in row).rstrip() for row in rows]
        return [("SENSOR " if i == 0 else "       ") + text
                for i, text in enumerate(lines)] + \
               [f"       camera: {self.sensor_status}"]


def next_view(studio):
    return VIEWS[(VIEWS.index(studio.view) + 1) % len(VIEWS)]


# Every button is literally a command line. RAW/CORR is expanded to the next
# concrete view at click time; keeping that tiny exception here still leaves the
# command engine as the only place that mutates Studio.
BUTTONS = [
    ("SAVE JSON", "save"),
    ("SNAP PNG", "snap"),
    ("WHITE BAL", "wb"),
    ("COLOUR CAL", "colourcal"),
    ("TUNE TO RAW PHONE IMAGE", "tunetoraw"),
    ("COLOUR ON/OFF", "colour"),
    ("COLOUR INFO", "colourinfo"),
    ("COLOUR RESET", "colourreset"),
    ("ZOOM +", "zoom +0.25"),
    ("ZOOM -", "zoom -0.25"),
    ("CROP", "crop"),
    ("UNDO CROP", "uncrop"),
    ("NO CROP", "nocrop"),
    ("REFIT", "refit"),
    ("RAW/CORR", "view"),
    ("GRID", "grid"),
    ("BLOCK CALIBRATION", "blockcal"),
    ("BLOCK CAL SAVE", "blockcalsave"),
    ("BLOCK CAL OFF", "blockcaloff"),
    ("TUNE VIEW", "tuneview"),
    ("TUNE RESET", "tunereset"),
    ("TUNE GUIDE", "straight"),
    ("RESET", "reset"),
    ("HELP", "help"),
    ("QUIT", "quit"),
]


# --- input channel 1: the terminal ------------------------------------------

def start_stdin_reader(studio):
    """Feed lines typed into the launching terminal into the command set.

    A daemon thread, because there is no portable way to interrupt a blocking
    stdin read — the process must be able to exit while this is still parked in
    readline(). It only ever appends to a queue the render loop drains, so the
    parameters are still mutated from one thread.

    This is the input path that works when the window will not take focus, which
    over VNC or ssh -X is often.
    """
    if sys.stdin is None or not sys.stdin.readable():
        studio.log.add(False, "no terminal attached — use ':' in the window instead")
        return None

    def run():
        try:
            for line in sys.stdin:
                if not studio.running:
                    return
                studio.pending.append(line)
        except (ValueError, OSError):
            pass   # stdin closed under us during shutdown; nothing to do
    thread = threading.Thread(target=run, name="stdin-commands", daemon=True)
    thread.start()
    return thread


# --- field metadata shared by widgets and commands --------------------------

@dataclass(frozen=True)
class Field:
    """One labelled, editable box in the control panel.

    A field IS a command, exactly like a button is: `label` is what the user
    reads, `command` is what gets run, and the text in the box is its argument.
    That is what keeps the panel, the typed commands, the keys and the buttons
    from ever disagreeing about what a parameter means — there is one setter and
    four ways to reach it.

    `step` drives Up/Down, which is the part that replaced the sliders: a float
    steps the number, a tuple of strings cycles through the choices. `start` is
    where a numeric step begins when the current value is "auto", since there is
    no number there to add to.
    """

    label: str
    command: str
    get: object              # (studio) -> the string shown in the box
    step: object = None      # float to step by, or a tuple of choices to cycle
    chars: int = 6           # box width, in characters
    group: str = ""          # non-empty starts a new labelled row
    start: object = None     # value to jump to when stepping away from "auto"

    @property
    def choices(self):
        return self.step if isinstance(self.step, tuple) else None


def _onoff(flag):
    return "on" if flag else "off"


def _crop_text(studio):
    return " ".join(f"{v:.3f}" for v in studio.crop_rect())


def _viewbox_text(studio):
    return f"{studio.view_size[0]} {studio.view_size[1]}" if studio.view_size else "-"


# Steps and starting points for the sensor fields, which are otherwise generated
# wholesale from SENSOR_CONTROLS. Split out because a sensible step is a fact
# about the control's units, not something the table can guess: 0.1 is a real
# change in contrast and an invisible one in exposure time.
SENSOR_STEPS = {
    "brightness": (0.1, 0.0), "contrast": (0.1, 1.0), "saturation": (0.1, 1.0),
    "sharpness": (0.5, 1.0), "ev": (0.5, 0.0), "exposure": (1000.0, 10000.0),
    "gain": (0.5, 1.0), "redgain": (0.1, 1.5), "bluegain": (0.1, 1.5),
    "fps": (5.0, 30.0),
}


def build_fields():
    """The panel's fields, in the order they are laid out.

    Grouped the way the work actually goes: the lens first, because that is what
    you came here to fix; then how it is rendered; then the framing; then the
    sensor, which is set once and left alone.
    """
    fields = [
        Field("lens fov", "fov", lambda s: f"{s.profile.lens_fov_deg:.0f}",
              2.0, 5, "LENS"),
        Field("ref", "ref", lambda s: s.profile.fov_reference,
              ("diagonal", "horizontal"), 10),
        Field("model", "model", lambda s: s.profile.model, tuple(MODEL_NAMES), 13),
        Field("correction", "undistort", lambda s: _onoff(s.correct),
              ("on", "off"), 4),

        Field("k1 broad", "k1", lambda s: f"{s.profile.k1:+.3f}",
              0.01, 6, "TUNING"),
        Field("k2 edge", "k2", lambda s: f"{s.profile.k2:+.3f}", 0.01, 6),
        Field("k3 outer", "k3", lambda s: f"{s.profile.k3:+.3f}", 0.005, 6),
        Field("k4 corner", "k4", lambda s: f"{s.profile.k4:+.3f}", 0.005, 6),
        Field("centre x px", "cx", lambda s: f"{s.profile.centre_dx:+.0f}", 2.0, 5),
        Field("centre y px", "cy", lambda s: f"{s.profile.centre_dy:+.0f}", 2.0, 5),
        Field("fx scale", "fxscale", lambda s: f"{s.profile.focal_x_scale:.3f}",
              0.005, 6),
        Field("fy scale", "fyscale", lambda s: f"{s.profile.focal_y_scale:.3f}",
              0.005, 6),
        Field("skew", "skew", lambda s: f"{s.profile.skew:+.4f}", 0.002, 7),
        Field("p1 tangent", "p1", lambda s: f"{s.profile.p1:+.4f}", 0.002, 7),
        Field("p2 tangent", "p2", lambda s: f"{s.profile.p2:+.4f}", 0.002, 7),

        Field("out fov", "out", lambda s: f"{s.profile.output_fov_deg:.0f}",
              5.0, 5, "OUTPUT"),
        Field("scale", "scale", lambda s: f"{s.profile.output_scale:.2f}", 0.1, 5),
        Field("interp", "interp", lambda s: s.interp, tuple(INTERP_NAMES), 9),
        Field("mip", "mip", lambda s: _onoff(s.mip), ("on", "off"), 4),
        Field("show", "view", lambda s: s.view, VIEWS, 10),
        Field("grid", "grid", lambda s: _onoff(s.show_grid), ("on", "off"), 4),

        Field("zoom", "zoom", lambda s: f"{s.zoom:.2f}", 0.25, 5, "FRAME"),
        Field("crop x0 y0 x1 y1", "crop", _crop_text, None, 23),
        Field("sizing", "fitmode", lambda s: s.fit_mode, FIT_MODES, 7),
        Field("view box", "viewbox", _viewbox_text, None, 10),
        Field("flip", "flip", lambda s: s.flip, FLIPS, 5),
        Field("rotate", "rotate", lambda s: str(s.rotate),
              tuple(str(r) for r in ROTATIONS), 4),
    ]

    fields += [
        Field("correct", "colour", lambda s: _onoff(s.colour.enabled),
              ("on", "off"), 4, "COLOUR"),
        Field("fit", "colourmode", lambda s: s.colour_mode,
              tuple(COLOUR_FIT_MODES), 7),
        Field("R gain", "rgain", lambda s: f"{s.colour.gain[2]:.3f}", 0.02, 6),
        Field("G gain", "ggain", lambda s: f"{s.colour.gain[1]:.3f}", 0.02, 6),
        Field("B gain", "bgain", lambda s: f"{s.colour.gain[0]:.3f}", 0.02, 6),
        Field("R off", "roff", lambda s: f"{s.colour.offset[2]:+.1f}", 2.0, 6),
        Field("G off", "goff", lambda s: f"{s.colour.offset[1]:+.1f}", 2.0, 6),
        Field("B off", "boff", lambda s: f"{s.colour.offset[0]:+.1f}", 2.0, 6),
        Field("gamma", "gamma", lambda s: f"{s.colour.gamma:.2f}", 0.05, 5),
        Field("sat", "csat", lambda s: f"{s.colour.saturation:.2f}", 0.05, 5),
    ]

    for i, (name, spec) in enumerate(SENSOR_CONTROLS.items()):
        step, start = SENSOR_STEPS.get(name, (None, None))
        if spec.kind == "choice":
            # range_text, not spec.choices: it is the one that includes "auto",
            # so cycling with Up/Down can reach it like every other value.
            step, start = tuple(spec.range_text.split("|")), None
        fields.append(Field(name, name, lambda s, n=name: str(s.sensor[n]),
                            step, spec.display_chars,
                            "SENSOR" if i == 0 else "", start))
    return fields


FIELDS = build_fields()


# --- rendering ---------------------------------------------------------------

def save_snapshot(raw, corrected, profile):
    """Write both images to captures/, tagging the corrected one with its params.

    The tag matters: comparing several tuning attempts later is impossible if
    the filenames do not record what produced them.
    """
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    tag = (f"{profile.model}-lens{profile.lens_fov_deg:.0f}"
           f"-out{profile.output_fov_deg:.0f}"
           f"-k{profile.k1:+.2f}_{profile.k2:+.2f}_{profile.k3:+.2f}_{profile.k4:+.2f}"
           f"-c{profile.centre_dx:+.0f}_{profile.centre_dy:+.0f}"
           f"-f{profile.focal_x_scale:.3f}_{profile.focal_y_scale:.3f}"
           f"-s{profile.skew:+.3f}-p{profile.p1:+.3f}_{profile.p2:+.3f}")
    raw_path = CAPTURE_DIR / f"{stamp}_raw.png"
    fixed_path = CAPTURE_DIR / f"{stamp}_corrected_{tag}.png"
    cv2.imwrite(str(raw_path), raw)
    cv2.imwrite(str(fixed_path), corrected)
    return f"saved {raw_path.name} + {fixed_path.name}"


def crop_resize(img, roi, out_size, interpolation):
    """Apply the ROI to an image directly — the path used when correction is OFF.

    With the correction on, the ROI is folded into the remap and this is not
    used. With it off there is no remap to fold anything into, so cropping and
    scaling really do happen here, and really are a second resample.
    """
    h, w = img.shape[:2]
    x0 = min(max(int(round(roi[0] * w)), 0), w - 1)
    y0 = min(max(int(round(roi[1] * h)), 0), h - 1)
    x1 = min(max(int(round(roi[2] * w)), x0 + 1), w)
    y1 = min(max(int(round(roi[3] * h)), y0 + 1), h)
    sub = img[y0:y1, x0:x1]
    if out_size is None or (sub.shape[1], sub.shape[0]) == tuple(out_size):
        return sub
    shrinking = out_size[0] < sub.shape[1]
    return cv2.resize(sub, tuple(out_size),
                      interpolation=cv2.INTER_AREA if shrinking else interpolation)


def side_by_side(raw, corrected):
    """Stack raw and corrected at a common height for an A/B comparison.

    They can differ in size, so both are fitted to the shorter height rather
    than assumed to match.
    """
    h = min(raw.shape[0], corrected.shape[0])

    def fit(img):
        scale = h / img.shape[0]
        return cv2.resize(img, (max(1, round(img.shape[1] * scale)), h),
                          interpolation=cv2.INTER_AREA)

    left, right = fit(raw), fit(corrected)
    pair = np.hstack([left, right])
    cv2.line(pair, (left.shape[1], 0), (left.shape[1], h), (0, 255, 0), 1)
    cv2.putText(pair, "RAW", (8, 20), FONT, 0.5, LABEL_COLOR, 1, cv2.LINE_AA)
    cv2.putText(pair, "CORRECTED", (left.shape[1] + 8, 20), FONT, 0.5,
                LABEL_COLOR, 1, cv2.LINE_AA)
    return pair


def draw_drag(image, studio):
    """Draw only the crop geometry; detailed values belong in Tk."""
    if studio.drag is None:
        return
    (x0, y0), (x1, y1) = studio.drag
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    # Dim everything outside the selection, so the crop is judged on what will
    # actually remain rather than on a thin outline over a full-brightness frame.
    mask = np.zeros(image.shape[:2], bool)
    mask[y0:y1, x0:x1] = True
    image[~mask] = (image[~mask] * 0.45).astype(np.uint8)
    cv2.rectangle(image, (x0, y0), (x1, y1), (0, 255, 0), 1)


# --- Tk application ---------------------------------------------------------

class StudioWindow:
    """The Tk presentation layer around Studio's UI-agnostic state.

    Every mutation still goes through CommandSet. Tk owns only StringVars,
    focus, layout and scheduling; replacing this class must not change what a
    command means or what gets written to JSON.
    """

    def __init__(self, root, studio, camera):
        self.root = root
        self.studio = studio
        self.camera = camera
        self._image_layout = None
        self.preview_title = "Camera Studio - Preview"
        self._preview_created = False
        self._help_window = None
        self._after_id = None
        self._closing = False
        self._fps = 0.0
        self._capture_rate = RateMeter()
        self._preview_rate = RateMeter()
        self._last_sequence = 0
        self._last_frame_age = None
        self._autosave_state = None
        self._autosave_due_at = time.monotonic() + 0.5 if studio.autosave else None
        self._last_widget_refresh = 0.0
        self._widgets_dirty = True
        self._reflow_after = None
        self._flow_width = None
        self._map_generation = 0
        self._map_applied_generation = 0
        self._last_map_result_count = 0
        self._last_snapshot_count = 0
        self._active_input_size = tuple(studio.capture_size)
        self._requested_input_size = tuple(studio.capture_size)

        self.frame_pump = LatestFramePump(camera)
        self.map_worker = LatestValueWorker(self._build_map_value,
                                            name="studio-map-builder")
        self.snapshot_worker = SnapshotWorker(save_snapshot, name="studio-snapshot")
        self.studio.snapshot_submitter = self._queue_snapshot
        self.frame_pump.start()

        self.field_vars = []
        self.field_widgets = []
        self._field_groups = []
        self._button_widgets = []
        self.log_labels = []

        self.root.title("Camera Studio")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._configure_styles()
        self._build_widgets()
        self._bind_shortcuts()

        # Tk is controls only; the NumPy frame lives in the separate HighGUI
        # preview and therefore cannot push this panel off a small Pi display.
        self.root.update_idletasks()
        screen_w, screen_h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        requested_w = self.root.winfo_reqwidth()
        requested_h = self.root.winfo_reqheight()
        width = max(780, min(requested_w, screen_w - 80))
        height = max(420, min(requested_h, screen_h - 100))
        width, height = min(width, screen_w), min(height, screen_h)
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 3)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(min(780, screen_w), min(400, screen_h))
        self.root.resizable(True, True)
        self.root.update_idletasks()
        self._reflow_controls(force=True)

    def _configure_styles(self):
        style = ttk.Style(self.root)
        style.configure("Studio.Group.TLabel", foreground="#4678b8")
        style.configure("Studio.Derived.TLabel", foreground="#a46800")
        style.configure("Studio.Calibrated.TLabel", foreground="#187a18")
        style.configure("Studio.Status.TLabel", foreground="#555555")
        style.configure("Studio.LogOk.TLabel", foreground="#187a18")
        style.configure("Studio.LogError.TLabel", foreground="#b02020")

    def _build_widgets(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        controls = ttk.Frame(self.root, padding=(6, 5))
        controls.grid(row=0, column=0, sticky="nsew")
        self.controls = controls

        buttons = ttk.Frame(controls)
        buttons.pack(fill="x", pady=(0, 4))
        self.button_frame = buttons
        for label, command in BUTTONS:
            button = ttk.Button(buttons, text=label,
                                command=lambda line=command: self._run_button(line))
            self._button_widgets.append(button)

        fields = ttk.Frame(controls)
        fields.pack(fill="x")
        group_content = None
        group_cells = None
        for index, field in enumerate(FIELDS):
            if group_content is None or field.group:
                group_row = ttk.Frame(fields)
                group_row.pack(fill="x", pady=1)
                group_row.columnconfigure(1, weight=1)
                ttk.Label(group_row, text=field.group, width=7,
                          style="Studio.Group.TLabel").grid(
                              row=0, column=0, padx=(0, 4), sticky="nw")
                group_content = ttk.Frame(group_row)
                group_content.grid(row=0, column=1, sticky="ew")
                group_cells = []
                self._field_groups.append((group_content, group_cells))

            cell = ttk.Frame(group_content)
            ttk.Label(cell, text=field.label).pack(side="left", padx=(0, 3))
            var = tk.StringVar(value=field.get(self.studio))
            if field.choices is not None:
                widget = ttk.Combobox(cell, textvariable=var,
                                      values=field.choices, state="readonly",
                                      width=field.chars)
                widget.bind("<<ComboboxSelected>>",
                            lambda event, i=index: self._choose_field(i))
            else:
                widget = ttk.Entry(cell, textvariable=var, width=field.chars)
                widget.bind("<Return>",
                            lambda event, i=index: self._entry_commit(i))
                widget.bind("<Up>",
                            lambda event, i=index: self._entry_step(i, +1))
                widget.bind("<Down>",
                            lambda event, i=index: self._entry_step(i, -1))
                widget.bind("<Escape>",
                            lambda event, i=index: self._revert_field(i))
                widget.bind("<FocusOut>",
                            lambda event, i=index: self._revert_field(i))
            widget.pack(side="left")
            group_cells.append(cell)
            self.field_vars.append(var)
            self.field_widgets.append(widget)

        self.derived_label = ttk.Label(controls, anchor="w",
                                       style="Studio.Derived.TLabel")
        self.derived_label.pack(fill="x", pady=(4, 0))
        self.camera_label = ttk.Label(controls, anchor="w",
                                      style="Studio.Status.TLabel")
        self.camera_label.pack(fill="x")
        # Standing state, not an event: whether a colour correction is applied
        # changes what every downstream tool sees, so it must not scroll away
        # with the log.
        self.colour_label = ttk.Label(controls, anchor="w",
                                      style="Studio.Status.TLabel")
        self.colour_label.pack(fill="x")
        for _ in range(LOG_LINES):
            label = ttk.Label(controls, anchor="w", style="Studio.LogOk.TLabel")
            label.pack(fill="x")
            self.log_labels.append(label)

        command_row = ttk.Frame(controls)
        command_row.pack(fill="x", pady=(3, 0))
        ttk.Label(command_row, text="command").pack(side="left", padx=(0, 4))
        self.command_var = tk.StringVar()
        self.command_entry = ttk.Entry(command_row, textvariable=self.command_var)
        self.command_entry.pack(side="left", fill="x", expand=True)
        self.command_entry.bind("<Return>", self._submit_command)
        self.command_entry.bind("<Escape>", self._clear_command)

    @staticmethod
    def _flow_widgets(container, widgets, width, gap=4):
        """Place a horizontal widget list into as many rows as the width needs.

        A Tk grid shares column widths between every row. That sounds helpful,
        but differently sized fields then make a later row wider than the sum
        used to wrap it. Explicit row positions keep the right edge honest at
        narrow window sizes.
        """
        x = y = line_height = 0
        for widget in widgets:
            if widget.winfo_manager() == "grid":
                widget.grid_forget()
            else:
                widget.place_forget()
            widget_width = widget.winfo_reqwidth()
            widget_height = widget.winfo_reqheight()
            if x and x + widget_width > width:
                x = 0
                y += line_height + 2
                line_height = 0
            widget.place(x=x, y=y, width=widget_width, height=widget_height)
            x += widget_width + gap
            line_height = max(line_height, widget_height)
        container.configure(height=max(1, y + line_height + 2))

    def _reflow_controls(self, force=False):
        """Wrap buttons and fields whenever the application width changes."""
        width = max(320, self.controls.winfo_width() - 12)
        if not force and width == self._flow_width:
            return
        self._flow_width = width
        self._flow_widgets(self.button_frame, self._button_widgets, width)
        for content, cells in self._field_groups:
            actual = content.winfo_width()
            group_width = max(240, actual if actual > 100 else width - 70)
            self._flow_widgets(content, cells, min(width - 70, group_width), gap=7)

    def _window_resized(self, event):
        if event.widget is not self.root or self._closing:
            return
        if self._reflow_after is not None:
            self.root.after_cancel(self._reflow_after)
        self._reflow_after = self.root.after_idle(self._finish_reflow)

    def _finish_reflow(self):
        self._reflow_after = None
        self._reflow_controls()

    def _execute(self, line, *, echo_terminal=False):
        """Run one command and put its own result into the shared log."""
        result = self.studio.commands.execute(line)
        self.studio.log.push(result)
        if result is not None and echo_terminal:
            print(("OK: " if result.ok else "ERR: ") + result.message)
        if self.studio.show_keys:
            self.studio.show_keys = False
            self.show_help()
        self._widgets_dirty = True
        if self.studio.autosave:
            self._autosave_due_at = time.monotonic() + 0.5
        return result

    def _run_button(self, line):
        if line == "view":
            line = f"view {next_view(self.studio)}"
        self._execute(line)

    def _entry_commit(self, index):
        field = FIELDS[index]
        value = self.field_vars[index].get().strip()
        if value:
            self._execute(f"{field.command} {value}")
        self.field_vars[index].set(field.get(self.studio))
        return "break"

    def _entry_step(self, index, direction):
        field = FIELDS[index]
        if field.step is None:
            self.studio.log.add(False, f"{field.label} has no step — type a value instead")
            return "break"
        if field.get(self.studio) == AUTO and field.start is not None:
            # There is no number to add to in auto mode. The metadata supplies a
            # useful first manual value, exactly as the old field editor did.
            value = f"{field.start:g}"
        else:
            sign = "+" if direction > 0 else "-"
            value = f"{sign}{abs(field.step):g}"
        self._execute(f"{field.command} {value}")
        self.field_vars[index].set(field.get(self.studio))
        return "break"

    def _choose_field(self, index):
        field = FIELDS[index]
        self._execute(f"{field.command} {self.field_vars[index].get()}")

    def _revert_field(self, index):
        self.field_vars[index].set(FIELDS[index].get(self.studio))
        return "break"

    def _submit_command(self, event=None):
        line = self.command_var.get().strip()
        if line:
            self._execute(line)
        self.command_var.set("")
        return "break"

    def _clear_command(self, event=None):
        self.command_var.set("")
        return "break"

    def _focused_widget(self):
        """Return the focused Python widget, including an open Combobox owner.

        ttk builds each dropdown as a private Tcl widget named
        ``<combobox>.popdown``. It is deliberately absent from Tkinter's Python
        widget tree, so ``focus_get()`` raises ``KeyError('popdown')`` while the
        list is open. Resolve that raw Tcl path back to its Combobox: besides
        avoiding the crash, this makes the live refresh leave the active choice
        alone until Tk reports ``<<ComboboxSelected>>``.
        """
        try:
            return self.root.focus_get()
        except KeyError:
            try:
                focus_path = str(self.root.tk.call("focus"))
            except tk.TclError:
                return None
            for widget in self.field_widgets:
                widget_path = str(widget)
                if focus_path.startswith(widget_path + ".popdown"):
                    return widget
            return None
        except tk.TclError:
            return None

    def _refresh_widgets(self, *, force=False):
        # A throttled refresh makes terminal commands, shortcuts and buttons
        # visible in the fields. The focused widget is load-bearing:
        # replacing its StringVar while somebody types would make entries lose
        # half-written values at camera frame rate.
        now = time.monotonic()
        if not force and not self._widgets_dirty and now - self._last_widget_refresh < 0.2:
            return
        self._widgets_dirty = False
        self._last_widget_refresh = now
        focused = self._focused_widget()
        for field, var, widget in zip(FIELDS, self.field_vars, self.field_widgets):
            if widget is not focused:
                value = field.get(self.studio)
                if var.get() != value:
                    var.set(value)

        self.derived_label.configure(
            text=self.studio.derived_line(self._fps),
            style=("Studio.Calibrated.TLabel" if self.studio.profile.calibrated
                   else "Studio.Derived.TLabel"))
        age = ("waiting" if self._last_frame_age is None else
               f"{self._last_frame_age * 1000:.0f} ms old")
        self.camera_label.configure(
            text=(f"camera: {self.studio.sensor_status} | capture "
                  f"{self._capture_rate.rate:5.1f} fps | preview "
                  f"{self._preview_rate.rate:5.1f} fps | {age}"))
        self.colour_label.configure(
            text=self.studio.colour_line(),
            style=("Studio.Calibrated.TLabel" if self.studio.colour.enabled
                   else "Studio.Status.TLabel"))
        recent = self.studio.log.recent(count=LOG_LINES, max_age=12.0)
        padded = [(True, "")] * (LOG_LINES - len(recent)) + recent
        for label, (ok, message) in zip(self.log_labels, padded):
            label.configure(text=message,
                            style=("Studio.LogOk.TLabel" if ok
                                   else "Studio.LogError.TLabel"))

    def _bind_shortcuts(self):
        self.root.bind("<KeyPress>", self._shortcut)
        self.root.bind("<Configure>", self._window_resized, add="+")

    @staticmethod
    def _is_text_widget(widget):
        return widget is not None and widget.winfo_class() in {
            "Entry", "TEntry", "TCombobox"
        }

    def _shortcut(self, event):
        # Root bindings also run after a child widget's class binding. Guarding
        # on focus is therefore essential: without it, typing 158 into an Entry
        # would also fire the 1, 5 and 8 lens shortcuts.
        if not getattr(event, "opencv", False) and self._is_text_widget(self._focused_widget()):
            return None

        p = self.studio.profile
        char = event.char
        keysym = event.keysym
        line = None
        if char == ":":
            self.command_entry.focus_set()
            return "break"
        if char == "?":
            line = "help"
        elif char == "[":
            line = "fov -2"
        elif char == "]":
            line = "fov +2"
        elif char == "-":
            line = "out -5"
        elif char in ("=", "+"):
            line = "out +5"
        elif char == ",":
            line = "scale -0.1"
        elif char == ".":
            line = "scale +0.1"
        elif char in "12345678":
            line = {
                "1": "k1 -0.01", "2": "k1 +0.01",
                "3": "k2 -0.01", "4": "k2 +0.01",
                "5": "cx -2", "6": "cx +2",
                "7": "cy -2", "8": "cy +2",
            }[char]
        elif char == "m":
            model = MODEL_NAMES[(MODEL_NAMES.index(p.model) + 1) % len(MODEL_NAMES)]
            line = f"model {model}"
        elif char == "i":
            interp = INTERP_NAMES[(INTERP_NAMES.index(self.studio.interp) + 1)
                                  % len(INTERP_NAMES)]
            line = f"interp {interp}"
        elif char == "n":
            line = "undistort"
        elif char == "x":
            line = f"zoom {self.studio.zoom * 1.25:g}"
        elif char == "z":
            line = f"zoom {self.studio.zoom / 1.25:g}"
        elif char == "0":
            self._execute("zoom 1")
            line = "pan centre"
        elif keysym == "Left":
            line = "pan -0.1 0"
        elif keysym == "Right":
            line = "pan 0.1 0"
        elif keysym == "Up":
            line = "pan 0 -0.1"
        elif keysym == "Down":
            line = "pan 0 0.1"
        elif char == "c":
            line = "crop"
        elif keysym == "BackSpace":
            line = "uncrop"
        elif char == "f":
            line = "refit"
        elif char == "v":
            mode = FIT_MODES[(FIT_MODES.index(self.studio.fit_mode) + 1)
                             % len(FIT_MODES)]
            line = f"fitmode {mode}"
        elif char == "u":
            line = f"view {next_view(self.studio)}"
        elif char == "g":
            line = "grid"
        elif char == "s":
            line = "save"
        elif char == "p":
            line = "snap"
        elif char == "r":
            line = "reset"
        elif char == "q" or keysym == "Escape":
            line = "quit"

        if line is not None:
            self._execute(line)
            return "break"
        if char and char.isprintable():
            self.studio.log.add(False, f"key '{char}' is not bound — press '?' for help")
        return None

    def _widget_to_image(self, x, y):
        """OpenCV preview coordinates -> pixels in the rendered image."""
        lay = self._image_layout
        if lay is None:
            return None
        if not (0 <= x < lay["image_w"] and 0 <= y < lay["image_h"]):
            return None
        return (min(lay["render_w"] - 1,
                    int(x * lay["render_w"] / lay["image_w"])),
                min(lay["render_h"] - 1,
                    int(y * lay["render_h"] / lay["image_h"])))

    def _drag_start(self, point):
        if point is None:
            return
        if self.studio.view == "both":
            self.studio.log.add(False, "cropping needs a single view — press 'u'")
            return
        self.studio.drag = (point, point)

    def _drag_move(self, point):
        if self.studio.drag is None:
            return
        if point is not None:
            self.studio.drag = (self.studio.drag[0], point)

    def _drag_end(self, point):
        if self.studio.drag is None:
            return
        if point is not None:
            self.studio.drag = (self.studio.drag[0], point)
        (sx, sy), (ex, ey) = self.studio.drag
        self.studio.drag = None
        x0, x1 = sorted((sx, ex))
        y0, y1 = sorted((sy, ey))
        if x1 - x0 < MIN_CROP_PX or y1 - y0 < MIN_CROP_PX:
            self.studio.log.add(False, "that drag was too small to be a crop — "
                                f"drag a box at least {MIN_CROP_PX} px across")
            return
        lay = self._image_layout
        rect = (x0 / lay["render_w"], y0 / lay["render_h"],
                x1 / lay["render_w"], y1 / lay["render_h"])
        vx0, vy0, vx1, vy1 = self.studio.roi()
        vw, vh = vx1 - vx0, vy1 - vy0
        absolute = (vx0 + rect[0] * vw, vy0 + rect[1] * vh,
                    vx0 + rect[2] * vw, vy0 + rect[3] * vh)
        # A drag is another command source. Use the absolute crop syntax so its
        # normalisation, composition and validation stay in the command layer.
        # The pointer rectangle is relative to the currently visible ROI, so it
        # must be composed into full-output coordinates before that command.
        self._execute("crop " + " ".join(f"{v:.9f}" for v in absolute))

    def _drag_cancel(self, event=None):
        self.studio.drag = None
        self.studio.log.add(True, "crop drag cancelled")

    def _opencv_mouse(self, event, x, y, _flags, _param=None):
        point = self._widget_to_image(x, y)
        if event == cv2.EVENT_LBUTTONDOWN:
            self._drag_start(point)
        elif event == cv2.EVENT_MOUSEMOVE and self.studio.drag is not None:
            self._drag_move(point)
        elif event == cv2.EVENT_LBUTTONUP:
            self._drag_end(point)
        elif event == cv2.EVENT_RBUTTONDOWN:
            self._drag_cancel()

    def _create_preview(self):
        if self._preview_created:
            return
        cv2.namedWindow(self.preview_title, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(self.preview_title, self._opencv_mouse)
        self._preview_created = True

    def _push_image(self, frame):
        self._create_preview()
        render_h, render_w = frame.shape[:2]
        scale = float(self.studio.args.display_scale)
        if self.studio.preview_size is not None:
            scale = min(self.studio.preview_size[0] / render_w,
                        self.studio.preview_size[1] / render_h)
        iw, ih = max(1, round(render_w * scale)), max(1, round(render_h * scale))
        shown = frame
        if (iw, ih) != (render_w, render_h):
            shown = cv2.resize(
                frame, (iw, ih),
                interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR)
        self._image_layout = {
            "image_w": iw, "image_h": ih,
            "render_w": render_w, "render_h": render_h,
        }
        cv2.imshow(self.preview_title, shown)

    def _pump_preview(self):
        if not self._preview_created:
            return
        key = cv2.waitKeyEx(1)
        if key >= 0:
            # waitKeyEx preserves special keys, but their values differ between
            # GTK/X11 and Win32. Keep the command layer platform-independent.
            keysym = {
                27: "Escape", 10: "Return", 13: "Return",
                8: "BackSpace", 127: "BackSpace",
                65361: "Left", 2424832: "Left",
                65362: "Up", 2490368: "Up",
                65363: "Right", 2555904: "Right",
                65364: "Down", 2621440: "Down",
            }.get(key, "")
            char = (chr(key) if 0 <= key < 256
                    and key not in (8, 10, 13, 27, 127) else "")
            event = type("OpenCVKey", (), {
                "char": char, "keysym": keysym, "opencv": True})()
            self._shortcut(event)
        try:
            visible = cv2.getWindowProperty(self.preview_title, cv2.WND_PROP_VISIBLE)
        except cv2.error:
            visible = -1
        if visible < 1:
            self.close()

    def _autosave(self):
        if (not self.studio.autosave or self._autosave_due_at is None
                or time.monotonic() < self._autosave_due_at):
            return
        if self.studio.dirty or self._map_applied_generation < self._map_generation:
            self._autosave_due_at = time.monotonic() + 0.1
            return
        self._autosave_due_at = None
        settings = self.studio.settings_dict()
        state = json.dumps([settings[k] for k in
                            ("lens", "correction", "framing", "sensor", "capture")],
                           default=str)
        if state != self._autosave_state:
            self._autosave_state = state
            self.studio.write_settings(self.studio.settings_path)

    def _queue_snapshot(self):
        if self.studio.last_raw is None or self.studio.last_corrected is None:
            return False
        profile = LensProfile(**asdict(self.studio.profile))
        return self.snapshot_worker.submit(
            self.studio.last_raw.copy(), self.studio.last_corrected.copy(), profile)

    @staticmethod
    def _build_map_value(profile, input_size, interpolation, mip, roi, view_size):
        maps = build_maps(profile, input_size, interpolation, mip=mip,
                          roi=roi, view_size=view_size)
        return tuple(input_size), maps

    def _request_map_rebuild(self, input_size):
        self.studio.capture_size = tuple(input_size)
        self._requested_input_size = tuple(input_size)
        profile = LensProfile(**asdict(self.studio.profile))
        self._map_generation += 1
        self.map_worker.submit(
            self._map_generation, profile, tuple(input_size), self.studio.interp,
            self.studio.mip, tuple(self.studio.roi()), self.studio.render_size())
        self.studio.dirty = False

    def _poll_background_work(self):
        result = self.map_worker.snapshot()
        if result.completed_count != self._last_map_result_count:
            self._last_map_result_count = result.completed_count
            if result.generation == self._map_generation:
                if result.error:
                    self.studio.log.add(False, result.error)
                elif result.value is not None:
                    input_size, maps = result.value
                    self.studio.maps = maps
                    self.studio.capture_size = tuple(input_size)
                    self._active_input_size = tuple(input_size)
                    self._map_applied_generation = result.generation
                    if self.studio.view_size is None:
                        self.studio.viewport = tuple(maps.out_size)
                    self._widgets_dirty = True

        snapshot = self.snapshot_worker.snapshot()
        if snapshot.completed_count != self._last_snapshot_count:
            self._last_snapshot_count = snapshot.completed_count
            if snapshot.error:
                self.studio.log.add(False, snapshot.error)
            elif snapshot.result is not None:
                self.studio.log.add(True, str(snapshot.result))
            self._widgets_dirty = True

    def show_help(self):
        if self._help_window is not None and self._help_window.winfo_exists():
            self._help_window.deiconify()
            self._help_window.lift()
            return
        win = tk.Toplevel(self.root)
        win.title("Camera Studio Help")
        win.geometry("900x650")
        self._help_window = win
        frame = ttk.Frame(win, padding=8)
        frame.pack(fill="both", expand=True)
        text = tk.Text(frame, wrap="none", font="TkFixedFont")
        scroll_y = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        scroll_x = ttk.Scrollbar(frame, orient="horizontal", command=text.xview)
        text.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        text.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        keys = __doc__.split("Keys\n----", 1)[1].split("Commands\n--------", 1)[0]
        body = "KEYBOARD SHORTCUTS\n" + keys.strip() + "\n\nCOMMANDS\n" + \
               "\n".join(self.studio.commands.help_lines())
        text.insert("1.0", body)
        text.configure(state="disabled")
        ttk.Button(frame, text="CLOSE", command=win.destroy).grid(
            row=2, column=0, pady=(6, 0), sticky="e")

    def tick(self):
        """Present each unique captured frame and keep both UIs responsive."""
        if self._closing or not self.studio.running:
            self.close()
            return
        try:
            for line in self.studio.drain_pending():
                self._execute(line, echo_terminal=True)
            self._poll_background_work()

            if self.studio.sensor_dirty:
                self.studio.log.add(
                    True, f"sensor: {self.studio.apply_sensor(self.camera)}")
                self._widgets_dirty = True

            snapshot = self.frame_pump.snapshot()
            self._last_frame_age = snapshot.age_s()
            new_frame = (snapshot.frame is not None
                         and snapshot.sequence != self._last_sequence)
            frame = None
            target_input = self._active_input_size
            if new_frame:
                self._last_sequence = snapshot.sequence
                self._capture_rate.tick()
                frame = snapshot.frame
                if self.studio.swap_rb:
                    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                frame = self.studio.orient(frame)
                # Keep the uncorrected frame: `wb` and `colourcal` measure the
                # camera's cast, and measuring it through a correction that is
                # already removing it would fold the correction into itself a
                # second time every press.
                self.studio.last_capture = frame
                frame = self.studio.colour.apply(frame)
                target_input = frame.shape[1::-1]

            if self.studio.dirty:
                self._request_map_rebuild(target_input)
            elif (target_input != self._active_input_size
                  and target_input != self._requested_input_size):
                self._request_map_rebuild(target_input)

            # A size-changing rotation needs its matching maps before display;
            # ordinary parameter rebuilds may safely keep showing the previous
            # valid map until the latest background result arrives.
            if (new_frame and target_input == self._active_input_size
                    and self.studio.maps is not None):
                if self.studio.correct:
                    corrected = undistort(frame, self.studio.maps)
                else:
                    corrected = crop_resize(
                        frame, self.studio.roi(), self.studio.maps.out_size,
                        INTERPOLATIONS[self.studio.interp])
                self.studio.last_raw, self.studio.last_corrected = frame, corrected

                if self.studio.view in ("both", "raw"):
                    raw_view = crop_resize(
                        frame, self.studio.roi(), self.studio.maps.out_size,
                        INTERPOLATIONS[self.studio.interp])
                    if self.studio.view == "both":
                        raw_view, corrected_view = raw_view.copy(), corrected.copy()
                        if self.studio.show_grid:
                            draw_grid(raw_view, 8, 8)
                            draw_grid(corrected_view, 8, 8)
                        image = side_by_side(raw_view, corrected_view)
                    else:
                        image = raw_view.copy()
                        if self.studio.show_grid:
                            draw_grid(image, 8, 8)
                else:
                    image = corrected.copy()
                    if self.studio.show_grid:
                        draw_grid(image, 8, 8)
                    # Only on the corrected single view: the lattice was fitted
                    # to corrected pixels, so drawing it over a raw or
                    # side-by-side frame would put it in the wrong place.
                    if self.studio.block_lattice is not None:
                        try:
                            draw_color_grid(image, self.studio.block_lattice,
                                            labels=True, shade=0.28)
                        except (ColorGridError, ValueError):
                            self.studio.block_lattice = None
                draw_drag(image, self.studio)
                self._push_image(image)
                self._preview_rate.tick()
                self._fps = self._preview_rate.rate

            self._pump_preview()
            self._refresh_widgets()
            self._autosave()
        except Exception as exc:
            print(f"Camera Studio stopped: {exc!r}")
            self.studio.log.add(False, f"stopped: {exc!r}")
            self.close()
            return

        if self.studio.running:
            self._after_id = self.root.after(2, self.tick)
        else:
            self.close()

    def close(self):
        if self._closing:
            return
        self._closing = True
        self.studio.running = False
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        if self._reflow_after is not None:
            try:
                self.root.after_cancel(self._reflow_after)
            except tk.TclError:
                pass
            self._reflow_after = None
        self.studio.snapshot_submitter = None
        self.map_worker.stop()
        self.snapshot_worker.stop(finish=True)
        if self.frame_pump.stop():
            self.camera.release()
        else:
            print("Camera Studio capture is still blocked; leaving it for process shutdown.",
                  file=sys.stderr)
        if self._preview_created:
            try:
                cv2.destroyWindow(self.preview_title)
            except cv2.error:
                pass
            self._preview_created = False
        try:
            self.root.destroy()
        except tk.TclError:
            pass


# --- setup -------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--backend", choices=["auto", "picamera2", "v4l2"], default="auto")
    parser.add_argument("--device", help="V4L2 path, e.g. /dev/video0 (skips the picker)")
    parser.add_argument("--width", type=int,
                        help=f"capture width (default {DEFAULT_SIZE[0]})")
    parser.add_argument("--height", type=int,
                        help=f"capture height (default {DEFAULT_SIZE[1]})")
    parser.add_argument("--hq", action="store_true",
                        help=f"capture the full {FULL_RES_SIZE[0]}x{FULL_RES_SIZE[1]} "
                             "sensor readout and render a half-size output: same "
                             "field of view, ~2x the real detail at the frame edges, "
                             "and the only thing that makes zooming worthwhile")
    parser.add_argument("--window", metavar="WxH", type=parse_size,
                        help="display-only bounding box for the OpenCV preview, "
                             "e.g. 800x600; processing geometry is unchanged")
    parser.add_argument("--display-scale", type=float, default=1.0,
                        help="display-only OpenCV preview scale (default 1.0)")
    parser.add_argument("--opencv-threads", type=int, default=2,
                        help="OpenCV worker threads (default: 2)")
    parser.add_argument("--list-modes", action="store_true",
                        help="print the sensor's modes and exit")

    files = parser.add_argument_group("files")
    files.add_argument("--settings", type=Path, default=SETTINGS_PATH,
                       help="the settings JSON — READ at startup if it exists, "
                            f"and what 'save' writes (default {SETTINGS_PATH})")
    files.add_argument("--fresh", action="store_true",
                       help="ignore the settings file and start from the "
                            "built-in defaults (which are undistorted_viewer.py's)")
    files.add_argument("--autosave", action="store_true",
                       help="save the newest settings after a 500 ms debounce")
    files.add_argument("--profile", type=Path, default=PROFILE_PATH,
                       help="lens profile the 'lens' command writes, for the other tools")

    lens = parser.add_argument_group("lens correction (all tunable live)")
    lens.add_argument("--lens-fov", type=float,
                      help="quoted lens FOV in degrees (default 160)")
    lens.add_argument("--fov-reference", choices=["diagonal", "horizontal"],
                      help="whether --lens-fov is the diagonal or horizontal FOV")
    lens.add_argument("--model", choices=MODEL_NAMES,
                      help="assumed fisheye projection curve (default equidistant)")
    lens.add_argument("--k1", type=float,
                      help="radial trim, edge-weighted (-0.5..0.5, default 0)")
    lens.add_argument("--k2", type=float,
                      help="radial trim, corner-weighted (-0.5..0.5, default 0)")
    lens.add_argument("--k3", type=float,
                      help="radial trim, extreme-edge weighted (-0.5..0.5, default 0)")
    lens.add_argument("--k4", type=float,
                      help="radial trim, extreme-corner weighted (-0.5..0.5, default 0)")
    lens.add_argument("--centre-x", type=float,
                      help="source optical-centre X offset in pixels")
    lens.add_argument("--centre-y", type=float,
                      help="source optical-centre Y offset in pixels")
    lens.add_argument("--focal-x-scale", type=float,
                      help="source X focal multiplier (0.5..1.5, default 1)")
    lens.add_argument("--focal-y-scale", type=float,
                      help="source Y focal multiplier (0.5..1.5, default 1)")
    lens.add_argument("--skew", type=float,
                      help="source X shear (-0.25..0.25, default 0)")
    lens.add_argument("--p1", type=float,
                      help="tangential/decentring trim (-0.25..0.25, default 0)")
    lens.add_argument("--p2", type=float,
                      help="tangential/decentring trim (-0.25..0.25, default 0)")
    lens.add_argument("--output-fov", type=float,
                      help="diagonal FOV of the rectilinear output (default 120)")
    lens.add_argument("--output-scale", type=float,
                      help="render resolution of the correction, relative to capture")
    lens.add_argument("--interp", choices=INTERP_NAMES,
                      help=f"resampling kernel (default {DEFAULT_INTERPOLATION})")
    lens.add_argument("--no-mip", action="store_true",
                      help="skip pyramid filtering of the regions the correction "
                           "shrinks: faster, but those regions alias")
    lens.add_argument("--no-correct", action="store_true",
                      help="start with the correction off (raw geometry)")

    frame = parser.add_argument_group("framing")
    frame.add_argument("--fit", choices=list(FIT_MODES),
                       help="fit (the default): render into an explicit view box; "
                            "native: render the crop at its natural size. Neither "
                            "mode derives processing size from a UI window")
    frame.add_argument("--flip", choices=list(FLIPS),
                       help="mirror the captured frame")
    frame.add_argument("--rotate", type=int, choices=list(ROTATIONS),
                       help="rotate the captured frame")
    frame.add_argument("--swap-rb", action="store_true",
                       help="fix inverted red/blue channels")

    sensor = parser.add_argument_group(
        "sensor at startup (Picamera2; all of these are also live commands)")
    sensor.add_argument("--sharpness", type=float, help="ISP sharpening, 0 = off")
    sensor.add_argument("--denoise", choices=["off", "fast", "hq"])
    sensor.add_argument("--shutter", type=int, metavar="US",
                        help="fixed exposure time in microseconds")
    sensor.add_argument("--gain", type=float, help="fixed analogue gain")
    sensor.add_argument("--awb", help="white balance preset, e.g. tungsten, daylight")
    return parser.parse_args()


def parse_size(text):
    """WxH -> (w, h), for --window. Raises argparse's own error on anything else."""
    try:
        w, h = text.lower().replace(" ", "").split("x")
        return (max(320, int(w)), max(240, int(h)))
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"'{text}' is not a size — write it as WIDTHxHEIGHT, e.g. 1600x900")


def capture_size(args):
    """Resolve the capture resolution from --hq and any explicit --width/--height."""
    default = FULL_RES_SIZE if args.hq else DEFAULT_SIZE
    return (args.width or default[0], args.height or default[1])


def apply_overrides(studio, args):
    """Lay the CLI flags over whatever the settings file supplied.

    The precedence chain, lowest first:

      1. the built-in defaults in Studio.__init__ and LensProfile — which are
         chosen to be exactly what undistorted_viewer.py renders;
      2. config/lens_profile.json, the lens parameters the OTHER tools read;
      3. the settings file (--settings), read at startup when it exists;
      4. these flags.

    A flag left off is None and overrides nothing, which is why the framing and
    interpolation flags have no argparse default — a default would be
    indistinguishable from an explicit value and would silently outrank the file.
    The store_true flags are the exception: they can only turn a thing on, never
    leave it alone, but "off" is also the do-nothing case for all of them.

    Returns the names of everything it overrode, for the startup banner.
    """
    changed = []
    for attr, value in (
        ("lens_fov_deg", getattr(args, "lens_fov", None)),
        ("fov_reference", getattr(args, "fov_reference", None)),
        ("model", getattr(args, "model", None)),
        ("k1", getattr(args, "k1", None)),
        ("k2", getattr(args, "k2", None)),
        ("k3", getattr(args, "k3", None)),
        ("k4", getattr(args, "k4", None)),
        ("centre_dx", getattr(args, "centre_x", None)),
        ("centre_dy", getattr(args, "centre_y", None)),
        ("focal_x_scale", getattr(args, "focal_x_scale", None)),
        ("focal_y_scale", getattr(args, "focal_y_scale", None)),
        ("skew", getattr(args, "skew", None)),
        ("p1", getattr(args, "p1", None)),
        ("p2", getattr(args, "p2", None)),
        ("output_fov_deg", getattr(args, "output_fov", None)),
        ("output_scale", getattr(args, "output_scale", None)),
    ):
        if value is not None:
            setattr(studio.profile, attr, value)
            changed.append(f"{attr}={value}")
    if args.hq and getattr(args, "output_scale", None) is None:
        # Render half the capture resolution, so --hq keeps the familiar
        # 1296x972 output but feeds it from four times as many sensor pixels.
        studio.profile.output_scale = 0.5
        changed.append("output_scale=0.5 (--hq)")
    studio.profile.clamp()

    for attr, value, label in (("interp", args.interp, "interp"),
                               ("fit_mode", args.fit, "fit"),
                               ("flip", args.flip, "flip"),
                               ("rotate", args.rotate, "rotate")):
        if value is not None:
            setattr(studio, attr, value)
            changed.append(f"{label}={value}")
    if args.window is not None:
        studio.preview_size = tuple(args.window)
        changed.append(f"window={args.window[0]}x{args.window[1]}")
    for flag, attr, value, label in ((args.no_mip, "mip", False, "mip=off"),
                                     (args.no_correct, "correct", False, "correction=off"),
                                     (args.swap_rb, "swap_rb", True, "swap_rb=on")):
        if flag:
            setattr(studio, attr, value)
            changed.append(label)

    # The sensor flags are applied at configure time too (build_controls), but
    # the studio has to know about them or the first `save` would record them as
    # "auto" and the JSON would disagree with the picture on screen.
    for name, value in (("sharpness", args.sharpness), ("denoise", args.denoise),
                        ("exposure", args.shutter), ("gain", args.gain),
                        ("awb", args.awb)):
        if value is not None:
            studio.sensor[name] = value
            changed.append(f"{name}={value}")

    studio.dirty = studio.sensor_dirty = True
    return changed


def main():
    args = parse_args()
    if args.display_scale <= 0 or args.opencv_threads <= 0:
        print("--display-scale and --opencv-threads must be positive",
              file=sys.stderr)
        return 1
    cv2.setNumThreads(args.opencv_threads)
    # Step 2 of the precedence chain in apply_overrides: the lens profile the
    # other tools read. The settings file, if there is one, lands on top of this
    # once the camera is open and the capture size is known.
    studio = Studio(args, LensProfile.load(args.profile))

    controls = build_controls(args.sharpness, args.denoise, args.shutter,
                              args.gain, args.awb)
    try:
        camera = open_camera(args.backend, capture_size(args), args.device, controls)
    except RuntimeError as exc:
        print(exc)
        sys.exit(1)

    if args.list_modes:
        print("\n".join(describe_sensor_modes(getattr(camera, "sensor_modes", None))))
        camera.release()
        return

    studio.camera_name = camera.name
    # Set before the load rather than by rebuild(), because read_settings needs
    # the capture size to tell you when a file was saved at a different one.
    studio.capture_size = camera.size

    if args.fresh:
        print("--fresh: ignoring the settings file, using the built-in defaults")
    elif args.settings.exists():
        try:
            print(studio.read_settings(args.settings))
        except CommandError as exc:
            print(f"{args.settings}: {exc}\n  carrying on with the defaults.")
    else:
        print(f"No settings file at {args.settings} yet — starting from the "
              "defaults. 'save' creates it.")

    overridden = apply_overrides(studio, args)
    if overridden:
        print("Command line overrode: " + ", ".join(overridden))
    studio.rebuild(camera.size)

    print(f"Camera: {camera.name}")
    for line in studio.status_lines():
        print("  " + line)
    print("\nCommands — type them right here in this terminal, then Enter:")
    print("\n".join(studio.commands.help_lines()))
    print("\nThe command entry is at the bottom of the Tk window; '?' opens help.")
    print(f"'save' writes {studio.settings_path}\n")

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        camera.release()
        print(f"Cannot open the Tk window: {exc}")
        print("A desktop display is required (the Pi also needs python3-tk).")
        sys.exit(1)

    window = StudioWindow(root, studio, camera)
    start_stdin_reader(studio)
    window._refresh_widgets()
    window._after_id = root.after(0, window.tick)
    try:
        root.mainloop()
    finally:
        window.close()


if __name__ == "__main__":
    main()
