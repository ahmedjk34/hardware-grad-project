# Camera Debugging Tools

## Run

```bash
source .venv/bin/activate
python debugging/undistorted_viewer.py  # live fisheye-corrected preview
python debugging/camera_viewer.py   # pick a device, preview it
python debugging/grid_viewer.py     # preview with a hoverable grid overlay
python tests/grid_viewer_35cm_vertical_20cm_horizontal.py  # grid overlay + real-world cm/m measurements
```

Or without activating:

```bash
.venv/bin/python debugging/undistorted_viewer.py
.venv/bin/python debugging/camera_viewer.py
.venv/bin/python debugging/grid_viewer.py
.venv/bin/python tests/grid_viewer_35cm_vertical_20cm_horizontal.py
```

Pick a device from the list, then press `q` or `Esc` in the popup window to quit.

`grid_viewer.py` overlays an 8x8 grid on the feed — hover any block to see its
row/col index, start point, end point, and size.

## Fisheye correction (`debugging/undistorted_viewer.py`)

Live preview of the OV5647 160° fisheye, remapped to a rectilinear (straight-line)
projection. Runs at 1296×972 — the OV5647's binned mode, which is the widest 4:3
readout, so the full 160° field is preserved. The 1080p mode is a **centre crop**
and is deliberately not used.

> **The lens parameters are estimates, not a calibration.** They come from the
> vendor's "160°" FOV number plus an assumed ideal projection curve. Straight
> edges will look substantially straight; distances are not measurement-grade.
> The HUD says `ESTIMATED` until a real calibration replaces it.

```bash
.venv/bin/python debugging/undistorted_viewer.py                      # defaults
.venv/bin/python debugging/undistorted_viewer.py --output-fov 140 --output-scale 1.5
.venv/bin/python debugging/undistorted_viewer.py --backend v4l2 --device /dev/video0
```

Tune by eye against a real straight edge, then press `w` to save:

| key | effect |
| --- | --- |
| `q` / `Esc` | quit |
| `u` | toggle correction on/off |
| `b` | raw \| corrected side by side |
| `g` | grid overlay (judge straightness against it) |
| `[` `]` | lens FOV ∓2° — **the main correction-strength knob** |
| `-` `=` | output FOV ∓5° (how much of the 160° to render) |
| `m` | cycle projection model |
| `s` | save raw + corrected snapshot to `captures/` |
| `w` | write current params to `config/lens_profile.json` |
| `r` | reset to defaults |

If edges still bow **outward** (barrel remains), press `]`. If they bow **inward**
(over-corrected), press `[`.

Parameters live in [config/lens_profile.json](config/lens_profile.json). Later,
checkerboard/ChArUco calibration writes real `camera_matrix` / `dist_coeffs` /
`calibration_size` into the same file and
[fisheye_undistort.py](debugging/fisheye_undistort.py) switches to the OpenCV
fisheye model automatically — the output geometry and the rest of the pipeline
stay unchanged.

### On the Raspberry Pi 5

The Pi 5's CSI camera is only reachable through libcamera/Picamera2 — the
`/dev/video*` nodes carry raw Bayer, so `cv2.VideoCapture` will not work on the
OV5647 there. `python3-picamera2` is an apt package, so the venv must be able to
see system packages:

```bash
sudo apt install -y python3-picamera2
python3 -m venv --system-site-packages .venv
.venv/bin/pip install opencv-python
```

`tests/grid_viewer_35cm_vertical_20cm_horizontal.py` is the same grid, calibrated
to a frame that spans 20cm across X (horizontal) and 35cm across Y (vertical) —
hover a block to see its pixel bounds plus real-world start/end and size in cm
and meters, per axis. Edit `FRAME_WIDTH_CM`/`FRAME_HEIGHT_CM` at the top of the
file if your setup's physical dimensions change.

## First-time setup (if `.venv` doesn't exist yet)

```bash
python3 -m venv .venv
.venv/bin/pip install opencv-python
```
