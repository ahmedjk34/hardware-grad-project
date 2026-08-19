#!/usr/bin/env python3
"""Plain camera preview — the "is the camera alive?" tool.

Shows the raw feed with no processing whatsoever, so it is the right thing to
reach for when checking wiring, focus, exposure or framing. Use
undistorted_viewer.py instead when you want the fisheye corrected.

    python camera_viewer.py                     # auto-detect (Picamera2, else V4L2)
    python camera_viewer.py --backend v4l2      # force the /dev/video* picker

Press 'q' or Esc in the window to quit.
"""

import argparse
import sys
from pathlib import Path

import cv2

# This tool lives one folder down, so python/ is not on the import path when it
# is run directly. Put it there before the shared libraries below are imported —
# without this, `python grid/grid_viewer.py` dies on `import vision`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vision.camera_source import DEFAULT_SIZE, open_camera


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--backend", choices=["auto", "picamera2", "v4l2"], default="auto")
    parser.add_argument("--device", help="V4L2 path, e.g. /dev/video0 (skips the picker)")
    parser.add_argument("--width", type=int, default=DEFAULT_SIZE[0])
    parser.add_argument("--height", type=int, default=DEFAULT_SIZE[1])
    return parser.parse_args()


def main():
    args = parse_args()

    try:
        camera = open_camera(args.backend, (args.width, args.height), args.device)
    except RuntimeError as exc:
        print(exc)
        sys.exit(1)

    print(f"Camera: {camera.name}")
    print("Streaming... press 'q' or Esc in the window to quit.")

    window = f"Camera Preview - {camera.name}"
    try:
        while True:
            ok, frame = camera.read()
            if not ok or frame is None:
                print("Failed to read frame from camera.")
                break

            cv2.imshow(window, frame)
            if (cv2.waitKey(1) & 0xFF) in (ord("q"), 27):
                break
            # Also exit when the window is closed with the title-bar button.
            if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
