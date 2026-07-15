# Camera Debugging Tools

## Run

```bash
source .venv/bin/activate
python debugging/camera_viewer.py   # pick a device, preview it
python debugging/grid_viewer.py     # preview with a hoverable grid overlay
```

Or without activating:

```bash
.venv/bin/python debugging/camera_viewer.py
.venv/bin/python debugging/grid_viewer.py
```

Pick a device from the list, then press `q` or `Esc` in the popup window to quit.

`grid_viewer.py` overlays an 8x8 grid on the feed — hover any block to see its
row/col index, start point, end point, and size.

## First-time setup (if `.venv` doesn't exist yet)

```bash
python3 -m venv .venv
.venv/bin/pip install opencv-python
```
