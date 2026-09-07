# Camera parallax and levels — why a stacked block is not where it looks

**Status: FUTURE WORK. Not built, and deliberately IGNORED by
[placement supervision](placement-supervision.md) v1 — which has now shipped,
so §4's price is being paid in production.**

The ceiling is **enforced in code**: `rig.supervisor.LEVEL_CEILING = 3`, and
`unjudged_cells()` refuses every cell whose expected top level reaches it.
Refused cells are never reported `NOT DETECTED` or `REMOVED` — above the ceiling
an absent detection is a *filter artifact*, and reporting it would be the
feature lying. They are listed on screen as `unjudged`, drawn with a 45° hatch
rather than a colour, and counted with their reason in the banner. Lifting this
document's arithmetic into `config/rig.json` is what raises that constant.

This document exists because ignoring parallax is a *choice with a measurable
price*, and the price has to be written down somewhere the next person will
find it. §4 is that price: **a hard level ceiling on what supervision can see
at all.** Everything else here is the design for lifting it later.

In one sentence: **the workspace map is fitted to one plane, a stacked block is
on a different one, so the map reports it displaced away from the camera —
predictably, by an amount this document gives a formula for.**

---

## 1. The geometry

`WorkspaceMap` ([python/rig/workspace.py](../../python/rig/workspace.py)) is a
homography. A homography models **exactly one plane** — and the plane this one
is fitted to is the **top face of a level-0 block**, `h₀ = 1.5 cm` above the
board, because that is the surface `workspace_map_from_calibration` saw when it
was built from placed blocks.

A block higher up is closer to the lens. Run its pixel centre through the
level-0 homography and the answer comes out **displaced radially outward from
the nadir** — the point on the board directly beneath the camera. Similar
triangles:

```
excess = k(L) · d          k(L) = (h − h₀) / (H − h)          h = (L + 1) · 1.5
```

| symbol | meaning |
| --- | --- |
| `L` | the block's level index — `0` is on the board |
| `h` | height of that block's **top face**, cm |
| `h₀` | 1.5 cm — the plane the map is fitted to |
| `H` | camera height above the board |
| `d` | the block's distance from the nadir, in cm, **per axis** |
| `excess` | how far the map reports it from where it actually is, same axis |

`k` is a **scalar**, so the two axes separate cleanly: the X error depends only
on `|x − nadir_x|` and the Y error only on `|y − nadir_y|`. There is no
cross-term and no rotation. That is what makes this correctable by arithmetic
rather than by a second calibration.

### The measured inputs

From the bench (recorded in
[stage-15-placement-correction.md](stage-15-placement-correction.md) §D4):

| Quantity | Value |
| --- | --- |
| Camera height `H` above the board | **57 cm** |
| Nadir, Y (from the Y home switch) | **32.5 cm** |
| Nadir, X | **≈ 11.4 cm — centred** on the 22.8 cm width |

**These are tape measurements and have not been independently re-checked.**
They are good enough to reason with — §5 shows the model is robust to ±2 cm on
either — but they are not yet a calibration, and there is **no `camera` section
in [config/rig.json](../../config/rig.json)** to hold them. Adding one is step 1
of §6.

---

## 2. How big it is

`k(L)` for the shipped 1.5 cm block, `H = 57`:

| `L` | top face `h` | `k(L)` |
| --- | --- | --- |
| 0 | 1.5 cm | **0.000** — the map's own plane |
| 1 | 3.0 cm | 0.028 |
| 2 | 4.5 cm | 0.057 |
| 3 | 6.0 cm | 0.088 |
| 4 | 7.5 cm | 0.121 |

In centimetres, at the extremes of the **vertical** grid (7 × 6, X pitch
3.8 cm, Y pitch 7.6 cm):

| `L` | X excess at col 0 or 6 (`d ≈ 11.4`) | Y excess at row 0 (`d ≈ 32.5`) |
| --- | --- | --- |
| 1 | 0.32 cm | 0.90 cm |
| 2 | 0.65 cm | 1.86 cm |
| 3 | 1.01 cm | 2.87 cm |
| 4 | 1.38 cm | 3.94 cm |

Two things follow, and the second is the dangerous one:

1. **It is large.** A *perfectly placed* level-2 block on row 0 appears ~1.9 cm
   out of position — bigger than Stage 15's entire correction band.
2. **It is directional and self-consistent.** The shift always points away from
   the nadir, so every upper-level block on row 0 appears pushed toward −Y by a
   similar amount. That does not look like noise. It looks like a real,
   repeatable machine fault, and it is worst on row 0 — exactly where a genuine
   homing or backlash error would show. **Anything that measures placement
   error without subtracting parallax first will invent a machine fault that
   does not exist, and the numbers will be consistent enough to believe.**

---

## 3. What it would buy

Three things, none of which supervision v1 attempts:

1. **Correct sub-cell placement error on stacked blocks.** Required before
   Stage 15's pick-and-replace can act above level 0, and before the deferred
   [between-build error calibration](between-build-error-calibration.md) could
   ever average a residual from a tower.
2. **Level discrimination from position alone.** If the memory says `[2,2]`
   should now top out at level 3, you can predict where a level-3 top *should*
   appear and check the detection is there rather than at the level-2 spot.
   That turns "is this cell occupied" into "is this cell occupied **to the
   level I commanded**" — for cells far enough from the nadir.
3. **Raising the detection ceiling in §4**, which is the reason this document
   is filed as a cost and not a nicety.

Note what it does **not** buy: seeing a block **underneath** another one. That
is occlusion, not parallax, and no amount of arithmetic fixes it.

---

## 4. THE PRICE OF IGNORING IT — the level ceiling

This is the part that constrains supervision v1, and it is derived from the
code, not assumed.

[ConsolePipeline](../../python/rig/console_pipeline.py) calls the detector
**with a grid**:

```python
detect_aligned_blocks(frame, grid=self.grid, **kwargs)
```

which runs `_lattice_filter`
([block_outline.py:132](../../python/vision/block_outline.py#L132)). That filter
solves every detection into lattice-index space and drops anything further than

```python
LATTICE_SNAP = MAX_INDEX_SNAP   # 0.34 cells
```

from an integer site. It exists to reject the holder's wooden offcuts beside
`[0,0]`. **Parallax eats that budget as levels rise**, and because the filter
takes the **max** of the two index components, the binding axis is whichever is
worse — on this rig, Y at row 0.

Parallax expressed in **cells** (excess ÷ that axis' pitch), vertical grid:

| Row | L1 | L2 | L3 | L4 |
| --- | --- | --- | --- | --- |
| 0 | 0.12 | 0.24 | **0.38 — DROPPED** | **0.52 — DROPPED** |
| 1 | 0.09 | 0.19 | 0.29 | **0.40 — DROPPED** |
| 2–5 | 0.08 | 0.17 | 0.26 | **0.36 — DROPPED** |
| X, col 0/6 | 0.08 | 0.17 | 0.26 | **0.36 — DROPPED** |

> **A block above the ceiling is not misjudged. It is silently discarded before
> supervision ever sees it** — and an absent detection is indistinguishable
> from a missing block.

So, with parallax ignored:

| Expected top level | Supervision v1 |
| --- | --- |
| 0, 1, 2 | **safe** — parallax stays inside the 0.34 budget everywhere |
| 3 | **marginal** — survives on rows 1–5, dropped on row 0 |
| 4 and above | **invisible everywhere** |

**The rule this forces on supervision v1** (see
[placement-supervision.md](placement-supervision.md) D6): *supervision must
refuse to judge any cell whose expected top level is ≥ 3, and must never emit
`NOT DETECTED` or `REMOVED` for one.* At those levels an absent detection is a
filter artifact, and reporting it as a missing block would be the feature
lying.

This is survivable **only because the structures actually being built are short
towers (2–3 high)**. If that changes, this document stops being future work.

### 4a. A subtlety that makes the ceiling approximate, not exact

`_lattice_filter` computes indices **relative to `detections[0]`**:

```python
raw = np.linalg.solve(basis, (centres - centres[0]).T).T
error = np.abs(raw - np.round(raw)).max(axis=1)
```

and `detect_aligned_blocks` returns detections **sorted by centre y then x**, so
`detections[0]` is whichever block happens to sit top-left in the image. If that
block is itself elevated, its own parallax offsets the frame of reference for
every other block — and a level-0 block can then read as off-lattice.

The table above therefore describes the **typical** case, not a guarantee. In a
mixed-level scene the drop behaviour depends on which block sorts first. This is
reasoned from the code and **has not been measured**; it is a second, independent
reason not to trust supervision above level 2 until §6 is done.

### 4b. The escape hatch already in the code

`_lattice_filter` opens with:

```python
if grid is None or len(detections) < MIN_LATTICE_BLOCKS:
    return list(detections), [], None
```

**With no grid there is no rejection at all**, and in both paths the centre is
untouched — *"The centre stays exactly where it was measured"*
([block_outline.py:181](../../python/vision/block_outline.py#L181)). So a
consumer that wants every block regardless of level can run its own pass with
`grid=None` and do its own matching. Stage 15 §D7 chooses exactly this. It costs
one detector call (~84 ms by the module's own benchmark), which is nothing at a
between-jobs cadence — but it also **gives up the offcut rejection**, so the
caller must supply its own filter. Memory-driven matching is that filter, and it
is only available to a consumer that has build memory.

Supervision v1 does **not** take this hatch: it runs off the live pipeline's
existing detections and accepts the ceiling instead. That is the whole reason
the ceiling applies.

---

## 5. Robustness — the good news

With both inputs measured, the model is forgiving. Being wrong by **2 cm in `H`
*or* in the nadir** moves the level-2 worst-case correction by at most
**0.11 cm** — comfortably inside the workspace map's own 0.27 cm flattening
error ([BLOCK-VISION §4](../BLOCK-VISION.md)).

That matters: it means parallax correction is **arithmetic, not a calibration**.
It does not need a fitting run, a residual, or a saved artefact — two constants
in `config/rig.json` and a function. What it *does* need is validation that the
model is right at all, which is §6.

---

## 6. The work, when it is done

### 6a. Config and the pure function

| Step | Detail |
| --- | --- |
| 1 | Add a `camera` section to [config/rig.json](../../config/rig.json) — there is none today: `{ "height_cm": 57.0, "nadir_x_cm": 11.4, "nadir_y_cm": 32.5 }` |
| 2 | Load it in [python/rig/config.py](../../python/rig/config.py) |
| 3 | `parallax_excess(level, x_cm, y_cm) -> (dx_cm, dy_cm)` — pure, no camera, no frame, no OpenCV. Signed, away from the nadir on each axis independently |
| 4 | Unit tests asserting **named physical scenarios**, not bare numbers: *"a block at row 0 level 2 is seen 1.86 cm toward −Y"*. `assert 1.86 == 1.86` passes just as happily with the sign inverted |

### 6b. The validation gate — do this before trusting anything downstream

**Tape measure against the camera, at level 2, at row 0.** Place a block at a
known cell at level 2, read its observed centre through the `WorkspaceMap`,
subtract the predicted parallax, and check the residual is under the ignore
threshold. Repeat at three or four cells at **different radii from the nadir** —
the consistency check across radii is the part that catches a wrong `H`, because
a single-cell fit will always produce *a* number that looks fine.

**If the parallax model does not validate, stop.** Everything in §3 inherits it.

### 6c. Then, and only then

- Feed `parallax_excess` into supervision's predicted centre, and lift the §4
  ceiling from "level ≥ 3 refused" to "level ≥ 3 refused **unless** the
  parallax-corrected prediction matches".
- Let Stage 15 act on stacked blocks.
- Reconsider the deferred between-build calibration's window, which currently
  could not include a stacked placement at all without inventing drift.

---

## 7. The other way to get levels, and why it is not this

[python/vision/block_levels.py](../../python/vision/block_levels.py) recovers a
block's height from the sliver of its **vertical side face** an overhead camera
catches — `h = H · s / r_top`. Neither focal length nor pixels-per-cm appears;
they cancel. It is the only thing in the repo that could see a block **taken off
the top of a stack**, which parallax cannot.

It is **not validated against real frames**. Per the project's own record:
*top-of-stack ordering is solid, level numbers need a tape-measured camera
height.* It is also filed as future work — see
[feature-ideas.md §3.2](../feature-ideas.md#32-the-rig-measures-its-own-camera-height),
which is the design for having the rig solve for `H` itself by stacking a block
on a block.

The two are complementary, not alternatives:

| | parallax | side-sliver height |
| --- | --- | --- |
| answers | *where* a known-level block appears | *what level* an unknown block is on |
| needs | `H`, nadir | `H`, validated detector behaviour |
| works at the nadir | **no** (`d = 0`) | yes |
| sees a stolen top block | no | **yes** |
| status | future work, this doc | future work, unvalidated |

**Build parallax first.** It is arithmetic over measured constants; the other is
a detector claim that needs its own evidence.

---

## 8. Not doing

- **Correcting parallax inside `vision/`.** The layering rule of
  [BLOCK-VISION §7](../BLOCK-VISION.md) holds: this is a `rig/`-level correction
  applied to a detection's projected position. `block_outline` keeps returning
  measured centres and knows nothing about levels.
- **Snapping detections onto the lattice to make the picture tidy.**
  `block_outline`'s docstring is explicit that a misplaced block must look
  misplaced. Parallax correction changes *where we predict a block should be*,
  never *where we say it was seen*.
- **Re-fitting the workspace map per level.** Four corners per plane, seventeen
  planes, and a map-invalidation story for each. The scalar model is right and
  cheap; a second homography is neither.
- **Using parallax as a substitute for occlusion handling.** A block hidden
  under another one is not displaced, it is absent. Different problem, §7's
  column.
