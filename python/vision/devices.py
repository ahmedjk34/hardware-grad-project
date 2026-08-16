#!/usr/bin/env python3
"""Enumerate and choose V4L2 (/dev/video*) capture devices.

Used by the tools when running against a USB webcam — typically the x86 dev
machine. On a Raspberry Pi 5 the CSI camera does NOT appear here as a usable
device (see camera_source.py for why), so this module is not the Pi path.
"""

import glob
import subprocess


def list_camera_devices():
    """Return [(path, human_name), ...] for every /dev/video* that can capture.

    Sorted numerically rather than lexically so /dev/video2 comes before
    /dev/video10. Devices that only expose metadata or output nodes are dropped,
    which matters because a single physical camera usually registers several
    /dev/video* nodes and only the first can actually deliver frames.
    """
    devices = sorted(
        glob.glob("/dev/video*"),
        key=lambda p: int(p.replace("/dev/video", "")),
    )
    return [(dev, info["name"]) for dev in devices
            if (info := get_device_info(dev))["can_capture"]]


def get_device_info(dev_path):
    """Query one device with v4l2-ctl. Falls back to "assume usable" if absent."""
    info = {"name": "Unknown device", "can_capture": False}
    try:
        result = subprocess.run(
            ["v4l2-ctl", "--device", dev_path, "--all"],
            capture_output=True, text=True, timeout=2,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        # v4l2-utils not installed: don't filter anything out, let OpenCV decide.
        info["can_capture"] = True
        return info

    # Walk the "Device Caps" block, which is indented two tabs under its header.
    in_device_caps = False
    for line in result.stdout.splitlines():
        if "Card type" in line:
            info["name"] = line.split(":", 1)[1].strip()
        if "Device Caps" in line:
            in_device_caps = True
            continue
        if in_device_caps:
            if not line.startswith("\t\t"):
                in_device_caps = False  # dedented: end of the block
                continue
            if "Video Capture" in line:
                info["can_capture"] = True
    return info


def choose_device(devices):
    """Prompt on stdin for one of `devices`; returns the chosen /dev/video* path."""
    print("Available camera devices:\n")
    for i, (dev, name) in enumerate(devices):
        print(f"  [{i}] {dev} - {name}")
    print()

    while True:
        choice = input(f"Select a device [0-{len(devices) - 1}]: ").strip()
        if choice.isdigit() and 0 <= int(choice) < len(devices):
            return devices[int(choice)][0]
        print("Invalid selection, try again.")
