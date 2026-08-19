#!/usr/bin/env python3
"""Fisheye correction and the measurement grid, in one window.

This is undistorted_viewer.py and measured_grid_viewer.py merged, which is the
combination that is actually useful: a pixels-to-centimetres grid is only
meaningful on a *corrected* image, because on the raw fisheye the centimetres
per pixel grows sharply toward the edges. Here the grid always sits on whichever
view you are looking at, and says so when that view is the raw one.

    python undistorted_grid_viewer.py
    python undistorted_grid_viewer.py --hq
    python undistorted_grid_viewer.py --frame-width-cm 60 --frame-height-cm 45

Three ways to drive it
----------------------
OpenCV only delivers keystrokes while the *image window* has focus — not the
terminal, and over VNC or ssh -X often not until the window has been clicked.
"I press keys and nothing happens" is nearly always that. So there are three
input channels, and every one of them echoes what it did onto the frame:

  1. TYPE IN THE TERMINAL. Commands typed into the shell that launched this tool
     are read from stdin and applied. This needs no window focus at all and is
     the one that always works. Try `help`.
  2. TYPE IN THE WINDOW. Press ':' to open a prompt on the frame, type a
     command, press Enter. The prompt shows each character as it arrives, so if
     nothing appears the window does not have focus.
  3. SLIDERS AND KEYS. Trackbars along the top of the window for the continuous
     parameters, plus the single-key shortcuts below.

Every keypress is reported on screen, including unrecognised ones, so you can
always tell whether the key reached the window.

Keys
----
  :         open the command prompt        u  cycle view: corrected / raw / both
  ?         show / hide the key list       g  cycle grid: off / px / cm
  [ / ]     lens FOV -/+ 2 deg             h  toggle the hover cell readout
  - / =     output FOV -/+ 5 deg           m  cycle projection model
  , / .     output scale -/+ 0.1           i  cycle interpolation kernel
  c         clear the measurement points   s  save a raw+corrected snapshot
  w         write params to the profile    r  reset to defaults
  q / Esc   quit

Mouse: hover a grid cell to read its bounds; click two points to measure the
distance between them.

Commands
--------
Run `help` for the full list. The numeric ones take an absolute value or a
signed step, so `fov 158` and `fov +2` both work.

What the numbers mean
---------------------
The lens parameters are ESTIMATES from the vendor's "160 degree" spec, not a
calibration — the HUD says ESTIMATED in amber until real data replaces them, and
the centimetre readings are a flat-plane approximation on top of that. See
GUIDE.md before trusting any of it to a millimetre.
"""

import argparse
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from rig import config as rig_config

from vision.camera_source import (
    DEFAULT_SIZE,
    FULL_RES_SIZE,
    build_controls,
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
    HINT_COLOR,
    OK_COLOR,
    PROMPT_COLOR,
    TEXT_COLOR,
    WARN_COLOR,
    draw_cell_info,
    draw_grid,
    draw_grid_labels,
    draw_measure,
    draw_text_panel,
    hovered_cell,
    draw_info_box,
)

CAPTURE_DIR = Path(__file__).resolve().parent / "captures"
INTERP_NAMES = list(INTERPOLATIONS)
VIEWS = ("corrected", "raw", "both")
GRID_MODES = ("off", "px", "cm")

# Physical span of the whole frame, measured by hand. Lives in config/rig.json
# so this tool and measured_grid_viewer.py cannot drift apart.
FRAME_CM = rig_config.load()["frame"]


class Viewer:
    """Everything mutable, in one place.

    Commands, trackbars and keys all funnel through the same setters, so there
    is exactly one definition of what each parameter means and one place that
    decides when the remap tables have gone stale.
    """

    def __init__(self, args, profile):
        self.args = args
        self.profile = profile
        self.interp = args.interp
        self.mip = not args.no_mip
        self.rows, self.cols = args.rows, args.cols
        self.frame_w_cm, self.frame_h_cm = args.frame_width_cm, args.frame_height_cm
        self.view = "corrected"
        self.grid = args.grid
        self.hover = True
        self.show_keys = False
        self.mouse = (-1, -1)
        self.points = []
        self.pending = []          # command lines queued by the stdin thread
        self.pending_click = None  # a click waiting to be mapped to image coords
        self.syncing_trackbars = False
        self.maps = None
        self.last_raw = None       # kept so `snap` can write the clean images,
        self.last_corrected = None # i.e. without the overlays drawn on them
        self.dirty = True          # rebuild the remap tables before the next frame
        self.running = True
        self.log = MessageLog()
        self.edit = EditBuffer()
        self.commands = self._build_commands()

    # --- parameters -------------------------------------------------------
    # Each setter reports what changed, in the form the log and the HUD show.
    # Returning the message rather than printing it is what lets the same code
    # serve a keypress, a typed command and a slider drag.

    def set_lens_fov(self, value):
        old = self.profile.lens_fov_deg
        self.profile.lens_fov_deg = value
        self.profile.clamp()
        self.dirty = True
        return f"lens FOV {old:.0f} -> {self.profile.lens_fov_deg:.0f} deg"

    def set_output_fov(self, value):
        old = self.profile.output_fov_deg
        self.profile.output_fov_deg = value
        self.profile.clamp()
        self.dirty = True
        clipped = ""
        if abs(self.profile.output_fov_deg - value) > 0.01:
            # Silently clamping here is how you end up believing you rendered a
            # 170-degree view that the lens never saw.
            clipped = f" (clamped: cannot exceed the {self.profile.lens_fov_deg:.0f} deg lens)"
        return f"output FOV {old:.0f} -> {self.profile.output_fov_deg:.0f} deg{clipped}"

    def set_output_scale(self, value):
        old = self.profile.output_scale
        self.profile.output_scale = value
        self.profile.clamp()
        self.dirty = True
        return f"output scale {old:.2f} -> {self.profile.output_scale:.2f}"

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

    def set_rows(self, n):
        self.rows = max(1, min(int(n), 64))
        return f"grid rows {self.rows}"

    def set_cols(self, n):
        self.cols = max(1, min(int(n), 64))
        return f"grid cols {self.cols}"

    def set_frame_cm(self, w_cm=None, h_cm=None):
        if w_cm is not None:
            self.frame_w_cm = max(0.1, w_cm)
        if h_cm is not None:
            self.frame_h_cm = max(0.1, h_cm)
        return f"frame span {self.frame_w_cm:.1f} cm (X) x {self.frame_h_cm:.1f} cm (Y)"

    def cycle(self, attr, options):
        current = getattr(self, attr)
        nxt = options[(options.index(current) + 1) % len(options)]
        setattr(self, attr, nxt)
        return nxt

    # --- derived ----------------------------------------------------------

    def drain_pending(self):
        """Take everything the stdin thread has queued since the last frame.

        Swapping the list out in one statement is the whole of the thread
        safety here: the reader only ever appends, so nothing can be lost
        between the read and the rebind.
        """
        lines, self.pending = self.pending, []
        return lines

    def image_mouse(self, view_shape, point=None):
        """Window coordinates -> coordinates in the rendered image.

        --display-scale resizes the window without touching the pixels, so a
        click at the bottom-right of a half-size window is at twice those
        coordinates in the image the grid was drawn on.
        """
        x, y = self.mouse if point is None else point
        if self.args.display_scale != 1.0:
            x, y = x / self.args.display_scale, y / self.args.display_scale
        h, w = view_shape[:2]
        return min(max(int(x), -1), w - 1), min(max(int(y), -1), h - 1)

    def cm_per_px(self, size):
        """Centimetres per pixel for a rendered image of `size` = (w, h).

        The measured span describes the whole field of view, so it divides by
        whatever the current output happens to be — which is why changing
        output_scale does not change any centimetre reading.
        """
        w, h = size
        return self.frame_w_cm / w, self.frame_h_cm / h

    def rebuild(self, input_size):
        self.maps = build_maps(self.profile, input_size, self.interp, mip=self.mip)
        self.dirty = False
        return self.maps

    # --- commands ---------------------------------------------------------

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

        cmds.add("fov", numeric(self.set_lens_fov,
                                lambda: self.profile.lens_fov_deg, "fov <deg|+N|-N>"),
                 "<deg|+N|-N>", "quoted lens FOV — the main correction knob",
                 aliases=("lensfov",))
        cmds.add("out", numeric(self.set_output_fov,
                                lambda: self.profile.output_fov_deg, "out <deg|+N|-N>"),
                 "<deg|+N|-N>", "how much of the lens cone to render",
                 aliases=("outfov",))
        cmds.add("scale", numeric(self.set_output_scale,
                                  lambda: self.profile.output_scale, "scale <f|+f|-f>"),
                 "<f|+f|-f>", "output size relative to the capture")
        cmds.add("model", choice(self.set_model, MODEL_NAMES, "model <name>"),
                 "<name>", f"projection curve: {', '.join(MODEL_NAMES)}")
        cmds.add("ref", choice(self.set_fov_reference, ("diagonal", "horizontal"),
                               "ref <diagonal|horizontal>"),
                 "<diagonal|horizontal>", "which FOV the lens number refers to")
        cmds.add("interp", choice(self.set_interp, INTERP_NAMES, "interp <name>"),
                 "<name>", f"resampling kernel: {', '.join(INTERP_NAMES)}")

        cmds.add("rows", numeric(self.set_rows, lambda: self.rows, "rows <n|+n|-n>", int),
                 "<n|+n|-n>", "grid rows")
        cmds.add("cols", numeric(self.set_cols, lambda: self.cols, "cols <n|+n|-n>", int),
                 "<n|+n|-n>", "grid columns")
        cmds.add("grid", choice(lambda v: self._set_attr("grid", v, "grid"), GRID_MODES,
                                "grid <off|px|cm>"),
                 "<off|px|cm>", "grid overlay and what it is labelled in")
        cmds.add("view", choice(lambda v: self._set_attr("view", v, "view"), VIEWS,
                                "view <corrected|raw|both>"),
                 "<corrected|raw|both>", "which image to show")

        cmds.add("wcm", numeric(lambda v: self.set_frame_cm(w_cm=v),
                                lambda: self.frame_w_cm, "wcm <cm|+cm|-cm>"),
                 "<cm|+cm|-cm>", "measured width of the whole frame, in cm")
        cmds.add("hcm", numeric(lambda v: self.set_frame_cm(h_cm=v),
                                lambda: self.frame_h_cm, "hcm <cm|+cm|-cm>"),
                 "<cm|+cm|-cm>", "measured height of the whole frame, in cm")

        cmds.add("mip", self._cmd_mip, "[on|off]", "pyramid filtering of shrunk regions")
        cmds.add("hover", self._cmd_hover, "[on|off]", "the hovered-cell readout")
        cmds.add("clear", self._cmd_clear, "", "drop the measurement points",
                 aliases=("c",))
        cmds.add("show", self._cmd_show, "", "print every current parameter")
        cmds.add("save", self._cmd_save, "", "write the lens profile to disk")
        cmds.add("snap", self._cmd_snap, "", "save a raw + corrected image pair")
        cmds.add("reset", self._cmd_reset, "", "back to the default lens profile")
        cmds.add("help", self._cmd_help, "", "list these commands", aliases=("h", "?"))
        cmds.add("quit", self._cmd_quit, "", "exit", aliases=("q", "exit"))
        return cmds

    def _set_attr(self, attr, value, label):
        setattr(self, attr, value)
        return f"{label} {value}"

    def _flag(self, args, current, usage):
        """Shared parsing for the on/off commands, where bare = toggle."""
        if not args:
            return not current
        return parse_choice(args[0], ("on", "off")) == "on"

    def _cmd_mip(self, args):
        self.mip = self._flag(args, self.mip, "mip [on|off]")
        self.dirty = True
        return f"mip filtering {'on' if self.mip else 'off'}"

    def _cmd_hover(self, args):
        self.hover = self._flag(args, self.hover, "hover [on|off]")
        return f"hover readout {'on' if self.hover else 'off'}"

    def _cmd_clear(self, args):
        self.points.clear()
        return "measurement points cleared"

    def _cmd_show(self, args):
        for line in self.status_lines():
            self.log.add(True, line)
        return "current settings above"

    def _cmd_save(self, args):
        return f"wrote {self.profile.save(self.args.profile)}"

    def _cmd_snap(self, args):
        if self.last_raw is None:
            raise CommandError("no frame captured yet")
        return save_snapshot(self.last_raw, self.last_corrected, self.profile)

    def _cmd_reset(self, args):
        self.profile = LensProfile()
        if self.args.hq and self.args.output_scale is None:
            self.profile.output_scale = 0.5
        self.dirty = True
        return "lens profile reset to defaults"

    def _cmd_help(self, args):
        for line in self.commands.help_lines():
            self.log.add(True, line)
        return "commands listed above (also printed in the terminal)"

    def _cmd_quit(self, args):
        self.running = False
        return "quitting"

    # --- reporting --------------------------------------------------------

    def status_lines(self):
        """The full parameter dump, for `show` and for the startup banner."""
        stats = sampling_stats(self.maps) if self.maps else {}
        return [
            f"lens FOV {self.profile.lens_fov_deg:.0f} deg ({self.profile.fov_reference})"
            f"  model {self.profile.model}",
            f"output FOV {self.profile.output_fov_deg:.0f} deg  scale "
            f"{self.profile.output_scale:.2f}  interp {self.interp}"
            f"  mip {'on' if self.mip else 'off'}",
            f"grid {self.grid} {self.rows}x{self.cols}  frame span "
            f"{self.frame_w_cm:.1f} x {self.frame_h_cm:.1f} cm  view {self.view}",
            f"sampling src px/out px: centre {stats.get('centre', 0):.2f}"
            f"  edge {stats.get('edge', 0):.2f}",
        ]


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
                             "field of view, ~2x the real detail at the frame edges")
    parser.add_argument("--display-scale", type=float, default=1.0,
                        help="scale the window only; does not affect processing")
    parser.add_argument("--profile", type=Path, default=PROFILE_PATH,
                        help="lens profile JSON to load (and to write with 'save')")
    parser.add_argument("--swap-rb", action="store_true",
                        help="fix inverted red/blue channels")

    lens = parser.add_argument_group("lens model (all tunable live)")
    lens.add_argument("--lens-fov", type=float,
                      help="quoted lens FOV in degrees (default 160)")
    lens.add_argument("--fov-reference", choices=["diagonal", "horizontal"],
                      help="whether --lens-fov is the diagonal or horizontal FOV")
    lens.add_argument("--model", choices=MODEL_NAMES,
                      help="assumed fisheye projection curve (default equidistant)")
    lens.add_argument("--output-fov", type=float,
                      help="diagonal FOV of the rectilinear output (default 120)")
    lens.add_argument("--output-scale", type=float,
                      help="output size relative to the capture")
    lens.add_argument("--interp", choices=INTERP_NAMES, default=DEFAULT_INTERPOLATION,
                      help=f"resampling kernel (default {DEFAULT_INTERPOLATION})")
    lens.add_argument("--no-mip", action="store_true",
                      help="skip pyramid filtering of the regions the correction "
                           "shrinks: faster, but those regions alias")

    grid = parser.add_argument_group("grid")
    grid.add_argument("--rows", type=int, default=8)
    grid.add_argument("--cols", type=int, default=8)
    grid.add_argument("--grid", choices=list(GRID_MODES), default="cm",
                      help="initial grid mode (default cm)")
    grid.add_argument("--frame-width-cm", type=float, default=FRAME_CM["width_cm"],
                      help="measured horizontal span of the whole frame")
    grid.add_argument("--frame-height-cm", type=float, default=FRAME_CM["height_cm"],
                      help="measured vertical span of the whole frame")

    sensor = parser.add_argument_group("image quality (Picamera2 only)")
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


def profile_from_args(args):
    """Load the saved profile, then let any explicit CLI flag override it."""
    profile = LensProfile.load(args.profile)
    if args.hq and args.output_scale is None:
        # Render half the capture resolution, so --hq keeps the familiar
        # 1296x972 output but feeds it from four times as many sensor pixels.
        profile.output_scale = 0.5
    for attr, value in (
        ("lens_fov_deg", args.lens_fov),
        ("fov_reference", args.fov_reference),
        ("model", args.model),
        ("output_fov_deg", args.output_fov),
        ("output_scale", args.output_scale),
    ):
        if value is not None:
            setattr(profile, attr, value)
    profile.clamp()
    return profile


# --- input channel 1: the terminal ------------------------------------------

def start_stdin_reader(viewer):
    """Feed lines typed into the launching terminal into the command set.

    A daemon thread, because there is no portable way to interrupt a blocking
    stdin read — the process must be able to exit while this is still parked in
    readline(). It only ever appends to a queue that the render loop drains, so
    the parameters are still mutated from one thread.

    This is the input path that works when the window will not take focus, which
    over VNC or ssh -X is often.
    """
    if sys.stdin is None or not sys.stdin.readable():
        viewer.log.add(False, "no terminal attached — use ':' in the window instead")
        return None

    def run():
        try:
            for line in sys.stdin:
                if not viewer.running:
                    return
                viewer.pending.append(line)
        except (ValueError, OSError):
            pass   # stdin closed under us during shutdown; nothing to do
    thread = threading.Thread(target=run, name="stdin-commands", daemon=True)
    thread.start()
    return thread


# --- input channel 3: trackbars ---------------------------------------------

# (label, getter, setter, slider min, slider max, units per slider step).
# Trackbars are integers only, hence the step factor for output scale.
TRACKBARS = [
    ("lens FOV", lambda v: v.profile.lens_fov_deg, "set_lens_fov", 20, 220, 1.0),
    ("out FOV", lambda v: v.profile.output_fov_deg, "set_output_fov", 10, 170, 1.0),
    ("scale x100", lambda v: v.profile.output_scale, "set_output_scale", 10, 400, 0.01),
    ("rows", lambda v: v.rows, "set_rows", 1, 32, 1.0),
    ("cols", lambda v: v.cols, "set_cols", 1, 32, 1.0),
]


def create_trackbars(window, viewer):
    """Attach the sliders, tolerating OpenCV builds that have no GUI for them.

    Each callback compares against the current value first: cv2 fires the
    callback on setTrackbarPos too, so without that guard syncing a slider back
    from a typed command would bounce straight back as a slider event.
    """
    def make(label, getter, setter_name, step):
        def on_change(pos):
            if viewer.syncing_trackbars:
                return
            value = pos * step
            if abs(getter(viewer) - value) < step / 2:
                return
            viewer.log.add(True, getattr(viewer, setter_name)(value))
        return on_change

    try:
        for label, getter, setter_name, lo, hi, step in TRACKBARS:
            cv2.createTrackbar(label, window, int(round(getter(viewer) / step)),
                               int(hi / step) if step < 1 else hi,
                               make(label, getter, setter_name, step))
            if step >= 1:
                cv2.setTrackbarMin(label, window, lo)
    except cv2.error as exc:
        viewer.log.add(False, f"trackbars unavailable ({exc.err.strip()[:40]}) — "
                              "use ':' or the terminal")
        return False
    return True


def sync_trackbars(window, viewer):
    """Push the current values back onto the sliders after a command or key."""
    viewer.syncing_trackbars = True
    try:
        for label, getter, _, _, _, step in TRACKBARS:
            cv2.setTrackbarPos(label, window, int(round(getter(viewer) / step)))
    except cv2.error:
        pass
    finally:
        viewer.syncing_trackbars = False


# --- input channel 2: keys in the window ------------------------------------

def handle_key(key, viewer):
    """Single-key shortcuts. Returns a (ok, message) pair, always.

    Every key produces feedback, including keys that do nothing — an
    unrecognised key still says so on screen, which is what distinguishes "that
    key isn't bound" from "the window never received it".
    """
    p = viewer.profile
    if key in (ord("q"), 27):
        viewer.running = False
        return True, "quitting"
    if key == ord(":"):
        viewer.edit.open()
        return True, "command prompt open — type, then Enter (Esc cancels)"
    if key == ord("?"):
        viewer.show_keys = not viewer.show_keys
        return True, f"key list {'shown' if viewer.show_keys else 'hidden'}"

    if key == ord("["):
        return True, viewer.set_lens_fov(p.lens_fov_deg - 2)
    if key == ord("]"):
        return True, viewer.set_lens_fov(p.lens_fov_deg + 2)
    if key == ord("-"):
        return True, viewer.set_output_fov(p.output_fov_deg - 5)
    if key in (ord("="), ord("+")):
        return True, viewer.set_output_fov(p.output_fov_deg + 5)
    if key == ord(","):
        return True, viewer.set_output_scale(p.output_scale - 0.1)
    if key == ord("."):
        return True, viewer.set_output_scale(p.output_scale + 0.1)
    if key == ord("m"):
        nxt = MODEL_NAMES[(MODEL_NAMES.index(p.model) + 1) % len(MODEL_NAMES)]
        return True, viewer.set_model(nxt)
    if key == ord("i"):
        nxt = INTERP_NAMES[(INTERP_NAMES.index(viewer.interp) + 1) % len(INTERP_NAMES)]
        return True, viewer.set_interp(nxt)

    if key == ord("u"):
        return True, f"view {viewer.cycle('view', VIEWS)}"
    if key == ord("g"):
        return True, f"grid {viewer.cycle('grid', GRID_MODES)}"
    if key == ord("h"):
        return True, viewer.commands.execute("hover").message
    if key == ord("c"):
        return True, viewer.commands.execute("clear").message
    if key == ord("s"):
        result = viewer.commands.execute("snap")
        return result.ok, result.message
    if key == ord("w"):
        result = viewer.commands.execute("save")
        return result.ok, result.message
    if key == ord("r"):
        result = viewer.commands.execute("reset")
        return result.ok, result.message

    label = chr(key) if 32 <= key <= 126 else "?"
    return False, f"key '{label}' ({key}) is not bound — press '?' for the list"


def on_mouse(event, x, y, flags, viewer):
    """Cursor tracking and click-to-measure, in displayed-window coordinates.

    --display-scale means the window is not 1:1 with the image, so the render
    loop converts these back; storing them raw keeps this callback trivial,
    which matters because it runs on OpenCV's UI thread.
    """
    viewer.mouse = (x, y)
    if event == cv2.EVENT_LBUTTONDOWN:
        viewer.pending_click = (x, y)
    elif event == cv2.EVENT_RBUTTONDOWN:
        viewer.pending_click = None
        viewer.points.clear()
        viewer.log.add(True, "measurement points cleared")


# --- rendering ---------------------------------------------------------------

def save_snapshot(raw, corrected, profile):
    """Write both images to captures/, tagging the corrected one with its params."""
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    tag = f"{profile.model}-lens{profile.lens_fov_deg:.0f}-out{profile.output_fov_deg:.0f}"
    raw_path = CAPTURE_DIR / f"{stamp}_raw.png"
    fixed_path = CAPTURE_DIR / f"{stamp}_undistorted_{tag}.png"
    cv2.imwrite(str(raw_path), raw)
    cv2.imwrite(str(fixed_path), corrected)
    return f"saved {raw_path.name} + {fixed_path.name}"


def side_by_side(raw, corrected):
    """Stack raw and corrected at a common height for an A/B comparison."""
    h = min(raw.shape[0], corrected.shape[0])

    def fit(img):
        scale = h / img.shape[0]
        return cv2.resize(img, (max(1, round(img.shape[1] * scale)), h),
                          interpolation=cv2.INTER_AREA)

    left, right = fit(raw), fit(corrected)
    pair = np.hstack([left, right])
    cv2.line(pair, (left.shape[1], 0), (left.shape[1], h), (0, 255, 0), 1)
    return pair


def draw_overlays(view, viewer, fps, corrected_view):
    """Grid, hover readout, measurements, HUD and console — in that order.

    `corrected_view` says whether the image underneath is the corrected one.
    Centimetre readings are only defensible there, so the grid falls back to
    pixels (with a warning) rather than quietly printing numbers that are wrong
    by a factor of three at the frame edges.
    """
    h, w = view.shape[:2]
    cm_x, cm_y = viewer.cm_per_px((w, h))
    metric = viewer.grid == "cm" and corrected_view
    # The side-by-side view is two rescaled images glued together, so no single
    # coordinate system covers it: the grid still works as a straightness ruler,
    # but cell bounds and measurements would be nonsense.
    pointing = viewer.view != "both"

    if viewer.grid != "off":
        cell_w, cell_h = draw_grid(view, viewer.rows, viewer.cols)
        draw_grid_labels(view, viewer.rows, viewer.cols,
                         cm_x if metric else None, cm_y if metric else None)

        if viewer.hover and pointing:
            mx, my = viewer.image_mouse(view.shape)
            cell = hovered_cell(mx, my, w, h, cell_w, cell_h, viewer.rows, viewer.cols)
            if cell:
                row, col, x1, y1, x2, y2 = cell
                lines = [f"cell (row={row}, col={col})",
                         f"px:  ({x1},{y1}) -> ({x2},{y2})  {x2 - x1}x{y2 - y1}"]
                if metric:
                    lines += [
                        f"X: {x1 * cm_x:.2f} -> {x2 * cm_x:.2f} cm  "
                        f"(w={(x2 - x1) * cm_x:.2f} cm)",
                        f"Y: {y1 * cm_y:.2f} -> {y2 * cm_y:.2f} cm  "
                        f"(h={(y2 - y1) * cm_y:.2f} cm)",
                    ]
                draw_cell_info(view, cell, lines, width=340 if metric else 240)

    if pointing:
        draw_measure(view, viewer.points,
                     cm_x if metric else None, cm_y if metric else None)

    stats = sampling_stats(viewer.maps)
    hud = [
        f"PROFILE: {'CALIBRATED' if viewer.profile.calibrated else 'ESTIMATED (uncalibrated)'}",
        f"lens FOV {viewer.profile.lens_fov_deg:.0f}deg ({viewer.profile.fov_reference})"
        f"  model {viewer.profile.model}",
        f"out FOV {viewer.profile.output_fov_deg:.0f}deg  "
        f"{viewer.maps.out_size[0]}x{viewer.maps.out_size[1]}  "
        f"scale {viewer.profile.output_scale:.2f}  {viewer.interp}",
        f"grid {viewer.grid} {viewer.rows}x{viewer.cols}  "
        f"span {viewer.frame_w_cm:.1f}x{viewer.frame_h_cm:.1f}cm  {fps:5.1f} fps",
        f"SAMPLE src px/out px: centre {stats['centre']:.2f}  edge {stats['edge']:.2f}",
    ]
    # Inset from the corner so the grid's own axis labels, which hug the top and
    # left edges, stay readable underneath a wide HUD.
    draw_info_box(view, hud, origin=(38, 20),
                  highlight_first=not viewer.profile.calibrated)

    warnings = []
    if viewer.grid == "cm" and not corrected_view:
        warnings.append(("cm grid needs the CORRECTED view — press 'u'", WARN_COLOR))
    if not pointing:
        warnings.append(("side-by-side: no cell readout or measuring", WARN_COLOR))
    if warnings:
        draw_text_panel(view, warnings, anchor="top-right")

    console = []
    if viewer.show_keys:
        console += [(line, HINT_COLOR) for line in __doc__.split("Keys\n----")[1]
                    .split("Mouse:")[0].strip().splitlines()]
    console += [(text, OK_COLOR if ok else ERR_COLOR)
                for ok, text in viewer.log.recent(count=6)]
    if viewer.edit.active:
        console.append((viewer.edit.render(), PROMPT_COLOR))
    else:
        console.append((
            "press ':' to type a command here, or type it in the terminal — 'help' lists them",
            HINT_COLOR))
    draw_text_panel(view, console, anchor="bottom-left")


def main():
    args = parse_args()
    profile = profile_from_args(args)
    viewer = Viewer(args, profile)

    controls = build_controls(args.sharpness, args.denoise, args.shutter,
                              args.gain, args.awb)
    try:
        camera = open_camera(args.backend, capture_size(args), args.device, controls)
    except RuntimeError as exc:
        print(exc)
        sys.exit(1)

    viewer.rebuild(camera.size)
    print(f"Camera: {camera.name}")
    for line in viewer.status_lines():
        print("  " + line)
    print("\nCommands (type them right here in this terminal, then Enter):")
    print("\n".join(viewer.commands.help_lines()))
    print("\nOr press ':' in the image window to type them there. '?' lists the keys.")

    window = "Undistorted Grid Viewer"
    cv2.namedWindow(window, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(window, on_mouse, viewer)
    create_trackbars(window, viewer)
    start_stdin_reader(viewer)

    fps, last = 0.0, time.perf_counter()
    try:
        while viewer.running:
            ok, frame = camera.read()
            if not ok or frame is None:
                print("Failed to read frame from camera.")
                break
            if args.swap_rb:
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

            # The driver can hand back a size we didn't ask for, and the maps are
            # built for one exact input size.
            if frame.shape[1::-1] != camera.size:
                camera.size = frame.shape[1::-1]
                viewer.dirty = True
            if viewer.dirty:
                viewer.rebuild(camera.size)
                sync_trackbars(window, viewer)

            corrected = undistort(frame, viewer.maps)
            viewer.last_raw, viewer.last_corrected = frame, corrected

            if viewer.view == "both":
                view = side_by_side(frame, corrected)
            else:
                # copy() so the overlays never contaminate the snapshot images.
                view = (corrected if viewer.view == "corrected" else frame).copy()

            # A click lands in window coordinates; convert once the view exists,
            # because only then is the displayed size known.
            if viewer.pending_click is not None and viewer.view == "both":
                viewer.pending_click = None
                viewer.log.add(False, "measuring needs a single view — press 'u'")
            if viewer.pending_click is not None:
                viewer.points.append(viewer.image_mouse(view.shape,
                                                        viewer.pending_click))
                viewer.points[:] = viewer.points[-2:]
                viewer.pending_click = None
                viewer.log.add(True, f"point {len(viewer.points)} placed "
                                     f"({'A' if len(viewer.points) == 1 else 'AB'})")

            now = time.perf_counter()
            dt, last = now - last, now
            if dt > 0:
                fps = 0.9 * fps + 0.1 * (1.0 / dt) if fps else 1.0 / dt

            # "both" halves the images to fit them side by side, so neither the
            # cm scale nor the hover cell means anything there.
            draw_overlays(view, viewer, fps, corrected_view=viewer.view == "corrected")

            if args.display_scale != 1.0:
                view = cv2.resize(view, None, fx=args.display_scale,
                                  fy=args.display_scale, interpolation=cv2.INTER_AREA)
            cv2.imshow(window, view)

            for line in viewer.drain_pending():
                result = viewer.commands.execute(line)
                if result is not None:
                    viewer.log.push(result)
                    print(("OK: " if result.ok else "ERR: ") + result.message)
                    sync_trackbars(window, viewer)

            key = cv2.waitKeyEx(1)
            if key != -1:
                if viewer.edit.active:
                    line = viewer.edit.key(key)
                    if line:
                        viewer.log.push(viewer.commands.execute(line))
                        sync_trackbars(window, viewer)
                    elif line == "":
                        viewer.log.add(True, "prompt closed")
                else:
                    ok_key, message = handle_key(key, viewer)
                    viewer.log.add(ok_key, message)
                    if ok_key:
                        sync_trackbars(window, viewer)

            if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        viewer.running = False
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
