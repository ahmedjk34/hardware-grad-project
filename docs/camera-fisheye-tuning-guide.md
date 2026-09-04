# Camera Studio fisheye-tuning guide

This guide covers every geometry control in Camera Studio, what it changes,
its accepted range, when to use it, and when to leave it alone.

The controls can make the image visually straight enough for grid detection.
They do not turn hand tuning into a measured camera calibration. For metric
accuracy, finish with a flat checkerboard or ChArUco calibration photographed
at several positions and angles.

## Before touching any value

Mechanically finish the camera first. Tighten the mount, focus the lens, choose
the capture resolution and orientation, and do not move the camera afterward.
Lens correction depends on all of these.

Use a target containing several genuinely straight lines:

- one near the left edge and one near the right edge;
- one near the top and one near the bottom;
- preferably diagonals too;
- lines that cross a large part of the image.

The machine rails or a rigid, flat calibration board are useful. A folded,
curled, sagging, or partly lifted printed colour sheet is **not** a lens target:
its real lines are already bent in 3D. It remains useful for testing the final
detector, but do not distort the camera model until it makes folded paper look
flat.

Start Camera Studio normally, then click **TUNE VIEW**. It deliberately:

- enables correction;
- displays raw and corrected images beside one another;
- draws a separate 8 x 8 straightness ruler on each image;
- removes crop and zoom;
- uses the full natural corrected frame;
- preserves sensor and colour settings.

Do not crop until lens tuning is finished. Cropping hides the outer image,
which is where most fisheye errors are visible.

## The required adjustment order

Use this order and return an advanced value to identity if it does not solve a
specific remaining error:

1. `lens fov`
2. `ref`
3. `model`
4. `k1`
5. `k2`
6. `k3`, then `k4`, only if necessary
7. `centre x`, `centre y`
8. `fx scale`, `fy scale`
9. `p1`, `p2`
10. `skew`, almost never
11. `out fov`, output scale, interpolation and mip for framing/quality
12. save, then test the colour-grid detector

Never tune all fields simultaneously. Change one value, inspect straight lines
on every side of the frame, and then keep or undo that change.

## Exact controls and ranges

### Lens FOV — `lens fov` / `fov`

| Property | Value |
| --- | --- |
| Accepted range | 20 to 220 degrees |
| Default | 160 degrees |
| Panel step | 2 degrees |
| Identity concept | No fixed identity; this is the base lens estimate |

This is the strongest geometry control. It establishes the focal length implied
by the advertised lens field of view and scales the whole source-radius model.

- Corrected edges still bow outward: increase the FOV.
- Corrected edges bow inward and look over-corrected: decrease the FOV.
- Tune against lines close to the frame edges. Lines through the centre look
  nearly straight over a wide range and are weak evidence.

Use 2-degree steps initially, then type 1-degree or 0.25-degree changes when
close. Do not compensate for a bad FOV with large `k1` through `k4` values.

The code accepts values above 180 because some commercial fisheye lenses quote
diagonal coverage above a hemisphere. That does not mean the camera actually
sees 220 degrees; use the smallest range supported by real image evidence.

### FOV reference — `ref`

| Property | Value |
| --- | --- |
| Choices | `diagonal`, `horizontal` |
| Default | `diagonal` |

This says which sensor measurement the quoted lens FOV describes.

- `diagonal`: the FOV reaches from one image corner to the opposite corner.
- `horizontal`: the FOV reaches from the left edge to the right edge.

Most “160-degree” lens advertisements mean diagonal unless explicitly stated
otherwise. Changing this has a large effect because the diagonal radius is
longer. Decide it before radial fine tuning.

### Projection model — `model`

| Choice | Source-radius curve | Typical character |
| --- | --- | --- |
| `stereographic` | `2 f tan(theta/2)` | Expands edges most |
| `equidistant` | `f theta` | Common starting estimate |
| `equisolid` | `2 f sin(theta/2)` | Compresses edges more |
| `orthographic` | `f sin(theta)` | Compresses edges most |

Default: `equidistant`.

Try all four after FOV is close. Choose the model that makes the broadest part
of several long lines straight with `k1` through `k4` near zero. A projection
model is a base curve, not a quality mode; “stereographic” is not inherently
better than “equidistant.”

### Radial trims — `k1`, `k2`, `k3`, `k4`

All four accept `-0.500` through `+0.500` and default to `0.000`.

| Control | Weight across the lens | Panel step | Use it for |
| --- | --- | --- | --- |
| `k1` | `(theta/theta_max)^2` | 0.010 | Broad residual curvature |
| `k2` | `(theta/theta_max)^4` | 0.010 | Error concentrated nearer edges |
| `k3` | `(theta/theta_max)^6` | 0.005 | Outer-edge residual only |
| `k4` | `(theta/theta_max)^8` | 0.005 | Extreme corners only |

Positive values make the remap sample farther from the source optical centre
at that radius. Negative values sample closer. All vanish at the optical axis,
and higher orders remain small until progressively nearer the frame boundary.

Practical method:

1. Keep `k2`, `k3`, and `k4` at zero.
2. Tune `k1` until the broad middle-to-edge curvature is smallest.
3. Tune `k2` only for what remains near the outer region.
4. Touch `k3` only if the line is good over most of its length but bends at the
   outer edge.
5. Touch `k4` only for a final corner-localised error.

Although each coefficient is clamped to +/-0.5, values remotely near those
limits are a warning. Several large negative terms can make the radial mapping
non-monotonic and fold the image. Typical manual changes should start around
0.005 to 0.02. If a coefficient needs a large magnitude, revisit FOV, reference
and projection model.

High-order terms can fit one particular rail while making other lines wavy.
Always check top, bottom, left, right and diagonals before accepting them.

### Optical centre — `centre x` / `cx`, `centre y` / `cy`

| Property | Value |
| --- | --- |
| Accepted range | -2000 to +2000 pixels |
| Default | 0 pixels on each axis |
| Panel step | 2 pixels |

These move the assumed source principal point relative to the exact image
centre.

- Positive X moves the sampled optical centre right in the source image.
- Negative X moves it left.
- Positive Y moves it down in OpenCV image coordinates.
- Negative Y moves it up.

Use centre offsets only for asymmetric errors. Examples:

- the left edge is straight while the right edge still bows;
- the top and bottom require opposite radial changes;
- curvature appears centred somewhere other than the image centre.

Adjust one axis at a time. Start with 2 pixels; reduce to 0.5-pixel typed steps
near the answer. A very large offset usually means the base lens model is wrong
or the target itself is not flat.

### Independent focal scales — `fx scale` / `fxscale`, `fy scale` / `fyscale`

| Property | Value |
| --- | --- |
| Accepted range | 0.500 to 1.500 |
| Default/identity | 1.000 |
| Panel step | 0.005 |

These multiply the source displacement separately along X and Y.

- `fx scale > 1`: sample farther horizontally from the optical centre.
- `fx scale < 1`: sample closer horizontally.
- `fy scale > 1`: sample farther vertically.
- `fy scale < 1`: sample closer vertically.

Use them only when horizontal and vertical straight lines clearly require
different correction strength after FOV/model/radial tuning. Keep one at 1.000
while finding the other. They also change aspect and scale, so do not use them
to compensate for perspective caused by a tilted camera.

Values beyond roughly 0.95 to 1.05 deserve suspicion for a normal sensor/lens
pair. The wider coded range is an emergency tuning range, not a target.

### Tangential/decentring trims — `p1`, `p2`

| Property | Value |
| --- | --- |
| Accepted range | -0.2500 to +0.2500 |
| Default/identity | 0.0000 |
| Panel step | 0.0020 |

These are standard Brown-Conrady tangential terms applied to the estimated
fisheye source coordinates. They model lens elements that are not perfectly
centred or parallel to the sensor.

Use them for diagonal or one-sided residuals that cannot be explained by a
simple optical-centre shift. Their effect varies by quadrant, so there is no
useful universal rule such as “positive p1 bends left.” Change one term by
0.002, compare all four corners, and undo it unless the total image improves.

Normal hand-tuned values should be close to zero. A value above about 0.02 in
magnitude should make you re-check camera tilt, target flatness, FOV and centre.
The +/-0.25 clamp merely prevents a wildly invalid entry from making an
unbounded map.

### Skew — `skew`

| Property | Value |
| --- | --- |
| Accepted range | -0.2500 to +0.2500 |
| Default/identity | 0.0000 |
| Panel step | 0.0020 |

Skew adds a source-X displacement proportional to source Y. Positive skew
makes the bottom sample farther right and the top farther left; negative skew
reverses that sampling shear.

Almost every modern camera should leave this at zero. Use it only when a true
sensor/lens shear remains after confirming that:

- the camera is not physically rotated;
- the target is rectangular and flat;
- perspective is not being mistaken for lens distortion;
- centre and tangential terms do not explain the residual.

Perspective makes parallel rails converge; skew shears the entire image. Lens
tuning cannot remove viewpoint perspective without a separate homography.

### Output FOV — `out fov` / `out`

| Property | Value |
| --- | --- |
| Accepted range | 10 to 170 degrees, never above current lens FOV |
| Default | 120 degrees |
| Panel step | 5 degrees |

This is the field of view of the virtual rectilinear camera. It controls how
much of the corrected source cone is retained; it does not identify the source
lens distortion.

- Larger output FOV retains more surroundings but stretches outer pixels more,
  creates softer edges, and may introduce black corners where no source ray
  exists.
- Smaller output FOV discards more of the outer source, looks less stretched,
  and normally gives more useful detail per output pixel.

Tune source geometry first. Then choose the smallest output FOV that still
contains the complete machine area needed by detection.

### Output scale — `scale`

| Property | Value |
| --- | --- |
| Accepted range | 0.10 to 4.00 |
| Default | 1.00 |
| Panel step | 0.10 |

This sets corrected output dimensions relative to the input dimensions. It
does not create sensor detail.

- Below 1.0 renders fewer output pixels and is faster.
- Above 1.0 renders more output pixels but mainly interpolates unless capture
  resolution is also increased.
- For the sharpest useful result, capture full sensor resolution (`--hq`) and
  render a smaller corrected output rather than enlarging a low-resolution
  capture.

Watch the `SAMPLE src px/out px` status. Values below 1 mean output pixels are
being magnified from less than one source pixel and will be soft.

### Interpolation — `interp`

| Choice | Use |
| --- | --- |
| `linear` | Fastest; useful if the Pi cannot maintain frame rate |
| `cubic` | Default; good balance of sharpness and cost |
| `lanczos4` | Highest sampling cost; small final-quality improvement |

Interpolation affects image quality, not geometry. Do not judge a lens model
as more correct merely because one kernel looks sharper.

### Mip filtering — `mip`

| Property | Value |
| --- | --- |
| Choices | `on`, `off` |
| Default | `on` |

Mip filtering reduces aliasing wherever correction shrinks source regions into
fewer output pixels. Leave it on for saved production settings. Turn it off
temporarily only to diagnose performance or compare sampling behaviour.

### Correction — `correction` / `undistort`

| Property | Value |
| --- | --- |
| Choices | `on`, `off` |
| Default | `on` |

This enables or bypasses the fisheye remap. It is the fastest sanity check:
switch between raw and corrected and confirm that the change being judged is
actually produced by the lens model.

### Display mode — `show` / `view`

| Choice | Meaning |
| --- | --- |
| `corrected` | Corrected output only |
| `raw` | Raw geometry, framed to the same output area |
| `both` | Raw and corrected side-by-side |

`both` is best while tuning. Each pane receives its own identical 8 x 8 guide
when the grid is on, so the two geometries can be compared directly.

### Straightness grid — `grid`

Choices: `on`, `off`. Default: `off`.

The grid is a screen-space ruler. It does not claim the real-world lines should
land on particular cells; it simply provides straight horizontal and vertical
references. Compare physical rails and printed edges with it.

## Helper actions

### TUNE VIEW — `tuneview`

Use this at the beginning of every tuning session. It clears crop and zoom,
sets full-frame fit mode, enables correction and grid, and selects raw/corrected
comparison. It preserves colour and sensor setup.

### TUNE RESET — `tunereset`

Resets only:

- `k1`, `k2`, `k3`, `k4` to 0;
- centre X/Y to 0 pixels;
- focal X/Y scale to 1;
- skew, `p1`, and `p2` to 0.

It preserves lens FOV, projection model, output settings, crop, colour and
sensor settings. Use it whenever advanced controls have become hard to reason
about. The ordinary **RESET** button is different: it resets the whole studio.

### TUNE GUIDE — `straight`

Prints the short adjustment recipe into the Studio log and launching terminal.
This document is the detailed version of that recipe.

### SAVE JSON — `save`

Writes the complete camera configuration to
`python/config/camera_settings.json` unless another settings path was selected.
The normal camera feed, gridded feed, build UI and colour-grid checker then use
the same correction.

The `lens` command additionally copies the lens portion to
`python/config/lens_profile.json` for the standalone lens/grid viewers. Camera
Studio does not silently write either generated artefact merely because a field
was changed unless autosave was explicitly enabled.

### SNAP PNG — `snap`

Saves clean raw and corrected images. The corrected filename records model,
FOV, all four radial values, centre, focal scales, skew and tangential values,
making separate tuning attempts comparable later.

## Separating lens distortion from other problems

Do not use fisheye controls to repair these unrelated effects:

| Visible problem | Correct tool |
| --- | --- |
| Whole grid is trapezoidal; parallel sides converge | Camera alignment or workspace homography |
| Paper lines bend because the sheet is folded or curled | Flatten/replace the physical target |
| Grid is straight but rotated | Frame rotation or physical camera rotation |
| Grid is straight but displaced/cropped | Framing crop/pan, then recalibrate workspace map |
| Cell colours are missed or green appears cyan | Colour calibration/white balance |
| Straight grid is mapped to the wrong machine cells | Workspace-map calibration |
| Image is geometrically correct but blurry | Capture resolution, focus, output FOV/scale |

Fisheye correction should make real straight lines straight. Workspace mapping
then handles camera perspective and maps that corrected image into machine
coordinates. Colour correction and cell detection happen after those choices.

## A practical acceptance test

Before saving final settings:

1. Inspect long horizontal, vertical and diagonal lines in all image regions.
2. Confirm no corrected line changes curvature direction along its length.
3. Confirm left/right and top/bottom errors are approximately symmetric.
4. Toggle raw/corrected and ensure the correction is a plausible smooth warp,
   with no folds, duplicated strips or sudden corner changes.
5. Confirm the entire required printed sheet (7 x 6 vertical / 3 x 10
   horizontal) or machine envelope remains visible at the selected output FOV.
6. Save settings and restart Camera Studio; the first frame should match.
7. Recreate the workspace map after any lens, orientation or framing change.
8. Run `color_grid_check.py` on several live frames, not only one favourable
   snapshot.

If straight lines are visually correct but cells still fail detection, stop
tuning the lens. The remaining problem is detector evidence, colour, occlusion,
paper shape, or workspace mapping—not fisheye curvature.

## Command examples

Commands can be typed into Camera Studio's command box or the terminal that
launched it:

```text
tuneview
fov 158
model equisolid
k1 +0.01
k2 -0.005
cx +2
fxscale 1.005
p1 -0.002
params
snap
save
lens
```

A leading `+` or `-` on numeric commands means a relative adjustment. Entering
an unsigned number sets the absolute value. For example, `k1 +0.01` steps the
current value while `k1 0.01` replaces it.

