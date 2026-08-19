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
part of that interface.
"""

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
    controls = {}
    if sharpness is not None:
        controls["Sharpness"] = float(sharpness)
    if denoise is not None:
        mode = noise_reduction_mode(denoise)
        if mode is not None:
            controls["NoiseReductionMode"] = mode
    if shutter_us is not None or gain is not None:
        # Any manual exposure setting only takes effect with the AE loop off.
        controls["AeEnable"] = False
        if shutter_us is not None:
            controls["ExposureTime"] = int(shutter_us)
        if gain is not None:
            controls["AnalogueGain"] = float(gain)
    if awb is not None:
        try:
            from libcamera import controls as libcontrols
            mode = getattr(libcontrols.AwbModeEnum, awb.capitalize(), None)
        except Exception:
            mode = None
        if mode is not None:
            controls["AwbEnable"] = True
            controls["AwbMode"] = mode
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
