#!/usr/bin/env python3
"""List available Linux camera devices, let the user pick one, and preview it with OpenCV."""

import glob
import subprocess
import sys

import cv2


def list_camera_devices():
    devices = sorted(glob.glob("/dev/video*"), key=lambda p: int(p.replace("/dev/video", "")))
    labeled = []
    for dev in devices:
        info = get_device_info(dev)
        if info["can_capture"]:
            labeled.append((dev, info["name"]))
    return labeled


def get_device_info(dev_path):
    info = {"name": "Unknown device", "can_capture": False}
    try:
        result = subprocess.run(
            ["v4l2-ctl", "--device", dev_path, "--all"],
            capture_output=True, text=True, timeout=2,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        # v4l2-ctl unavailable: assume it's a capture device and let OpenCV decide.
        info["can_capture"] = True
        return info

    lines = result.stdout.splitlines()
    in_device_caps = False
    for line in lines:
        if "Card type" in line:
            info["name"] = line.split(":", 1)[1].strip()
        if "Device Caps" in line:
            in_device_caps = True
            continue
        if in_device_caps:
            if not line.startswith("\t\t"):
                in_device_caps = False
                continue
            if "Video Capture" in line:
                info["can_capture"] = True
    return info


def choose_device(devices):
    print("Available camera devices:\n")
    for i, (dev, name) in enumerate(devices):
        print(f"  [{i}] {dev} - {name}")
    print()

    while True:
        choice = input(f"Select a device [0-{len(devices) - 1}]: ").strip()
        if choice.isdigit() and 0 <= int(choice) < len(devices):
            return devices[int(choice)][0]
        print("Invalid selection, try again.")


def preview_camera(dev_path):
    cap = cv2.VideoCapture(dev_path, cv2.CAP_V4L2)

    if not cap.isOpened():
        print(f"Failed to open {dev_path}")
        sys.exit(1)

    window_name = f"Camera Preview - {dev_path} (press 'q' or ESC to quit)"
    print("Streaming... press 'q' or ESC in the window to quit.")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("Failed to read frame from camera.")
                break

            cv2.imshow(window_name, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):  # 'q' or ESC
                break
            if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


def main():
    devices = list_camera_devices()
    if not devices:
        print("No camera devices found under /dev/video*.")
        sys.exit(1)

    dev_path = choose_device(devices)
    preview_camera(dev_path)


if __name__ == "__main__":
    main()
