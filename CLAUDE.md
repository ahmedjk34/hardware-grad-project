# CLAUDE.md

**[`AGENTS.md`](AGENTS.md) is the authority for this repo. Read it before
editing anything.** This file exists so Claude Code loads that pointer
automatically; it deliberately does not restate the rules, because a second
copy of a rule is a rule that goes stale.

## Before you touch a number

The rig is **two machines that must agree**: a Raspberry Pi 5 running Python
and an Arduino MEGA 2560 running compiled C++. **The Arduino cannot read
`config/rig.json`** — it has no filesystem, its numbers are baked in at flash
time. A handful of values therefore genuinely live in two places.

> **If you change one of these, change its partner in the same commit.**

`AGENTS.md` is the list of them.

## The section you will need most

**[The calibration knobs — the complete reference](AGENTS.md#the-calibration-knobs--the-complete-reference)**
— every offset, trim, shift, margin, skew and error value: what it moves, its
sign convention, and whether it affects `config/rig.json`, the web Studio, or
the Python/camera side.

Read it **before** changing any such value, and **before acting on a report
that a block landed in the wrong place.** These knobs look interchangeable and
are not; the wrong one gives a rig that is right in one mode, wrong in another,
with a Studio drawing that disagrees with reality.

Three things from it that are load-bearing enough to repeat:

1. **One sign convention.** Every calibration number is a magnitude from that
   axis' home switch. `+` = away from home, `−` = toward home. For Z, "home" is
   the ground switch, so `+` = taller. No exceptions.
2. **Magnitudes are not machine positions.** X's `axisPos[]` runs *negative*
   away from home while Y and Z run positive, so on X the two spaces have
   opposite signs. Anything tested only on Y or Z proves nothing. Cross between
   the spaces **only** via `axisPosFromHomeSteps()` / `axisStepsFromHome()`.
3. **A reported error and a requested placement take opposite signs.** "It
   landed 0.4 cm too close to home" wants `+0.4`; "I want it 0.4 cm toward
   home" wants `−0.4`. If the sentence is ambiguous, **ask** — do not guess.

## Checks to run after a firmware or geometry edit

```bash
python3 python/tests/test_grid.py     # firmware <-> config pairing (221 checks)
cd web && npx vitest run               # Studio / coords / Twin
cd python && python3 -m pytest tests/  # the rest
```

`test_grid.py` parses the sketch itself and fails on any drift between the
firmware constants, `config/rig.json`, and the documented values — it is the
check that catches a knob edited in one place only.

Known pre-existing failures, **not** regressions: `mock_camera_test.py`
(frame-pump timing and mock block detection), plus `test_combined_grid`,
`test_color_tuning`, `test_camera_performance` and `test_block_outline` on a
clean checkout, which want fixtures/assets that are not in the repo.

## Environment notes

- **No local Arduino toolchain.** There is no `arduino-cli` here, so `.ino`
  edits cannot be compiled the normal way. Syntax-check them with a
  stub-Arduino `g++` harness before handing them over, and say plainly that
  the result is unflashed and unverified on hardware.
- **Camera code cannot be verified locally** — it is developed on the desktop
  and deployed to the Pi. Keep a V4L2 fallback and flag what is untested.
- `docs/STUDIO.md` is the Studio's living source of truth: update it and its
  changelog in the same commit as any Studio change.
- `arduino/archive/` is dead code. Do not edit it, do not copy from it.
