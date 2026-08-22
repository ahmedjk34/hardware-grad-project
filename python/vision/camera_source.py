#!/usr/bin/env python3
"""One frame source for both machines: Picamera2 on the Pi, V4L2 anywhere else.

Why two backends
----------------
On a Raspberry Pi 5 the CSI camera is reachable ONLY through libcamera/Picamera2.
The /dev/video* nodes the Pi exposes carry raw Bayer sensor data, not decoded
frames, so cv2.VideoCapture cannot read the OV5647 there at all. The V4L2 path
exists so these same tools still run on a dev laptop with a USB webcam.

Both classes present the same tiny interface, so callers never branch on backend:

    camera = open_camera()
    ok, frame = camera.read()      # frame is BGR uint8, ready for OpenCV
    camera.release()

Attributes `camera.size` (w, h) and `camera.name` (human description) are also
part of that interface, as is `camera.apply(settings)` — see SENSOR_CONTROLS.
"""

from dataclasses import dataclass
import threading
import time

import cv2

from vision.devices import choose_device, list_camera_devices

# OV5647 binned readout: the widest 4:3 mode, i.e. the full sensor area and so
# the full 160-degree field. Deliberately NOT 1920x1080 — see pick_full_fov_mode.
DEFAULT_SIZE = (1296, 972)

# OV5647 full readout: same field of view, four times the pixels, and capped at
# about 15 fps. Capturing here and rendering a smaller corrected image is the
# single biggest sharpness win available, because fisheye correction magnifies
# the edges of the frame by ~3x and that detail has to come from somewhere.
FULL_RES_SIZE = (2592, 1944)


AUTO = "auto"          # "hand this back to the camera's own loop"

# libcamera's white-balance presets. Spelled as libcamera spells them, because
# the enum member is looked up by name.
AWB_MODES = ("auto", "incandescent", "tungsten", "fluorescent", "indoor",
             "daylight", "cloudy")
DENOISE_MODES = ("off", "fast", "hq")


@dataclass(frozen=True)
class FrameSnapshot:
    """The newest frame a :class:`LatestFramePump` has received.

    ``age_s`` is deliberately measured by the caller rather than at capture
    time.  That lets a UI show a truthful "last frame was N seconds ago"
    warning even when a camera backend has stopped returning from ``read()``.
    """

    frame: object | None
    captured_at: float | None
    sequence: int
    error: str | None

    def age_s(self, now: float | None = None) -> float | None:
        if self.captured_at is None:
            return None
        return max(0.0, (time.monotonic() if now is None else now) - self.captured_at)


class LatestFramePump:
    """Read a camera on one daemon thread and expose its latest frame safely.

    Picamera2's ``capture_array()`` is a synchronous call.  If its CSI/libcamera
    pipeline gets stuck, a UI that calls it directly cannot redraw a warning,
    handle its close key, or keep reporting build state.  This pump contains
    that one blocking call in a producer thread.  Consumers always get the
    latest completed frame immediately; a stale timestamp says when the camera
    stopped advancing.

    The pump intentionally does not call ``source.release()``.  A backend may
    be stuck inside ``read()`` and releasing it concurrently is unsafe.  Call
    :meth:`stop` first and release the source only after it returns ``True``.
    """

    def __init__(self, source):
        self._source = source
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._frame = None
        self._captured_at: float | None = None
        self._sequence = 0
        self._error: str | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="camera-frame-pump", daemon=True
        )
        self._thread.start()

    def snapshot(self) -> FrameSnapshot:
        """Return immediately, including while the backend is stuck in read()."""
        with self._lock:
            return FrameSnapshot(self._frame, self._captured_at, self._sequence,
                                 self._error)

    def stop(self, timeout: float = 2.0) -> bool:
        """Ask the reader to stop; ``False`` means it remains blocked in read()."""
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
        return not self.running

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                ok, frame = self._source.read()
            except Exception as exc:  # backend errors must not take down the UI
                with self._lock:
                    self._error = f"camera read failed: {exc}"
                # Avoid a hot loop if a disconnected backend raises instantly;
                # keep trying because a transient libcamera fault may recover.
                self._stop.wait(0.1)
                continue

            if not ok or frame is None:
                with self._lock:
                    self._error = "camera returned no frame"
                self._stop.wait(0.02)
                continue

            with self._lock:
                self._frame = frame
                self._captured_at = time.monotonic()
                self._sequence += 1
                self._error = None


@dataclass(frozen=True)
class ControlSpec:
    """One adjustable sensor setting, and how each backend spells it.

    The point of this table is that the tools never name a libcamera control or
    a cv2.CAP_PROP_ directly: they say "saturation" and the backend translates.
    That is what lets one set of commands and one set of sliders drive both a Pi
    CSI camera and a USB webcam.

    `lo`/`hi` are the PICAMERA2 ranges, which are the meaningful ones — libcamera
    normalises these controls to documented units. UVC webcams do not: a V4L2
    driver reports whatever integer range it likes (0..255 and -64..64 are both
    common) and the same number means something different on each. On the V4L2
    backend, treat these as raw driver units and tune by eye.
    """

    name: str
    kind: str              # "float" | "int" | "choice"
    lo: float = 0.0
    hi: float = 1.0
    choices: tuple = ()
    libcamera: str = ""    # libcamera control name, "" if unsupported there
    v4l2: int = -1         # cv2.CAP_PROP_*, -1 if unsupported there
    auto: bool = False     # the camera runs a real feedback LOOP for this one
    help: str = ""

    # EVERY control accepts "auto", not just the ones with `auto` set — see
    # libcamera_controls, which simply omits anything set to AUTO. The flag
    # distinguishes the two things that then happen: with it, a hardware loop
    # (AE, AWB) takes the wheel; without it, the ISP keeps its own default.
    # Either way the control is not sent, and either way "auto" is accepted.

    @property
    def range_text(self):
        if self.kind == "choice":
            choices = self.choices
            if AUTO not in choices:
                choices = (AUTO,) + tuple(choices)
            return "|".join(choices)
        return f"{self.lo:g}..{self.hi:g}|auto"

    @property
    def display_chars(self):
        """Widest value this control can display, for sizing a text box.

        Computed from the control rather than from whatever it holds right now,
        so a value growing from 4 characters to 12 does not shove the rest of
        the panel row sideways.
        """
        if self.kind == "choice":
            return max(len(c) for c in self.range_text.split("|")) + 1
        return max(8, len(f"{self.hi:g}") + 2)


# Ordered because this is also the order they are printed and given sliders in.
SENSOR_CONTROLS = {
    c.name: c for c in (
        ControlSpec("brightness", "float", -1.0, 1.0, libcamera="Brightness",
                    v4l2=cv2.CAP_PROP_BRIGHTNESS,
                    help="lift/lower the whole image; 0 is neutral"),
        ControlSpec("contrast", "float", 0.0, 8.0, libcamera="Contrast",
                    v4l2=cv2.CAP_PROP_CONTRAST,
                    help="1.0 is neutral, 0 is flat grey"),
        ControlSpec("saturation", "float", 0.0, 8.0, libcamera="Saturation",
                    v4l2=cv2.CAP_PROP_SATURATION,
                    help="1.0 is neutral, 0 is monochrome"),
        ControlSpec("sharpness", "float", 0.0, 16.0, libcamera="Sharpness",
                    v4l2=cv2.CAP_PROP_SHARPNESS,
                    help="ISP sharpening; LOWER it, the correction magnifies halos"),
        ControlSpec("ev", "float", -8.0, 8.0, libcamera="ExposureValue",
                    help="exposure compensation in stops, while AE is on"),
        ControlSpec("exposure", "int", 100, 200000, libcamera="ExposureTime",
                    v4l2=cv2.CAP_PROP_EXPOSURE, auto=True,
                    help="shutter time in microseconds; a number turns AE off"),
        ControlSpec("gain", "float", 1.0, 16.0, libcamera="AnalogueGain",
                    v4l2=cv2.CAP_PROP_GAIN, auto=True,
                    help="analogue gain; a number turns AE off. Pin low, add light"),
        ControlSpec("awb", "choice", choices=AWB_MODES + ("off",),
                    libcamera="AwbMode", v4l2=cv2.CAP_PROP_AUTO_WB,
                    help="white balance preset; 'off' hands over to red/bluegain"),
        ControlSpec("redgain", "float", 0.1, 8.0, libcamera="ColourGains",
                    help="manual red channel gain; needs 'awb off'"),
        ControlSpec("bluegain", "float", 0.1, 8.0, libcamera="ColourGains",
                    help="manual blue channel gain; needs 'awb off'"),
        ControlSpec("denoise", "choice", choices=DENOISE_MODES,
                    libcamera="NoiseReductionMode",
                    help="'fast' blurs fine texture away; 'hq' keeps much more"),
        ControlSpec("fps", "float", 1.0, 120.0, libcamera="FrameDurationLimits",
                    v4l2=cv2.CAP_PROP_FPS, auto=True,
                    help="cap the frame rate; a low cap lets AE use a longer shutter"),
    )
}


def libcamera_controls(settings: dict) -> dict:
    """Translate our setting names into a libcamera control dict.

    Anything set to "auto" (or left out) is omitted, so the camera keeps running
    its own loop for it — which is different from, and better than, pinning it to
    whatever value the loop happened to have settled on.

    The couplings that are easy to get wrong are all handled here, once:

      * ExposureTime and AnalogueGain do nothing while the AE loop is running,
        so setting either of them also sets AeEnable False. Setting neither
        leaves AE on, and ExposureValue then works as compensation.
      * ColourGains does nothing while AWB is running, so red/bluegain imply
        AwbEnable False. They are one control taking a PAIR, hence the lookup
        of both before emitting it.
    """
    out = {}

    def num(name):
        value = settings.get(name, AUTO)
        return None if value in (None, AUTO) else value

    for name in ("brightness", "contrast", "saturation", "sharpness", "ev"):
        value = num(name)
        if value is not None:
            out[SENSOR_CONTROLS[name].libcamera] = float(value)

    shutter, gain = num("exposure"), num("gain")
    if shutter is not None or gain is not None:
        out["AeEnable"] = False
        if shutter is not None:
            out["ExposureTime"] = int(shutter)
        if gain is not None:
            out["AnalogueGain"] = float(gain)
    else:
        out["AeEnable"] = True

    awb = settings.get("awb", AUTO)
    red, blue = num("redgain"), num("bluegain")
    if awb == "off" or red is not None or blue is not None:
        out["AwbEnable"] = False
        # Both halves are needed: libcamera takes the pair or nothing.
        out["ColourGains"] = (float(red or 1.0), float(blue or 1.0))
    elif awb not in (None, AUTO):
        mode = _libcamera_enum("AwbModeEnum", awb)
        if mode is not None:
            out["AwbEnable"] = True
            out["AwbMode"] = mode

    denoise = settings.get("denoise")
    if denoise not in (None, AUTO):
        mode = noise_reduction_mode(denoise)
        if mode is not None:
            out["NoiseReductionMode"] = mode

    fps = num("fps")
    if fps is not None:
        # libcamera caps the rate through the frame DURATION, in microseconds,
        # as a (min, max) pair. Both ends equal pins it to exactly that rate.
        micros = int(round(1_000_000.0 / max(1.0, float(fps))))
        out["FrameDurationLimits"] = (micros, micros)
    return out


def _libcamera_enum(enum_name, member):
    """Look up e.g. AwbModeEnum.Daylight by our lower-case name, tolerantly.

    Returns None rather than raising when libcamera is absent or has moved the
    enum — an unavailable preset must never stop the camera from running.
    """
    try:
        from libcamera import controls as libcontrols
        enum = getattr(libcontrols, enum_name)
    except Exception:
        return None
    return getattr(enum, member.capitalize(), None)


def noise_reduction_mode(name):
    """Map a friendly name onto libcamera's NoiseReductionMode enum.

    Kept tolerant: libcamera moved this control between namespaces across
    releases, and an unavailable denoise setting must not stop the camera from
    opening. Returns None if the enum cannot be found.
    """
    try:
        from libcamera import controls as libcontrols
        enum = libcontrols.draft.NoiseReductionModeEnum
    except Exception:
        return None
    return {
        "off": getattr(enum, "Off", None),
        "fast": getattr(enum, "Fast", None),
        # HighQuality denoises with a larger, edge-aware kernel. Slower, but it
        # smears fine detail far less than Fast does — and Fast's smearing is
        # exactly what the undistortion then magnifies at the frame edges.
        "hq": getattr(enum, "HighQuality", None),
    }.get(name)


class V4L2Source:
    """cv2.VideoCapture wrapper: USB webcams, and any non-Pi dev machine."""

    def __init__(self, dev_path=None, size=DEFAULT_SIZE, controls=None):
        # No device given: fall back to the interactive picker.
        if dev_path is None:
            devices = list_camera_devices()
            if not devices:
                raise RuntimeError("No camera devices found under /dev/video*.")
            dev_path = choose_device(devices)

        self.cap = cv2.VideoCapture(dev_path, cv2.CAP_V4L2)
        if not self.cap.isOpened():
            raise RuntimeError(f"Failed to open {dev_path}")

        # MJPG first: most USB cameras are limited to ~5 fps at this resolution
        # on raw YUYV, because uncompressed frames saturate the USB bandwidth.
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, size[0])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])

        # Read the size back — drivers silently substitute the nearest mode they
        # support, and the undistortion maps must match the real frame size.
        w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.size = (w, h)
        self.name = f"v4l2 {dev_path} @ {w}x{h}"
        # Image-quality controls are libcamera concepts; a UVC webcam has its
        # own unrelated set, so say so rather than failing silently.
        if controls:
            print("Note: --sharpness/--denoise/--shutter/--gain/--awb are "
                  "Picamera2-only and were ignored on the V4L2 backend.")

    def read(self):
        return self.cap.read()

    def apply(self, settings):
        """Push settings onto the driver. Returns (applied, skipped) name lists.

        Every cap.set() is checked by reading the property back, because a UVC
        driver's usual response to a control it does not implement is to return
        success and change nothing. Reporting it as applied when it was not is
        how you end up turning a knob for a minute wondering why the picture
        never moves.
        """
        applied, skipped = [], []
        for name, value in settings.items():
            spec = SENSOR_CONTROLS.get(name)
            if spec is None or spec.v4l2 < 0:
                skipped.append(f"{name} (no V4L2 equivalent)")
                continue
            if value in (None, AUTO):
                # Auto-exposure and auto-WB are the only autos V4L2 exposes, and
                # only as their own separate properties.
                if name == "exposure":
                    self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 3)   # 3 = aperture priority
                    applied.append("exposure auto")
                elif name == "awb":
                    self.cap.set(cv2.CAP_PROP_AUTO_WB, 1)
                    applied.append("awb auto")
                continue
            if name == "awb":
                self.cap.set(cv2.CAP_PROP_AUTO_WB, 0.0 if value == "off" else 1.0)
                applied.append(name)
                continue
            if spec.kind == "choice":
                skipped.append(f"{name} (no V4L2 equivalent)")
                continue
            if name == "exposure":
                self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)       # 1 = manual
            before = self.cap.get(spec.v4l2)
            self.cap.set(spec.v4l2, float(value))
            after = self.cap.get(spec.v4l2)
            if abs(after - float(value)) < 1e-6 or after != before:
                applied.append(name)
            else:
                skipped.append(f"{name} (driver refused; it reports {after:g})")
        return applied, skipped

    def release(self):
        self.cap.release()


class Picamera2Source:
    """Raspberry Pi CSI camera (OV5647) via libcamera/Picamera2."""

    def __init__(self, size=DEFAULT_SIZE, controls=None):
        # Imported lazily: this module must stay importable on machines without
        # libcamera, so that open_camera() can fall through to V4L2.
        from picamera2 import Picamera2

        self.picam2 = Picamera2()
        mode = pick_full_fov_mode(self.picam2.sensor_modes, size)

        kwargs = {
            # libcamera's "RGB888" is stored in memory as B,G,R — already the
            # byte order OpenCV expects, so no per-frame conversion is needed.
            # If colours ever come out inverted, the tools take --swap-rb.
            "main": {"size": tuple(size), "format": "RGB888"},
            # A few buffers in flight keeps capture from stalling on the
            # undistortion of the previous frame. Full-resolution RGB frames are
            # 15 MB each, so back off there rather than tie up 60 MB of CMA.
            "buffer_count": 3 if size[0] * size[1] > 2_500_000 else 4,
        }
        if controls:
            kwargs["controls"] = dict(controls)
        if mode is not None:
            # Pin the sensor readout, otherwise libcamera may pick a cropped
            # mode and quietly narrow the field of view.
            kwargs["raw"] = {"size": tuple(mode["size"])}

        try:
            config = self.picam2.create_video_configuration(**kwargs)
            self.picam2.configure(config)
            self.picam2.start()
        except Exception:
            self.picam2.close()  # don't leave the CSI device claimed on failure
            raise

        w, h = config["main"]["size"]
        self.size = (w, h)
        raw_desc = f", sensor mode {mode['size'][0]}x{mode['size'][1]}" if mode else ""
        self.name = f"picamera2 @ {w}x{h}{raw_desc}"
        self.sensor_modes = self.picam2.sensor_modes

    def read(self):
        frame = self.picam2.capture_array("main")
        return frame is not None, frame

    def apply(self, settings):
        """Push settings onto the running camera. Returns (applied, skipped).

        set_controls is asynchronous — it queues the values against a future
        frame — so the picture changes a frame or three after the call, not
        during it. That lag is normal and is not a failed control.
        """
        wanted = libcamera_controls(settings)
        available = set(getattr(self.picam2, "camera_controls", {}) or {})
        skipped = []
        if available:
            # Which controls exist depends on the sensor and the libcamera
            # build. Dropping the unknown ones keeps one bad name from making
            # set_controls reject the whole batch.
            unknown = [k for k in wanted if k not in available]
            for key in unknown:
                wanted.pop(key)
                skipped.append(f"{key} (not offered by this sensor)")
        if not wanted:
            return [], skipped
        try:
            self.picam2.set_controls(wanted)
        except Exception as exc:
            return [], skipped + [f"set_controls failed: {exc}"]
        return sorted(wanted), skipped

    def release(self):
        self.picam2.stop()
        self.picam2.close()


def pick_full_fov_mode(sensor_modes, want):
    """Smallest sensor mode that still reads out the *full* sensor area.

    This matters more than it looks. The OV5647's 1920x1080 mode is a centre
    crop of the sensor, not a downscale — selecting it would throw away most of
    the 160-degree field AND silently invalidate the focal length that
    vision.fisheye derives from the quoted FOV. So: first keep only the modes
    that see the whole sensor, then take the cheapest of those.

    Returns a sensor_modes entry, or None if the list is empty (caller then
    lets libcamera choose).
    """
    if not sensor_modes:
        return None

    def fov_area(mode):
        # crop_limits is (x, y, w, h) of the sensor area this mode reads out,
        # which is the real field-of-view measure. Older Picamera2 builds may
        # not report it; output size is then the best available proxy.
        crop = mode.get("crop_limits")
        if crop and len(crop) == 4 and crop[2] and crop[3]:
            return crop[2] * crop[3]
        return mode["size"][0] * mode["size"][1]

    widest = max(fov_area(m) for m in sensor_modes)
    # 2% tolerance: full-sensor modes can differ by a row or two of padding.
    full_fov = [m for m in sensor_modes if fov_area(m) >= widest * 0.98]

    # Prefer a mode at least as large as requested, so the main stream is
    # downscaled rather than upscaled. If none qualifies, take the largest.
    big_enough = [m for m in full_fov
                  if m["size"][0] >= want[0] and m["size"][1] >= want[1]]
    pool = big_enough or full_fov
    return min(pool, key=lambda m: m["size"][0] * m["size"][1])


def open_camera(backend="auto", size=DEFAULT_SIZE, device=None, controls=None):
    """Open a camera.

    backend:  "auto"      try Picamera2, fall back to V4L2 (the default)
              "picamera2" Pi CSI only; raises if unavailable
              "v4l2"      /dev/video* only
    device:   V4L2 path such as "/dev/video0"; None prompts interactively.
    controls: libcamera control dict (Sharpness, NoiseReductionMode, ...)
              applied at configure time. Picamera2 only; see build_controls.

    Note that on a Pi 5 the "auto" fallback to V4L2 will open a device but will
    not produce a usable image from the CSI camera — if you see the fallback
    message on the Pi, treat it as the real error.
    """
    if backend in ("auto", "picamera2"):
        try:
            return Picamera2Source(size, controls)
        except Exception as exc:
            if backend == "picamera2":
                raise
            print(f"Picamera2 unavailable ({exc}); falling back to V4L2.")
    return V4L2Source(device, size, controls)


def build_controls(sharpness=None, denoise=None, shutter_us=None, gain=None, awb=None):
    """Assemble a libcamera control dict from the tools' image-quality flags.

    Every argument is optional; anything left as None keeps libcamera's default,
    so passing nothing produces an empty dict and changes no behaviour.

    Why these five, specifically — they are the controls that decide whether the
    frame reaching the fisheye correction has real detail in it:

      sharpness   0 disables the ISP's sharpening entirely, 1.0 is the default,
                  higher over-sharpens. Worth turning DOWN when the correction
                  magnifies the edges, because it magnifies the halos too.
      denoise     "fast" (the video default) is a cheap spatial blur that eats
                  fine texture; "hq" keeps much more of it; "off" leaves the
                  sensor noise in, which is the honest input for calibration.
      shutter_us  fixes the exposure time. In dim light the AE otherwise picks a
                  long exposure AND high gain, and motion blur plus denoised
                  noise is the usual cause of a mushy-looking preview.
      gain        fixes analogue gain. Pin this low (1.0-2.0) and add light
                  rather than letting the AE run it up.
      awb         a named white-balance preset, for when auto AWB drifts into a
                  colour cast under artificial lighting.
    """
    settings = {"sharpness": sharpness, "denoise": denoise,
                "exposure": shutter_us, "gain": gain, "awb": awb}
    controls = libcamera_controls({k: v for k, v in settings.items()
                                   if v is not None})
    # libcamera_controls always states AeEnable, because a live tool needs to be
    # able to hand exposure back to the camera. At configure time, saying
    # nothing is what "leave the default alone" means, so drop the redundant
    # True and keep the historic behaviour of this function exactly.
    if controls.get("AeEnable") is True:
        controls.pop("AeEnable")
    return controls


def describe_sensor_modes(modes):
    """One line per sensor mode, marking which ones see the whole sensor.

    Printed by --list-modes. The point is to make it obvious at a glance which
    modes are full-field and which are centre crops, since picking a cropped one
    silently invalidates the lens FOV the correction is built on.
    """
    if not modes:
        return ["(no sensor modes reported)"]
    widest = max(
        (m.get("crop_limits") or (0, 0, *m["size"]))[2] *
        (m.get("crop_limits") or (0, 0, *m["size"]))[3]
        for m in modes
    )
    lines = []
    for m in modes:
        crop = m.get("crop_limits") or (0, 0, *m["size"])
        full = crop[2] * crop[3] >= widest * 0.98
        lines.append(
            f"  {m['size'][0]:>5}x{m['size'][1]:<5} "
            f"{str(m.get('format', '?')):<12} "
            f"crop {crop[2]}x{crop[3]} "
            f"{'FULL FIELD' if full else 'cropped — narrows the FOV'}"
        )
    return lines
