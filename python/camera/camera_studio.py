#!/usr/bin/env python3
"""Live camera + fisheye tuning bench, with a control panel and a JSON save.

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
the tool picks up where it left off. The committed default in that file is
exactly what undistorted_viewer.py renders, so a first run — or a run after
`--fresh`, or after `reset` — shows the same picture that tool does: the same
lens profile, the same 120-degree rectilinear output at the same size,
correction on, no zoom, no crop, no grid.

Four layers, each overriding the one before:

  1. the built-in defaults (undistorted_viewer.py's);
  2. config/lens_profile.json, the lens parameters the OTHER tools read;
  3. config/camera_settings.json, or whatever --settings names;
  4. the command-line flags.

The window is the image — as big as the capture allows — with a control panel
under it: a row of clickable buttons, then a labelled TEXT FIELD for every
parameter. Click a field, type a value, press Enter, and the picture changes as
you watch. Up/Down step it without typing. Drag a rectangle on the image to crop
to it.

It opens showing EXACTLY what undistorted_viewer.py shows: the same lens
profile, the same 120-degree rectilinear output at the same size, correction on,
no zoom, no crop, no grid. Everything below is a departure from that, and
`reset` gets back to it.

Zoom and crop are not what they usually are
-------------------------------------------
They are folded into the correction's lookup table rather than applied to the
finished image, so a 2x zoom re-renders that part of the field straight from the
sensor frame instead of enlarging pixels that were already interpolated once.
The SAMPLE line reports the real cost: at zoom 2 you should see `centre` roughly
halve, and if it drops well under 1.00 the answer is `--hq`, not a sharper
interpolation kernel.

Three ways to drive it
----------------------
OpenCV only delivers keystrokes while the *image window* has focus — not the
terminal, and over VNC or ssh -X often not until the window has been clicked.
"I press keys and nothing happens" is nearly always that. So there are four
input channels, and every one of them echoes what it did into the panel:

  1. TYPE IN THE TERMINAL. Commands typed into the shell that launched this tool
     are read from stdin and applied. This needs no window focus at all and is
     the one that always works. Try `help`.
  2. TYPE IN THE WINDOW. Press ':' to open a prompt in the panel, type a
     command, press Enter. Each character appears as it arrives, so if nothing
     appears the window does not have focus.
  3. CLICK AND TYPE. Click any field in the panel and it becomes editable —
     type, Enter commits, Esc cancels, Tab moves to the next field, and Up/Down
     step the value in place without typing at all. Choice fields (model,
     interp, awb...) accept any unambiguous prefix, so `equi` is enough.
  4. CLICK AND DRAG. The buttons under the image, and a drag on the image to
     crop to a rectangle.

Plus the single-key shortcuts below, which work whenever no field has focus.

Keys
----
  :  command prompt      ?  key list        q / Esc  quit
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

While a field has focus it takes the keyboard instead: Enter commits, Up/Down
step the value, Tab moves to the next field, Esc lets go without committing.

Commands
--------
`help` lists them all with their ranges. The numeric ones take an absolute value
or a signed step, so `fov 158` and `fov +2` both work, and every sensor control
also takes `auto` to hand it back to the camera's own loop. Every field and
every button is one of these commands, so the four ways in cannot drift apart.

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
  3. `k1` / `k2` third — the residual. If the edge is straight in the middle of
     the frame but still bends in the last fifth, that is what these fix: they
     do nothing on the optical axis and grow toward the edge, which is exactly
     the shape `fov` cannot make. Start with k1 in steps of 0.01.
  4. `cx` / `cy` last, and only if the bowing is ASYMMETRIC — straight along the
     left edge but curved along the right. That means the sensor is not centred
     behind the lens, and no amount of k1 will fix it.

None of this is a calibration. It is straight to the eye, not metric, and the
panel says ESTIMATED in amber to keep that in view. A real ChArUco calibration
writes camera_matrix / dist_coeffs into the profile and the tools switch to it
automatically.
"""

import argparse
import json
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

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
    SENSOR_CONTROLS,
    build_controls,
    describe_sensor_modes,
    open_camera,
)
from vision.commands import (
    CommandError,
    CommandSet,
    EditBuffer,
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
    ERR_COLOR,
    FONT,
    HINT_COLOR,
    LABEL_COLOR,
    OK_COLOR,
    PROMPT_COLOR,
    TEXT_COLOR,
    WARN_COLOR,
    draw_grid,
    draw_info_box,
)

CAPTURE_DIR = Path(__file__).resolve().parents[1] / "captures"
SETTINGS_PATH = Path(__file__).resolve().parents[1] / "config" / "camera_settings.json"

INTERP_NAMES = list(INTERPOLATIONS)
VIEWS = ("corrected", "raw", "both")
FIT_MODES = ("fit", "native")
FLIPS = ("none", "h", "v", "both")
ROTATIONS = (0, 90, 180, 270)

# Panel geometry. The panel is a solid strip drawn UNDER the image, not an
# overlay on it — the whole point of this tool is to see the picture unobscured
# while the numbers that produced it sit somewhere fixed. There are deliberately
# no cv2 trackbars: eight of them stacked above the image cost ~350 px of screen
# that the picture wants, and a slider cannot show you that a value is 158.
PANEL_BG = (26, 26, 26)
PANEL_MIN_WIDTH = 900
BUTTON_H = 26
BUTTON_GAP = 6
PANEL_LINE = 17
PANEL_PAD = 8
LOG_LINES = 3

# One editable field: label, box, and the gap between them.
FIELD_H = 21
FIELD_GAP = 14
FIELD_ROW_GAP = 7
LABEL_SCALE = 0.38
VALUE_SCALE = 0.44
BOX_BG = (44, 44, 44)
BOX_BG_FOCUS = (70, 62, 30)
BOX_EDGE = (105, 105, 105)
GROUP_COLOR = (150, 190, 255)
GROUP_WIDTH = 62          # left gutter the group labels live in

# waitKeyEx arrow codes. GTK and Qt disagree and both turn up on a Pi desktop.
# Deliberately NOT the short 81-84 forms: those are what the MASKED waitKey
# returns, and they are also Shift+Q/R/S/T — which would turn "shift-Q to quit"
# into a pan. waitKeyEx reports the long codes, so there is no need for them.
KEY_LEFT = (65361, 2424832)
KEY_RIGHT = (65363, 2555904)
KEY_UP = (65362, 2490368)
KEY_DOWN = (65364, 2621440)
KEY_BACKSPACE = (8, 127, 65288)
KEY_ENTER = (13, 10)
KEY_ESC = (27,)
KEY_TAB = (9, 65289)

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

        self.flip = "none"
        self.rotate = 0
        self.swap_rb = False

        self.view = "corrected"
        self.show_grid = False
        self.show_keys = False
        self.autosave = bool(args.autosave)
        self.settings_path = args.settings

        self.capture_size = None       # filled in by main() once the camera opens
        self.camera_name = ""
        self.maps = None
        self.last_raw = None           # kept so 'snap' writes clean images,
        self.last_corrected = None     # i.e. without the grid drawn on them

        self.mouse = (-1, -1)          # window coords, straight from the callback
        self.drag = None               # (start, current) in image coords, mid-crop
        self.pending_clicks = []       # (x, y) in window coords, awaiting layout
        self.layout = None             # where the image and buttons ended up
        self.pending = []              # command lines queued by the stdin thread
        self.focus = None              # index into FIELDS of the field being typed in
        self.field_text = ""           # what has been typed into it so far

        self.dirty = True              # rebuild the remap tables before next frame
        self.sensor_dirty = True       # push sensor controls before next frame
        self.running = True
        self.log = MessageLog()
        self.edit = EditBuffer()
        self.commands = self._build_commands()
        self.buttons = self._build_buttons()

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

    def set_centre_dx(self, v):
        return self._lens("centre_dx", v, "optical centre X", fmt="{:+.1f}", unit=" px")

    def set_centre_dy(self, v):
        return self._lens("centre_dy", v, "optical centre Y", fmt="{:+.1f}", unit=" px")

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

        fit     the ROI is scaled to fill the view box, so the window keeps the
                same size however far you zoom in. `scale` then becomes a pure
                quality knob: it changes how much source detail feeds the
                correction, not how big the window is.
        native  the ROI is rendered at its natural size, so zoom and crop never
                interpolate anything — at the cost of the window resizing under
                you every time you touch them.
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

        if spec.kind == "choice":
            value = parse_choice(text, spec.choices)
        elif text in ("auto", "a"):
            if not spec.auto:
                raise CommandError(
                    f"{name} has no auto mode — give a number in {spec.range_text}")
            value = AUTO
        else:
            current = self.sensor[name]
            base = float(current) if current not in (AUTO, None) else 0.0
            value = parse_number(text, base, float)
            if not (spec.lo <= value <= spec.hi):
                raise CommandError(f"{value:g} is outside {spec.range_text}")
            if spec.kind == "int":
                value = int(round(value))

        self.sensor[name] = value
        self.sensor_dirty = True
        return f"{name} {value}"

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
        if self.view_size is None:
            # Default the view box to the untouched output size, so launching
            # the tool gives the same window undistorted_viewer.py would.
            self.view_size = full_output_size(self.profile, input_size)
        self.maps = build_maps(self.profile, input_size, self.interp, mip=self.mip,
                               roi=self.roi(), view_size=self.render_size())
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
        cmds.add("cx", numeric(self.set_centre_dx,
                               lambda: self.profile.centre_dx, "cx <px|+px|-px>"),
                 "<px|+px|-px>", "optical axis offset X — for ASYMMETRIC bowing")
        cmds.add("cy", numeric(self.set_centre_dy,
                               lambda: self.profile.centre_dy, "cy <px|+px|-px>"),
                 "<px|+px|-px>", "optical axis offset Y")
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
                 "<fit|native>", "fit: window stays put. native: crop renders 1:1")
        cmds.add("viewbox", self._cmd_viewbox, "<w> <h>",
                 "size of the image area in fit mode")
        cmds.add("refit", self._cmd_refit, "",
                 "resize the view box so the crop renders 1:1 (no interpolation)")

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
                 "rewrite that JSON after every single change")
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

    def _cmd_swaprb(self, args):
        self.swap_rb = self._flag(args, self.swap_rb)
        return f"red/blue swap {'on' if self.swap_rb else 'off'}"

    def _cmd_autosave(self, args):
        self.autosave = self._flag(args, self.autosave)
        if self.autosave:
            self.write_settings(self.settings_path)
            return f"autosave ON — {self.settings_path} rewritten on every change"
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
        return f"view box {self.view_size[0]}x{self.view_size[1]} (fit mode)"

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
        return save_snapshot(self.last_raw, self.last_corrected, self.profile)

    def _cmd_params(self, args):
        for line in self.status_lines() + self.sensor_lines():
            self.log.add(True, line)
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
        self.view_size = None
        self.fit_mode = "fit"
        self.flip, self.rotate, self.swap_rb = "none", 0, False
        self.all_auto()
        apply_overrides(self, self.args)
        return ("back to the undistorted_viewer.py defaults"
                " (the settings file is untouched — 'load' re-reads it)")

    def _cmd_help(self, args):
        for line in self.commands.help_lines():
            self.log.add(True, line)
        print("\n".join(self.commands.help_lines()))
        return "commands listed in the terminal (and scrolling past above)"

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
                "view_size": list(self.view_size) if self.view_size else None,
            },
            "sensor": dict(self.sensor),
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
        if fr.get("view_size"):
            self.view_size = tuple(fr["view_size"])

        cap = data.get("capture") or {}
        self.swap_rb = bool(cap.get("swap_rb", self.swap_rb))
        if cap.get("flip") in FLIPS:
            self.flip = cap["flip"]
        if cap.get("rotate") in ROTATIONS:
            self.rotate = cap["rotate"]

        for name, value in (data.get("sensor") or {}).items():
            if name in SENSOR_CONTROLS:
                self.sensor[name] = value

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
            f"  k1 {p.k1:+.3f}  k2 {p.k2:+.3f}  centre {p.centre_dx:+.0f},{p.centre_dy:+.0f} px",
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

    def sensor_lines(self):
        """One line per sensor control, three to a row to fit the panel."""
        cells = [f"{n} {self.sensor[n]}" for n in SENSOR_CONTROLS]
        rows = [cells[i:i + 4] for i in range(0, len(cells), 4)]
        lines = ["  ".join(f"{c:<20}" for c in row).rstrip() for row in rows]
        return [("SENSOR " if i == 0 else "       ") + text
                for i, text in enumerate(lines)] + \
               [f"       camera: {self.sensor_status}"]

    # --- the button row ----------------------------------------------------

    def _build_buttons(self):
        """(label, command line, width) for the clickable row under the image.

        Every button is literally a command line, so there is no third code path
        to keep in step with the keys and the typed commands — the button IS the
        command, and it lands in the log the same way.
        """
        return [
            ("SAVE JSON", "save", 104),
            ("SNAP PNG", "snap", 94),
            ("ZOOM +", "zoom +0.25", 78),
            ("ZOOM -", "zoom -0.25", 78),
            ("CROP", "crop", 62),
            ("UNDO CROP", "uncrop", 104),
            ("NO CROP", "nocrop", 88),
            ("REFIT", "refit", 66),
            ("RAW/CORR", "view", 96),      # rewritten below to cycle
            ("GRID", "grid", 62),
            ("RESET", "reset", 70),
            ("HELP", "help", 62),
        ]


def next_view(studio):
    return VIEWS[(VIEWS.index(studio.view) + 1) % len(VIEWS)]


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


# --- input channel 3: the fields --------------------------------------------

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
        Field("k1", "k1", lambda s: f"{s.profile.k1:+.3f}", 0.01, 6),
        Field("k2", "k2", lambda s: f"{s.profile.k2:+.3f}", 0.01, 6),
        Field("centre x", "cx", lambda s: f"{s.profile.centre_dx:+.0f}", 2.0, 5),
        Field("centre y", "cy", lambda s: f"{s.profile.centre_dy:+.0f}", 2.0, 5),
        Field("correction", "undistort", lambda s: _onoff(s.correct),
              ("on", "off"), 4),

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

    for i, (name, spec) in enumerate(SENSOR_CONTROLS.items()):
        step, start = SENSOR_STEPS.get(name, (None, None))
        if spec.kind == "choice":
            step, start = tuple(spec.choices), None
        fields.append(Field(name, name, lambda s, n=name: str(s.sensor[n]),
                            step, max(6, len(spec.range_text.split("|")[0]) + 2),
                            "SENSOR" if i == 0 else "", start))
    return fields


FIELDS = build_fields()


def field_value(studio, index):
    return FIELDS[index].get(studio)


def focus_field(studio, index):
    """Give a field the keyboard, pre-filled with its current value.

    Pre-filled rather than blank because most edits here are a nudge — 158 to
    160 — and a box that empties itself when clicked has thrown away the one
    number you were about to adjust. Everything numeric also accepts `+2` and
    `-2`, so a relative tweak never needs the current value retyped either way.
    """
    studio.focus = index
    studio.field_text = field_value(studio, index)
    return (f"{FIELDS[index].label}: type a value and press Enter "
            "(Up/Down step it, Tab moves on, Esc cancels)")


def blur_field(studio):
    studio.focus = None
    studio.field_text = ""


def step_field(studio, direction):
    """Up/Down on the focused field — the part that replaced the sliders.

    Runs the same command a typed value would, so a stepped change is logged,
    clamped, echoed and saved identically. Returns that command's own message.
    """
    field = FIELDS[studio.focus]
    if field.step is None:
        return False, f"{field.label} has no step — type a value instead"

    if field.choices:
        current = field_value(studio, studio.focus)
        options = field.choices
        # Tolerate a value that is not in the list — a sensor control the camera
        # reported back oddly, say — by starting from the beginning.
        index = options.index(current) if current in options else -1
        argument = options[(index + direction) % len(options)]
    elif field_value(studio, studio.focus) == AUTO and field.start is not None:
        # Nothing to add to. Jump to a sane starting point instead, so the first
        # press does something visible rather than failing the range check.
        argument = f"{field.start:g}"
    else:
        argument = f"{'+' if direction > 0 else '-'}{abs(field.step):g}"

    result = studio.commands.execute(f"{field.command} {argument}")
    studio.field_text = field_value(studio, studio.focus)
    return result.ok, result.message


def commit_field(studio):
    """Enter on the focused field: run its command with whatever was typed."""
    field = FIELDS[studio.focus]
    text = studio.field_text.strip()
    if not text:
        return True, f"{field.label} left as it was"
    result = studio.commands.execute(f"{field.command} {text}")
    studio.field_text = field_value(studio, studio.focus)
    return result.ok, result.message


def handle_field_key(key, studio):
    """Keys while a field has focus. Returns (ok, message), or None to just redraw.

    Enter commits and lets go; Tab commits and moves on, which is how the whole
    panel can be walked from the keyboard without touching the mouse.
    """
    if key in KEY_ESC:
        blur_field(studio)
        return True, "field closed, nothing changed"
    if key in KEY_ENTER:
        ok, message = commit_field(studio)
        blur_field(studio)
        return ok, message
    if key in KEY_TAB:
        ok, message = commit_field(studio)
        focus_field(studio, (studio.focus + 1) % len(FIELDS))
        return ok, f"{message}  ->  {FIELDS[studio.focus].label}"
    if key in KEY_UP:
        return step_field(studio, +1)
    if key in KEY_DOWN:
        return step_field(studio, -1)
    if key in KEY_BACKSPACE:
        studio.field_text = studio.field_text[:-1]
        return None
    if 32 <= key <= 126:
        studio.field_text += chr(key)
        return None
    return None


# --- input channel 3: the mouse ----------------------------------------------

def on_mouse(event, x, y, flags, studio):
    """Cursor tracking, button clicks and the crop drag.

    Coordinates are stored raw, in window pixels, and converted by the render
    loop — only there is the layout (and --display-scale) known. This keeps the
    callback trivial, which matters because it runs on OpenCV's UI thread.
    """
    studio.mouse = (x, y)
    if event == cv2.EVENT_LBUTTONDOWN:
        studio.pending_clicks.append(("down", x, y))
    elif event == cv2.EVENT_MOUSEMOVE and studio.drag is not None:
        studio.pending_clicks.append(("move", x, y))
    elif event == cv2.EVENT_LBUTTONUP:
        studio.pending_clicks.append(("up", x, y))
    elif event == cv2.EVENT_RBUTTONDOWN:
        # A right-click abandons a drag in progress: the drag rectangle is the
        # one action here with no keyboard escape once it has started.
        studio.drag = None
        studio.log.add(True, "crop drag cancelled")


# --- input channel 4: keys ---------------------------------------------------

def handle_key(key, studio):
    """Single-key shortcuts. Returns (ok, message), always.

    Every key produces feedback, including keys that do nothing — an
    unrecognised key still says so on screen, which is what distinguishes "that
    key isn't bound" from "the window never received it".
    """
    p = studio.profile

    if key in (ord("q"), 27):
        studio.running = False
        return True, "quitting"
    if key == ord(":"):
        studio.edit.open()
        return True, "command prompt open — type, then Enter (Esc cancels)"
    if key == ord("?"):
        studio.show_keys = not studio.show_keys
        return True, f"key list {'shown' if studio.show_keys else 'hidden'}"

    # the correction
    if key == ord("["):
        return True, studio.set_lens_fov(p.lens_fov_deg - 2)
    if key == ord("]"):
        return True, studio.set_lens_fov(p.lens_fov_deg + 2)
    if key == ord("-"):
        return True, studio.set_output_fov(p.output_fov_deg - 5)
    if key in (ord("="), ord("+")):
        return True, studio.set_output_fov(p.output_fov_deg + 5)
    if key == ord(","):
        return True, studio.set_output_scale(p.output_scale - 0.1)
    if key == ord("."):
        return True, studio.set_output_scale(p.output_scale + 0.1)
    if key == ord("1"):
        return True, studio.set_k1(p.k1 - 0.01)
    if key == ord("2"):
        return True, studio.set_k1(p.k1 + 0.01)
    if key == ord("3"):
        return True, studio.set_k2(p.k2 - 0.01)
    if key == ord("4"):
        return True, studio.set_k2(p.k2 + 0.01)
    if key == ord("5"):
        return True, studio.set_centre_dx(p.centre_dx - 2)
    if key == ord("6"):
        return True, studio.set_centre_dx(p.centre_dx + 2)
    if key == ord("7"):
        return True, studio.set_centre_dy(p.centre_dy - 2)
    if key == ord("8"):
        return True, studio.set_centre_dy(p.centre_dy + 2)
    if key == ord("m"):
        return True, studio.set_model(
            MODEL_NAMES[(MODEL_NAMES.index(p.model) + 1) % len(MODEL_NAMES)])
    if key == ord("i"):
        return True, studio.set_interp(
            INTERP_NAMES[(INTERP_NAMES.index(studio.interp) + 1) % len(INTERP_NAMES)])
    if key == ord("n"):
        return True, studio.commands.execute("undistort").message

    # zoom, pan, crop
    if key == ord("x"):
        return True, studio.set_zoom(studio.zoom * 1.25)
    if key == ord("z"):
        return True, studio.set_zoom(studio.zoom / 1.25)
    if key == ord("0"):
        studio.zoom = 1.0
        x0, y0, x1, y1 = studio.crop_rect()
        return True, "zoom reset — " + studio.set_pan((x0 + x1) / 2, (y0 + y1) / 2)
    if key in KEY_LEFT:
        return True, studio.nudge_pan(-0.1, 0)
    if key in KEY_RIGHT:
        return True, studio.nudge_pan(0.1, 0)
    if key in KEY_UP:
        return True, studio.nudge_pan(0, -0.1)
    if key in KEY_DOWN:
        return True, studio.nudge_pan(0, 0.1)
    if key == ord("c"):
        result = studio.commands.execute("crop")
        return result.ok, result.message
    if key in KEY_BACKSPACE:
        result = studio.commands.execute("uncrop")
        return result.ok, result.message
    if key == ord("f"):
        return True, studio.commands.execute("refit").message
    if key == ord("v"):
        nxt = FIT_MODES[(FIT_MODES.index(studio.fit_mode) + 1) % len(FIT_MODES)]
        return True, studio.commands.execute(f"fitmode {nxt}").message

    # views and files
    if key == ord("u"):
        return True, studio.commands.execute(f"view {next_view(studio)}").message
    if key == ord("g"):
        return True, studio.commands.execute("grid").message
    for code, line in ((ord("s"), "save"), (ord("p"), "snap"), (ord("r"), "reset")):
        if key == code:
            result = studio.commands.execute(line)
            return result.ok, result.message

    label = chr(key) if 32 <= key <= 126 else "?"
    return False, f"key '{label}' ({key}) is not bound — press '?' for the list"


# --- rendering ---------------------------------------------------------------

def save_snapshot(raw, corrected, profile):
    """Write both images to captures/, tagging the corrected one with its params.

    The tag matters: comparing several tuning attempts later is impossible if
    the filenames do not record what produced them.
    """
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    tag = (f"{profile.model}-lens{profile.lens_fov_deg:.0f}"
           f"-out{profile.output_fov_deg:.0f}-k{profile.k1:+.2f}")
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


def text_width(text, scale):
    return cv2.getTextSize(text, FONT, scale, 1)[0][0]


def field_cell_width(field):
    """Total width of one `label [ value ]` cell.

    The box is sized from the field's declared character count rather than from
    its current value, so a number growing from 9 to 10 does not shove every
    field to its right along the row.
    """
    box = 12 + text_width("0" * field.chars, VALUE_SCALE)
    return text_width(field.label, LABEL_SCALE) + 7 + box, box


def layout_field_rows(width):
    """Flow the fields into rows that fit `width`. Pure geometry, no drawing.

    Returns a list of rows, each a list of (field index, x, cell width, box
    width). A field with a `group` starts a new row, so the four groups always
    read as four blocks however wide the window is; long groups wrap within
    themselves.
    """
    rows, row = [], []
    x = PANEL_PAD + GROUP_WIDTH
    for i, field in enumerate(FIELDS):
        cell, box = field_cell_width(field)
        if (field.group and row) or (x + cell > width - PANEL_PAD and row):
            rows.append(row)
            row, x = [], PANEL_PAD + GROUP_WIDTH
        row.append((i, x, cell, box))
        x += cell + FIELD_GAP
    if row:
        rows.append(row)
    return rows


def draw_fields(panel, studio, y):
    """Draw every field and return its hit rectangle.

    The whole cell — label included — is clickable, not just the box: a 40-pixel
    target that needs precision is a worse control than the slider it replaced.
    """
    rects = []
    rows = layout_field_rows(panel.shape[1])
    group = ""
    for row in rows:
        first = FIELDS[row[0][0]]
        if first.group:
            group = first.group
            cv2.putText(panel, group, (PANEL_PAD, y + FIELD_H - 6), FONT,
                        LABEL_SCALE, GROUP_COLOR, 1, cv2.LINE_AA)

        for index, x, cell, box in row:
            field = FIELDS[index]
            focused = studio.focus == index
            label_w = text_width(field.label, LABEL_SCALE)
            cv2.putText(panel, field.label, (x, y + FIELD_H - 6), FONT,
                        LABEL_SCALE, HINT_COLOR, 1, cv2.LINE_AA)

            bx = x + label_w + 7
            cv2.rectangle(panel, (bx, y), (bx + box, y + FIELD_H),
                          BOX_BG_FOCUS if focused else BOX_BG, -1)
            cv2.rectangle(panel, (bx, y), (bx + box, y + FIELD_H),
                          PROMPT_COLOR if focused else BOX_EDGE, 1)

            # While focused the box shows what is being TYPED, not the live
            # value — otherwise a half-typed "1" would read as the real setting.
            text = (studio.field_text + "_") if focused else field.get(studio)
            cv2.putText(panel, text, (bx + 5, y + FIELD_H - 6), FONT, VALUE_SCALE,
                        PROMPT_COLOR if focused else TEXT_COLOR, 1, cv2.LINE_AA)
            rects.append((x, y, bx + box, y + FIELD_H, index))
        y += FIELD_H + FIELD_ROW_GAP
    return rects, y


def panel_height(studio, width):
    """How tall the control strip needs to be for what it holds."""
    rows = len(layout_field_rows(width))
    lines = 2 + LOG_LINES + 1          # status, sensor status, log, prompt
    if studio.show_keys:
        lines += len(key_list_lines())
    return (PANEL_PAD * 2 + BUTTON_H + BUTTON_GAP
            + rows * (FIELD_H + FIELD_ROW_GAP) + FIELD_ROW_GAP
            + PANEL_LINE * lines)


def key_list_lines():
    return [l for l in __doc__.split("Keys\n----")[1]
            .split("Commands\n--------")[0].strip().splitlines()]


def draw_buttons(panel, studio, y):
    """Lay the button row out left to right, and record where each one landed.

    Returns the hit rectangles, which is the only thing the click handler needs
    — so the drawing and the hit-testing cannot disagree about position.
    """
    rects = []
    x = PANEL_PAD
    for label, command, width in studio.buttons:
        if x + width > panel.shape[1] - PANEL_PAD:
            break   # narrow window: drop the tail rather than draw off the edge
        cv2.rectangle(panel, (x, y), (x + width, y + BUTTON_H), (58, 58, 58), -1)
        cv2.rectangle(panel, (x, y), (x + width, y + BUTTON_H), (110, 110, 110), 1)
        (tw, th), _ = cv2.getTextSize(label, FONT, 0.42, 1)
        cv2.putText(panel, label, (x + (width - tw) // 2, y + (BUTTON_H + th) // 2),
                    FONT, 0.42, TEXT_COLOR, 1, cv2.LINE_AA)
        rects.append((x, y, x + width, y + BUTTON_H, command))
        x += width + BUTTON_GAP
    return rects


def draw_panel(studio, width, fps):
    """The control strip: buttons, an editable field per parameter, the log.

    Deliberately BELOW the image rather than over it. The tool exists to judge
    whether an edge is straight, and a translucent panel sitting on the picture
    is exactly what stops you being able to.

    Note what is a FIELD and what is a LINE: anything you can set is a field, and
    the two lines under them are the things you cannot — what the correction is
    costing in sharpness, and what the camera did with the settings it was sent.
    """
    panel = np.full((panel_height(studio, width), width, 3), PANEL_BG, np.uint8)
    y = PANEL_PAD
    buttons = draw_buttons(panel, studio, y)
    y += BUTTON_H + BUTTON_GAP
    fields, y = draw_fields(panel, studio, y)
    y += FIELD_ROW_GAP

    def line(text, color=TEXT_COLOR, scale=0.42):
        nonlocal y
        y += PANEL_LINE
        cv2.putText(panel, text, (PANEL_PAD, y - 4), FONT, scale, color, 1, cv2.LINE_AA)

    line(studio.derived_line(fps),
         WARN_COLOR if not studio.profile.calibrated else OK_COLOR)
    line(f"camera: {studio.sensor_status}", HINT_COLOR)

    if studio.show_keys:
        for text in key_list_lines():
            line(text, HINT_COLOR, scale=0.40)

    for ok, text in studio.log.recent(count=LOG_LINES, max_age=12.0):
        line(text, OK_COLOR if ok else ERR_COLOR)

    if studio.edit.active:
        line(studio.edit.render(), PROMPT_COLOR, scale=0.5)
    elif studio.focus is not None:
        line(f"editing {FIELDS[studio.focus].label} — Enter commits, Up/Down step, "
             f"Tab next, Esc cancels", PROMPT_COLOR)
    else:
        line("click a field to edit it, drag on the image to crop, ':' for a "
             f"command, '?' for keys   |   {fps:5.1f} fps   |   {studio.settings_path}",
             HINT_COLOR)
    return panel, buttons, fields


def draw_drag(image, studio):
    """The crop rectangle being dragged, with its size in output pixels."""
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
    label = f"{x1 - x0}x{y1 - y0}"
    cv2.putText(image, label, (x0 + 4, max(14, y0 - 6)), FONT, 0.45,
                (0, 255, 0), 1, cv2.LINE_AA)


def compose(image, studio, fps):
    """Image on top, control panel underneath, on one canvas.

    The canvas is at least PANEL_MIN_WIDTH wide so the button row and the status
    lines are never truncated by a small preview, and the image is centred in
    whatever is left over.
    """
    width = max(image.shape[1], PANEL_MIN_WIDTH)
    panel, buttons, fields = draw_panel(studio, width, fps)

    x_off = (width - image.shape[1]) // 2
    top = np.full((image.shape[0], width, 3), PANEL_BG, np.uint8)
    top[:, x_off:x_off + image.shape[1]] = image

    canvas = np.vstack([top, panel])
    studio.layout = {
        "image_x": x_off,
        "image_y": 0,
        "image_w": image.shape[1],
        "image_h": image.shape[0],
        "panel_y": image.shape[0],
        "buttons": buttons,
        "fields": fields,
    }
    return canvas


def window_to_image(studio, x, y):
    """Window coordinates -> pixel coordinates inside the displayed image.

    Returns None when the point is not on the image (the panel, or the letterbox
    beside a narrow preview). --display-scale is undone first, since it resizes
    the finished canvas without touching anything the coordinates mean.
    """
    lay = studio.layout
    if lay is None:
        return None
    if studio.args.display_scale != 1.0:
        x, y = x / studio.args.display_scale, y / studio.args.display_scale
    ix, iy = int(x) - lay["image_x"], int(y) - lay["image_y"]
    if 0 <= ix < lay["image_w"] and 0 <= iy < lay["image_h"]:
        return ix, iy
    return None


def hit_panel(studio, x, y, key):
    """What is under a window-coordinate click, in the panel row named by `key`.

    Returns the payload of the rectangle hit — a command line for "buttons", a
    field index for "fields" — or None. Both rows store the same 5-tuple shape
    for exactly this reason.
    """
    lay = studio.layout
    if lay is None:
        return None
    if studio.args.display_scale != 1.0:
        x, y = x / studio.args.display_scale, y / studio.args.display_scale
    py = int(y) - lay["panel_y"]
    for x0, y0, x1, y1, payload in lay.get(key, ()):
        if x0 <= int(x) <= x1 and y0 <= py <= y1:
            return payload
    return None


def process_mouse(studio):
    """Turn the queued mouse events into crops, button presses and drag state.

    Run from the render loop rather than the callback because it needs the
    layout, which only exists once a frame has been composed.
    """
    events, studio.pending_clicks = studio.pending_clicks, []
    for kind, x, y in events:
        if kind == "down":
            index = hit_panel(studio, x, y, "fields")
            if index is not None:
                studio.log.add(True, focus_field(studio, index))
                continue

            command = hit_panel(studio, x, y, "buttons")
            if command is not None:
                # RAW/CORR is the one button that cycles rather than sets.
                if command == "view":
                    command = f"view {next_view(studio)}"
                studio.log.push(studio.commands.execute(command))
                continue

            # A click anywhere else lets go of the field being edited, the way
            # clicking off a text box does everywhere else. Deliberately without
            # committing: an abandoned edit should not take effect.
            if studio.focus is not None:
                blur_field(studio)

            point = window_to_image(studio, x, y)
            if point is not None:
                if studio.view == "both":
                    studio.log.add(False,
                                   "cropping needs a single view — press 'u'")
                else:
                    studio.drag = (point, point)
        elif kind == "move" and studio.drag is not None:
            point = window_to_image(studio, x, y)
            if point is not None:
                studio.drag = (studio.drag[0], point)
        elif kind == "up" and studio.drag is not None:
            (sx, sy), (ex, ey) = studio.drag
            studio.drag = None
            lay = studio.layout
            x0, x1 = sorted((sx, ex))
            y0, y1 = sorted((sy, ey))
            if x1 - x0 < MIN_CROP_PX or y1 - y0 < MIN_CROP_PX:
                studio.log.add(False, "that drag was too small to be a crop — "
                                      f"drag a box at least {MIN_CROP_PX} px across")
                continue
            rect = (x0 / lay["image_w"], y0 / lay["image_h"],
                    x1 / lay["image_w"], y1 / lay["image_h"])
            studio.log.add(True, studio.push_crop(rect))


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
    parser.add_argument("--display-scale", type=float, default=1.0,
                        help="scale the whole window; does not affect processing")
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
                       help="rewrite the settings JSON after every change")
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
                       help="fit (the default): the window stays the same size "
                            "as you zoom. native: the crop renders 1:1 and the "
                            "window resizes")
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
        ("lens_fov_deg", args.lens_fov),
        ("fov_reference", args.fov_reference),
        ("model", args.model),
        ("k1", args.k1),
        ("k2", args.k2),
        ("output_fov_deg", args.output_fov),
        ("output_scale", args.output_scale),
    ):
        if value is not None:
            setattr(studio.profile, attr, value)
            changed.append(f"{attr}={value}")
    if args.hq and args.output_scale is None:
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
    print("\nOr press ':' in the window to type them there; '?' lists the keys.")
    print(f"'save' writes {studio.settings_path}\n")

    window = "Camera Studio"
    cv2.namedWindow(window, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(window, on_mouse, studio)
    start_stdin_reader(studio)

    fps, last = 0.0, time.perf_counter()
    autosave_state = None
    try:
        while studio.running:
            ok, frame = camera.read()
            if not ok or frame is None:
                print("Failed to read frame from camera.")
                break
            if studio.swap_rb:
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            frame = studio.orient(frame)

            if studio.sensor_dirty:
                studio.log.add(True, f"sensor: {studio.apply_sensor(camera)}")

            # The driver can hand back a size we didn't ask for, and a rotation
            # swaps width and height. The maps are built for one exact input size.
            if frame.shape[1::-1] != studio.capture_size:
                camera.size = frame.shape[1::-1]
                studio.dirty = True
            if studio.dirty:
                studio.rebuild(frame.shape[1::-1])

            if studio.correct:
                corrected = undistort(frame, studio.maps)
            else:
                # No remap to fold the ROI into, so crop and scale it here.
                corrected = crop_resize(frame, studio.roi(), studio.maps.out_size,
                                        INTERPOLATIONS[studio.interp])
            studio.last_raw, studio.last_corrected = frame, corrected

            if studio.view in ("both", "raw"):
                # The SAME normalised ROI is applied to the raw frame, so the two
                # halves show the same part of the scene. It is only approximate
                # — the raw fisheye and the rectilinear output do not cover the
                # field identically — but at zoom 1 with no crop it is exactly
                # the whole-frame A/B comparison you want, which is the case it
                # is looked at in.
                raw_view = crop_resize(frame, studio.roi(), studio.maps.out_size,
                                       INTERPOLATIONS[studio.interp])
                image = (side_by_side(raw_view, corrected) if studio.view == "both"
                         else raw_view.copy())
            else:
                # copy() so the grid never contaminates the snapshot images.
                image = corrected.copy()

            if studio.show_grid:
                draw_grid(image, 8, 8)
            if not studio.correct:
                draw_info_box(image, ["CORRECTION OFF — press 'n'"],
                              origin=(8, 8), highlight_first=True)
            draw_drag(image, studio)

            now = time.perf_counter()
            dt, last = now - last, now
            if dt > 0:
                # Exponential moving average: a raw instantaneous rate is too
                # jumpy to read off the screen.
                fps = 0.9 * fps + 0.1 * (1.0 / dt) if fps else 1.0 / dt

            canvas = compose(image, studio, fps)
            if args.display_scale != 1.0:
                canvas = cv2.resize(canvas, None, fx=args.display_scale,
                                    fy=args.display_scale, interpolation=cv2.INTER_AREA)
            cv2.imshow(window, canvas)

            process_mouse(studio)

            for line in studio.drain_pending():
                result = studio.commands.execute(line)
                if result is not None:
                    studio.log.push(result)
                    print(("OK: " if result.ok else "ERR: ") + result.message)

            key = cv2.waitKeyEx(1)
            if key != -1:
                if studio.focus is not None:
                    feedback = handle_field_key(key, studio)
                    if feedback is not None:
                        studio.log.add(*feedback)
                elif studio.edit.active:
                    line = studio.edit.key(key)
                    if line:
                        studio.log.push(studio.commands.execute(line))
                    elif line == "":
                        studio.log.add(True, "prompt closed")
                else:
                    ok_key, message = handle_key(key, studio)
                    studio.log.add(ok_key, message)

            if studio.autosave:
                # Compare the settings themselves, not a dirty flag: the flags
                # are cleared by rebuild() further up. Only the sections a user
                # can change are hashed — "saved_at" and the sampling figures
                # would make every single frame look like a change.
                settings = studio.settings_dict()
                state = json.dumps([settings[k] for k in
                                    ("lens", "correction", "framing", "sensor",
                                     "capture")], default=str)
                if state != autosave_state:
                    autosave_state = state
                    studio.write_settings(studio.settings_path)

            if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        studio.running = False
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
