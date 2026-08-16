#!/usr/bin/env python3
"""One frame source for both machines: Picamera2 on the Pi, V4L2 anywhere else.

On a Pi 5 the CSI camera is only reachable through libcamera/Picamera2 - the
/dev/video* nodes carry raw Bayer, so cv2.VideoCapture cannot be used on the
OV5647 there. The V4L2 path exists so these tools still run on a dev laptop
with a USB webcam.
"""

import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
from camera_viewer import choose_device, list_camera_devices

DEFAULT_SIZE = (1296, 972)  # OV5647 binned mode: full sensor FOV, 4:3, fast


class V4L2Source:
    """cv2.VideoCapture wrapper (USB webcams, and non-Pi dev machines)."""

    def __init__(self, dev_path=None, size=DEFAULT_SIZE):
        if dev_path is None:
            devices = list_camera_devices()
            if not devices:
                raise RuntimeError("No camera devices found under /dev/video*.")
            dev_path = choose_device(devices)

        self.cap = cv2.VideoCapture(dev_path, cv2.CAP_V4L2)
        if not self.cap.isOpened():
            raise RuntimeError(f"Failed to open {dev_path}")

        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, size[0])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])

        w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.size = (w, h)
        self.name = f"v4l2 {dev_path} @ {w}x{h}"

    def read(self):
        return self.cap.read()

    def release(self):
        self.cap.release()


class Picamera2Source:
    """Raspberry Pi CSI camera via libcamera/Picamera2."""

    def __init__(self, size=DEFAULT_SIZE):
        from picamera2 import Picamera2

        self.picam2 = Picamera2()
        mode = pick_full_fov_mode(self.picam2.sensor_modes, size)

        kwargs = {
            # libcamera's "RGB888" lands in memory as B,G,R - i.e. already what
            # OpenCV wants. Use --swap-rb in the viewer if that ever changes.
            "main": {"size": tuple(size), "format": "RGB888"},
            "buffer_count": 4,
        }
        if mode is not None:
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

    def read(self):
        frame = self.picam2.capture_array("main")
        return frame is not None, frame

    def release(self):
        self.picam2.stop()
        self.picam2.close()


def pick_full_fov_mode(sensor_modes, want):
    """Smallest sensor mode that still reads out the *full* sensor area.

    Matters because the OV5647's 1080p mode is a centre crop - picking it would
    silently throw away most of the 160 degree field of view and invalidate the
    FOV-derived focal length estimate.
    """
    if not sensor_modes:
        return None

    def fov_area(mode):
        crop = mode.get("crop_limits")
        if crop and len(crop) == 4 and crop[2] and crop[3]:
            return crop[2] * crop[3]
        return mode["size"][0] * mode["size"][1]

    widest = max(fov_area(m) for m in sensor_modes)
    full_fov = [m for m in sensor_modes if fov_area(m) >= widest * 0.98]

    big_enough = [
        m for m in full_fov if m["size"][0] >= want[0] and m["size"][1] >= want[1]
    ]
    pool = big_enough or full_fov
    return min(pool, key=lambda m: m["size"][0] * m["size"][1])


def open_camera(backend="auto", size=DEFAULT_SIZE, device=None):
    """backend: "auto" (Picamera2 then V4L2), "picamera2", or "v4l2"."""
    if backend in ("auto", "picamera2"):
        try:
            return Picamera2Source(size)
        except Exception as exc:
            if backend == "picamera2":
                raise
            print(f"Picamera2 unavailable ({exc}); falling back to V4L2.")
    return V4L2Source(device, size)
