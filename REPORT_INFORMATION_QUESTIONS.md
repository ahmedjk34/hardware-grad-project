# Report Information — Questions to Answer

Fill in each **Answer:** block below. These are only the gaps that the
repository cannot answer on its own. Anything the repo already documents well
(system architecture, serial protocols, the guard stack, the 14 build phases,
dual-grid geometry maths, the X-rail skew model, colour correction, the block
detection layers, calibration routes, the console/Studio software architecture,
firmware command vocabulary, both firmwares' pin maps, repo layout, test
coverage) is **not** asked about here.

Sections follow `WANTED_REPORT_STRUCTURE.md`.

Legend:

- **[CONFIRM]** — the repo strongly implies an answer; just say yes/no or correct it.
- **[NEEDED]** — genuinely missing; needs your input.
- **[EVIDENCE]** — a measurement, photo, or diagram is probably needed.

---

## Front Matter

**Q0.1 [NEEDED]** Project title, your full name(s), supervisor, department,
university, and submission date, exactly as they should appear on the title page.

**Answer:**
Title: Vision-Assisted Cartesian Robotic System for 3D Block Construction
Names: Ahmed Taher Gharib
Mohie Aldeen Amjad Halawa
Khalil Mahmoud Qanabita

       REST OF STUFF FOR COVER PAGE, FORGET ABOUT IT, PLACEHOLDERS

**Q0.2 [NEEDED]** Is this a solo or team project? If a team, who did what
(mechanical, electronics, firmware, vision, web)?

THIS DOESNT MATTER, ITS A TEAM EFFORT AND SHOULD BE TREATED AS SUCH

**Answer:**

**Q0.3 [EVIDENCE]** Which figures/photos/diagrams do you already have or can
produce? (rig photos, wiring diagram, mechanical drawings/CAD, system block
diagram, console screenshots, Studio screenshots, photos of completed block
structures, oscilloscope/measurement shots). List what exists.

**Answer:**
I ACTUALLY DONT HAVE MANY, JUST ADD PLACEHOLDERS FOR NOW, AND I'D REMOVE WHAT'S NOT AVAILABLE

---

# 1. Introduction

## 1.1 Background and Motivation

**Q1.1.1 [NEEDED]** In one or two paragraphs: what is the real-world context or
problem area this project sits in (automated construction / robotic assembly /
pick-and-place / vision-guided robotics / education)? Why did _you_ choose to
build a vision-assisted block-stacking gantry specifically?

YOU DO UR RESEARCH AND THINK ABOUT IT AND ENHANCE IT, IT'S THE JOB OF THE REPORT WRITER, AT THE END OF THE DAY, ITS A 'TOY' KIND OF PROJECT, SOMETHING U PLAY WITH

**Answer:**

**Q1.1.2 [NEEDED]** The mechanical X/Y design is a modified version of the
Instructables "Automated Chessboard" (Greg06). Why did you start from that
design, and what about it made it a good base for a _3D block construction_
machine rather than a chess machine?

**Answer:**
INVENT SOMETHING UP THAT MAKES SENSE, BASED ON THE DESIGN AND IT'S QUALITIES [SO DEDEUCE AN ANSWER]

## 1.2 Problem Statement

**Q1.2.1 [NEEDED]** State the problem the finished system is meant to solve, in
your own words. (The repo frames it as "build a human-designed 3D block
structure with no human placing a block by hand, with closed-loop feedback at
every stage instead of open-loop timing" — is that your intended problem
statement, or is the emphasis elsewhere?)

YES GOOD REPO DESCRIPTION, ENHANCE IT

**Answer:**

**Q1.2.2 [NEEDED]** Why does this problem need a solution / why is open-loop
timing-based automation insufficient? (What goes wrong without the feedback the
system adds?)

**Answer:**
AGAIN - DO UR RESEARCH AND DEDUCE AN ANSWER

## 1.3 Project Objectives

**Q1.3.1 [NEEDED]** State the single main goal and 4–8 specific, measurable
objectives the _completed_ system was meant to achieve (e.g. "place a block
within X mm of the target cell", "stack to N levels", "verify each placement by
camera", "operate entirely from a browser"). Give the target numbers you set.

**Answer:**
AGAIN - DO UR RESEARCH AND DEDUCE AN ANSWER

**Q1.3.2 [CONFIRM]** Autonomous "which block goes where" planning is explicitly
out of scope — the human designs the structure and the system builds exactly
that. Correct?

**Answer:**
NO THO, WE ACTUALYL DO HAVE THE ABILTIY TO PLACE A BLOCK WHERE U NEED, AND TECHICNALYL ,THE BUILD IS AUTONOMOUS, THE DESIGN PROCESS ISN'T. WHICH MAKES SENSE

## 1.4 Scope and Boundaries

**Q1.4.1 [CONFIRM]** In scope: Cartesian gantry pick/place/stack + claw rotation
(2 block orientations), a separate feeder module that doses one block at a time,
overhead-camera block detection and grid calibration, a browser operator console
plus a 3D design/compile/twin/run Studio. Out of scope: chess/AI move planning,
autonomous target selection, a hardware emergency-stop / safety interlock,
WebRTC video, real user accounts, multi-operator coordination. Is this the right
scope statement? Correct or add anything.

**Answer:**
YES CORRECT

**Q1.4.2 [NEEDED]** Which parts are you presenting as _fully working_ vs
_designed/partially working_ for the defence? (See the readiness notes — the
feeder module's physical commissioning, printed-sheet camera calibration on the
real rig, placement supervision, and the Studio "wow pass" are the uncertain
ones.)

**Answer:**
ITS ALL FULLY WORKING

## 1.5 Significance of the Project

**Q1.5.1 [NEEDED]** What do you consider the project's main contribution or the
thing it best demonstrates (e.g. the closed-loop feedback discipline, the
vision→physical-coordinate pipeline, the design-compile-twin-run software chain,
the dual-orientation grid)? Who would a system like this be useful to?

**Answer:**
AGAIN - DO UR RESEARCH AND DEDUCE AN ANSWER

---

# 2. System Requirements and Design

## 2.1 System Requirements

**Q2.1.1 [NEEDED]** List the functional requirements you designed to. The repo
implies many (place at any addressable cell; stack to a level; two block
orientations; single-block feeding with sensor confirmation at both ends;
camera verification; browser control; no queued commands). Please give them as
an explicit numbered list, including any you had that the repo doesn't state.

**Answer:**
AGAIN - DO UR RESEARCH AND DEDUCE AN ANSWER

**Q2.1.2 [NEEDED / EVIDENCE]** What performance requirements did you set, and
what were the actual measured values? Candidates: placement accuracy /
repeatability, cycle time per block (logs show ~20–32 s per direct gantry
build), max stack height / max structure size, camera frame rate, calibration
residual. Give target vs achieved for each.

**Answer:**
AGAIN - DO UR RESEARCH AND DEDUCE AN ANSWER

**Q2.1.3 [NEEDED]** What safety / operational requirements did you adopt? The
repo's stated model is: one command at a time, never queued; an aborted or
timed-out build locks the session and requires a human + service restart; no
software cancel of an in-flight Mega move; feeder `[0,0]` is never a build
target. Is there anything else (guarding, run-only-attended, power switch
placement, keeping hands clear)?

**Answer:**
AGAIN - DO UR RESEARCH AND DEDUCE AN ANSWER

## 2.2 Design Constraints

**Q2.2.1 [NEEDED]** What constrained the design? Known from the repo: 8 KB AVR
SRAM forced `F()` string handling and a terse serial protocol; 9600 baud;
opening the USB port resets the Mega; the Mega goes deaf during a ~40 s build;
no EEPROM so mode/grid must be re-pushed each connect; Pi camera only via
Picamera2; no local Arduino toolchain. Add any budget, time, workshop-access,
or component-availability constraints that shaped decisions.

**Answer:**
AGAIN - DO UR RESEARCH AND DEDUCE AN ANSWER, OTHER CONSTRAINTS DO INCLUDE THE FACT THAT THE DESIGN CAUSES A PULL IN THE DIRECTION THE X IS MOVING TO WHICH CASUSE ACCURACY ERRROS, THINK THIS IS DOCUMENTED, AND OBV THERE ARE OTHER CONTAINSTRS CAN SEE

**Q2.2.2 [NEEDED]** Were there physical constraints on the workspace size, the
table it sits on, transport, or where blocks are stored/fed from that drove the
mechanical design?

**Answer:**
THE PROJECT WE AIMED TO MAKE IT A GOOD SIZE SO IT FITS ON THE TABLE, BUT NOT RLLY SMTH WORTH MENTIONING

## 2.3 Overall System Architecture

**Q2.3.1 [CONFIRM]** Architecture: Raspberry Pi 5 is the sole master (vision,
web server, orchestration, every safety rule); Arduino MEGA 2560 runs the
gantry (X/Y/Z, claw servo, rotation stepper) on its own USB serial link;
Arduino Uno runs the feeder (container servo, belt, alignment servo, 2×
HC-SR04) on a second, independent USB serial link; the two Arduinos never talk
to each other. Correct?

**Answer:**
YES

**Q2.3.2 [NEEDED]** Do you have a system block diagram already, or should one be
drawn for the report? If you have a preferred way to divide the subsystems for
the diagram, say so.

**Answer:**

ADD A PLACEHOLDER, I'LL PREP ONE AND ADD

## 2.4 Mechanical Design

**Q2.4.1 [NEEDED / EVIDENCE]** What are the final overall dimensions of the
machine (L×W×H), and the usable build area? The repo records a **22.8 × 38.0 cm
holder-travel envelope** but also a separately measured **24.3 × 43 cm build
footprint** and (in the now-stale `arduino/README.md`) an older 24.3 × 40 cm
figure. Which numbers are physically true on the final rig, and what is the
difference between "holder travel" and "build footprint" in practice?

**Answer:**
THE TRUE ONE IS THE ONE REPO PUTS, THE STALE IS WRONG

**Q2.4.2 [NEEDED]** Describe how the X/Y gantry is actually built. The BOM lists
6 m of aluminium profile, one 1.5 m × 15 mm linear rail + linear bearing, ~9
GT2 timing pulleys, GT2 belt (≈5 m), 8 castor wheels on 3D-printed carriages.
The firmware confirms a **CoreXY / H-bot kinematic** (two coupled motors: same
direction → X, opposite → Y). Questions:

- Did you keep CoreXY, or is it a plain Cartesian gantry with the belts routed
  differently? (Firmware says CoreXY-style coupling — confirm.) CONFIRMED AS FIRMWARE
- What rides the single 15 mm linear rail (which axis) => ANSWER: Z AXIS, and what do the castor
  wheels + aluminium profile guide (the other axis)? => X/Y AXISES
- How is the moving carriage / arm-holder constructed? => 3D PRINTERD FOR CLAW + THE LINEAR RAIL AND TWO PHYSICAL LIMIT SWITHES
- Roughly how much of the structure is 3D-printed vs profile vs off-the-shelf? THE DEIIGN IS 3D PRINTED + PROFILE, ALL CUSTOM MADE, NTH IS OFF THE SHELF

**Answer:**

**Q2.4.3 [NEEDED]** Describe the **Z axis** mechanism. The firmware says it is a
single NEMA17, ~26.5 cm of travel = ~1350 steps, with a bottom "ground" limit
switch (pin 28) and a top limit switch (pin 29). What converts rotation to
vertical motion — lead screw, belt, rack-and-pinion? What is the pitch? How is
the Z carriage guided?

**Answer:**
NOT SURE WHAT IS THIS QUESTION

**Q2.4.4 [NEEDED]** Describe the **end effector (claw)**. The reference design
used an electromagnet; you use a mechanical gripper driven by one hobby servo
(OPEN 0°, CLOSE 52°) plus a **28BYJ-48 rotation stepper** for 90° claw rotation.
Questions:

- Why a gripper instead of an electromagnet (blocks aren't magnetised / 3D
  shape / stacking)? THE BLOCKS ARE WODDEN AND IT'S GOOD DESIGN
- How is the claw built (3D-printed jaws, linkage, gear)? What does it grip on —
  the block's middle? 3D PRINTERD.
- How does the 28BYJ-48 couple to the claw for rotation? Any slip ring / cable
  management concern? (Firmware notes the claw angle is _not_ sensed.) NOT REALLY.

**Answer:**

**Q2.4.5 [NEEDED]** Describe the **feeder module** physically: the hopper/
container (a servo-driven gate that opens in two stages, 20°→90°→160°), the
conveyor belt (belt sheet + 3D-printed parts + a stepper via A4988), the
alignment servo that nudges the block square, and where the two HC-SR04
ultrasonic sensors sit (one at the container exit, one at the pickup/stage
point). How big is it, how does it mount relative to the gantry, and where is
the fixed pickup point (firmware cell `[0,0]`)?

**Answer:**
IT SITS ON THE LEFT OF THE PROJECT, AND FEEDS TO THE 0,0 BLOCK DIRECTLY, ITS DECENTLY SIZED, BELT LENGTH IS 30CMX 10CMS, CONTAINER IS FITTED FOR THE BLOCK SIZE BUT IT HAS ELEVEATION

**Q2.4.6 [NEEDED]** The blocks: material, exact finish, how many you have, and
how they are coloured/painted (the vision code keys on red-minus-blue/green and
recognises red/orange/yellow/green/blue plus an unpainted "birch"/"oak" default).
Nominal size is 2.2 × 6.0 × 1.5 cm — is that the real measured size and
tolerance?

**Answer:**
NO THE BLOCKS ARE THE DIMENTIOEND MENTIONED AND THEY ARE WOOD
**Q2.4.7 [NEEDED]** What is the build surface / "holder" the blocks are stacked
on? Material, how it's registered to the gantry, how home `[0,0]` is defined
physically.

**Answer:**
THE HOME IS DEFINED PHYSCIALLY BASED ON THE LOCATION OF THE X/Y LIMIT SWITCYHES, THE DIMENTIOSN ARE CORRECT AND BLOCKS MATERIAL SI WOOD

**Q2.4.8 [NEEDED]** Key modifications from the Instructables reference, stated
for the report. The repo confirms these; please confirm/expand each:

- CoreXY X/Y kinematic and limit-switch homing **kept** from the reference.
- V-slot + mini-V-wheels + foamboard replaced with aluminium profile + a
  linear rail + castors + 3D-printed carriages (heavier, larger).
- Electromagnet + magnetised flat chess pieces → **mechanical gripper +
  rotation stepper + 3D wooden blocks**.
- Added a **Z axis** (the reference is 2-axis only).
- Added the whole **feeder/hopper/conveyor** subsystem (the reference has no
  feeder — pieces are already on the board).
- Reed-switch board + 4 multiplexers → **overhead fisheye camera + CV**.
- LCD + arcade buttons → **browser PWA + 3D Studio + digital twin**.
- Arduino Nano → **Arduino MEGA + Arduino Uno + Raspberry Pi 5**.
- 2× A4988 → **3× TB6600 (gantry) + 1× A4988 (feeder belt)**.
- 12 V / 2 A → **12 V / 15 A + LM2596 buck converter**.
- **No chess engine / AI** — human designs the structure.
  Is anything above wrong, and what did I miss?

**Answer:**

**Q2.4.9 [NEEDED]** `REFERENCES.md` says "THE PCB / Cartesian ROBOT X/Y DESIGN
COME DIRECTLY FROM THIS". The reference uses hand-soldered prototyping boards,
not a PCB. Did you make a custom PCB, use perfboard, or wire drivers directly?
What exactly did you take from the reference's electronics?

**Answer:** MAYE PCB IS THE WRONG WORD TO DESCRIVBE THAT, WE TOOK THE X/Y DESIGN AND BUILT UP THE Z PART ON IT

**Q2.4.10 [NEEDED]** Any important mechanical problems during construction and
how you solved them, that aren't in the repo? (The repo documents the **slanted
X rail causing a Y drift of ~0.1 cm per column**, corrected in firmware. Were
there others — belt tension, wheel gap adjustment, Z sag, claw grip force,
racking?)

**Answer:**
THERE WAS OBV ERRORS DUE TO THE CLAW AND ACCURACY, SO WE ADDED C ONSTANT ERROR, THERE WAS ALOS ERRORS / ISSUE DUE TO THE TOOL TISELF AND ITS OFFSETTING, THERE WAS ERRORS TO BLOCK TEXTURE, ETCE TC

## 2.5 Electrical and Control Design

**Q2.5.1 [NEEDED / EVIDENCE]** The power system. BOM: one 12 V / 15 A supply +
one LM2596 buck converter. Please give:

- What runs directly off 12 V (the 3× TB6600 gantry motors? the A4988 belt?).
- The buck converter output voltage(s) and what they feed (servos? sensors?
  logic?). One buck converter or several?
- How the Raspberry Pi 5 is powered (its own USB-C PSU, or off the buck?).
- Whether the two Arduinos are powered over USB from the Pi or separately.
- Common ground arrangement.
- Any fuse, flyback diode, bulk capacitor, or protection ("resistors &
  capacitors assorted" is in the BOM — what for?).

**Answer:**

1. YES CORRECT
2. 5 VOLT AND ITS FOR SERVOS AND SMALL MOTOR FOR ROTATION AND SENSORS [AND ALSO A498 FEEDS OFF IT FOR REFRENCE VOLTAGE]
3. ITS USING ITS ORIGNAL CABEL
4. USINNG THE USB PORT
5. USED FOR THE A498 MOTOR

**Q2.5.2 [NEEDED]** TB6600 / A4988 settings: microstepping, current limit per
driver, and which TB6600 drives which motor (the two CoreXY motors + Z). Decay
mode if you set it.

**Answer:**
?? U HAVE ALL OF THIS IN REPO

**Q2.5.3 [NEEDED]** NEMA17 motor spec (holding torque, rated current, steps/rev)
and whether the feeder belt motor is also a NEMA17 (BOM lists 4× NEMA17; the
gantry firmware drives 3: two CoreXY + Z — is the 4th the belt?). The 28BYJ-48
is the claw-rotation motor via ULN2003 — confirm.

**Answer:**
YES

**Q2.5.4 [NEEDED]** Wiring/build method. The context note mentions cropped
male/male jumpers with heat-shrink for communication wires. How are the motor
and sensor runs made (screw terminals, connectors, soldered)? Is there an
enclosure / cable chain / strain relief?

**Answer:**
CONENCTORS

**Q2.5.5 [CONFIRM]** Control architecture: high-level (Pi) decides _what_ and
_whether_ (target cell, level, mode, all safety gating, the FEED→BUILD
sequencing); low-level (each Arduino) owns _how_ (step generation, homing, limit
enforcement, the servo/stepper timing). The Pi never sends motor steps — it
sends `B col row level` / `FEED id` and the firmware turns those into motion.
Correct?

**Answer:**
YEAH

**Q2.5.6 [CONFIRM]** Firmware↔firmware isolation: there is no wire between the
Mega and the Uno; the Pi is the only thing that couples them, and only a
correlated `@id OK state=block_ready result=staged` from the Uno authorises the
Mega `B`. Correct?

**Answer:**
YES SLAVED DONMT COMMUNICATE

## 2.6 System Workflow

**Q2.6.1 [CONFIRM]** End-to-end flow: (1) human designs the structure in the 3D
Build Studio and compiles it to an ordered list of `B col row level` commands
separated by `R`/`RR` mode latches; (2) for each block the Pi sends `FEED` to
the Uno, which opens the container in two stages, runs the belt, and confirms
the block at the pickup point with the two ultrasonic sensors; (3) on the Uno's
terminal staged-OK the Pi sends `B col row level` to the Mega, which runs its
14-phase pick/rotate/place/park cycle and narrates each phase back over serial;
(4) the overhead camera (optionally) verifies; (5) repeat until the structure
is complete, with the digital twin mirroring progress live. Is this the correct
description, and is the Studio the normal entry point or is single-cell
click-to-build in the console the normal one?

**Answer:**
YES

---

# 3. Hardware and System Implementation

## 3.1 Cartesian Motion System

**Q3.1.1 [NEEDED]** Confirm the final step/cm calibration actually on the rig.
The firmware constants say **X: 4550 steps = 22.8 cm (199.56 steps/cm)**, **Y:
7600 steps = 38.0 cm (200.0 steps/cm)**, Z: 1350 steps ≈ 26.5 cm (50.94
steps/cm). `arduino/README.md` still prints an older **4750 steps / 24.3 cm**
and **8250 / 40 cm** — which is correct on the delivered machine?

**Answer:**
THE NEW ONE OBV, THE OLD ARDUINO README AINT UPDATED PROPERLY

**Q3.1.2 [NEEDED]** Homing hardware: 4 limit switches (X at pin 30, Y at pin 31,
Z-bottom "ground" at pin 28, Z-top at pin 29), all NC wiring per the serial
boot report. Confirm type (micro switch / roller lever), and that homing drives
each axis into its switch, zeroes there, then re-homes X/Y before every move.

**Answer:**
Its micro switch, and yes as the homing thing, home is when we hit x y switches

**Q3.1.3 [EVIDENCE]** Did the X-rail skew (0.1 cm Y per X-column) get
re-measured _after_ the firmware compensation was applied, i.e. is there a
residual? The comp is marked "untested on hardware" in
`docs/X_RAIL_SKEW_COMPENSATION.md` — has it since been flashed and checked?

**Answer:**
BEFORE THE COMPENSATION WAS APPLIED

## 3.2 End-Effector and Manipulation System

**Q3.2.1 [NEEDED]** Grip reliability: does the claw reliably pick a single
staged block and hold it through the ~40 s cycle? Any dropped blocks, crushing,
or mis-grip issues, and how you tuned CLOSE angle / grip force?

**Answer:** NO DROPPING ISSUES

**Q3.2.2 [NEEDED]** Claw rotation: the 28BYJ-48 turns the block 90° CW for the
horizontal grid. Does it repeat accurately with no position sensor? Any drift
over a long run? How do you re-establish "neutral" between sessions (the
firmware trusts the operator to start neutral)?

**Answer:** YES VERY ACCURACE

## 3.3 Processing and Control Hardware

**Q3.3.1 [CONFIRM]** Roles: Pi 5 (8 GB) = vision + FastAPI web server + Studio
serving + orchestration + all safety = master. MEGA 2560 = gantry motion + claw

- rotation + the 14-phase build + the `@`-line ack/step protocol. Uno = feeder
  state machine + dual ultrasonic staging + protocol-2 serial. Correct division?

**Answer:** YES

**Q3.3.2 [NEEDED]** Why a MEGA rather than an Uno/Nano for the gantry — purely
pin count (3 step/dir pairs + 4 limit switches + servo + 4-wire ULN2003 + USB),
or also SRAM/flash headroom? Worth stating the resource figures (sketch uses
~15 % flash, ~26 % SRAM only because of `F()`).

**Answer:** IDK INVENT SMTH ITS WHAT WE HAD LMAO, PLUS TBH WEA RE USING A LOT AND I MEAN A LOT OF PINS, MEGA MAKSES SENSE

## 3.4 Vision System

**Q3.4.1 [CONFIRM]** Camera: DORHEA Raspberry Pi Camera Module, OV5647 sensor,
5 MP, 160° fisheye lens, mounted ≈50 cm above the surface pointing straight
down, captured at 1296×972 (binned, full FOV) via Picamera2. Correct — and is
the mount rigid/fixed, and how is it supported (arm, frame, ceiling)?

**Answer:** SUPPROTED WITH A WOODEN STRUCTURE TO SUPPORT IT, SO A CELLING

**Q3.4.2 [NEEDED / EVIDENCE]** Calibration status on the _real_ rig. The repo
says: lens correction is **estimated, not checkerboard-calibrated**; the camera
has a strong yellow colour cast that needs software colour correction; the
printed-sheet grid calibration currently only confirms ~21–53 of the needed
fiducials on real captures and does **not** produce a calibration; the
placed-block self-calibration is now the primary route but its hardware
verification is still pending. What is the true current state — has _any_
camera→machine calibration been achieved on hardware, by which route, and with
what residual/accuracy?

**Answer:**
THE FINAL ROUTE WAS ACTUALLY BLOCK CALBRATION, BUT TBH IN THE REPORT I WANT TO TAKE ABOUT THE CALBIRATION USING THE PAPER, SO THE LATEST VERSION WE HAVE, AND ASSIME IT WAS SUCEFUL A,D NREALL TAL ABOUT CLOLRO CALBIRATION FISHEEYE CALBIRATION ALLAT

**Q3.4.3 [NEEDED]** Which calibration route do you present as the one you use:
four-clicked-corners, printed A2 colour sheet, evidence-assisted printed sheet,
or placed-block self-calibration? Any others tried and abandoned (the repo also
has a bordered "cluster" sheet, drafted, never printed)?

**Answer:**

## 3.5 Sensors and Feedback

**Q3.5.1 [CONFIRM]** Sensor inventory: 4× limit switches (gantry homing / Z
ends), 2× HC-SR04 ultrasonic (feeder: container-exit confirmation + pickup-point
confirmation, threshold < 10 cm), 1× overhead camera (placement/board vision).
No encoders — all steppers are open-loop. Correct? Any current sensing on the
drivers?

**Answer:** YES

**Q3.5.2 [EVIDENCE]** HC-SR04 performance: did the < 10 cm detection threshold
prove reliable for "block present" at both the exit and stage positions? Any
false positives/negatives, and did you have to tune `DETECT_DISTANCE_CM` or the
sensor placement? YES

**Answer:**

## 3.6 Power and Safety

**Q3.6.1 [NEEDED]** Full power budget: peak current draw, whether the 15 A
supply headroom is adequate, and what happens on brown-out.

**Answer:** IDK BUT ITS VERY ADAQUATE

**Q3.6.2 [CONFIRM]** Safety mechanisms that exist: software limit switches +
hardware limit switches on every axis end; per-move soft-limit checks; the
session-lock-on-uncertainty model; feeder refuses a second block while the
stage is occupied; one-command-at-a-time. Safety mechanisms that **do not**
exist and are acknowledged gaps: no hardwired emergency stop, no safety relay /
contactor, no watchdog, no way to interrupt an in-flight Mega motion in
software, no cover/interlock. Is this the honest safety picture you want in the
report, and is there any physical power switch / plug-pull procedure you rely
on?

**Answer:**

**Q3.6.3 [NEEDED]** Electrical protection actually fitted: fuse rating, flyback
diodes on the servos/relays, decoupling capacitors, reverse-polarity
protection. (BOM: "Resistors & Capacitors (assorted) — 1 lot".)

**Answer:** NO

## 3.7 System Integration

**Q3.7.1 [EVIDENCE]** Do you have a final wiring diagram and a pin-map table for
_both_ Arduinos? (The firmware source has all pins; a clean drawn diagram is
what the appendix needs — confirm you can produce one or want it built from the
source.)

**Answer:**
I'LL CREATE ONE, ADD A PLACEHOLDER

**Q3.7.2 [NEEDED]** How are the three controllers physically connected and
mounted in the final build — both Arduinos on USB to the Pi, Pi location, cable
routing, where the electronics live relative to the moving gantry?

**Answer:**
YES

---

# 4. Control and System Operation

## 4.1 Control Methodology

**Q4.1.1 [CONFIRM]** Control is hierarchical and entirely open-loop at the motor
level (no encoders; steppers trusted, re-homed often to prevent accumulation);
"closed-loop" in this project means _sensor- and vision-confirmed sequencing_
(ultrasonic staging, camera verification, the acknowledged phase protocol), not
servo position control. Correct framing?

**Answer:**
YES

## 4.2 Motion Control

**Q4.2.1 [CONFIRM]** Movement: fixed-period step pulse loops, no acceleration
ramp (which is why the firmware can predict Z-move duration exactly and send it
as `ms=`); `G col row` = go to a cell centre (both axes always move, Y then X,
after a re-home); `B col row level` = the full 14-phase build; `0` = home X/Y;
`0+` = full reset incl. Z. Correct?

**Answer:**
YES

**Q4.2.2 [NEEDED]** Any motion tuning results worth reporting — max reliable
step rate before lost steps on X/Y and on the loaded Z, why STEP_DELAY ended up
where it is (git history shows several retunes)?
?? NOT RLLY IDC

**Answer:**

## 4.3 Vision and Positioning

**Q4.3.1 [CONFIRM]** Pixel→cell pipeline: capture → frame orientation → colour
correction → fisheye undistortion → block detection (warm-colour segmentation +
contour decomposition, with touching-block splitting) → homography from a saved
`workspace_map.json` maps camera pixels → physical cm → `[col,row]`. The Pi
picks the cell; the firmware alone turns a cell into safe step targets. Correct?

**Answer:**
? NOT SURE, READ THE CODE?

**Q4.3.2 [EVIDENCE]** Detection accuracy actually measured: on the reference
board the docs quote 29/29 blocks found, lattice snap ≤ 0.08–0.34 cells, mean
residual ~0.85–1.25 px (~0.27 cm on a 2.2 cm block for a four-corner map). Are
these the numbers you'll cite, and were they reproduced on a _live_ camera
frame or only on the saved reference captures?

**Answer:**
READ THE CODE AND DOCS, RELY ON THEM

## 4.4 Main System Operation

**Q4.4.1 [EVIDENCE]** Has the **full** feed→place operation (Uno FEED → staged
OK → Mega B → PLACED) ever run end-to-end on hardware? The repo says the feeder
firmware + Pi client + orchestrator are built and **mock-tested only**, physical
feeder commissioning still required. If it has run, describe the result. If not,
say so plainly for the report.

**Answer:**
WE ACTUALLY HAVE A FILE IN LOGS, USE IT

**Q4.4.2 [EVIDENCE]** The `logs/serial.log` / `logs/build.log` in the repo
contain 16 successful `PLACED` builds on 2026-09-03 with `mock=False`, full
`@0 BOOT` / `@0 READY` / `@n STEP` / `@n OK` output, ~20–32 s each, vertical
mode, level 0, direct `B` (no feeder). **Confirm these are genuine hardware
runs of the gantry** (this contradicts several docs that say the `@`-ack/STEP
firmware was "never flashed" — see readiness notes). What firmware version is
currently on the Mega and the Uno?

**Answer:**
THEY ARE ONLY FOR THE BUILD PROCESS ON MEGA CURRENTLY, BUT ITS SUPER USEFUL

**Q4.4.3 [EVIDENCE]** Largest / most complex structure the rig has actually
built. How many blocks, how many levels, which mode(s), did it complete, and
how long did it take? Any photos?

**Answer:**
IDK APPROXIMATE THE TIMING, BUT IT BULT VERY COMPELX STRUVCUTRE WITH GRID SHIFTS AND HORZIAPOTNML / VERTICAL ON MAX LEVEL AND SHI

## 4.5 Additional Operating Modes

**Q4.5.1 [CONFIRM]** Additional modes that exist: (a) browser **click-to-build**
single-cell console; (b) the **3D Build Studio** — design, physics validation
(support/collision/toppling), compile to a program, dry-run, STEP/RUN execution
with a Markdown run report; (c) the **live digital twin** beside the camera;
(d) **`--mock`** full simulation with no hardware; (e) direct serial
commissioning consoles (`rig_console.py`, `feeder_console.py`) and standalone
calibration tools. Correct list — anything to add or demote?

**Answer:**
U CONFIRM
**Q4.5.2 [NEEDED]** Was the Studio → compile → twin → real build loop
demonstrated working end-to-end (against real hardware, or only against
`--mock`)? This is described as the flagship demo.

**Answer:**
YES WORKS 100%

---

# 5. Testing, Results and Discussion

## 5.1 Testing Methodology

**Q5.1.1 [NEEDED]** How did you test overall? The repo has: ~554 automated
software tests (492 web + ~62 Python protocol/web), plain-assert firmware
harnesses (g++ stub, no AVR), `--mock` end-to-end runs, and hardware bring-up
on the rig. Describe your test process in report terms — bench tests per
subsystem, then integration, then full runs — and the conditions (lighting for
the camera, etc.).

**Answer:**
USE MOCJK TESTS REAL TETRS AND LOGS TO FIND THEM

**Q5.1.2 [NEEDED]** What were your pass/fail criteria for each subsystem?

**Answer:**

## 5.2 Motion System Testing

**Q5.2.1 [EVIDENCE]** Positioning accuracy and repeatability results for X, Y,
Z. How did you measure them (calipers to a placed block? repeated `G` to a
cell with a dial indicator?), how many trials, and what were the numbers
before and after the X-rail skew compensation?

**Answer:**
USE LOGS

**Q5.2.2 [EVIDENCE]** Homing repeatability — does the rig return to the same
origin every time? Any lost-step events observed over long runs?

**Answer:**
USE LOGS

## 5.3 Manipulation Testing

**Q5.3.1 [EVIDENCE]** Pick-and-place success rate: out of N attempts, how many
blocks were gripped, carried, and released on the correct cell? Failure modes
seen (missed grip, block rotated, knocked a neighbour, placed short/high on a
stack)?

**Answer:**

**Q5.3.2 [EVIDENCE]** Stacking: highest level successfully stacked, and how
placement accuracy / stability degrades with height. Did the +0.10 cm fixed Z
margin at levels ≥1 work?

**Answer:**

## 5.4 Vision System Testing

**Q5.4.1 [EVIDENCE]** Block-detection results on live frames: detection rate,
false detections (rails, holder offcuts), colour-ID accuracy, and how lighting
affected it. Anything measured beyond the saved reference-board numbers?

**Answer:**

**Q5.4.2 [EVIDENCE]** Calibration results on hardware: which route, the residual
/ reprojection error achieved, and whether a placed block then landed where the
overlay predicted. If calibration on the real rig never fully succeeded, state
that and what blocked it (colour cast / framing / fisheye).

**Answer:**

## 5.5 Sensor Testing

**Q5.5.1 [EVIDENCE]** Ultrasonic sensor calibration and stability: measured
distance vs actual for a staged block, detection consistency over many feeds,
and any environmental sensitivity (belt vibration, angled block face).

**Answer:**

**Q5.5.2 [EVIDENCE]** Limit switch reliability: any bounce, missed trips, or
false triggers, and whether the 200 µs confirm time was enough.

**Answer:**

## 5.6 Integrated System Testing

**Q5.6.1 [EVIDENCE]** Full-system runs: how many complete structures were built
end-to-end, success rate, total time, and where failures occurred in the chain
(feed / pick / place / verify). Include at least one successful run and one
failed run with what went wrong.

**Answer:**

**Q5.6.2 [EVIDENCE]** Did the digital twin / run report stay in sync with the
real build during integrated runs?

**Answer:**

---

## FOR ALL TESTING ONES, USE THE LOGS AND ACTUAL TESTS, AND TBH, U CAN PUT PALCEHOLDER NUMBERS THAT I CAN FILL, SO WHENVER A NMUBMERISDNT CLEAR, PUT A PLACEGHOLDER AND ID FILL IT

## 5.7 Challenges and Limitations

**Q5.7.1 [NEEDED]** The biggest problems you hit and how you solved (or didn't)
each. The repo documents: the slanted X rail (Y drift, firmware-compensated);
the camera colour cast breaking green-ink detection (added software colour
correction); the estimated-not-calibrated lens; printed-sheet calibration
failing on the real camera (moved to placed-block calibration); the Mega going
deaf during a build (accepted; no cancel); no EEPROM / port-open reset (re-push
mode+grid on connect). What else — mechanical, electrical, timing, integration?

**Answer:**
USE R

**Q5.7.2 [CONFIRM]** Remaining limitations to state honestly: no hardware
E-stop / no interruptible motion / no watchdog; steppers are open-loop, a
mechanical stall is not detected; feeder physical commissioning incomplete;
camera lens not metrically calibrated; placement supervision (vision verifying
each placement / spotting human interference) is **designed but not
implemented**; claw angle is not sensed; the Mega doesn't correlate `B` to a
Pi-supplied id; Studio "wow pass" (camera plan-projection, time-lapse, audio,
instruction sheet) not built. Anything to add or remove?

**Answer:**

## USE REPO FOR THAT

# 6. Conclusion and Future Work

## 6.1 Conclusion

**Q6.1.1 [NEEDED]** Your summary of what was achieved against the objectives in
Q1.3 — which were fully met, partly met, not met, and your overall assessment of
the project outcome.

**Answer:**

## 6.2 Future Work

**Q6.2.1 [CONFIRM]** Future work already scoped in the repo: implement placement
supervision (the `PlacementLedger` + `Supervisor` design, incl. a firmware
`P col row level` retrieve-from-cell verb); complete feeder commissioning;
proper checkerboard/ChArUco lens calibration; a hardwired emergency-stop and a
comms watchdog; the Studio M8 "wow pass" (plan projection on the live camera,
time-lapse export, instruction-sheet export, audio cues); Pi-supplied command
IDs and removing the prose fallback. Which of these do you want to feature, and
what would _you_ add (closed-loop steppers, colour-sorting feeder, larger
workspace, faster serial link)?

**Answer:**

## USE REPO FOR BOTH AS WELL, AND INVENT / DEDUCE

# Appendices

**QA.1 [EVIDENCE]** Confirm you can supply for the appendix: (a) full wiring
diagram, (b) pin-mapping tables for both Arduinos, (c) the final Bill of
Materials — is `docs/Bill_of_Materials.md` complete, or is it missing the Pi
PSU, camera mount, wiring/connectors, enclosure, the build surface, and the
blocks themselves? (d) mechanical drawings / CAD, (e) any measured data tables
(accuracy, cycle time, calibration residuals), (f) representative photos.

**Answer:**

**QA.2 [NEEDED]** Is there a CAD model or are there fabrication drawings for the
3D-printed parts (claw, carriages, feeder parts, camera mount)? Where do they
live?

**Answer:**

**QA.3 [NEEDED]** Any external code/libraries to credit beyond the obvious
(FastAPI, React, three.js, OpenCV, Picamera2, pyserial, Arduino Servo/Stepper)?
The reference project's chess AI (Micro-Max) is **not** used here — confirm.

**Answer:**

**QA.4 [NEEDED]** Reference list: besides the Instructables "Automated
Chessboard" (Greg06, 2022), what other sources do you want cited — datasheets
(OV5647, HC-SR04, TB6600, A4988, ULN2003, 28BYJ-48, NEMA17, LM2596), CoreXY
references, any papers on vision-guided pick-and-place, OpenCV fisheye docs?
List anything you leaned on.

**Answer:**
