# Camera Debugging Tools

## Run

```bash
source .venv/bin/activate
python debugging/camera_viewer.py   # pick a device, preview it
python debugging/grid_viewer.py     # preview with a hoverable grid overlay
python tests/grid_viewer_35cm_vertical_20cm_horizontal.py  # grid overlay + real-world cm/m measurements
```

Or without activating:

```bash
.venv/bin/python debugging/camera_viewer.py
.venv/bin/python debugging/grid_viewer.py
.venv/bin/python tests/grid_viewer_35cm_vertical_20cm_horizontal.py
```

Pick a device from the list, then press `q` or `Esc` in the popup window to quit.

`grid_viewer.py` overlays an 8x8 grid on the feed — hover any block to see its
row/col index, start point, end point, and size.

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
