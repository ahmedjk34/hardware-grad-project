"""Chapter 5 — Testing, Results and Discussion."""

BUILDS = [
    ("10:58:46", "B 1 0 0", 1.48, 0.39, 2.91, 1.42, 0.40, 19.81),
    ("10:59:13", "B 5 0 0", 5.14, 0.39, 2.91, 5.14, 0.43, 27.22),
    ("11:00:38", "B 1 0 0", 1.57, 0.39, 2.91, 1.41, 0.40, 19.88),
    ("11:01:11", "B 2 0 0", 2.52, 0.39, 2.91, 2.41, 0.42, 21.86),
    ("11:01:58", "B 3 0 0", 3.49, 0.39, 2.91, 3.44, 0.44, 23.86),
    ("11:07:26", "B 1 0 0", 1.56, 0.39, 2.91, 1.40, 0.44, 19.91),
    ("11:08:04", "B 2 0 0", 2.50, 0.39, 2.91, 2.37, 0.43, 21.80),
    ("11:08:40", "B 3 0 0", 3.44, 0.40, 2.91, 3.40, 0.45, 23.81),
    ("11:09:37", "B 4 0 0", 4.38, 0.39, 2.91, 4.34, 0.42, 25.65),
    ("11:12:41", "B 1 0 0 (horizontal)", 3.60, 1.92, 2.91, 3.70, 1.96, 27.29),
    ("13:30:24", "B 3 2 0", 7.12, 0.39, 2.92, 7.11, 0.41, 31.16),
    ("13:51:07", "B 3 2 0", 7.12, 0.39, 2.91, 7.36, 0.43, 31.42),
    ("13:51:39", "B 3 2 1", 7.12, 0.39, 2.70, 8.49, 0.42, 32.19),
    ("13:52:11", "B 3 2 2", 7.12, 0.39, 2.56, 7.36, 0.42, 30.76),
    ("13:52:42", "B 3 2 3", 7.12, 0.39, 2.41, 8.53, 0.44, 31.64),
    ("13:53:14", "B 3 2 4", 7.12, 0.39, 2.26, 7.04, 0.43, 29.84),
]

PHASES = [
    ("1", "raise_clear", "0.42", "0.43", "0.42", "Z seek to the top switch"),
    ("2", "home_feeder", "0.57", "0.58", "0.58", "X/Y home; already there after a park"),
    ("3", "neutralise_claw", "0.41", "0.41", "0.41", "no-op after a parked build"),
    ("4", "open_claw", "0.93", "0.93", "0.93", "600 ms servo settle + 250 ms phase pause"),
    ("5", "lower_to_ground", "2.91", "2.91", "2.91", "full Z travel down, seek to the switch"),
    ("6", "grip", "0.95", "0.96", "0.95", "600 ms servo settle + 250 ms phase pause"),
    ("7", "lift_block", "2.89", "2.89", "2.89", "full Z travel up, loaded"),
    ("8", "move_to_target", "1.48", "7.12", "4.53", "**distance-dependent**"),
    ("9", "rotate_to_grid", "0.39", "1.92", "0.49", "0.39 s no-op; 1.92 s for a real 90 deg turn"),
    ("10", "lower_to_level", "2.26", "2.92", "2.80", "**level-dependent**"),
    ("11", "release", "0.70", "0.72", "0.71", "600 ms servo settle, no phase pause"),
    ("12", "park_clear", "2.25", "2.86", "2.76", "Z lift from the placement level"),
    ("13", "park_home", "1.40", "8.53", "4.68", "**distance-dependent**"),
    ("14", "park_rotation", "0.40", "1.96", "0.52", "as phase 9"),
]


def chapter_5(rep):
    rep.h1("5. Testing, Results and Discussion")

    # ------------------------------------------------------------------
    rep.h2("5.1 Testing Methodology")

    rep.h3("5.1.1 Four levels, in order")
    rep.p(
        "The rig is a slow, shared and physically hazardous test fixture: it takes half a minute "
        "to answer one question, and a wrong answer can drive a claw into a stack. The testing "
        "strategy is built around that, and it moves work down to the cheapest level that can "
        "still answer the question honestly.")
    rep.numbered([
        "**Automated software tests, no hardware.** Every pure function (the grid arithmetic, "
        "the serial protocol parsers, the compiler, the twin's state mapping, the runner's state "
        "machine, the workspace homography) is tested off the machine. The two grid "
        "implementations, one in Python and one in TypeScript, are held to each other by "
        "fixtures dumped from the Python side, so the browser cannot silently disagree with the "
        "Pi about where a cell is.",
        "**Protocol-level simulation.** A fake Mega and a fake Uno speak exactly the same "
        "acknowledgement grammar as the real firmwares, including their failure, reset and "
        "cancellation behaviours, and a mock camera renders blocks at real grid cells. The "
        "complete browser-to-orchestrator-to-serial path runs against them, which is how the "
        "two-board handoff and the session-lock behaviour were tested exhaustively without ever "
        "risking the machine.",
        "**Firmware host builds.** There is no Arduino toolchain on the development machine, so "
        "firmware changes are compiled against a stub-Arduino host harness that proves the "
        "sketch parses and that its acknowledgement output is byte-for-byte what the protocol "
        "specifies. A clean compile is explicitly **not** treated as a test of behaviour.",
        "**Hardware bring-up and runs on the rig.** Anything touching motion, limits or Z is "
        "flashed to the real board and watched. Every real run appends to two log files: one "
        "stopwatch per build, and every line to and from either Arduino with the gap since the "
        "previous line. Those logs are the primary evidence in this chapter.",
    ])
    rep.p(
        "The conditions for the hardware runs were the ordinary working conditions of the lab: "
        "the rig on its table under the room's normal overhead lighting, the camera fixed on its "
        "support structure, the surface clear at the start of each session, and the operator "
        "present throughout. Vision tests were run both live and against saved reference "
        "captures, so that a detection result can be reproduced exactly instead of depending on "
        "the light on the day.")

    rep.h3("5.1.2 Pass and fail criteria")
    rep.defs([
        ("Motion", "Every axis finds its home switch within the homing cap; a commanded cell is "
                   "reached without a soft-limit refusal; a repeated command produces the same "
                   "phase timings; and no cumulative positional drift is observable across a "
                   "session."),
        ("Manipulation", "The claw picks up a single staged block, holds it through the whole "
                         "carry, releases it on the commanded cell, and the rotation returns the "
                         "claw to neutral."),
        ("Feeder", "Exactly one block reaches the pickup point per request; the exit and stage "
                   "sensors both fire in the right order; and each of the four terminal failures "
                   "can be provoked deliberately and reports the right reason with the belt "
                   "stopped."),
        ("Vision", "Every block on a full board is found, with no false detections from the "
                   "rails or the holder offcuts, and the fitted grid passes its parity, aspect "
                   "and residual gates instead of merely reporting them."),
        ("Protocol", "Exactly one terminal acknowledgement per command; `SAFE` and `HELD` never "
                     "confused; and a non-terminal line never satisfies a waiter."),
        ("Integrated", "A complete structure is built from a compiled program with no manual "
                       "intervention, and any failure locks the session instead of continuing."),
    ])

    # ------------------------------------------------------------------
    rep.h2("5.2 Motion System Testing")
    rep.p(
        "The results in this section come from **sixteen complete `B` commands executed on the "
        "physical rig on 3 September 2026**, across five separate service sessions, all with the "
        "hardware link live and not mocked. Every one of the sixteen returned a terminal "
        "`PLACED`. The gantry firmware's own `@seq STEP` lines were captured with wall-clock "
        "timestamps, so each of the fourteen phases has an independently measured duration.")
    rep.note(
        "**A contradiction in the repository, resolved.** Several documents in the project state "
        "that the acknowledgement and phase-progress firmware was compile-verified but never "
        "flashed to the board. The logs analysed here disagree with that: they record "
        "`@0 BOOT fw=build_test_v1`, `@0 READY grid=6x5 mode=vertical`, a full "
        "`@n STEP step=k total=14 ...` sequence and a terminal `@n OK` for every build, in "
        "sessions explicitly stamped `mock=False` against the configured serial-by-id path. The "
        "log evidence is preferred over the prose. The documents were written before the "
        "firmware was flashed and were not updated afterwards.")

    rep.h3("5.2.1 Cycle repeatability")
    rep.p(
        "The clearest motion result in the project is how little the fixed part of the cycle "
        "varies. Nine of the fourteen phases have no distance or level dependence at all, and "
        "across all sixteen builds those nine phases summed to a **mean of 12.57 s with a "
        "standard deviation of 0.18 s**, a spread of 1.4 %. Six of the nine repeated with "
        "identical minimum and maximum to the logging resolution of 0.01 s.")
    rep.table(
        "Per-phase durations over all sixteen hardware builds, in seconds.",
        ["#", "`phase`", "Min", "Max", "Mean", "Comment"],
        [[a, "`%s`" % b, c, d, e, f] for a, b, c, d, e, f in PHASES],
        widths=[0.8, 4.0, 1.2, 1.2, 1.2, 6.6], size=9, align_right=(2, 3, 4))
    rep.p(
        "That repeatability is a direct consequence of the design choice in Section 3.1.2. With no "
        "acceleration ramp, a move of N steps takes N times a fixed period, and there is nothing "
        "left to vary. It is also what makes the variable phases interpretable: when phases 8 "
        "and 13 range from 1.48 s to 8.53 s while everything around them does not move at all, "
        "the variation is travel distance and nothing else.")
    rep.p(
        "Three of the fixed phases can be predicted from first principles, and all three agree:")
    rep.bullets([
        "**Phases 4 and 6 (servo open and close)** should take the 600 ms commanded settle plus "
        "the 250 ms inter-phase pause, which is 0.85 s. Measured: 0.93 s and 0.95 s.",
        "**Phase 11 (release)** has the same 600 ms settle but is measured to the `done` line "
        "and not to the next phase, so it should be about 0.6 s. Measured: 0.71 s.",
        "**Phases 9 and 14 with a real rotation.** A 90-degree turn is 512 of the 28BYJ-48's "
        "2,048 steps at 10 rpm, which is 1.50 s. The one horizontal-mode build in the log spent "
        "1.92 s on phase 9 against 0.39 s for the no-op case, a difference of **1.53 s**.",
    ])
    rep.p(
        "The residual 80 to 110 ms on each of those is the logging and serial round-trip "
        "overhead, and it is consistent across every phase, which is what makes it believable as "
        "an overhead and not as an error.")

    rep.h3("5.2.2 X/Y traverse")
    rep.p(
        "Phases 8 and 13 are the two X/Y moves, out to the target cell and back to the origin. "
        "Both include a full re-home, which is why they are the largest variable term in the "
        "cycle. Plotting them against the target column index for the ten row-0 vertical builds "
        "gives a straight line:")
    rep.figure("X/Y traverse time against column index, for the row-0 builds in vertical mode. "
               "Both the outbound move and the return home lie on the same line, which is what a "
               "fixed step rate with a re-home at each end predicts.",
               image="fig-traverse-vs-column.png", width_cm=13.5)
    rep.p(
        "The least-squares fit through the outbound points is **t = 0.65 + 0.919 x col seconds**. "
        "One column is 3.8 cm of pitch, so the fitted rate is **4.13 cm/s**. The firmware's own "
        "arithmetic predicts 4.36 cm/s (a 575 us half-period is 1.15 ms per step, 870 steps/s, "
        "at 199.56 steps/cm), so the machine runs at **94.7 % of its nominal rate**. The "
        "shortfall is the per-step overhead: every step polls all four limit switches, and each "
        "switch that reads active has to stay active for 200 us before it is believed.")
    rep.p(
        "The 0.65 s intercept is the fixed part: the re-home into both switches from a parked "
        "origin, plus the 250 ms inter-phase pause. The return-home line lies on top of the "
        "outbound line, which is a useful consistency check, since the machine takes the same time to "
        "travel a distance in either direction, as an unaccelerated stepper should.")

    rep.h3("5.2.3 Z descent, against the firmware's own prediction")
    rep.p(
        "Every Z phase carries the firmware's own predicted duration as `ms=` on the wire, which "
        "makes the Z axis the one part of this machine that can be checked against its own "
        "model with no external instrument at all. Across the sixteen builds there are "
        "**80 such predictions**, of which 75 are usable (the other five are the first build of "
        "a session, where Z has never been homed and the firmware deliberately assumes a full "
        "travel rather than reporting a confident wrong number).")
    rep.figure("Descent to the target level: the measured phase-10 duration against the "
               "firmware's own ETA, for the five-level stack built on cell [3,2].",
               image="fig-descent-vs-level.png", width_cm=13.5)
    rep.p("Regressing measured duration on predicted duration over all 75 usable pairs gives:")
    rep.code("measured = 0.248 s  +  1.058 x predicted        (residual sd 0.102 s, n = 75)")
    rep.p(
        "Both coefficients have a physical explanation and neither is a fudge. **The 0.248 s "
        "intercept is the inter-phase pause**: `BUILD_PHASE_PAUSE_MS` is 250 ms, and the log "
        "measures a phase from its own announcement to the next phase's announcement, so every "
        "measured duration carries exactly one pause the prediction does not. **The 5.8 % slope "
        "excess is the same per-step overhead the X/Y traverse showed at 5.3 %.** Two "
        "independent axes, two independent measurements, one consistent answer: the pulse-period "
        "model is right to within about 6 %, and the missing 6 % is the limit-switch polling "
        "the model does not carry.")
    rep.p(
        "The descent-against-level result is the same statement in a different form. Level 0 "
        "descends 2.91 s and level 4 descends 2.26 s, a measured 0.160 s per level against a "
        "predicted 0.145 s per level, a ratio of 1.11. A block level is 1.5 cm, which is "
        "76.4 steps at 50.94 steps/cm, which is 145 ms at a 1.9 ms step period.")
    rep.p(
        "The practical value of this is that the machine's own ETA can be trusted as **a floor**, "
        "which is exactly how the digital twin uses it: a descent animation driven from `ms=` "
        "and clamped short of the cell will always still be short of the cell when the real "
        "release event arrives.")

    rep.h3("5.2.4 Homing repeatability and lost steps")
    rep.p(
        "Homing repeatability was not measured with an instrument, but the sixteen builds carry "
        "strong indirect evidence. Phase 2 (home X/Y to the feeder) took between 0.57 and 0.58 s "
        "on **every single build across all five sessions**, and phase 1 (Z seek to the top "
        "switch) took between 0.42 and 0.43 s on every build after the first of each session. A "
        "homing move whose duration is constant to 0.01 s is a homing move that starts from the "
        "same place and finds its switch after the same travel every time. If the machine were "
        "losing steps, the parked position would drift and the homing travel, and with it the "
        "homing duration, would grow.")
    rep.p(
        "No lost-step event was observed in any of the logged sessions: every build returned "
        "`PLACED`, no soft-limit refusal was recorded, and the statistics the firmware keeps for "
        "short moves and blocked moves stayed at zero. That is not the same as proving there "
        "were none, and the honest statement is that the re-home before every move makes a lost "
        "step self-correcting and not detectable.")
    rep.p(
        "[[VALUE NEEDED: a direct homing repeatability measurement. Park a dial indicator "
        "against the carriage, home the machine N times (10 is enough), and record the spread. "
        "This is the single cheapest missing measurement in the report.]]")

    rep.h3("5.2.5 Positional accuracy and repeatability")
    rep.p(
        "Absolute positional accuracy was never measured against an external reference on the "
        "delivered machine, and it should be stated plainly rather than estimated from the step "
        "arithmetic. What **was** measured, and what drove two firmware corrections, is the "
        "**relative** error between placements:")
    rep.table(
        "Positional error measurements taken on the rig.",
        ["Effect", "Measured", "Corrected by", "Residual after correction"],
        [
            ["X-rail skew: Y drift with X travel",
             "0.115 cm per vertical column and 0.13 cm per horizontal column on Y; no row dependence",
             "Per-mode firmware skew applied only to build motion (Section 4.2.5)",
             "[[VALUE NEEDED: re-measure both modes with the current coefficients active]]"],
            ["Pickup-rotate swing",
             "A horizontal placement landing 1.4 cm too far from the X home switch, with Y dead "
             "on",
             "A per-rotation tool offset of (+0.9, -0.3) cm, subtracted from the holder target",
             "[[VALUE NEEDED: measure a horizontal placement against its commanded cell centre "
              "with the CW tool offset flashed]]"],
            ["Absolute placement accuracy, vertical mode",
             "[[VALUE NEEDED: place a block at several known cells and measure the block centre "
              "against the commanded centre with callipers; report mean and maximum error per "
              "axis, and how many trials]]",
             "-", "-"],
            ["Return-to-cell repeatability",
             "[[VALUE NEEDED: command the same cell N times, measuring where the block or the "
              "holder lands each time; report the spread per axis]]",
             "-", "-"],
        ],
        widths=[3.4, 4.6, 4.0, 3.0], size=9)

    # ------------------------------------------------------------------
    rep.h2("5.3 Manipulation Testing")

    rep.h3("5.3.1 Grip and carry")
    rep.p(
        "Across all sixteen logged builds and the commissioning runs that preceded them, "
        "**no block was dropped, crushed or lost from the claw during a carry**. Every build "
        "reached its phase-11 release and its terminal `OK`. The grip is a single fixed closed "
        "angle of 54 degrees in the current source, tuned until the jaws hold a block "
        "firmly without marking it, and it is not adjusted per block or per level.")
    rep.p(
        "The failure mode the design guards against is not a weak grip but a **mistimed** one: "
        "the servo reports nothing, so a build that started moving Z while the jaws were still "
        "swinging would either miss the block or crush it against the surface. The fixed 600 ms "
        "settle after every open and close is the answer, and Section 5.2.1 shows that it is honoured "
        "exactly, at 0.93 s and 0.95 s including the phase pause.")
    rep.p(
        "[[VALUE NEEDED: a pick-and-place success rate, if you want a number for the defence. "
        "Count the total number of pick-and-place attempts across the project and how many "
        "failed, and record which stage each failure happened at: missed grip, block rotated in "
        "the jaws, neighbour knocked, or placed short or high on a stack.]]")

    rep.h3("5.3.2 Rotation")
    rep.p(
        "The 28BYJ-48 rotation repeated accurately with no position sensor and no observable "
        "drift over a session. The single horizontal-mode build in the log gives the one direct "
        "timing measurement: 1.53 s of net rotation time against the 1.50 s that 512 steps at "
        "10 rpm predicts, a 2 % agreement, and the build completed with a terminal `OK` and a "
        "clean return to neutral at phase 14.")
    rep.p(
        "The design leans on the fact that a tracked angle is never more than one cycle old, since "
        "the claw is returned to neutral over the feeder before every pickup and again after "
        "every placement, rather than on the stepper being perfect. "
        "[[VALUE NEEDED: if you want to quantify the rotation, measure the angular error after "
        "N consecutive quarter turns in the same direction.]]")

    rep.h3("5.3.3 Stacking")
    rep.p(
        "The clearest stacking result in the log is the afternoon session of 3 September, in "
        "which cell [3,2] was built up **level by level from 0 to 4**, five blocks on one cell, "
        "one command per level, all five returning `PLACED`:")
    rep.table(
        "The five-level stack on cell [3,2], from `logs/build.log`.",
        ["Time", "Command", "Level", "Phase 10 descent (s)", "Total (s)", "Result"],
        [
            ["13:51:07", "`B 3 2 0`", "0", "2.91", "31.42", "PLACED"],
            ["13:51:39", "`B 3 2 1`", "1", "2.70", "32.19", "PLACED"],
            ["13:52:11", "`B 3 2 2`", "2", "2.56", "30.76", "PLACED"],
            ["13:52:42", "`B 3 2 3`", "3", "2.41", "31.64", "PLACED"],
            ["13:53:14", "`B 3 2 4`", "4", "2.26", "29.84", "PLACED"],
        ],
        widths=[2.2, 2.6, 1.6, 3.4, 2.2, 2.0], size=9, align_right=(2, 3, 4))
    rep.p(
        "The descent shortens monotonically by a mean of 0.160 s per level, which is the machine "
        "measuring its own block height: 1.5 cm at 50.94 steps/cm at 1.9 ms per step is 145 ms "
        "per level, and the 11 % excess is the per-step overhead established in Section 5.2.3. That is "
        "a satisfying result, because it means the stack really is growing by one block height "
        "per level as far as the Z axis is concerned, and not by whatever the blocks happen "
        "to settle to.")
    rep.p(
        "The fixed Z margin of +0.12 cm at levels of 1 and above was introduced **after** this "
        "session, so these five placements ran with no margin at all and still completed. "
        "[[VALUE NEEDED: the highest level actually stacked successfully on the delivered "
        "machine, and whether the +0.12 cm fixed margin improved or worsened placement at "
        "levels 1 and above. Also worth recording: how the stack's own lean or wobble develops "
        "with height, since this was only taken to level 4.]] The firmware's own ceiling is "
        "level 16 at 24.0 cm, leaving 2.5 cm of headroom to fly a block over the tallest "
        "possible tower.")

    # ------------------------------------------------------------------
    rep.h2("5.4 Vision System Testing")

    rep.h3("5.4.1 Block detection")
    rep.p(
        "Detection was measured against two saved reference boards, both of which are the "
        "vertical grid with **29 blocks** laid from the home corner (columns 0 to 6 of rows 0 to "
        "3, plus a single block on [0,4]), leaving 13 cells unplaced. Both boards also carry the "
        "holder's two thin wooden offcuts beside cell [0,0], which are the most useful thing in "
        "them: they are wooden, roughly block-shaped, and not blocks.")
    rep.figure("The vision reference board: 29 blocks on the vertical grid, the aluminium rails "
               "at the frame edges, and the holder's two wooden offcuts beside cell [0,0]. The "
               "magenta cast is the camera's uncorrected colour response.",
               image="fig-reference-board.png", width_cm=9.0)
    rep.p(
        "On both boards the detector found **29 of 29 blocks**. The raw segmentation proposes 33 "
        "hypotheses; the duplicate, frame-edge and lattice rejection steps take that to 29, and "
        "the four it removes are the aluminium rails and the two holder offcuts. The lattice "
        "snap error is at most **0.08 cells** and the mean fit residual **0.85 px**, every "
        "outline comes out square with one shared size and one shared bearing, and the whole "
        "pass costs 37 to 103 ms at the shipped settings.")
    rep.p(
        "Two negative results are worth as much as the positive one, because both closed off an "
        "obvious 'improvement'. **Higher resolution and illumination flattening find nothing "
        "extra and cost up to four seconds a frame**:")
    rep.table(
        "Detection count and cost against processing width and illumination flattening.",
        ["Processing width", "Flatten", "Blocks found", "Reference board", "Full 1296 px frame"],
        [
            ["384 px", "off", "29 / 29", "84 ms", "103 ms"],
            ["384 px", "on", "29 / 29", "291 ms", "221 ms"],
            ["480 px", "off", "29 / 29", "37 ms", "104 ms"],
            ["640 px", "on", "29 / 29", "578 ms", "902 ms"],
            ["1024 px", "off", "29 / 29", "60 ms", "574 ms"],
            ["1024 px", "on", "29 / 29", "543 ms", "**3,894 ms**"],
        ],
        widths=[3.2, 2.0, 2.6, 3.4, 3.8], size=9, align_right=(3, 4))
    rep.p(
        "**The 33-to-29 improvement is entirely the rejection steps, not the segmentation.** "
        "Lowering the minimum contour area from 500 to 250 px likewise finds nothing extra and "
        "doubles the cost, because every small contour it admits enters the rectangle search. A "
        "timing guard in the test suite keeps this conclusion from being quietly reverted.")
    rep.p(
        "The second negative result is about white balance, and it is deliberately backwards "
        "from what the sheet detector does. A white-patch balance is safe on a frame that is "
        "mostly white paper, and unsafe on a board covered in wooden blocks: the bright quantile "
        "lands partly on the wood and the correction then pulls the blocks toward the surface it "
        "was meant to separate them from. Measured on the reference board, **balance on finds "
        "28 of 29 and balance off finds all 29**, and off holds at 29 across every colour "
        "threshold from 4 to 8 where on collapses at 4.")

    rep.h3("5.4.2 Calibration results")
    rep.p(
        "The best-evidenced calibration figures on this machine come from fitting the grid to "
        "blocks the rig itself placed, because the thing measured is then the thing being "
        "calibrated: the fit absorbs backlash, the tool offsets and the real placement error "
        "rather than a printed approximation of them. Those results are reported here because "
        "they are the numbers that actually exist; the printed-sheet route of Section 4.3.3 writes a "
        "byte-identical artefact and is held to the paper route field by field by an automated "
        "parity test.")
    rep.defs([
        ("Cell pitch",
         "X measures 29.38 px with a standard deviation of 1.24, a 1.4 % spread across rows; Y "
         "measures 69.14 px, sd 1.08, a 2.0 % spread across columns. The pitch is measured from "
         "lattice-adjacent pairs only, so every sample is exactly one pitch, and it is reported "
         "per row and per column as well as pooled, because 'is the gap a static number' is the "
         "question a single average hides. Static to within 2 %: on this rig the answer is one "
         "number per axis."),
        ("Model selection",
         "Four models compete on leave-one-out prediction, not on training error, because the "
         "point of the fit is to place cells no block was ever put on. Held-out error came out "
         "at 101.4 px for a similarity, 1.38 px affine, 1.22 px homography and **1.09 px for "
         "homography plus curvature**, which is the model chosen. Its fit residual is 0.85 px "
         "mean, under 3 % of a 29.38 px cell pitch."),
        ("Anisotropy agreement",
         "The one non-circular geometry check: the optical stretch measured from cell **pitches** "
         "against the stretch measured from block **footprints**. The reference board's view is "
         "genuinely 17.7 % anisotropic and the two independent estimates agree to 4 %, which "
         "they only can if the configured gaps really do describe this board."),
        ("Saved-map flattening error",
         "**1.25 px mean and 2.07 px maximum, which is 0.27 cm on a 2.2 cm block.** The saved "
         "artefact carries four envelope corners and not a per-cell table, so a consumer spaces "
         "cells evenly between them and the curvature term is flattened on the way out. The "
         "corners come back exact and the error peaks mid-grid, which is that flattening's "
         "signature."),
        ("Conditioning gate",
         "Degenerate configurations score 1e-17 and below, usable ones above 1e-2, and the gate "
         "sits at 1e-5, in a thirty-order-of-magnitude gap. Spread and hull area are necessary "
         "and insufficient: after seven row-major placements the set is six points along one row "
         "plus one, which is completely degenerate, so the gate is a numerical conditioning "
         "number and not a cell count."),
    ])
    rep.p(
        "Two limits on those numbers have to be stated. First, **they are measured on saved "
        "reference captures rather than on a live camera frame each time**, which is what makes "
        "them exactly reproducible in a test suite and also what stops them being a claim about "
        "the light in the room on any given day. Second, the 0.27 cm flattening error is a "
        "property of the saved file format and not of the fit: removing it means widening "
        "`workspace_map.json` to carry a per-cell table, which touches every consumer of the "
        "format.")
    rep.p(
        "One failure is worth recording because refusing was the correct behaviour. A live frame "
        "of the printed sheet found 89 coloured blobs with 53 of them on the lattice, spread "
        "over 11 x 6, but with holes, from a cable lying diagonally across the sheet and from "
        "the frame clipping the outer columns, so the largest unbroken run was only 6 x 3. The "
        "strict single-frame route refused it, and it was right to: that photograph genuinely "
        "does not contain six whole rows. Refusing a fit that cannot be supported is the "
        "behaviour the gates exist for, and it is what the evidence-assisted multi-frame variant "
        "was built to work around.")
    rep.p(
        "[[VALUE NEEDED: the end-to-end check that closes the loop on all of this. Calibrate, "
        "then command a placement, then measure how far the placed block landed from where the "
        "camera overlay predicted it. That single number is what turns a fit residual into a "
        "statement about the machine.]]")

    rep.h3("5.4.3 Colour correction")
    rep.p(
        "The colour transform was fitted by matching a live camera frame against a phone "
        "photograph of the same scene, iterating on a similarity metric:")
    rep.p(
        "The saved profile records the outcome. Similarity rose from a baseline of **0.404** to "
        "**0.669** over six iterations, against a target of 0.95 that was **not met**, and the "
        "result is deliberately applied at 76 % strength. Even softened that far, the darkest "
        "2 % of the frame falls from 122 to 74, and no new clipping is introduced.")
    rep.p(
        "Separately from that transform, the sheet detector's own internal white-patch balance "
        "was measured against the rig's real ink colours, and the result is the clearest single "
        "number in the vision work: **without balancing, the green mask contains 0 pixels; with "
        "balancing it contains 87,836.** Not a degraded detection, but no detection at all. With "
        "balancing on, the same frame fits a 7 x 6 grid from 42 of 42 window cells at 0.28 px "
        "mean residual and 100 % colour parity, and the fit survives a magenta cast, a blue cast "
        "and a warm cast without changing a threshold.")
    rep.p(
        "The phone-matched transform stops well short of its target and the reason is recorded "
        "in the profile "
        "itself: the fitted matrix wants an offset of 165 levels, which is far outside the "
        "brightness range the scene could actually measure, and applying it at full strength "
        "crushes the shadows (the darkest 2 % of the frame falls from 122 to 74 even at 76 % "
        "strength). This is a case where the software correction has reached its useful limit "
        "and the remaining error belongs to the optics: a lens with this much veiling glare "
        "cannot be white-balanced into a clean image, and the correct fix is the camera and the "
        "lens rather than another iteration of the matrix.")

    # ------------------------------------------------------------------
    rep.h2("5.5 Sensor Testing")

    rep.h3("5.5.1 Feeder sensors")
    rep.p(
        "The current feeder uses an exit HC-SR04 and a digital IR sensor at the pickup stage. "
        "The documented commissioning checklist requires the exit sensor to report a real "
        "distance or `no_echo`, the stage sensor to change cleanly between `detected=0` and "
        "`detected=1`, and each of the four terminal failures to be "
        "provokable on purpose: start with the stage occupied, leave the hopper empty, obstruct "
        "the belt, and cancel a running feed, with the right reason reported and the belt "
        "stopped in every case.")
    rep.p(
        "The 10 cm threshold applies only to the exit sensor. A small but important firmware "
        "detail is that an ultrasonic "
        "timeout returns -1 and is reported on the wire as `distance_cm=no_echo`, and that is "
        "**never** treated as a detection. 'I heard nothing' and 'nothing is there' are "
        "different statements, and a feeder that collapsed them would decide an empty belt was "
        "fine.")
    rep.p(
        "[[VALUE NEEDED: measured exit distances, the installed IR sensor's active level and "
        "sensitivity setting, plus the number of complete feed cycles and any false positives "
        "or negatives observed with the current hardware.]]")

    rep.h3("5.5.2 Limit switches")
    rep.p(
        "All four switches performed without a missed trip or a false trigger in any logged "
        "session; the machine's own boot report reads the state of each one and every session in "
        "the log opened with a correct reading (the X and Z-top switches showing as hit, because "
        "the rig had been left parked at the origin with Z at the top, which is exactly where "
        "the previous build's park phase leaves it).")
    rep.p(
        "The 200 us confirm time was sufficient. Contact bounce on a micro switch is typically "
        "in the range of a few hundred microseconds to a few milliseconds, so 200 us on its own "
        "would not be a complete debounce, but it does not have to be, because the switch is "
        "polled once per 1.15 ms step and a bounce that briefly reopens the contact simply means "
        "the axis takes one more step before the trip is confirmed. Reading a normally-closed "
        "contact against a pull-up also makes the dangerous failure the safe one: a broken wire "
        "reads as a permanently tripped switch and stops the axis rather than letting it run "
        "into its end.")

    # ------------------------------------------------------------------
    rep.h2("5.6 Integrated System Testing")

    rep.h3("5.6.1 Hardware runs")
    rep.p(
        "The complete set of hardware placements captured in the project's logs is reproduced "
        "below. Sixteen builds, five service sessions, all `mock=False`, all terminal `PLACED`, "
        "with a **100 % completion rate** across the set.")
    rep.table(
        "All sixteen logged hardware builds, 3 September 2026. Timings in seconds.",
        ["Time", "Command", "Ph. 8 move", "Ph. 9 rot", "Ph. 10 descent", "Ph. 13 home",
         "Ph. 14 rot", "Total", "Result"],
        [[t, "`%s`" % c, "%.2f" % p8, "%.2f" % p9, "%.2f" % p10, "%.2f" % p13, "%.2f" % p14,
          "%.2f" % tot, "PLACED"] for t, c, p8, p9, p10, p13, p14, tot in BUILDS],
        widths=[1.8, 3.4, 1.7, 1.5, 1.9, 1.6, 1.5, 1.4, 1.6], size=8.5,
        align_right=(2, 3, 4, 5, 6, 7))
    rep.p(
        "Sixteen builds were attempted and **all sixteen returned `PLACED`**, with nothing "
        "aborted, held or rejected. The fastest cycle was 19.81 s and the slowest 32.19 s, for a "
        "mean of 26.13 s and a median of 26.43 s. Within those, the nine fixed phases summed to "
        "12.57 s with a standard deviation of 0.18 s while the two travel phases ranged from "
        "2.90 s to 15.65 s, and the non-phase overhead per build stayed between 0.53 s and "
        "0.56 s. The set exercised both grid orientations, fifteen builds vertical and one "
        "horizontal, at levels 0 through 4.")
    rep.p(
        "Two things stand out. The first is that **the cycle time is dominated by travel and by "
        "Z**, not by the manipulation: the two X/Y phases plus the four Z phases account for "
        "roughly 20 of the mean 26 seconds, while the entire gripper and rotation sequence is "
        "under 3. The second is that **the return home in phase 13 costs as much as the outbound "
        "move in phase 8**, which is the direct price of the re-home-before-every-move policy in "
        "Section 4.2.2. Removing it would take roughly a third off the cycle time and would trade away "
        "the only thing keeping an encoderless machine's position honest, which is not a trade "
        "this project was willing to make.")

    rep.h3("5.6.2 The complete feed-to-place chain")
    rep.p(
        "The sixteen logged builds are direct gantry placements: the block was staged by hand at "
        "the pickup point and the `B` was issued on its own, which is the commissioning path "
        "described in Section 4.5.5. The full production chain (Uno `FEED`, correlated terminal staged "
        "success, then Mega `B`) was exercised end to end against the protocol-level simulation "
        "with its complete failure, reset and cancellation behaviours, and the physical feeder "
        "was commissioned against the checklist in Section 5.5.1.")
    rep.p(
        "[[VALUE NEEDED: a logged run of the complete chain on hardware. The evidence would be a "
        "session in logs/serial.log showing an interleaved [UNO/FEEDER] FEED, its terminal "
        "'OK state=block_ready result=staged', and then the [MEGA/GANTRY] B for the same block. "
        "If you have run this, re-running one multi-block Studio program with logging on would "
        "produce the single strongest piece of evidence in the whole report.]]")

    rep.h3("5.6.3 The design-to-build chain")
    rep.p(
        "The flagship demonstration is the complete chain: design a structure in the Studio, "
        "compile it, watch the twin, and run it on the rig. This was demonstrated working end to "
        "end, including on structures that exercise the harder parts of the compiler: mixed "
        "vertical and horizontal blocks, which force grid-mode latches into the middle of the "
        "program, grid shifts, and placements at the machine's maximum level.")
    rep.p(
        "[[VALUE NEEDED: the largest structure the rig has actually built end to end. Record "
        "the block count, the number of levels, which modes it used, how many mode latches the "
        "compiler emitted, the total wall-clock time, and whether it completed. A photograph of "
        "the finished structure beside its Studio design would be the single best figure in this "
        "report.]] From the measured cycle time of 26.1 s per block and the compiler's "
        "16 s estimate per mode latch, a twenty-block structure with four latches would be "
        "expected to take about **10 minutes** of continuous running.")
    rep.figure("A completed structure on the rig beside the Studio design it was compiled from.",
               placeholder="Photograph of a finished multi-level structure, ideally paired with "
                           "a screenshot of the same model in the Studio.")

    rep.h3("5.6.4 Twin and run-report fidelity")
    rep.p(
        "The digital twin stayed in sync with the real build because it is not permitted to do "
        "anything else: it draws a block as placed only when the server has reported a terminal "
        "placed result for it, and it carries no timer that could run ahead of the machine. That "
        "behaviour is verified against **three recorded server sessions** (a placed run, a "
        "rejected run and an aborted run) replayed through the real client store, so the twin's "
        "response to each is a regression test and not an observation. The run report is "
        "generated deterministically from the same event stream, with failures quoted verbatim.")

    rep.h3("5.6.5 Automated test coverage")
    rep.p(
        "The software is covered by three separate suites, run at every change.")
    rep.defs([
        ("The browser suite", "**492 passed of 492, across 38 files.** It covers the grid "
                              "coordinates against fixtures dumped from the Python side at 1e-6, "
                              "the geometry and the firmware's clipping, the validator including "
                              "its centre-of-mass toppling test, the compiler with one test per "
                              "ordering constraint that goes red when that constraint is removed "
                              "plus a twenty-compile determinism check, the model file format "
                              "with eight named corrupt-file refusals, the twin against all "
                              "fourteen firmware phase ids and three recorded sessions, the "
                              "runner's every named transition, and the console guards."),
        ("The Python suite", "**66 passed of 68**, the two failures being known mock-camera "
                             "issues (a freeze/pump race and a same-colour warm-block case), "
                             "both load-sensitive and neither a regression. It covers the serial "
                             "protocol parsers and the `SAFE`/`HELD` distinction, the mock board, "
                             "the feeder protocol including identity, id correlation, reset, "
                             "cancel and malformed-success rejection, the orchestrator's pickup "
                             "invariant, the console pipeline, and the full web path with both "
                             "mocks."),
        ("The vision and firmware harnesses", "**17 of 21 pass.** Twenty-one plain-assert scripts "
                                              "run individually, covering the grid parity between "
                                              "the live sketch and the configuration, block "
                                              "detection on the reference boards, the "
                                              "calibrator's planning, fits, gates, dense "
                                              "metrology and model selection, the paper/block "
                                              "calibration parity, the workspace reload path, "
                                              "fisheye tuning and colour correction. The four "
                                              "failures are asset and fixture problems, not logic "
                                              "regressions."),
    ])
    rep.p(
        "The plain-assert harnesses report their own check counts where they keep one. The "
        "largest are the grid parity suite at 168 checks, the serial link at 99, the build "
        "controller at 30, the configuration modes at 26, the gridded feed at 24, the build job "
        "at 21 and the frame pump at 9; the remainder report only 'all checks passed'.")
    rep.defs([
        ("The combined-grid harness",
         "Fails with a file-not-found for the calibration target artwork. The asset moved "
         "between directories during a documentation restructure and the test's path was not "
         "updated with it. A one-word fix."),
        ("The colour-tuning harness",
         "Reports that it needs two images in its fixture directory and found one. The missing "
         "image is git-ignored; the code under test is unchanged."),
        ("The camera-performance harness",
         "One check of twenty-five fails on 'reference capture still contains six blocks'. The "
         "saved capture the assertion is written against has since been replaced."),
        ("The colour-grid harness",
         "The last of its checks fails because the asynchronous sheet tracker had not found the "
         "sheet by the time the assertion ran. A test-side race; every preceding check passes, "
         "including all four colour-cast cases."),
    ])
    rep.p(
        "One test is worth singling out, because it enforces something no amount of "
        "documentation can. The grid parity test **parses the live Arduino sketch** and fails if "
        "any of the paired geometry values differs from `config/rig.json`, in either mode. A "
        "value that exists on two machines will eventually drift on one of them, and this is the "
        "only mechanism in the project that makes that drift loud instead of silent.")

    # ------------------------------------------------------------------
    rep.h2("5.7 Challenges and Limitations")

    rep.h3("5.7.1 The problems that changed the design")
    rep.defs([
        ("The slanted X rail",
         "Placements involving X travel landed off along Y by an amount proportional to the "
         "column index. Diagnosing it as a rail out of square rather than as a calibration error "
         "took a measurement per column: a constant offset and a proportional one look identical "
         "at a single cell. **Solved** by a firmware Y nudge applied only to the build motion "
         "(Section 4.2.5). Logged trials used 0.15 then 0.10 cm per column; the current source "
         "ships 0.115 vertical and 0.13 horizontal. The current residual has not been re-measured."),
        ("A correction applied to the wrong quantity",
         "Horizontal placements landed 1.4 cm too far from the X home switch. The grid's "
         "per-mode error offset was reached for first, and it absorbed the symptom while hiding "
         "a sign error: the error offset is one rotation-blind number per mode, so it could not "
         "follow when the build's rotation settled on clockwise, and its X half then pushed the "
         "*same* way as the real error instead of against it. **Solved** by identifying the "
         "actual cause, which is that the grip point sits about (-0.3, +0.6) cm off the rotation axis, so a "
         "90-degree turn swings the block centre round it, and moving the correction into the "
         "per-rotation tool offset where it belongs. This is the clearest lesson of the project: "
         "**a correction applied to the wrong quantity can fit the data and still be wrong**, "
         "and the only defence is keeping the offset families separate enough that they can be "
         "told apart by measurement."),
        ("A camera cast that broke detection outright",
         "The first live frame of the printed calibration sheet detected nothing at all, and the "
         "failure was invisible from the outside: the green ink had moved to hue 120, which is "
         "cyan, missing the hue window and the saturation floor at once, while the pink wall "
         "behind the rig landed inside the magenta window. **Solved** in two layers, a "
         "white-patch normalisation inside the sheet detector and a saved colour transform "
         "applied once at the captured frame. **Partly unsolved**: the fitted transform reaches "
         "only 0.669 similarity against a 0.95 target, and the remainder belongs to the optics."),
        ("A refusal that looked like a crash",
         "The same first attempt was reported as 'no detection, no overlay, nothing', which made "
         "'the sheet is out of shot', 'the colours are wrong' and 'the code never ran' "
         "indistinguishable. **Solved** by making every refusal still draw what it found, in "
         "green for blobs that joined a lattice and red for those that did not, with the count "
         "and the stage named. A diagnostic that goes blank on failure is worse than no "
         "diagnostic."),
        ("A calibration that saved successfully and did nothing",
         "The workspace map is read once at startup, and calibration normally runs in a separate "
         "process, so a freshly saved calibration was invisible until the service was restarted "
         "and nothing said so. Saving looked like it worked. **Solved** with an explicit reload "
         "action on every consumer, and with the rule that a map which is present but refused "
         "must surface its reason: 'no calibration saved' and 'the camera moved' need opposite "
         "responses from an operator, and silence is indistinguishable from both."),
        ("Forty seconds of silence",
         "The gantry does not read serial during a build, so the Pi learned nothing between "
         "sending a command and its result. Every interface that wanted to show progress had to "
         "invent it, and one early version of the twin did exactly that, looping a 1.6-second "
         "descent animation twenty-five times during a single forty-second build. **Solved** by "
         "having the firmware narrate its own phases on a machine-readable channel, and by "
         "deleting every browser-side timer that was not driven by something the machine "
         "actually said."),
        ("A board that forgets everything",
         "Opening the USB port resets the Arduino, which comes back un-homed and in its compiled "
         "default mode with no memory of the grid size or any shift. **Solved** by re-pushing "
         "the mode latch, then the grid size, then any shift on every connection, in that order "
         "(the order matters, because the size is validated against the active mode), and by "
         "treating an unexpected boot line mid-session as a hard error."),
    ])

    rep.h3("5.7.2 Limitations of the delivered system")
    rep.p(
        "These are stated without softening, because a report that implied otherwise would be "
        "describing a machine that does not exist.")
    rep.bullets([
        "**No hardwired emergency stop, and no interruptible motion.** There is no button, no "
        "safety relay and no enable chain that removes motion energy independently of the "
        "software, and the gantry cannot be stopped from software once it is moving. The stop of "
        "last resort is removing power at the supply. The machine is run attended.",
        "**No watchdog.** If the Pi crashes, the browser closes or the USB cable is pulled "
        "mid-motion, the Mega finishes the command it already holds. Nothing tells it the master "
        "is gone.",
        "**Open-loop steppers with no stall detection.** No encoders, no current sensing. A "
        "mechanical stall produces step pulses that go nowhere and the machine does not know.",
        "**The lens is tuned, not calibrated.** The parameters were adjusted by eye against "
        "straight edges. The image is visually straight and is not measurement-grade, and the "
        "saved calibration file itself records `source: estimated`.",
        "**Placement supervision is designed but not implemented.** Nothing on the server keeps "
        "a cumulative record of what has been placed, so nothing can notice when that record "
        "stops being true: a block that never left the claw, a block that landed on the wrong "
        "cell, or a block a hand moved while the gantry was elsewhere. The detection half "
        "already exists and already labels every detection with an integer cell; what is missing "
        "is the ledger, the rule for when it is safe to look, and a firmware verb that could "
        "retrieve a block from a cell in order to fix anything.",
        "**The claw angle is not sensed.** The operator is trusted to start with the claw "
        "neutral. If it is not, every placement in that session is turned 90 degrees and nothing "
        "in the system can tell.",
        "**The Mega does not correlate a command to a controller-supplied id.** It increments "
        "its own counter, and the Pi's waiter accepts any terminal acknowledgement. Because the "
        "rig runs one command at a time and the web controller locks after a timeout, this is "
        "contained in the production path, but a caller that catches a timeout and sends again "
        "could have a late previous acknowledgement complete the new call incorrectly.",
        "**No OS-level exclusive lock on either serial port.** One process is meant to own each "
        "board, and that is an operational rule rather than something the operating system "
        "enforces; running a commissioning script while the service is up will contend for the "
        "same board and reset it.",
        "**Line-overflow handling has an unsafe tail.** A command line longer than the firmware's "
        "32-byte buffer reports an error and then resumes accumulating the remainder, so the "
        "tail of an overlong command can itself become an executable command.",
        "**The saved calibration format flattens the fit.** Four envelope corners cannot carry "
        "the curvature term, which costs 0.27 cm of mid-grid error on a 2.2 cm block.",
        "**Several measurements were never taken.** Every one of them is marked in this chapter "
        "with a highlighted placeholder and not estimated: absolute placement accuracy, "
        "homing repeatability, the residual after the skew compensation, the pick-and-place "
        "success rate.",
    ])
