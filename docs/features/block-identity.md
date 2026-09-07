# Block identity — what it would buy, what it costs, and why it is deferred

**Status: DEFERRED. No tracker is built, and D1 of
[placement-supervision.md](placement-supervision.md) says so on purpose.** This
file exists because "why don't we just tell the blocks apart?" is a reasonable
question that keeps coming up, and the answer is long enough to be worth writing
once.

In one sentence: **the rig treats every block as interchangeable, every verdict
is a set comparison, and the only thing that suffers is that supervision says
"the block at [3,2]" instead of "block #17" — which changes no operator
action.**

---

## 1. What "identity" could mean — three tiers, not one

The word covers three very different capabilities, and they are not the same
project:

| Tier | What it does | Scope | Feasible here? |
| --- | --- | --- | --- |
| **A — window association** | "these detections, across the ~5 frames of one settle window, are the same physical objects" | one quiet, parked window; seconds | **yes, cheaply** — D5 guarantees no occlusion and no fast motion inside the window |
| **B — attribute class** | "this detection is a *red* block" / "a tall one" — a label that partitions the 29 into a handful of classes | any frame | **only if the blocks are given distinguishing attributes** (paint, marks). `hue` is already on every detection and is currently one value for all of them |
| **C — persistent re-ID** | "this is block #17, the same one I placed at [1,0] four minutes ago" | the whole program, across the gantry, hands, mode latches | **no** — see §3 |

D1 forbids **C**. It says nothing against **A**, and **A** is most of what the
questions are actually reaching for.

---

## 2. What identity would unblock

| Consumer | What it wants | Which tier | Does it actually need it? |
| --- | --- | --- | --- |
| `MOVED` / `DISPLACED` refinement | pair "cell X emptied" with "a detection appeared in the gap" and be sure it is the same block | A, or B as a corroborant | **no** — the pairing is already bounded (one in, one out, in a window with no occlusion by construction). Identity would raise confidence, not enable it |
| `BOARD DISAGREES` disambiguation | when 2 cells empty and 2 fill, say which went where | C | **yes** — this is the case D9 explicitly refuses to guess. But it is also the case where association is least trustworthy (most change, most motion) |
| Theft off the top of a stack (D4 limit) | notice a block is gone when the cell stays occupied | needs **height**, not identity | identity does not help here at all |
| [Stage 15](stage-15-placement-correction.md) residual attribution | "block at [3,2] landed 0.4 cm short" | none — the ledger's `(col,row,level)` already names the cell | **no** |
| Supervision M4 auto-repair | re-place *the* block that moved | A within the repair window | **partly** — enough to aim the claw, not enough to prove provenance |

The pattern: the cheap tier (**A**) covers the cases that matter, and the
expensive tier (**C**) is wanted only for `DISAGREES`, which is the one case
where it would also be least reliable.

---

## 3. Why persistent re-ID (tier C) is not feasible on this rig

Not a limitation of effort — a limitation of the hardware:

- **Size carries no information.** `config/rig.json` has one `block_x_cm` /
  `block_y_cm` per mode. Every block is 2.2 × 6.0 cm. `BlockDetection.width` /
  `.height` / `.area` measure the same rectangle 29 times.
- **Colour carries almost none.** [`block_detector.py`](../../python/vision/block_detector.py)
  §module-docstring: *"pale, warm-coloured pieces on a pale work surface."* They
  are bare wood. `BlockDetection.hue` is populated (`cv2.mean` over the block
  ROI) but reads ~one value for all of them, and the rig has a **magenta cast**
  that attacks exactly the red-minus-blue response the detector segments on.
- **Texture is below the camera's floor.** Wood grain exists physically, but the
  feed is soft, magenta-cast, carries veiling glare in the raw
  ([[raw-phone-colour-tuning]]), runs at the measured 8.6–8.7 Hz, and is JPEG
  compressed. Grain fingerprinting needs sharp, stable, evenly-lit macro frames.
  This is not that camera.
- **29 near-identical objects** is the worst case for any re-ID method — the
  descriptors would overlap.
- **Occlusion is the norm, not the exception.** The gantry arm crosses the board
  on every placement; a hand reaches in on every correction. Tier C has to
  survive precisely the events that break it, and a tracker that is reliable
  except when it matters is negative value.

`BlockDetection` today: `box`, `center`, `width`, `height`, `angle`, `area`,
`rectangularity`, `solidity`, `confidence`, `hue`. No descriptor, no id, and
nothing that would separate two blocks of the same wood.

---

## 4. Why the current job does not need it

Supervision answers one question: **does the board match the plan?** That is a
comparison of two sets of *cells* —
[`ledger.expected_occupancy(mode)`](../../python/rig/placement_ledger.py) against
the cells detections landed on. Identity would let a verdict say "block #17
moved" instead of "the block at [3,2] moved"; the operator picks it up and
straightens it either way. D9 states this outright:

> `MOVED` does **not** claim it is the same block — identical objects, no
> identity, no proof available. It does not need one: the actionable fact is
> that the board no longer matches the plan at two cells.

The `PlacementLedger` follows the same rule (D2): it records *commands* —
`(mode, col, row, level, placed_at)` — never a block reference, because a block
reference is something it cannot verify and therefore should not assert.

---

## 5. The tier that is cheap and safe: window association (A)

Inside a quiet, parked, settled window, D5's interlocks have already guaranteed
the two things that make association hard everywhere else: **nothing is
occluding the board** (gantry parked, scene quiet) and **nothing is moving
fast** (that is what "quiet" measures). So linking a detection in frame *n* to
one in frame *n+1* is a nearest-centroid match within a small gate — the same
arithmetic `block_grid` already does to fit a lattice, minus the lattice.

This is **not** "tracking a block through a build." It is "these detections, in
this one settled window, are the same handful of objects" — which is enough to:

- say a detection that is now in a gap is the *continuation* of one that was on
  cell X five frames ago → a confident `DISPLACED [X]` instead of a bare
  `FOREIGN`;
- carry a short-lived local index so the per-cell hysteresis
  ([`_CellHistory`](../../python/rig/supervisor.py)) is voting on the same
  object frame to frame rather than on "whatever is nearest this cell now".

It resets on every tripped interlock, every mode latch and every regime change —
exactly like the hysteresis counters (D7) — because evidence from a window that
was not allowed to be judged must not leak into the next one.

---

## 6. The cheap corroborant: hue class (B)

If the blocks are ever **painted in a few distinct colours**, `BlockDetection.hue`
becomes a real class label at zero new pipeline cost. It would not give 29
identities, but "a *red* block left [3,2] and a *red* detection appeared in the
adjacent gap" is a materially stronger pairing than "*a* block moved." This is
the highest value-per-effort change in this whole document, and it is a
**physical** change to the blocks, not a software one.

---

## 7. Decision, and when to revisit

**Deferred. Build no tracker.** The `MOVED` / `DISPLACED` split
([placement-supervision.md](placement-supervision.md) D9, progress.md P9) is
**built** on the bounded one-in-one-out pairing and did not wait on this — the
pairing holds because D5 guarantees the window has no occlusion, not because
identity was established.

Revisit when **any** of these becomes true:

1. **The blocks are given distinct colours or marks.** Then tier B is nearly
   free and should be wired into the MOVED/DISPLACED pairing and, if it helps,
   into `DISAGREES`.
2. **A measured failure** in `MOVED` / `DISPLACED` / `DISAGREES` on real
   hardware that window association (tier A) would demonstrably fix — bring the
   trace, per D1's own rule: *"revisit only if a measured failure demands it,
   and bring the measurement."*
3. **[M5 height inference](camera-parallax-and-levels.md) lands** and theft off
   the top of a stack becomes detectable. At that point *which* block was taken
   starts to matter, and tier A within the detection window is the minimum that
   answers it.

Until then: every block is interchangeable, and every verdict names a **cell**.

---

## 8. If tier A is ever built — the shape of it

Not a work item. A sketch so the next person does not re-derive it:

- **`rig/window_associator.py`** — stateful, window-scoped. Lives in `rig/`, not
  `vision/`, for the same reason the supervisor does: it needs to know whether
  the gantry is parked and whether a latch just happened, which a per-frame
  detector may not.
- **Input:** the same `ProcessedFrame.detections` the supervisor already gets,
  plus the interlock state.
- **Per frame in a judgeable window:** greedy nearest-centroid match of this
  frame's detections to the previous frame's, within a gate of ~1 cell pitch.
  Matched → carry the local id forward; unmatched new → fresh local id;
  unmatched old → dropped after K misses.
- **Output:** for each current detection, the local id and "where its track
  started in this window" (first-seen cell or gap).
- **Never** persists a local id across a tripped interlock, a mode latch, a
  `MIN_LATTICE`-style regime change, or the gap between two windows. There is no
  block #17. There is only "the object this window has been watching."
- **Tests:** synthetic detection streams — a clean hold keeps one id per object;
  a block sliding cell→gap keeps its id; an interlock trip mid-slide drops every
  id; two blocks crossing within the gate is an *acceptable* mislabel and is
  asserted as such, because resolving it is tier C.
