# Design system — rig operator console

This is the visual and interaction specification for the browser console
(`web/`). It exists because the console is the only part of this project a
person actually *touches*: the gantry, the vision pipeline and the firmware are
all judged through it.

Read [plans/plan-3-web-operator-console.md](../plans/plan-3-web-operator-console.md)
first for what the console *does*. This document covers only how it should look
and behave.

---

## 1. What this interface actually is

Not a dashboard. Not a SaaS app. **It is the control panel of a machine that
moves 40-second, uninterruptible cycles while a person stands next to it.**

Four facts from the hardware drive every decision below:

1. **The Arduino goes deaf during a build.** There is no cancel. The UI must
   never imply otherwise — no stop button, no progress scrubber, no "retry".
2. **`ABORTED` / timeout locks the session permanently.** A human has to walk to
   the rig and restart the service. That state is terminal and must look it.
3. **The operator is holding a phone, standing at the rig, looking at the
   machine — not at the screen.** Feedback must be readable at arm's length and
   survive being glanced at.
4. **The camera image is the interface.** Everything else is chrome around a
   live video frame the app does not control the contents of.

Design north star: **an instrument, not a website.** Closer to a CNC readout,
an oscilloscope or a mission-control panel than to a product landing page.

---

## 2. Theme — "Machine Shop"

A dark, low-noise industrial console. The only saturated colour in the app is
carrying safety meaning; everything else is graphite, steel and light grey.

Why dark: the hero content is a live camera frame, usually of a bright surface
under work lighting. A dark chrome makes the frame the light source of the
screen and stops the UI competing with it. It also reads correctly on a tablet
mounted at the rig in a dim lab.

Three principles:

- **Colour is reserved.** Green, amber and red mean READY, MOVING and LOCKED.
  Nothing decorative is allowed to use them. If a colour appears, it is telling
  you about the machine.
- **Numbers are instruments.** Every coordinate, command, level, age and count
  is monospace, tabular, and never re-flows when a digit changes.
- **Chrome recedes, state advances.** In the idle case the UI is almost
  monochrome. State changes are the only thing that introduces colour, weight
  or motion.

---

## 3. Tokens

Define these once in `web/src/style.css` as custom properties. Nothing in a
component should contain a raw hex value.

### 3.1 Colour

```css
:root {
  /* ground */
  --void:        #0B0D0F;  /* page background, camera letterbox */
  --surface:     #14181C;  /* panels, rails */
  --raised:      #1C2126;  /* cards, inputs, hovered rows */
  --line:        #2A3138;  /* 1px hairlines, panel edges */
  --line-strong: #3A444D;  /* focused / active edges */

  /* text */
  --text:        #E6EDF3;
  --text-dim:    #9AA7B2;  /* labels, units, secondary */
  --text-faint:  #6B7883;  /* disabled, timestamps */

  /* interaction (never a state colour) */
  --signal:      #6FC6FF;  /* selection, links, focus ring, grid overlay */
  --signal-dim:  #2E6E93;

  /* machine state — reserved, load-bearing */
  --ready:       #3DD68C;  /* READY, PLACED, calibrated, live camera */
  --motion:      #F0A73E;  /* RUNNING, STALE, APPROXIMATION ONLY, REJECTED */
  --danger:      #FF5C5C;  /* LOCKED, ABORTED, disconnected */

  /* detection palette — matches web/geometry.py _colour_name() exactly */
  --block-red:    #FF6B6B;
  --block-orange: #FF9F4A;
  --block-yellow: #FFD84A;
  --block-green:  #5AE08B;
  --block-blue:   #5FA8FF;
}
```

**Semantic rule for amber vs red.** Amber = *degraded but recoverable, or the
machine is moving*. Red = *stop, a human is required*. `REJECTED` is amber —
nothing moved, the selection is still yours. `ABORTED` is red — it is over.

**A light theme is optional and lower priority.** If added, it is for a
sunlit-bench scenario only, and it must keep the identical state semantics.
Do not ship a half-finished one; a single well-executed dark theme is better.

### 3.2 Type

No web fonts. The Pi serves this over LAN with no guaranteed internet, and a
blocked font request would leave the console in a fallback nobody designed.

```css
--font-ui:   system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
--font-mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
```

If you want more character, **self-host** one variable family (IBM Plex Sans +
IBM Plex Mono is the right register for this project) into `web/public/` and
`@font-face` it locally with `font-display: swap`. Never a CDN.

Scale — deliberately short, five sizes only:

| Token | Size / line | Use |
| --- | --- | --- |
| `--t-hero` | 40px / 1.0, mono, 600 | the command readout `B 3 2 1` |
| `--t-lg` | 20px / 1.3, 600 | panel headings, banner text |
| `--t-md` | 15px / 1.45 | body, buttons |
| `--t-sm` | 13px / 1.4 | labels, chips |
| `--t-xs` | 11px / 1.3, mono, 0.08em tracking, uppercase | field labels, units |

Every numeric readout gets `font-variant-numeric: tabular-nums`.

### 3.3 Space, radius, elevation

Spacing is a 4px scale: `4 8 12 16 24 32 48`. Nothing in between.

Radius: `--r-sm: 4px` (chips, inputs), `--r-md: 8px` (cards, buttons),
`--r-lg: 12px` (the camera stage). Nothing is a pill except status chips.

Elevation is drawn with **borders and background steps, not shadows**. One
exception: the mobile action sheet gets `0 -8px 24px rgba(0,0,0,.5)` so it
reads as floating above the video.

### 3.4 Motion

```css
--ease: cubic-bezier(.2, 0, 0, 1);
--fast: 120ms;  /* hover, focus, chip toggles */
--base: 200ms;  /* panel and banner transitions */
```

Hard rules:

- **Nothing loops except while the rig is actually moving.** A spinner or pulse
  on an idle screen is a lie about a machine that has physical state.
- The RUNNING banner carries **one** continuous indicator (a slow indeterminate
  bar or a 2s pulse on the amber edge). That is the app's only ambient motion.
- Respect `prefers-reduced-motion: reduce` — replace the pulse with a static
  amber edge and keep the elapsed-seconds counter, which is the real signal.

---

## 4. The state model is the design

The whole screen has three modes. These are not badges in a corner; they change
the frame of the app.

| Machine state | Screen treatment |
| --- | --- |
| **READY** | Full colour, all controls live, `--ready` dot in the status rail. Calm. |
| **RUNNING** | Every mutating control disabled *and visibly dimmed* (`opacity:.4`, `cursor:not-allowed`). A persistent amber banner above the camera with the elapsed second count. The camera keeps streaming at full brightness — you must be able to watch the machine. |
| **LOCKED** | Red banner pinned at the top, cannot be dismissed. Controls are not just disabled but **removed or struck through**. Text names the reason and says a human must inspect the rig and restart the service. **No retry affordance anywhere.** |

Two secondary axes layer on top:

- **Socket connected / disconnected.** Disconnected greys the video
  (`grayscale(1) brightness(.5)`), overlays a `DISCONNECTED` plate, and — if a
  build was running — keeps the warning that the rig may still be moving.
- **Camera LIVE / STALE / WAITING.** LIVE is a green dot plus the frame age in
  ms. STALE is amber and blocks selection. WAITING is a skeleton on the stage,
  never a blank white box.

**Never use colour alone.** Every state carries a word, and where possible an
icon shape: ● live, ▲ stale, ■ locked. Video sits behind half of these and
glare eats saturation.

---

## 5. Layout

### 5.1 Desktop / tablet landscape (≥ 900px)

```
┌──────────────────────────────────────────────────────────────┐
│ STATUS RAIL   RIG CONSOLE · VERTICAL 7×6 · CALIBRATED        │  40px
│               ● LIVE 42ms   ● SOCKET   LEVEL 1   00:14:32    │
├───────────────────────────────────────────┬──────────────────┤
│ [ amber RUNNING banner, when running ]    │  TARGET          │
│ ┌───────────────────────────────────────┐ │  ┌────────────┐  │
│ │                                       │ │  │  B 3 2 1   │  │ hero mono
│ │        CAMERA STAGE                   │ │  └────────────┘  │
│ │        video + SVG overlay            │ │  col 3  row 2    │
│ │                                       │ │  LEVEL  [-] 1 [+]│
│ │  ┌ HUD ─────────────┐                 │ │                  │
│ │  │ cell [3,2] · L1  │                 │ │  [   BUILD    ]  │ 56px
│ │  └──────────────────┘                 │ │  [  Deselect  ]  │
│ │  ⌗grid ◎detect ▦sheet ◐overlay        │ │                  │
│ └───────────────────────────────────────┘ │  MODE            │
│                                           │  [Vertical|Horiz]│
├───────────────────────────────────────────┤  CALIBRATION     │
│ RIG LOG                          ⌄        │  ...             │
│ @0 READY                                  │                  │
│ @1 PLACED 3 2 1                           │                  │
└───────────────────────────────────────────┴──────────────────┘
```

Grid: `grid-template-columns: minmax(0, 1fr) clamp(20rem, 26vw, 24rem)`. The
camera column must carry `min-width: 0` or the video will push the rail off
screen — the current CSS already learned this lesson, keep it.

### 5.2 Phone portrait (< 900px)

Single column, and **the primary action moves into the thumb zone**:

1. Compact status rail (sticky top, 36px).
2. Camera stage, full bleed, `aspect-ratio` locked to the frame.
3. A **sticky bottom action sheet** carrying the command readout, the level
   stepper and BUILD. It stays above the fold, always. Never make the operator
   scroll to reach BUILD while standing at a machine.
4. Log and calibration collapse into accordions below.

Touch targets are **48px minimum**, 56px for BUILD. Assume a cold hand, maybe a
glove, definitely one hand.

---

## 6. Component specifications

### 6.1 Camera stage

The hero. Treat it as a piece of equipment, not an `<img>`.

- Black (`--void`) letterbox, `--r-lg` corners, 1px `--line` border.
- The image and the SVG overlay share one `aspect-ratio` box derived from
  `geometry.image_size`, so the overlay can never drift from the video.
- **WAITING**: a graphite skeleton with a slow scanline, plus the words
  `WAITING FOR FIRST FRAME`. Never a white flash.
- **STALE**: amber hairline border plus a `STALE · 2,140ms` chip. Selection
  taps are rejected by the server anyway; show that pre-emptively by dimming
  the grid overlay.
- A small **HUD** in the bottom-left of the stage showing the hovered/selected
  cell and level. It floats over the video with a `rgba(11,13,15,.72)` plate and
  `backdrop-filter: blur(6px)`.
- **View toggles** as chips along the bottom of the stage (grid / detections /
  sheet / overlay). These already exist on the server at `POST /api/view` and
  are unused by the current UI — wire them up.

### 6.2 Overlay drawing rules

The overlay sits on arbitrary video. A single-stroke line will disappear over a
bright block or a dark shadow. **Every overlay stroke is drawn twice**: a
`rgba(0,0,0,.55)` halo at `stroke-width + 3`, then the coloured stroke on top.
This one technique is what makes the overlay look professional.

| Element | Treatment |
| --- | --- |
| Grid cell, calibrated | `--signal`, 1.5px, 55% opacity |
| Grid cell, approximate | `--motion`, 1.5px, dashed `6 4` — dashes carry "not measured" without relying on colour |
| Hover cell | fill `rgba(111,198,255,.10)`, no stroke change |
| Selected cell | `--ready` 3px stroke, `rgba(61,214,140,.18)` fill, plus a corner-tick frame so it reads at a glance |
| Feeder `[0,0]` | hatched, `--text-faint`, labelled `FEED` — it is never a target and the UI should say so before the server rejects it |
| Detection box | its `--block-*` colour, 2px, with a 3px centre dot |
| Level indicator | small stacked-square glyph in the selected cell's corner, one square per level |

Overlay is `pointer-events: none` except the interactive `<svg>` surface, and
the cursor is `crosshair` over selectable cells only.

### 6.3 Command readout

The single most important text in the app. It is the exact string that will be
sent to the Mega.

- `--t-hero` mono, `--text`, letter-spaced, in a `--raised` well with a
  `--line-strong` border.
- Empty state is `— — —` in `--text-faint` with the label `NO CELL SELECTED`.
  Never collapse the well; the layout must not jump when a cell is picked.
- Under it, a decoded line in `--t-xs`: `column 3 · row 2 · level 1`. Operators
  should never have to remember the argument order.

### 6.4 BUILD button

The two-tap confirmation from Plan 3 Step 9 is a safety mechanism, so it gets
design weight:

- **Idle**: full-width, 56px, `--ready` background, `--void` text, 600 weight.
- **Disabled**: `--raised` with `--text-faint`, and the reason rendered *as
  visible text underneath*, not only a `title` tooltip. A phone has no hover.
  ("Select a cell first" / "Camera is not live" / "Rig is unavailable".)
- **Armed** (after first tap): switches to `--motion`, text becomes
  `CONFIRM B 3 2 1`, and a 3-second countdown ring or bar drains visibly so the
  operator understands the arm will expire.
- The arm state must be obvious from two metres away.

### 6.5 Level stepper

`[−] LEVEL 1 [+]` with 48px square buttons and a mono tabular value. Add a
direct-entry field — `POST /api/level {value}` already supports it and stepping
to level 6 with `+` is tedious. Guard the input: never negative.

### 6.6 Mode switch (vertical / horizontal)

`POST /api/mode` exists and the UI does not expose it. It **homes the X/Y axes**
before entering horizontal — that is physical motion. So it is a segmented
control that opens a confirm step: *"Switching to HORIZONTAL homes the X and Y
axes and clears your selection. The rig will move."* Never a silent toggle.

### 6.7 Rig log

The backend already broadcasts every serial line as `{type:"log", line}` and the
client drops it. Wire it up — it is the highest value-per-hour item in the app.

- Terminal styling: mono, `--t-sm`, `--void` background, 1.5 line-height,
  auto-scroll with a "jump to latest" pill when scrolled up.
- Colour by prefix: `@` acknowledgement lines get `--signal`, lines containing
  `ERROR`/`ABORT` get `--danger`, `PLACED` gets `--ready`. Everything else is
  `--text-dim`.
- Timestamp each line client-side in `--text-faint`.
- Collapsible, and collapsed by default on phones.

### 6.8 Status rail

One 40px row, always visible, left to right: rig name, grid mode + `7×6`,
calibration chip (`CALIBRATED` green / `APPROXIMATION ONLY` amber), camera chip
with age in ms, socket chip, session uptime. Every item is a chip: `--r-sm`,
1px `--line`, `--t-xs` uppercase label + mono value.

### 6.9 Banners and result feedback

- Banners are full-bleed bars directly above the camera, never floating toasts
  that could cover the video.
- `PLACED` is a green bar that auto-dismisses after 4s. `REJECTED` is amber and
  **persists** until the next action — the operator needs to read the reason.
  `LOCKED` never dismisses.
- Pair each with a distinct short sound and, on mobile, a `navigator.vibrate`
  pattern. The operator is looking at the rig, not the screen; this is a real
  usability feature, not decoration. Make it mutable and remember the choice.

---

## 7. Accessibility and field conditions

- Contrast: body text ≥ 4.5:1 on its own surface, state text ≥ 7:1. Check the
  amber on `--surface` specifically; amber is the one that usually fails.
- Focus is visible everywhere: `outline: 2px solid var(--signal);
  outline-offset: 2px`. Keyboard operation matters — the Pi may be driven from a
  bench keyboard.
- Keyboard map: arrows nudge the selected cell, `+`/`−` change level, `Esc`
  deselects, `B` arms build, `Enter` confirms. Show it behind a `?` key.
- Live regions: the result banner is `role="status"`, the locked banner is
  `role="alert"`. The current components already do this — keep it while
  restyling.
- Every icon-only control has an `aria-label`. Every disabled control has a
  reason in text.
- Screen glare: avoid state information conveyed only by thin 1px hairlines.

---

## 8. What must not be done

- No decorative gradients, glassmorphism on chrome, or animated backgrounds. A
  machine console that looks like a crypto dashboard reads as untrustworthy.
- No skeleton shimmer on the camera stage that could be mistaken for a frame.
- No colour used decoratively from the state palette.
- No "Cancel build" or "Retry" control, ever. The hardware cannot honour it.
- No client-side safety logic that isn't also enforced by the server. The
  browser is untrusted by design — the UI mirrors server state, it does not
  decide it.
- No layout that pushes BUILD below the fold on a phone.

---

## 9. Implementation notes

- Keep it dependency-light: plain CSS custom properties and CSS Grid are enough,
  and the bundle is served off a Pi to phones over LAN. If a utility framework
  is introduced, the tokens above are still the source of truth.
- The current source is written one-statement-per-line with whole components on
  a single line. Restyling is the right moment to break those out into readable
  multi-line components — but **do not change any behaviour**: the guarded call
  sequence, the two-tap confirm, the reconnecting socket and the geometry maths
  in `GridOverlay` are all tested (`web/src/step7.test.tsx`, `step9`, `step10`,
  `lib/workspace.test.tsx`). Those tests must still pass.
- Keep the PWA offline shell working; assets must be local for the same reason
  fonts are.
