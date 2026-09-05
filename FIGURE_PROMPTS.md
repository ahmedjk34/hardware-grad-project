# Figure generation prompts

Every figure placeholder left in `Graduation_Project_Report.docx`, with a complete,
self-contained prompt for the ones that can actually be **generated**.

The report currently has **24 figures**: 9 are already real images (including
both wiring diagrams, now generated), **15 are placeholders**. Of those 15,
**6 are diagrams you can generate** and **9 need a camera or a screen capture** —
no generator can invent a photograph of your rig.

---

## Read this before you start

**Text-to-image models (Midjourney, DALL·E, Stable Diffusion, Nano Banana, etc.)
cannot render accurate text, numbers or pin labels.** They will produce
plausible-looking diagrams with garbled captions, invented pin numbers and wrong
connections. For anything in this file that carries labels — which is all of it —
you have three good options, in order of reliability:

| Tool | Best for | Why |
| --- | --- | --- |
| **Mermaid** (mermaid.live, or paste into the doc) | F2, F8, F15, F17 | Text-defined, so labels are exact. Free. Renders to SVG/PNG. |
| **draw.io / diagrams.net** | F2, F7, F13, F14, F15, F17 | Full manual control, has electronics shape libraries. Free. |
| **Fritzing** or **KiCad** | F7, F13, F14 | Purpose-built for wiring; produces something an examiner recognises as a real schematic. |
| **Python + matplotlib** | F6 | The grid overlay is pure geometry from exact numbers; a 20-line script beats any drawing tool. |

The prompts below are written so they work **either** pasted into an AI assistant
that can produce SVG/Mermaid/Python (recommended — ask it for code, not an image),
**or** used as a specification you follow by hand in draw.io.

**One instruction to prepend to every prompt below:**

> Produce this as clean, editable vector output (SVG or Mermaid or matplotlib
> Python), not a raster image. Style it for a conservative academic engineering
> report printed in A4 portrait: white background, thin black or dark-grey lines,
> a serif or neutral sans label font, no gradients, no drop shadows, no 3D effects,
> no decorative icons, no colour except where the specification below explicitly
> asks for it. Every label must be legible at 10 pt when the figure is 14 cm wide.
> Do not invent any component, connection, number or label that is not listed.

---

# PART 1 — The figures you can generate

---

## F2 · System block diagram

**Goes in:** Section 2.3, Overall System Architecture
**Caption in the report:** *System block diagram: the three controllers, the two
independent USB serial links, the camera, and the browser clients on the local
network.*

### Prompt

> Draw a system block diagram of a three-controller robotic cell. Layout is
> top-to-bottom in four bands.
>
> **Band 1 (top): clients.** One box labelled `Browser clients (phone / tablet /
> desktop)`, with a sub-line `operator console + 3D Build Studio`. Mark this box
> as **untrusted mirror** with a small italic note beside it.
>
> **Band 2: the master.** One large box labelled `Raspberry Pi 5 (8 GB) — MASTER`.
> Inside it, five stacked sub-blocks:
> - `Vision pipeline` (sub-label: colour correction → lens correction → block detection)
> - `FastAPI web service` (sub-label: /api/state, /api/build, /api/events, MJPEG stream)
> - `CellOrchestrator` (sub-label: serialises feeder then gantry)
> - `BuildController + BuildJob` (sub-label: one command at a time)
> - `Safety gates + session lock`
>
> **Band 3: the two controllers, side by side and clearly separate.**
> - Left box: `Arduino Uno — FEEDER`, firmware `belt_v1`, sub-label `feed state machine, protocol 2`
> - Right box: `Arduino MEGA 2560 — GANTRY`, firmware `build_test_v1`, sub-label `motion, limits, 14-phase build cycle`
>
> **Band 4 (bottom): the hardware each controller owns.**
> - Under the Uno: `Container servo`, `Belt stepper (A4988)`, `Alignment servo`, `2 x HC-SR04`
> - Under the Mega: `2 x NEMA17 CoreXY (TB6600)`, `NEMA17 Z (TB6600)`, `Gripper servo`, `28BYJ-48 (ULN2003)`, `4 x limit switch`
>
> **Connections, drawn as labelled arrows:**
> - Browser ↔ Pi: bidirectional, labelled `HTTPS + WebSocket (local network)`
> - Pi → Uno: bidirectional, labelled `USB serial A — 9600 8N1, protocol 2`
> - Pi → Mega: bidirectional, labelled `USB serial B — 9600 8N1, @-ack protocol`
> - Camera → Pi: one arrow from a box labelled `OV5647 fisheye camera, 160°, 1296 x 972` into the Vision pipeline block, labelled `CSI ribbon`
>
> **The single most important visual element:** draw a **dashed red line with a
> circle-slash symbol** directly between the Uno box and the Mega box, labelled
> **`NO CONNECTION — the two Arduinos never exchange a byte`**. This isolation is a
> deliberate safety property and the diagram exists mainly to show it.
>
> Keep the two serial links visually distinct (for example one solid, one dashed)
> so it is obvious they are separate physical links, not a bus.

---

## F6 · The two grids overlaid

**Goes in:** Section 2.4.7, The two grids
**Caption in the report:** *The two grids overlaid on the same build surface: the
vertical 7 x 6 lattice and the horizontal 3 x 10 lattice, sharing one envelope and
one feeder cell at [0,0].*

**Best tool: a matplotlib script.** This is pure geometry, every number below is
exact, and the figure lives or dies on the edges lining up. Ask an assistant for
the Python, not an image.

### Prompt

> **Draw a to-scale, fully dimensioned technical plan view of two overlaid grids.
> Produce it as matplotlib Python or SVG, not a raster image — every coordinate
> below is exact and must be plotted, not eyeballed.**
>
> Units are centimetres. X runs left to right, Y runs bottom to top. The origin
> (0,0) is at the bottom-left and is the machine's home corner.
>
> ## The one identity that generates the whole figure
>
> **6.0 = 2.2 + 1.6 + 2.2**
>
> A block is 2.2 x 6.0 cm. The gap between neighbouring cells is a uniform
> **1.6 cm on every axis of both modes**. So a block's *long* side is exactly equal
> to *two short sides plus one gap*. Every alignment in this drawing falls out of
> that single fact. If your drawing does not show that, it is wrong.
>
> ## Colour system — use these exactly
>
> | element | stroke | fill | line style |
> | --- | --- | --- | --- |
> | **VERTICAL grid** | `#1A5FB4` (blue), 1.2 pt | `#1A5FB4` at **12 % opacity** | solid |
> | **HORIZONTAL grid** | `#C64600` (burnt orange), 1.2 pt | `#E66100` at **12 % opacity** | dashed, 4-2 pattern |
> | **Feeder cell [0,0]** | `#1A5FB4`, 1.6 pt | `#5E5C64` (grey) at **35 % opacity** | solid |
> | **Travel envelope** | `#000000`, 1.8 pt | none | solid |
> | **Dimension lines** | `#3D3846` (dark grey), 0.6 pt | — | solid, arrowheads both ends |
> | **Extension lines** | `#9A9996` (light grey), 0.5 pt | — | solid, thin |
> | **Coincident-edge highlight** | `#2EC27E` (green), 2.4 pt | — | solid |
>
> Both grids are **translucent**, so where a horizontal block sits over vertical
> blocks the two fills combine into a deeper tone and the overlap is visible
> without any extra annotation. That combined tone is the figure's main message.
>
> ## Envelope
>
> Rectangle (0,0) to (22.8, 38.0), labelled `holder travel envelope - 22.8 x 38.0 cm`.
> Mark (0,0) with a filled square: `HOME [0,0] - X and Y limit switches`.
>
> ## Grid A - VERTICAL (blue)
>
> Block **2.2 wide (X) x 6.0 tall (Y)**. 7 columns x 6 rows = 42 cells.
>
> Column X centres and their **left / right edges** (centre +/- 1.1):
>
> | col | centre | left | right |
> |---|---|---|---|
> | 0 | 0.0 | -1.1 | 1.1 |
> | 1 | 3.8 | 2.7 | 4.9 |
> | 2 | 7.6 | 6.5 | 8.7 |
> | 3 | 11.4 | 10.3 | 12.5 |
> | 4 | 15.2 | 14.1 | 16.3 |
> | 5 | 19.0 | 17.9 | 20.1 |
> | 6 | 22.8 | 21.7 | 23.9 |
>
> Row Y centres and their **bottom / top edges** (centre +/- 3.0):
>
> | row | centre | bottom | top |
> |---|---|---|---|
> | 0 | 0.0 | -3.0 | 3.0 |
> | 1 | 7.6 | 4.6 | 10.6 |
> | 2 | 15.2 | 12.2 | 18.2 |
> | 3 | 22.8 | 19.8 | 25.8 |
> | 4 | 30.4 | 27.4 | 33.4 |
> | 5 | 38.0 | 35.0 | 41.0 |
>
> ## Grid B - HORIZONTAL (orange)
>
> Block **6.0 wide (X) x 2.2 tall (Y)**. 3 columns x 10 rows = 30 cells.
> Registered **+1.9 cm on both axes**.
>
> Column X centres and **left / right edges** (centre +/- 3.0):
>
> | col | centre | left | right |
> |---|---|---|---|
> | 0 | 1.9 | -1.1 | 4.9 |
> | 1 | 9.5 | 6.5 | 12.5 |
> | 2 | 17.1 | 14.1 | 20.1 |
>
> Row Y centres and **bottom / top edges** (centre +/- 1.1):
>
> | row | centre | bottom | top |
> |---|---|---|---|
> | 0 | 1.9 | 0.8 | 3.0 |
> | 1 | 5.7 | 4.6 | 6.8 |
> | 2 | 9.5 | 8.4 | 10.6 |
> | 3 | 13.3 | 12.2 | 14.4 |
> | 4 | 17.1 | 16.0 | 18.2 |
> | 5 | 20.9 | 19.8 | 22.0 |
> | 6 | 24.7 | 23.6 | 25.8 |
> | 7 | 28.5 | 27.4 | 29.6 |
> | 8 | 32.3 | 31.2 | 33.4 |
> | 9 | 36.1 | 35.0 | 37.2 |
>
> ## THE PERFECT MATCH - this is what the figure exists to show
>
> The two grids are not merely overlapping. Their **edges coincide exactly**, on
> both axes, and the relationship is the same identity transposed.
>
> **Along X - one horizontal block = two vertical blocks + the gap between them.**
>
> | horizontal col | spans exactly | check |
> |---|---|---|
> | 0 (-1.1 to 4.9) | vertical cols **0 + 1** (-1.1 to 4.9) | both edges coincide |
> | 1 (6.5 to 12.5) | vertical cols **2 + 3** (6.5 to 12.5) | both edges coincide |
> | 2 (14.1 to 20.1) | vertical cols **4 + 5** (14.1 to 20.1) | both edges coincide |
>
> Vertical column **6 has no horizontal partner** - a fourth horizontal column
> would need vertical columns 6 + 7, and column 7 does not exist. **This is exactly
> why horizontal is 3 columns and not 4.** Tint vertical column 6 slightly and
> label it `no horizontal partner - why horizontal stops at 3 columns`.
>
> **Along Y - two horizontal blocks + their gap = one vertical block.**
>
> | vertical row | covered by horizontal rows | check |
> |---|---|---|
> | 0 (-3.0 to 3.0) | row **0** only (0.8 to 3.0) | top edges coincide at 3.0; row 0 is half off the machine so it takes one, not two |
> | 1 (4.6 to 10.6) | rows **1 + 2** (4.6 to 6.8, 8.4 to 10.6) | outer edges coincide; 2.2 + 1.6 + 2.2 = 6.0 |
> | 2 (12.2 to 18.2) | rows **3 + 4** | outer edges coincide |
> | 3 (19.8 to 25.8) | rows **5 + 6** | outer edges coincide |
> | 4 (27.4 to 33.4) | rows **7 + 8** | outer edges coincide |
> | 5 (35.0 to 41.0) | row **9** only (35.0 to 37.2) | bottom edges coincide at 35.0; row 5's top is past the cap |
>
> **Draw every coincident edge as one shared line, not two lines a hair apart.**
> Then overdraw a short segment of six of them in the green highlight colour to
> make the coincidence unmissable: X at -1.1, 4.9, 12.5, 20.1 and Y at 4.6, 10.6.
>
> ## DIMENSIONS - draw these on the figure
>
> Use proper engineering-drawing convention: thin light-grey **extension lines**
> projecting from the feature being measured, a dark-grey **dimension line** with
> arrowheads at both ends running between them, and the value centred just above
> the dimension line. Stack them in tiers so nothing collides, nearest feature on
> the innermost tier.
>
> **Below the figure, five tiers along X (innermost first):**
>
> | tier | measures | value | label |
> |---|---|---|---|
> | 1 | one vertical block width | `2.2` | on vertical col 2 |
> | 1 | one gap | `1.6` | between vertical cols 2 and 3 |
> | 2 | vertical X pitch, centre to centre | `3.8` | col 2 centre to col 3 centre |
> | 3 | one horizontal block width | `6.0` | on horizontal col 1, annotated `= 2.2 + 1.6 + 2.2` |
> | 4 | horizontal X pitch | `7.6` | col 1 centre to col 2 centre, annotated `= 2 x 3.8` |
> | 5 | overall travel | `22.8` | from x=0 to x=22.8, annotated `X holder travel` |
>
> **To the left of the figure, five tiers along Y (innermost first):**
>
> | tier | measures | value | label |
> |---|---|---|---|
> | 1 | one horizontal block height | `2.2` | on horizontal row 3 |
> | 1 | one gap | `1.6` | between horizontal rows 3 and 4 |
> | 2 | horizontal Y pitch | `3.8` | row 3 centre to row 4 centre |
> | 3 | one vertical block height | `6.0` | on vertical row 2, annotated `= 2.2 + 1.6 + 2.2` |
> | 4 | vertical Y pitch | `7.6` | row 2 centre to row 3 centre, annotated `= 2 x 3.8` |
> | 5 | overall travel | `38.0` | from y=0 to y=38.0, annotated `Y holder travel` |
>
> **Registration dimensions, drawn diagonally at the bottom-left corner:**
> - Horizontal dimension from x=0.0 to x=1.9, value `1.9`
> - Vertical dimension from y=0.0 to y=1.9, value `1.9`
> - One shared callout: `+1.9 cm registration on both axes. 1.9 = (6.0 - 2.2)/2,
>   which seats horizontal [0,0] flush against vertical [0,0]: near edge in X at
>   -1.1, far edge in Y at +3.0.`
>
> **Overhang dimensions, drawn outside the envelope with a distinct short-dash
> style so they read as "past the machine":**
> - From x=-1.1 to x=0.0, value `1.1`, label `X overhang - half a block past the switch`
> - From y=-3.0 to y=0.0, value `3.0`, label `Y overhang - half a block past the switch`
> - From x=22.8 to x=23.9, value `1.1`, label `far-edge overhang`
> - From y=38.0 to y=41.0, value `3.0`, label `far-edge overhang`
> - Group note: `The firmware checks block EDGES against a per-mode overhang
>   budget. Vertical allows 1.1 cm in X and 3.0 cm in Y - exactly half a block on
>   each axis.`
>
> **Axis tick labels.** Put a light tick and numeric label at every vertical
> column centre along the bottom X axis (0.0, 3.8, 7.6, 11.4, 15.2, 19.0, 22.8)
> and at every vertical row centre up the left Y axis (0.0, 7.6, 15.2, 22.8, 30.4,
> 38.0). Add the horizontal-grid centres as a **second, orange tick row just
> inside** each axis (X: 1.9, 9.5, 17.1 / Y: 1.9, 5.7, 9.5, 13.3, 17.1, 20.9,
> 24.7, 28.5, 32.3, 36.1) so the offset between the two lattices is readable
> straight off the axis.
>
> ## Other annotations required
>
> 1. **The feeder cell.** Vertical [0,0] in the grey fill: `[0,0] is the FEEDER -
>    never built on, in either mode. Its centre IS the home corner.` It is centred
>    on the origin, so half of it hangs outside the envelope below y=0 and left of
>    x=0. **Do not clip it** - that overhang is correct.
> 2. **One worked X example.** Bracket vertical columns 2 and 3 under horizontal
>    column 1: `6.0 = 2.2 + 1.6 + 2.2, so pitch 7.6 = 2 x 3.8`.
> 3. **One worked Y example.** Bracket horizontal rows 3 and 4 beside vertical
>    row 2: `the same identity, transposed`.
> 4. **Cell labels.** Label the four corner cells of each grid with their
>    `[col,row]` index, in that grid's own colour. Do not label all 72 - it becomes
>    unreadable.
> 5. **Legend**, with a colour swatch per grid:
>    `VERTICAL - block 2.2 x 6.0 cm - 7 x 6 addressable, 41 buildable`
>    `HORIZONTAL - block 6.0 x 2.2 cm - 3 x 10 addressable, 29 buildable`
>    plus a note: `both counts exclude the shared feeder cell at [0,0]`.
>
> ## Before you output, verify
>
> - [ ] Horizontal col 0 left edge = vertical col 0 left edge = **-1.1**
> - [ ] Horizontal col 0 right edge = vertical col 1 right edge = **4.9**
> - [ ] Horizontal col 2 right edge = vertical col 5 right edge = **20.1**
> - [ ] Horizontal row 1 bottom = vertical row 1 bottom = **4.6**
> - [ ] Horizontal row 2 top = vertical row 1 top = **10.6**
> - [ ] Horizontal row 9 bottom = vertical row 5 bottom = **35.0**
> - [ ] Vertical col 6 is the only column with no horizontal block over it
> - [ ] Every dimension tier is drawn and none of the dimension text overlaps
> - [ ] Aspect ratio is true to scale - the surface is taller than it is wide (22.8 : 38.0)
>
> Style: white background, no gradients or shadows, all labels legible at 10 pt
> when the figure is 14 cm wide. Leave generous margin outside the envelope for
> the five dimension tiers on each axis.


## F7 · Power distribution schematic

**Goes in:** Section 2.5.1, Power architecture
**Caption in the report:** *Power distribution schematic: the 12 V supply, the
LM2596 buck converter, the two rails and the common ground.*

### Prompt

> Draw a power distribution schematic (a block/rail diagram, not a full circuit
> schematic — no component-level symbols needed beyond the supply and the
> converter).
>
> **Sources, across the top:**
> - `Mains AC` → `Switched-mode PSU, 12 V / 15 A`
> - Separate and unconnected to the above: `Raspberry Pi 5 official USB-C PSU`
>
> **Rails, as two horizontal bus lines:**
> - **12 V rail**, drawn straight from the PSU. Label it `12 V`.
> - **5 V rail**, fed from a block labelled `LM2596 adjustable buck converter
>   (4–40 V in, set to 5 V out, 3 A)` which takes its input from the 12 V rail.
>   Label the output rail `5 V`.
>
> **Loads on the 12 V rail (draw as four drops off the bus):**
> - `TB6600 #1 → NEMA17, CoreXY motor 1`
> - `TB6600 #2 → NEMA17, CoreXY motor 2`
> - `TB6600 #3 → NEMA17, Z axis`
> - `A4988 → NEMA17, feeder conveyor belt` (motor supply only)
>
> **Loads on the 5 V rail (draw as five drops off the bus):**
> - `Gripper servo` (on the Mega)
> - `Container gate servo` (on the Uno)
> - `Alignment servo` (on the Uno)
> - `ULN2003 → 28BYJ-48 claw rotation stepper`
> - `2 x HC-SR04 ultrasonic sensors`
> - `A4988 logic / reference supply`
>
> **The two Arduinos are NOT on either rail.** Draw them fed from the Pi:
> `Raspberry Pi 5` → two separate arrows labelled `USB (power + data)` → to
> `Arduino MEGA 2560` and `Arduino Uno`. Make it clear the same USB cable carries
> both power and the serial link.
>
> **Ground.** Draw a single common ground rail along the bottom, tied to: the 12 V
> PSU negative, the buck converter ground, both Arduino grounds, all four motor
> drivers, and both ultrasonic sensors. Label it
> `COMMON GROUND — all supplies, drivers and sensors share one ground`.
>
> **Annotation, placed as a note box:** `Sequential operation: the build cycle
> moves Z, then X/Y, then Z again; the feeder belt runs only while the gantry is
> idle. Peak instantaneous draw is normally one stepper plus logic, well inside
> the 15 A rating.`
>
> Do not draw any fuse, flyback diode or reverse-polarity protection — none is
> fitted on this machine.

---

## F8 · End-to-end workflow

**Goes in:** Section 2.6, System Workflow
**Caption in the report:** *End-to-end workflow, from a design in the browser to a
block on the stack, showing where each of the five stages is confirmed and not
assumed.*

**Best tool: Mermaid flowchart.**

### Prompt

> Draw a vertical flowchart of a five-stage robotic build sequence. Two of the
> stages are **confirmation gates** and must be visually emphasised — this is the
> entire point of the figure.
>
> **Stage 1 — DESIGN** (actor: a person, in a browser)
> `Human places blocks in the 3D Build Studio` → `Live physics validation: support,
> collision, toppling`
>
> **Stage 2 — COMPILE** (actor: the browser)
> `Build a support graph from footprint overlap` → `Order bottom-up with Kahn's
> algorithm, grouping same-orientation runs` → `Emit an ordered program of
> B col row level commands separated by R / RR mode latches`
> Add a note: `An invalid model compiles to nothing at all, never to a half-program.`
>
> **Then a loop begins: "for each block in the program".** Draw the next three
> stages inside a labelled loop box.
>
> **Stage 3 — FEED** (actor: Arduino Uno)
> `Pi sends FEED <id>` → `Close container, settle 500 ms` → `Open gate in two
> stages: 20° → 90° → 160°` → `Wait for EXIT sensor (10 s timeout)` → `Shut gate
> behind the block` → `Run belt` → `Wait for STAGE sensor (15 s timeout)` →
> `Nudge square with the alignment servo, 350 ms` → `Re-read STAGE sensor`
>
> **★ GATE 1 — a decision diamond, drawn prominently:**
> `Uno returns @id OK state=block_ready result=staged ?`
> - **NO** → red path → `No B is sent. Session LOCKS. A person inspects.` (terminate)
> - **YES** → continue
>
> Annotate gate 1: `This exact message, with a matching id, is the ONLY thing that
> authorises the gantry to move. ACK / STATE / SENSOR / EVENT lines are progress,
> never permission.`
>
> **Stage 4 — PLACE** (actor: Arduino MEGA)
> `Pi sends B col row level` → `14-phase pick / rotate / place / park cycle` →
> `Firmware narrates each phase back as @seq STEP ... status=begin`
>
> **★ GATE 2 — a second decision diamond:**
> `Mega returns terminal @seq OK ?`
> - **SAFE / HELD / timeout** → red path → `Session LOCKS. A block is already
>   staged, so no retry and no next feed.` (terminate)
> - **OK** → continue
>
> **Stage 5 — VERIFY**
> `Overhead camera observes the surface` → `Digital twin updates from the
> firmware's own phase telemetry`
>
> Then a **loop-back arrow** to the top of the loop, labelled `next block`, and an
> exit arrow labelled `program complete`.
>
> Use green for the success path, red for the two lock paths, and make both
> decision diamonds the largest elements in the diagram. Everything else in
> greyscale.

---

## F13 and F14 · The two wiring diagrams — ALREADY DONE

**Status: generated and already in the report.** These were the two figures that
made image models hallucinate Arduino boards with invented pins. They are no
longer prompts.

**Why the prompt approach failed.** Asking any image model for "a wiring diagram
of an Arduino MEGA" gives you a *picture of a board*, and the model draws the
board from its training data, not from your pin list. It will invent headers,
relabel pins, add components you never mentioned and drop ones you did. No amount
of prompt detail fixes it, because the model is drawing a photograph of an idea of
an Arduino, not reading your netlist.

**What replaced it.** `report_src/mkwiring.py` renders both diagrams as SVG
directly from a netlist. The board is a plain labelled rectangle — deliberately
**not** a picture of a real Arduino — with a pin stub per connection, a box per
peripheral, and one wire per netlist row. The pin numbers appear in exactly one
place in the script, so the drawing physically cannot disagree with the firmware.

```
report_src/mkwiring.py          the generator
report_src/figs/fig-wiring-mega.svg / .png
report_src/figs/fig-wiring-uno.svg  / .png
```

Regenerate after any firmware pin change:

```bash
python3 report_src/mkwiring.py
cd report_src/figs && convert -density 130 -background white fig-wiring-mega.svg fig-wiring-mega.png
convert -density 130 -background white fig-wiring-uno.svg fig-wiring-uno.png
```

**The netlist, for reference.** Transcribed from
`arduino/build_test_v1/build_test_v1.ino` and `arduino/belt_v1/belt_v1.ino`.

**Arduino MEGA 2560 — gantry:**

| pin | connects to | note |
|---|---|---|
| 2 | TB6600 #1 DIR | CoreXY motor 1 |
| 3 | TB6600 #1 STEP | NEMA17 |
| 4 | TB6600 #1 ENABLE | **active LOW** |
| 8 | TB6600 #2 DIR | CoreXY motor 2 |
| 9 | TB6600 #2 STEP | NEMA17 |
| 10 | TB6600 #2 ENABLE | active LOW |
| 11 | TB6600 #3 DIR | Z axis |
| 12 | TB6600 #3 STEP | **no ENABLE line fitted** |
| 6 | Gripper servo signal | OPEN 0°, CLOSE 52° |
| 28 | Z bottom limit switch | NC + pull-up, Z zero / GROUND reference |
| 29 | Z top limit switch | NC + pull-up, far-end stop, does not redefine zero |
| 30 | X limit switch | NC + pull-up, X home / zero |
| 31 | Y limit switch | NC + pull-up, Y home / zero |
| 38 | ULN2003 IN1 | black |
| 36 | ULN2003 IN2 | green |
| 39 | ULN2003 IN3 | blue |
| 37 | ULN2003 IN4 | red |
| USB | Raspberry Pi 5 | 9600 8N1, also powers the board |

> **The trap worth keeping in the caption:** the Stepper library is constructed in
> the order IN1, IN3, IN2, IN4 — that is **pins 38, 39, 36, 37**. Wiring the
> ULN2003 in numerical pin order gives a motor that buzzes and does not turn.

**Arduino Uno — feeder:**

| pin | connects to | note |
|---|---|---|
| 2 | A4988 DIR | belt direction |
| 3 | A4988 STEP | NEMA17 conveyor, 150 steps/s default |
| 4 | Exit HC-SR04 TRIG | container exit |
| 5 | Exit HC-SR04 ECHO | proves a block left the hopper |
| 8 | Stage HC-SR04 TRIG | pickup point |
| 9 | Stage HC-SR04 ECHO | proves a block reached [0,0] |
| 6 | Alignment servo signal | rest 90°, nudge 120° |
| 12 | Container servo signal | closed 20°, stage 1 at 90°, open 160° |
| USB | Raspberry Pi 5 | 9600 8N1, protocol 2, also powers the board |

> A4988 **ENABLE is tied directly to ground**, not driven by the Arduino — there is
> no enable pin in the firmware. Detection threshold is **< 10.0 cm**, with a 30 ms
> echo timeout reported as `no_echo` and never treated as a detection.

**Both boards:** motor supplies come off the **12 V** rail; servos, the ULN2003 and
the sensors come off the **5 V** rail from the LM2596 — **not** from either
Arduino's own 5 V pin. One common ground across everything. The two boards have no
connection to each other.

---

## If you ever do need a diagram from a model

The lesson generalises to F2, F7, F15 and F17. **Never ask for an image of a
thing.** Ask for **code that draws** the thing — SVG, Mermaid, matplotlib,
Graphviz — and give the data as a table. The model then places labels from your
data instead of recalling what the object usually looks like, and you get a file
you can edit and regenerate rather than a picture you have to accept or redo.


## F15 · Vision pipeline block diagram

**Goes in:** Section 4.3.1, The pipeline, in order
**Caption in the report:** *Vision pipeline: capture, orientation, colour
correction, lens correction, detection, and the pixel-to-centimetre-to-cell
mapping.*

**Best tool: Mermaid flowchart, left-to-right.**

### Prompt

> Draw a left-to-right block diagram of a camera processing pipeline with six
> stages in a fixed order, plus one branch that runs off the main loop.
>
> **Main chain, in this exact order:**
> 1. `CAPTURE` — sub-label: `OV5647 fisheye, 1296 x 972 via Picamera2, into a
>    non-blocking latest-frame pump`
> 2. `FRAME ORIENTATION` — sub-label: `configured flip and rotation, applied first
>    so everything downstream shares one convention`
> 3. `COLOUR CORRECTION` — sub-label: `saved 3x4 gain/offset matrix + saturation,
>    applied ONCE here and never inside a detector`
> 4. `LENS CORRECTION` — sub-label: `equidistant fisheye remap table, then the
>    framing crop and zoom`
> 5. `DETECTION` — sub-label: `runs on a background worker at a lower rate than
>    the video`
> 6. `MAPPING` — sub-label: `saved workspace homography: pixel → physical cm →
>    [col, row]`
>
> **Draw stage 5 as a branch off the main line, not inline.** The main loop
> continues straight through to the display, and the analysis worker hangs below
> it, with a return arrow labelled `last completed result`. Annotate:
> `The main loop draws the last completed result instead of waiting, so a slow
> analysis can never stall the video.`
>
> **Expand the DETECTION box into three stacked sub-layers**, since the report
> makes a point of them being distinct:
> - `Layer 1 — segmentation` : `red-minus-blue AND red-minus-green thresholds
>   (never brightness); 3x3 open, 5x5 close; then straight-through, touching-block
>   split, or compound decomposition`. Tag it: **"returns a hypothesis, not an answer"**
> - `Layer 2 — live overlay` : `reject IoU duplicates → reject anything off the
>   frame → reject anything >0.34 cells off the lattice → rectify to a shared size
>   and bearing`. Tag it: **"the measured centre is never snapped"**
> - `Layer 3 — calibration` : `runs once, deliberately; the only layer allowed to
>   write workspace_map.json`
>
> Add a final note box on the output: `The Pi picks the cell. The firmware alone
> turns a cell into safe step targets.`
>
> Show the two settings files as small cylinder/document shapes feeding the
> relevant stages: `camera_settings.json` → stages 2, 3, 4; `workspace_map.json` →
> stage 6.

---

## F17 · The fourteen-phase build cycle

**Goes in:** Section 4.4.1, The fourteen-phase build cycle
**Caption in the report:** *The fourteen-phase build cycle, drawn against the
machine's axes: the pick at the feeder, the carry at top-switch height, the
placement at the target level, and the park.*

**This is the most valuable diagram in the report — the 14-phase cycle is the core
of the machine.** Draw it as an annotated side elevation with the tool path traced.

### Prompt

> Draw a side-elevation diagram of a Cartesian gantry executing one pick-and-place
> cycle, with the tool path traced and fourteen numbered phases marked along it.
>
> **The stage.** Horizontal axis is X/Y travel (left to right), vertical axis is Z
> height. Mark three horizontal reference lines:
> - Top: `Z TOP SWITCH (pin 29) — carry height, ~26.5 cm` (dashed)
> - Bottom: `Z GROUND SWITCH (pin 28) — Z = 0, the level datum` (solid)
> - A mid line at the target: `target block level = level x 1.5 cm + 0.10 cm fixed margin`
>
> On the left of the X axis mark `[0,0] THE FEEDER — its centre IS the home corner`.
> On the right mark `TARGET CELL [col, row]`.
>
> **Trace the tool path as a single continuous line with numbered waypoints:**
>
> | # | phase id | what happens | where on the path |
> | --- | --- | --- | --- |
> | 1 | `raise_clear` | Raise Z into the top switch | vertical up, at start |
> | 2 | `home_feeder` | Home X/Y to the feeder cell [0,0] | horizontal, to the left, at top height |
> | 3 | `neutralise_claw` | Return the claw to neutral | at the feeder, no movement — draw a rotation symbol |
> | 4 | `open_claw` | Open the jaws | at the feeder, top height |
> | 5 | `lower_to_ground` | Lower Z into the bottom switch — **also re-zeroes Z** | vertical down, at the feeder |
> | 6 | `grip` | Close the claw — **the block is now held** | at ground, feeder |
> | 7 | `lift_block` | Raise Z to carry height | vertical up, at the feeder |
> | 8 | `move_to_target` | Move X/Y to the target cell | horizontal, left to right, at top height |
> | 9 | `rotate_to_grid` | Apply the grid's rotation (90° CW in horizontal mode) | above the target — draw a rotation symbol |
> | 10 | `lower_to_level` | Lower Z to the target block level | vertical down, at the target |
> | 11 | `release` | Open the claw — **the block is placed** | at the target level |
> | 12 | `park_clear` | Raise Z clear of the stack | vertical up, at the target |
> | 13 | `park_home` | Return X/Y to the origin | horizontal, right to left, at top height |
> | 14 | `park_rotation` | Return the claw to neutral | back at home |
>
> **Colour the path in three segments:**
> - Phases 1–5 in grey, labelled `APPROACH (empty claw)`
> - Phases 6–11 in solid blue and slightly thicker, labelled `CARRYING A BLOCK`
> - Phases 12–14 in dashed grey, labelled `PARK`
>
> **Callouts that must appear:**
> - At phase 5: `Every build re-establishes Z's zero on the physical ground switch
>   before it picks up. Neither end of a build's Z travel is a remembered number.`
> - At phase 11: `The ONLY status=done in the protocol is emitted here, the instant
>   the jaws open. It is NOT terminal — the rig still has to park.`
> - At phase 12: `Z must rise before any X/Y move, or the claw drags through the
>   stack it just added to.`
> - Beside phases 12–14: `A failure here is a WARNING, not a failed build — the
>   block is already down. But it downgrades the terminal result from OK to HELD.`
> - Somewhere prominent: `The firmware announces each phase BEFORE it runs, as
>   @seq STEP step=n total=14 phase=... status=begin`
> - On the five Z-move phases (1, 5, 7, 10, 12): a small tag `carries ms= ETA`
>
> Show a small block shape being carried by the claw between phases 6 and 11, and
> a small stack of previously placed blocks at the target cell.

---

# PART 2 — The 9 figures that must be captured, not generated

No prompt will produce these. This is a shot list.

## Photographs (6)

| Fig | Section | What to shoot | Must be visible in frame |
| --- | --- | --- | --- |
| **F1** | 1.1 | The completed rig, three-quarter view | The CoreXY gantry, the Z column and claw, the feeder module on the left, and the overhead camera on its wooden support frame — all in one shot. This is the report's opening image, so shoot it clean: clear the bench, even lighting, plain background if you can. |
| **F3** | 2.4.2 | The X/Y stage from directly above | The belt path (trace it in an image editor afterwards with a coloured line), both frame-mounted NEMA17s, the castor-wheel carriages, and the X and Y limit switches. Label the two switches. |
| **F4** | 2.4.4 | The claw, close up | The 3D-printed jaws, the gripper servo, and the 28BYJ-48 rotation stepper. Mark the grip axis and, if you can, the ≈(−0.3, +0.6) cm offset between the grip centre and the rotation axis — that offset is discussed in the text. |
| **F5** | 2.4.5 | The feeder module alongside the gantry | The hopper with its gate servo, the conveyor belt, the alignment servo, and **both** HC-SR04 sensors. Label the exit sensor, the stage sensor, and the pickup point at cell [0,0]. |
| **F10** | 3.4.1 | The overhead camera mount | The camera on its wooden support structure with the whole rig underneath, so the ~50 cm working distance is legible. A tape measure in shot would make the distance verifiable. |
| **F24** | 5.6.3 | A completed structure | A finished multi-level structure on the rig. **Ideally paired side by side with a screenshot of the same model in the Studio** — the report explicitly calls this the single best possible figure, because it closes the design-to-build loop visually. Record the block count, level count and modes used; the caption has a placeholder for them. |

## Screenshots (3)

| Fig | Section | What to capture |
| --- | --- | --- |
| **F18** | 4.5.1 | The operator console, on a phone or tablet. Must show: the live camera view with the grid overlay, a **cell selected**, the exact `B col row level` command displayed, the level stepper, and the status rail with both board chips connected. |
| **F19** | 4.5.2 | The 3D Build Studio with a **multi-level, mixed-orientation** model open (so mode latches appear), the level scrubber, the diagnostics panel, and the compiled program view visible alongside. |
| **F20** | 4.5.3 | The digital twin **mid-build**, showing a block being carried, the current phase readout, and previously confirmed placements. Best captured beside the camera view of the same moment. |

---

# Suggested order of work

1. **F17** (14-phase cycle) — highest value, and pure diagram work.
2. **F2** (system block diagram) — an examiner will look for this first.
3. **F8** (workflow) and **F15** (vision pipeline) — both quick in Mermaid.
4. **F6** (two grids) — a short matplotlib script; all numbers are in the prompt.
5. **F13**, **F14** (wiring) — slowest, but the pin data is complete and exact.
6. **F7** (power) — quick once the wiring diagrams exist.
7. The photographs, in one session with the rig set up.
8. The three screenshots, in one session with the service running.

Drop each finished image into `report_src/figs/`, then in `report_src/` change the
matching `rep.figure(...)` call from a `placeholder=` to `image="your-file.png"`
and re-run `build_report.py`. Figure numbers renumber themselves.
