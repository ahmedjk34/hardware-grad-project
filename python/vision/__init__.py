"""Reusable camera/vision building blocks.

Nothing in this package opens a window, parses arguments, or prints to stdout on
import — that all lives in the runnable tools one directory up. Keeping the split
means the same code can later be imported by the block-detection and
robot-coordinate stages without dragging a preview UI along with it.

Modules
-------
devices        enumerate and pick /dev/video* capture devices
camera_source  one frame source: Picamera2 on the Pi, V4L2 elsewhere
fisheye        the 160-degree fisheye -> rectilinear correction
overlays       shared OpenCV drawing helpers (grids, info boxes)
block_detector segment the work surface's blocks out of one frame
color_grid     find the printed two-colour calibration sheet and fit a grid
color_grid_overlay  draw that fitted sheet, and the envelope it calibrates to
"""
