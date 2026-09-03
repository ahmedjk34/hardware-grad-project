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
combined_grid  detect the one-page target shared by both machine-grid modes
cluster_grid   detect the black-bordered 3x3-cluster sheet by its printed lattice
grid_evidence  pool sheet observations across frames when the gantry occludes
block_grid     calibrate from blocks the rig places on cells it was told, and
               fill in every cell the block supply could not reach
color_grid_overlay  draw that fitted sheet, and the envelope it calibrates to

The two calibration families answer the same question differently. The
``*_grid`` sheet detectors measure the camera against a printed artefact and
then assume the artefact sits where the firmware's cells are. ``block_grid``
uses the machine's own blocks, so the thing measured is the thing calibrated —
see AGENTS.md 3d-bis for which to reach for and why.
"""
