# Grid capture & calibration playbook

Why the combined A2 target is not calibrating on the rig, what you can do about
it, and everything `camera_studio.py` and the config can change.

Read this next to [printed-color-grid.md](printed-color-grid.md) (how the
detector works) and [camera-fisheye-tuning-guide.md](camera-fisheye-tuning-guide.md)
(lens geometry).

---

## TL;DR

The detector code is not the problem. **The rig camera has a strong, uncorrected
yellow colour cast, no software colour correction is saved, auto white balance is
on, and the sheet is not fully in frame.** On the two captures you shared the
detector can only confirm **21 of 80** fiducials — the combined target needs
**76 of 80** to hand back a calibration.

Do these, in order, and it will work:

1. **Colour-calibrate the camera** — `camera_studio.py` → `colourcal <phone photo of the same sheet>`. Mandatory. `wb` alone is not enough here.
2. **Reframe** — the whole A2 page in view, with a white margin, nothing (gantry, cable, ruler) lying across it.
3. **Full resolution** — `camera_studio.py --hq`, and drop the zoomed-in crop stack.
4. **Pin the sensor** — `awb tungsten` (or manual `redgain`/`bluegain`), fixed `exposure`, `sharpness 1`.
5. Re-`save`, then re-run `color_grid_check.py`.

If you still can't get 76/80 in one shot, lower the gate with
`--page-plane-min 64` or use the evidence route (`e` / Space / `k` in the
gridded feed).

---

## What each capture shows

All paths are under `python/captures/`.

| capture | what it is | verdict |
| --- | --- | --- |
| `grad project grid white background.png` | the digital artwork (clean, 8×5 tiles of 6×6 cm composites) | reference only — this is what the ink *should* look like |
| `GRID_DETECTOR_VERTICAL_RESULT.png` / `..._HORIZONTAL_RESULT.png` | detector run on the **clean artwork** | **80/80, 95 %+ confidence, workspace corners drawn.** This is a pass. The code works on good input. |
| `grid_training/original_image_VERTICAL.jpeg` | **phone photo** of the old plain sheet, good light | greens are true green, whole sheet + white border visible. This is what a *usable* rig frame has to look like. |
| `grid_vertical.png` | rig camera, combined target, "vertical" | **21/80.** Green ink desaturated to grey (S≈41) while the yellow-cast paper is *more* saturated (S≈82) and at nearly the same hue. Page clipped at the bottom, rig mounts + cable top-left. Cannot calibrate. |
| `grid_horizontal.png` | rig camera, combined target, "horizontal" | **21/80.** Decodes orientation at 96 % but only 21 fiducials support the page plane → `workspace_corners()` refuses. Same cast + framing problem. |
| `camera_grid_real_capture/live_grid_1.png` | rig camera, old plain sheet, Aug 24 | gantry bar straight across the sheet, a ruler on it, frame edge cutting the outer columns. "66 blobs, 42 on a lattice, stage: window" — failed. Framing. |
| `camera_grid_real_capture/grid_live_v2.png` | rig camera, larger frame | 110 blobs but "do not form a regular lattice" — the cast breaks the colour separation before geometry even runs. |
| `LIVE_RAW.png` / `LIVE_WITH_GRID.png` | rig camera, old **plain** sheet | 26/80 on the combined path; these are photos of the pre-6 cm sheet so they will not match the current spec regardless. |

**The pattern:** every frame shot with a *phone* works; every frame shot with the
*rig camera* fails on colour, framing, or both. Nothing shot through the rig
camera has ever been colour-corrected.

---

## What you CAN do right now

- **Run the detector on a phone photo** of the combined A2 sheet
  (`color_grid_check.py --image <photo>`). It will produce a real calibration —
  but that calibration is only valid if the phone was where the rig camera is,
  which it is not. Use it to sanity-check the print, not to calibrate the rig.
- **Read orientation** off the rig frames — both `grid_vertical.png` and
  `grid_horizontal.png` decode the woven orientation correctly (vertical 83 %,
  horizontal 96 %). So the *print* is fine and the *decoder* is fine.
- **Lower the page-plane gate** to see a (risky) partial calibration:
  `color_grid_check.py --page-plane-min 20` — this will let 21/80 through. Do
  **not** save a workspace map from it; the envelope corners are an
  extrapolation from a quarter of the page.
- **Tune the ink floor** for the cast: `--min-saturation 8` feeds the faded and
  channel-order passes a lower threshold.

## What you CAN'T do (and why)

- **Calibrate the rig camera → machine mapping from `grid_vertical.png` or
  `grid_horizontal.png`.** 21/80 fiducials, page clipped. No amount of detector
  tuning invents fiducials that were not imaged. This is a capture-quality wall.
- **Fix the cast purely in software after the fact.** `white_balance()` (the
  detector's built-in fallback) actually makes the green ink *less* saturated on
  this cast, because the "white" it balances to is itself yellow-green. Only a
  real 3×3 `colourcal` matrix — fitted from three known colours — can pull the
  desaturated greens back and neutralise the paper at the same time.
- **Rely on `awb: auto`.** Auto white balance on a scene that is mostly pink/
  magenta ink pulls the balance away from neutral every frame, so the cast is
  also *unstable*. It has to be pinned or overridden.
- **Use the aggressive frame-border margin on the combined target.** The A2 page
  fills the frame by design; `--edge-margin` is a legacy-plain-sheet tool and
  the combined path ignores it.

---

## Fix the camera — step by step

Run `camera_studio.py`, watch the preview, `save` at the end.

### 1. Resolution & framing

```
--hq                    # start it at the sensor's full 2592x1944, not 1296x972
nocrop                  # drop the stacked crops in the current settings
zoom 1                  # no digital zoom
grid on                 # 8x8 straightness ruler
```

Then physically move the camera / sheet so the **whole A2 page plus a white
margin** is inside the `grid` overlay, square-ish, with **nothing lying across
it** — no gantry, no cable, no ruler. The page should occupy ~70–85 % of the
frame, not touch any edge.

### 2. Colour — the one that matters

Take a **phone photo of the exact same printed sheet** in even light — e.g.
`python/captures/COLOR_SAMPLE.jpeg`. Point the **rig camera** at that same sheet,
filling most of the frame and roughly in focus, then:

```
colourmode matrix       # full linear 3x3
colourcal captures/COLOR_SAMPLE.jpeg
colourinfo              # read the residual and any warnings
```

`colourcal` measures the sheet's colours in the **live rig frame** and in the
reference photo and solves the transform between them. The sampler now pulls up
to eight tones from the combined target — `green`, `green_dark`, `green_muted`,
`magenta`, `magenta_dark`, `magenta_muted`, the warm `beige` lane and `paper` —
and pairs whichever appear in both images. More tones ⇒ a better-conditioned
`matrix` fit. It only needs the rig frame to show **any two** of green / magenta
/ paper cleanly; it falls back to a cast-invariant channel-order classifier at a
low saturation floor when the plain hue window has lost one ink.

`colourcal` with no mode now:

1. Locates the missing ink by **grid structure** — on this camera the olive
   green reads as neutral grey, invisible to every colour test, so the sampler
   uses the *magenta* cells to lay out the grid and reads whatever colour sits
   in the green-cell positions.
2. Tries `matrix` → `affine` → `gain` and keeps the strongest that is **not
   implausible** (a negative channel gain, a runaway offset, cross-mix as big
   as the gains). On a green-blind rig frame the 3×3 always fails those, so it
   lands on `gain` — a per-channel white balance — and says so:
   *"matrix/affine looked implausible on this frame, used gain; fix the
   light/sensor so the green ink is not grey for a full correction."*

That `gain` correction is real and worth saving, but it barely touches green.
**The full fix is upstream:** the light + sensor must stop crushing the green
channel before capture.

- `sensor` shows what the camera accepted; `redgain` / `bluegain` let you push
  the sensor's own white balance (start near the equivalent gains `colourcal`
  printed), and a warmer or more neutral light source will bring the olive back.
- If green still reads grey, a **more saturated green ink** on the reprint would
  survive where the current `#647c48` olive cannot.
- `wb` first (needs only paper) gives a rough correction that can make the ink
  visible enough for a better follow-up `colourcal`.
- A page of a few **big solid** green / magenta / white swatches (5 cm+) is an
  easier `colourcal` subject than the fine woven target.

After the fit, `colour on` (auto-enabled). Eyeball the preview.

### 3. Sensor — stop the camera fighting you

```
awb tungsten            # or:  redgain 1.4   bluegain 1.9   (pin it, don't let it drift)
exposure 8000           # a fixed exposure so brightness stops hunting
gain 1.0                # fixed analogue gain
sharpness 1             # 10 is way too high — it eats the thin dark fiducial stripe and adds edge ringing
brightness 0.0
contrast 1.0
saturation 1.0          # let the colour matrix do the saturation work, not the ISP
denoise light
```

`sensor` prints what the camera actually accepted. `autoall` hands everything
back if you want to start over.

### 4. Save

```
lens                    # also refresh config/lens_profile.json for the other tools
save                    # writes config/camera_settings.json — every tool reads it
snap                    # dump a raw + corrected PNG so you have a record
```

Now `color_grid_check.py` (no flags) should climb well past 21/80. If it lands
at, say, 70/80 because the very outer ring is still soft, add
`--page-plane-min 64`.

---

## Everything `camera_studio.py` can calibrate

`camera_studio.py` writes one file, `config/camera_settings.json`, in sections:

### COLOUR — software correction, applied to every captured frame

| command | what |
| --- | --- |
| `colour on/off` | enable/disable the whole software correction |
| `wb` | white-balance now from the sheet's white paper (quick, weak on a bad cast) |
| `colourcal <image> [gain\|affine\|matrix]` | fit the correction by matching a reference photo of the same sheet |
| `colourmode <gain\|affine\|matrix>` | what a fit solves: 3 numbers / 6 / full 9 |
| `rgain rgain bgain` / `roff goff boff` | per-channel gain (0.05–8) and offset (−128–128) |
| `gamma <v>` | 0.2–5 |
| `csat <v>` | software saturation 0–3 (not the sensor's) |
| `nomix` | drop a fit's cross-channel terms, keep its white balance |
| `colourinfo` | print the matrix and everything implausible about it |
| `colourreset` | back to identity, off |

The combined detector applies this transform before it ever segments colour, so
a good `colourcal` is the single highest-leverage change.

### SENSOR — the camera's own ISP, before capture

`brightness` `contrast` `saturation` `sharpness` `ev` `exposure` (µs) `gain`
(analogue) `awb` (preset) `redgain` `bluegain` `denoise` `fps`. Each takes a
number or `auto`. `sensor` reports, `autoall` resets. Prefer these over the
software COLOUR knobs where the backend supports them — they act on cleaner data.

### LENS — geometry / fisheye correction

`k1 k2 k3 k4` (radial trims, default 0), `cx cy` (optical centre offset),
`fxscale fyscale` (focal multipliers), `skew`, `p1 p2` (tangential),
`out` (output FOV, currently 120° from a 160° lens), `scale` (render resolution),
`interp`, `mip`, `straight` (prints a straightening recipe), `tuneview`,
`tunereset`. `lens` writes the shared `config/lens_profile.json`.

The trims default to zero and that zero is load-bearing — a non-zero default
would move every grid viewer's geometry. No checkerboard calibration has been
done, so the correction is *visually* straight, not measurement-grade; residual
barrel distortion at the page edges is part of why the outer fiducial ring is
the first to fail the 76/80 gate.

### ZOOM / CROP

`zoom` `pan` `crop` `uncrop` `nocrop` `fitmode` `viewbox` `refit` `fill`.
**The current settings carry a stacked crop that ends at an ROI of about
[0.28, 0.25, 0.62, 0.78] of the sensor** — that alone can keep the full page out of frame. `nocrop`.

### FRAME

`view <corrected|raw|both>` `flip` `rotate` `swaprb` `grid`.

### FILES

`save` `autosave` `load` `lens` `snap` `params` `reset`. CLI: `--hq`,
`--width/--height`, `--shutter`, `--gain`, `--awb`, `--sharpness`, `--fresh`.

---

## Current config audit

### `python/config/camera_settings.json`

*(As of the `2026-09-03` `camera_settings.json`. Re-read the file — the audit
below drifts as the camera is tuned.)*

| field | value now | issue |
| --- | --- | --- |
| `colour` | present but `enabled: false` (`source: "tuned to raw_with_phone.jpeg"`, `similarity ≈ 0.67`) | a `matrix`/`gain` fit exists from the raw-phone tuner but is switched off, so identity still reaches the detector. **Enable it or refit.** |
| `sensor.awb` | `auto` | unstable cast frame-to-frame; pin it |
| `sensor.saturation` / `contrast` / `ev` / `exposure` / `gain` | `auto` | brightness/colour hunt; pin exposure + gain at least |
| `sensor.sharpness` | `16.0` | far too aggressive for a fiducial with a thin dark centre stripe; set `1` |
| `capture.width/height` | `1296 × 972` | not full res; `--hq` for an 80-fiducial target |
| `framing.crops` | **2 stacked crops → ROI ≈ [0.28, 0.25, 0.62, 0.78]** | cropped to a centre window; `nocrop` |
| `lens.output_fov_deg` | `120` (from a 168° fisheye) | `lens.source: "estimated"` with hand-tuned `k1≈0.14 / k2≈0.18 / k3≈0.035` — visually straightened, not checkerboard-calibrated; edge distortion remains |
| `correction.enabled` | `true` | good |

### `config/rig.json` (unchanged by this work, for reference)

- `grid.modes.vertical` = 7 × 6 addressable, block `2.2 × 6.0`, gap `1.6 / 1.6`,
  trims `0`.
- `grid.modes.horizontal` = 3 × 10 addressable, block `6.0 × 2.2`, gap
  `1.6 / 1.6`, `trim_x = trim_y = +1.9`.
- `workspace` = 22.8 × 38.0 cm (holder travel; the combined target's page plane
  must contain this rectangle, and the A2 page — 59.4 × 42.0 cm — does).
- The combined A2 fiducial geometry lives in `vision/combined_grid.py`, **not**
  in `rig.json`, and did not change: 6.0 × 2.2 cm bars, 0.8 / 1.6 cm gaps, 8 × 10
  lattice. Changing block/gap geometry does **not** require reprinting the
  combined page.

---

## Detector changes shipped with this playbook

All in the **combined A2 path** (`vision/combined_grid.py`, `vision/color_grid.py`).
No legacy fallback was added.

| change | what it does |
| --- | --- |
| **channel-order classifier** (`channel_order_masks`) | classifies a pixel green/magenta by *which BGR channel is largest/smallest*, not by hue+saturation. Survives any single global cast — the exact failure mode here. Runs as two extra passes, last, so a clean-but-faded print still takes the stripe path. |
| **`flatten_illumination`** | optional divide-by-blur pre-pass that removes a low-frequency cast + vignette. Helps when the sheet is small in frame; a no-op safety valve when it fills it. |
| **best-of-passes** | `detect_combined_grids` now runs every pass and keeps the strongest (page-plane support, then fitted extent) instead of returning on the first that doesn't error — a weak "full bars" fit no longer blocks a complete channel-order fit. |
| **`page_plane_min`** | the 76/80 gate is now a parameter. Lower it (`--page-plane-min 64`) for a rig that always crops the outer ring; a low value still has to span the full 8×10 extent or it is refused. |
| **`min_saturation`** | override the faded passes' ink floor (`--min-saturation 8`) for a strong uncorrected cast. |
| **actionable errors** | the refusal now says how many more fiducials are needed, the fitted extent, and names `colourcal` / reframing / evidence as the fixes. |

New flags on `color_grid_check.py` and `gridded_camera_feed.py`:
`--page-plane-min N`, `--min-saturation S` (plus the existing `--edge-margin`,
`--process-width`, `--grid-window`).

**None of this substitutes for `colourcal` + reframing.** It makes a *marginal*
frame calibratable; it cannot rescue a quarter-page frame.

---

## The capture checklist

Before you press `s` in `color_grid_check.py`, all of these must be true:

- [ ] `camera_settings.json` has a `colour` block (`colourcal` was run and saved)
- [ ] preview: green ink reads green, paper reads white
- [ ] `sensor.awb` is pinned (not `auto`); exposure and gain are fixed
- [ ] `sensor.sharpness` ≤ 2
- [ ] no crop stack (`nocrop`), no digital zoom, --hq (full-res) capture
- [ ] the entire A2 page + a white margin is inside the frame, not touching an edge
- [ ] nothing physical is lying across the sheet
- [ ] `color_grid_check.py` reports **≥ 76/80** (or ≥ your `--page-plane-min`) and the fitted extent is **8×10**
- [ ] the drawn envelope corners sit on the page, not off it
