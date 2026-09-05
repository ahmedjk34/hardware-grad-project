"""Chapter 4 — Control and System Operation."""


def chapter_4(rep):
    rep.h1("4. Control and System Operation")

    # ------------------------------------------------------------------
    rep.h2("4.1 Control Methodology")

    rep.h3("4.1.1 A hierarchy, and what closed-loop means here")
    rep.p(
        "The control system is hierarchical, with a hard boundary between the two levels. The "
        "Raspberry Pi decides **what** should happen and **whether** it is allowed to; each "
        "Arduino decides **how**. The Pi never sends a motor step, a direction bit or a "
        "millisecond delay: it sends `B col row level` or `FEED <id>`, and the firmware turns "
        "that into motion using numbers the Pi does not hold a copy of.")
    rep.p(
        "That boundary is drawn where it is because of one rule: **the firmware owns everything "
        "that cannot change without reflashing.** The step caps, the steps-per-centimetre "
        "ratios, the Z calibration, the block height, the build ceiling, the servo angles, the "
        "pin assignments and the motor direction polarity are all physical facts about the "
        "machine. Nothing can push them over serial, so a copy of them in the Pi's configuration "
        "would be a lie that nobody notices until the rig drives into something. What the "
        "configuration file does own is what can change without reflashing: the grid counts, the "
        "block and gap geometry, the trims, the two serial ports.")
    rep.p(
        "At the motor level the machine is **entirely open-loop**. There are no encoders, the "
        "step counters are trusted, and the only thing that keeps them honest is that every "
        "commanded move begins by driving both axes back into their home switches. When this "
        "report calls the system closed-loop, it means something specific and narrower: "
        "**sensor- and vision-confirmed sequencing**. The machine does not verify a shaft "
        "position; it verifies that a block left the container, that a block reached the pickup "
        "point, that a build phase began, that a block was released, and that a block is visible "
        "where one was commanded. Each of those is measured, and each of them can refuse "
        "permission for the step after it.")

    rep.h3("4.1.2 The acknowledgement protocol")
    rep.p(
        "The firmware talks to a human. Its serial output is a long, readable banner, a full "
        "machine report, an ASCII grid map and a running commentary on the build. Matching that "
        "prose is a bad way for the Pi to know what happened, because it breaks the day someone "
        "rewords a message, and because it cannot answer the two questions that matter during a "
        "forty-second build: is it still alive, and which of my commands is this about.")
    rep.p(
        "The answer was not to remove the prose. It is to print **one extra line beside it**, "
        "for the machine, on a channel a human can ignore by eye:")
    rep.code(
        "======================================\n"
        "BUILD COMPLETE - block placed at [3,5] level 0 (0.00 cm)      <- for the human\n"
        "Place time: 31.6s\n"
        "======================================\n"
        "@12 OK col=3 row=5 level=0                                    <- for the Pi")
    rep.p(
        "Every machine line starts with `@`, a character no other line in either sketch begins "
        "with, so the Pi's filter is one string test. The envelope is a sequence number, a kind, "
        "and space-separated `key=value` fields; there is no JSON, because on an 8 KB AVR at "
        "9600 baud braces and quotes cost SRAM and airtime for nothing.")
    rep.code("@<seq> <KIND> [reason text | key=value ...]")
    rep.table(
        "Acknowledgement kinds emitted by the gantry firmware.",
        ["Kind", "Terminal", "Meaning"],
        [
            ["`BOOT`", "no", "`@0 BOOT fw=build_test_v1`, the first line after a reset. An "
                             "unexpected one mid-session means the board reset under the "
                             "controller, which is a hard error."],
            ["`READY`", "no", "`@0 READY grid=<cols>x<rows> mode=<mode>`, the last line of "
                              "startup and the Pi's sync marker. It carries the mode because a "
                              "reset silently returns the board to vertical."],
            ["`RECV`", "no", "The command parsed and was accepted. It pins the sequence number "
                             "to this command **before** the validation that may still reject "
                             "it, which is what makes 'accepted, validating' a state distinct "
                             "from 'moving'."],
            ["`STEP`", "no", "One build phase, announced before that phase runs."],
            ["`ERR`", "**yes**", "Refused on syntax or arguments. Nothing moved."],
            ["`SAFE`", "**yes**", "Refused on validation. **Nothing moved.** A retry is fine."],
            ["`HELD`", "**yes**", "Failed part way through. The claw may still be gripping a "
                                  "block and the position is unknown. **Needs a person.**"],
            ["`OK`", "**yes**", "Finished: the block is placed and the rig is parked."],
        ],
        widths=[2.2, 2.0, 10.8], size=9)
    rep.p(
        "`SAFE` and `HELD` are separate **kinds** rather than a flag on one kind, and that is "
        "the single most important decision in the protocol. The firmware already draws the "
        "distinction for the human (one path prints 'Nothing moved', the other prints 'The claw "
        "may still be holding a block'), and it is the difference between a typo and somebody "
        "walking over to the rig. Making them two kinds means code on the Pi **cannot** collapse "
        "them into a generic `if not ok: retry`; the `HELD` branch has to be written on purpose. "
        "The retry is the thing that breaks the machine.")
    rep.p(
        "The sequence number is assigned by the Arduino and not by the Pi, so that the "
        "command grammar stays typeable by hand in a serial monitor. Since the rig runs strictly "
        "one command at a time, 'the acknowledgement that followed my command' is never "
        "ambiguous. Section 5.7 records the honest weakness of that choice.")

    rep.h3("4.1.3 Real-time build progress")
    rep.p(
        "A build is about forty seconds during which the firmware never reads serial. Before the "
        "progress channel existed the Pi learned exactly two things in that window: that it had "
        "sent a command, and, eventually, how it ended. Everything in between was invisible, and "
        "every interface that wanted to show it had to invent something.")
    rep.p(
        "The firmware now prints one machine line per phase, immediately **before** that phase "
        "runs:")
    rep.code(
        "@12 STEP step=8 total=14 phase=move_to_target action=move \\\n"
        "    text=Move_XY_to_the_target_cell status=begin\n"
        "[BUILD 8/14] Move X/Y to the target cell")
    rep.table(
        "Fields on a `STEP` line.",
        ["Field", "Meaning"],
        [
            ["`<seq>`", "The same sequence number as the `B` it belongs to, so every phase is "
                        "attributable to one command."],
            ["`step`", "1 to `total`."],
            ["`total`", "14, on the wire so that nothing downstream hard-codes it."],
            ["`phase`", "A **stable machine identifier** that user interfaces switch on. "
                        "Renaming one is a protocol change, not a wording change, and a silent "
                        "one: a browser that does not recognise an id falls back to a generic "
                        "'moving' instead of crashing."],
            ["`action`", "`move` / `grip` / `release` / `rotate` / `park`. Coarse on purpose: a "
                         "consumer needs to know whether a block is being carried, not which "
                         "motor turns."],
            ["`text`", "The human label, underscored so it survives as one whitespace-separated "
                       "token."],
            ["`status`", "`begin` before the phase runs, and `done` exactly once."],
            ["`ms`", "The firmware's own prediction of the phase duration. **Z moves only**, and "
                     "omitted and not sent as zero when unknown."],
        ],
        widths=[2.2, 12.8], size=9)
    rep.p(
        "Three properties of that channel are load-bearing. **One line per phase, never one per "
        "motor step**: fourteen lines is about 0.3 s of 9600-baud airtime inside a 40 s build, "
        "while per-step telemetry would be minutes of it, would fill the output buffer and would "
        "starve the terminal acknowledgement. **Exactly one `done`**, on phase 11, the instant "
        "the jaws open and the block is on the stack; nothing else can carry that fact, because "
        "parking is optional and there may be no phase 12 to imply it, and it is emphatically "
        "**not** terminal: the command is still running and a parking failure downgrades the "
        "whole build to `HELD`. And **`ms=` is a floor, not a schedule**: nothing moves faster "
        "than its step rate, so the real phase can only take longer, and no consumer may treat "
        "its expiry as the phase having finished.")
    rep.p(
        "The reason the firmware sends `ms=` rather than the browser computing it is the "
        "hierarchy rule from Section 4.1.1. Working the descent out requires `Z_TRAVEL_STEPS`, "
        "`Z_TRAVEL_CM` and `BLOCK_HEIGHT_CM`, all three of which are firmware-only numbers, and "
        "a browser holding copies of them would drift silently the day the Z step rate is "
        "retuned. The board owns the numbers, so the board does the arithmetic. For the shipped "
        "calibration that is:")
    rep.code(
        "full travel        1350 steps            = 2565 ms  (+ DIR_SETTLE_MS = 2570)\n"
        "one block height   76.4 steps            =  145 ms\n"
        "descent to level K 1350 - 76.4*K steps   = 2565 - 145*K  ms")

    # ------------------------------------------------------------------
    rep.h2("4.2 Motion Control")

    rep.h3("4.2.1 Command vocabulary")
    rep.p(
        "The gantry firmware's commands are the contract between the two machines. They are "
        "short because they are typed by hand during commissioning as often as they are sent by "
        "the Pi.")
    rep.table(
        "The gantry (MEGA) command vocabulary.",
        ["Command", "Does", "Moves?"],
        [
            ["`1` `2` `3` `4`", "One manual jog of `stepsPerMove` on X- / X+ / Y- / Y+.", "yes"],
            ["`D` / `U`", "One manual Z jog down / up.", "yes"],
            ["`0`", "Home: drive into the X and Y switches. This is the origin.", "yes"],
            ["`0+`", "Full reset: Z down to the bottom switch, Z up to the top switch, then home "
                     "X and Y. It also measures the real switch-to-switch Z distance.", "yes"],
            ["`G <col> <row>`", "Go to a cell centre. Both axes always move, after a re-home.",
             "yes"],
            ["`B <col> <row> <level>`", "The complete fourteen-phase build cycle. Three numbers, "
                                        "no rotation word.", "yes"],
            ["`O` / `C`", "Servo open / close.", "the claw"],
            ["`V <angle>`", "Servo to an arbitrary angle, 0 to 180. Bench use.", "the claw"],
            ["`A <degrees>`", "Signed **relative** rotation jog, -360 to +360, positive "
                              "clockwise. Bench use; capped at one turn per command because the "
                              "mechanism has no limit switch.", "the claw"],
            ["`R` / `RR`", "Latch the vertical / horizontal grid. **Neither moves anything.** "
                           "Each is refused when it is already true, and both need X and Y "
                           "homed first.", "no"],
            ["`S <cols> <rows>`", "Set the highest addressable index for the **active** mode "
                                  "only. The other mode keeps what it was given.", "no"],
            ["`shiftX <cm>` / `shiftY <cm>`", "Translate the whole placement lattice of the "
                                              "active mode. The pick-up is not shifted.", "no"],
            ["`5` / `9` / `Z` / `?`", "Full machine report / ASCII grid map / Z calibration "
                                      "table / help.", "no"],
            ["`6` / `7` / `8`", "Reset statistics / disable the X-Y drivers / declare the "
                                "current position zero without homing.", "no"],
        ],
        widths=[3.6, 9.4, 2.0], size=9)
    rep.p(
        "Two of these changed meaning during the project and one lost an argument, and all three "
        "changes are worth stating because they are the kind that break a controller silently. "
        "`R` and `RR` used to be free rotation jogs and are now grid latches that move nothing. "
        "`A <degrees>` is manual bench rotation and explicitly not a new grid orientation. And "
        "`B` no longer takes a rotation word: **how the block is laid comes from the active "
        "grid, not from the command**, because a per-block rotation could place a rotated block "
        "inside a grid whose cell geometry does not match it, which is exactly the failure the "
        "two-grid design exists to prevent. A fourth word on a `B` is now a parse error whose "
        "message names the mode latch.")

    rep.h3("4.2.2 The coordinate system and homing")
    rep.p(
        "Each home switch zeroes its own axis the instant it trips, so the corner where both the "
        "X and Y switches are pressed is machine position (0, 0). The two switches sit at "
        "opposite ends of their axes, so the two axes do not share a sign:")
    rep.code(
        "X switch at the X+ end  ->  X runs   0  ...  -4550   (software cap)\n"
        "Y switch at the Y- end  ->  Y runs   0  ...  +7600   (software cap)\n"
        "Z switch at the Z- end  ->  Z runs   0  ...  +1350   (TOP SWITCH, physical)")
    rep.p(
        "Grid indices hide that sign asymmetry entirely: column 0 is nearest the X switch, row 0 "
        "is nearest the Y switch, and both increase away from home. Every axis is described "
        "generically as extending from 0 in the direction of its travel end for its travel "
        "distance, whether that far end is held by a software cap (X, Y) or by a switch (Z), "
        "which is what lets one set of code handle all three.")
    rep.p("The go-to sequence is deliberately expensive:")
    rep.numbered([
        "Home Y into its switch, then home X into its switch. That is the origin.",
        "Move Y to the target row.",
        "Move X to the target column.",
    ])
    rep.p(
        "Re-homing every time means lost steps never accumulate. It costs a full return to the "
        "origin on every move, and Section 5.2.2 measures that cost: it is the second-largest term in "
        "the cycle time, and it is the price of position integrity on a machine with no "
        "encoders.")

    rep.h3("4.2.3 The lattice, and why there are two grids")
    rep.p(
        "A block measures 2.2 x 6.0 cm in plan and can be laid either way round, and which way "
        "round it is laid decides how many cells fit, where they sit and how far the grid has to "
        "be registered. That is not one grid with a flag; it is two grids, each with its own "
        "complete geometry. Both share one physical envelope, because a block lying down does "
        "not move a limit switch.")
    rep.p("The lattice itself is one line of arithmetic, and it is **centre-anchored**:")
    rep.code(
        "pitch     = block + gap\n"
        "centre(i) = trim + error_offset + shift + i * pitch")
    rep.p(
        "Cell indices are 0-based and **coordinate zero is a real block whose centre sits on the "
        "home corner**. There is no leading gap, no trailing gap and no centring of the "
        "allocation inside the travel: the trim is the only thing that moves a grid. Two "
        "consequences follow. Cell 0's block hangs half a block back past the switches, which is "
        "expected and is what the per-mode edge-overhang budget exists to allow. And a "
        "full-travel grid lands its last centre exactly on the software cap, which is why the "
        "vertical grid's 6 x 3.8 = 22.8 cm and 5 x 7.6 = 38.0 cm come out even: that is what "
        "'the build area is the travel area' means, and it is why vertical X has seven columns "
        "and not six.")
    rep.p(
        "The gaps are a uniform **1.6 cm on every axis of both modes**. That was settled by "
        "measuring the printed sheet (6.00 cm tiles, 1.56 cm gaps, identical on both axes); an "
        "earlier revision claimed 0.8 cm along Y, which made the horizontal Y lattice alternate "
        "0.8 and 1.6, and that alternation was an artefact of the wrong gap and not a "
        "feature of the paper.")
    rep.p(
        "Cell [0,0] is the **feeder** in both modes and is never built on. The feeder never "
        "rotates: a block is always presented standing, on the vertical [0,0] footprint, "
        "whichever mode is latched. Because the lattice is centre-anchored, that cell's centre "
        "**is** the home corner, so a pick-up is a plain home with no move afterwards and the "
        "claw closes on the block's middle without any additional positioning. That costs "
        "exactly one cell per mode and no more: `B 0 0 <level>` is an inert no-op, while "
        "`B 0 3` and `B 4 0` are ordinary placements.")

    rep.h3("4.2.4 The horizontal registration, and four kinds of offset")
    rep.p(
        "The horizontal grid ships with a trim of **+1.9 cm on both axes**, and the reason is "
        "geometric rather than empirical. The block is picked up standing at the vertical [0,0] "
        "feeder, centred on home, and then rotated 90 degrees about the grip. The rotated 6.0 cm "
        "face overhangs the 2.2 cm vertical footprint by 6.0/2 - 2.2/2 = 1.9 cm per side, so a "
        "+1.9 cm trim on each axis seats horizontal [0,0] flush against the vertical [0,0] "
        "block's edge (the near edge in X, the far edge in Y).")
    rep.note(
        "**A caveat that is easy to get wrong, and that this project got wrong once.** The "
        "overhang is an *extent*; the trim is a *translation*. A 90-degree turn about the grip "
        "moves the block's centre by zero however far its face overhangs, so the rotation does "
        "not by itself justify any trim at all. What justifies +1.9 cm is the **layout choice**: "
        "horizontal [0,0] is defined edge-flush with vertical [0,0] rather than "
        "centre-coincident. The rotation's real, non-zero contribution is the grip-to-axis "
        "swing, and that lives in the tool offset (Section 3.2.3), not here.")
    rep.p(
        "Four families of offset exist and each has exactly one job. Keeping them separate is "
        "what makes calibration falsifiable: two knobs that both look like 'shift everything' "
        "cannot be told apart by any measurement.")
    rep.table(
        "The four offset families.",
        ["Family", "What it is", "Moves", "Shipped value"],
        [
            ["`block` / `gap`", "The physical lattice itself.", "the cell spacing",
             "2.2 / 6.0 cm and a uniform 1.6 cm"],
            ["`trim`", "Registration of a whole grid against the home switches.",
             "every cell centre of that mode",
             "vertical (0, 0); horizontal (+1.9, +1.9)"],
            ["`error_offset`", "The calibration knob: a constant per-mode nudge for a measured "
                               "placement error. It cannot fix an error that grows with "
                               "distance, which is a scale or pitch problem.",
             "every cell centre of that mode", "(0, 0) in both modes"],
            ["`tool_offset`", "Purely mechanical: how far the claw's grip centre sits from the "
                              "holder centre, per rotation state.",
             "the **holder**, not the cells", "neutral (0, 0); CW (+0.9, -0.3)"],
        ],
        widths=[2.8, 6.4, 3.0, 3.8], size=9)
    rep.p(
        "Because a tool offset never enters the lattice, the cell centres in the table in Section 2.4.7 "
        "are also where a placed block physically comes to rest, which is why the camera "
        "overlay, the Studio and the digital twin can all draw the truth without carrying a "
        "correction of their own.")

    rep.h3("4.2.5 X-rail skew compensation")
    rep.p(
        "A placement made with pure Y motion (the same column, for example `B 0 3 0`) lands "
        "exactly where the grid says. A placement that involves X motion lands off along **Y**, "
        "and the error grows with how far along X the rig travels. It is not a constant offset.")
    rep.p(
        "Measured on the rig, the introduced Y error is **0.10 cm per column of X travel**, and "
        "it is linear in the column index with no row dependence at all: 0.00 cm at column 0 "
        "where there is no X travel, 0.10 cm at column 1, 0.20 cm at column 2, and 0.10 x k cm "
        "at column k.")
    rep.p(
        "The cause is mechanical and is described in Section 2.2.1: the arm holder's asymmetric loading "
        "leaves the X rail very slightly out of square with Y, so the further the carriage is "
        "driven along X, the more of that angled rail it has travelled over and the more it "
        "drifts along Y. The drift is linear in the column index with no row dependence, which "
        "is exactly what an angled rail predicts and is a useful check that the diagnosis is "
        "right.")
    rep.p(
        "Re-machining or re-bracing the rail was out of scope, so the drift is cancelled in "
        "firmware. For a build the Y target is deliberately offset by exactly the drift the "
        "rail will add, so that the two cancel:")
    rep.code(
        "yNudge_cm = SKEW_Y_PER_COL_CM    * col        // 0.1, measured\n"
        "          + SKEW_Y_PER_ROW_CM    * row        // 0.0, no row dependence\n"
        "          + SKEW_Y_PER_COLROW_CM * col * row  // 0.0, cross term, unused\n"
        "\n"
        "targetY  = cellTargetPosition(AXIS_Y, row, rot) + lround(yNudge_cm * stepsPerCm_Y)")
    rep.p(
        "The scope of that correction is as important as the correction itself. It is applied in "
        "**`gotoBuildTarget()` alone**, and the `B` motion is the only path that gets it. It is not "
        "in the cell-centre arithmetic, not in the `G` command, not in the grid map, not in the "
        "Python link, and not in the camera grid, the Studio grid or the 3D lattice. **Every "
        "representation of the grid stays a perfectly rectangular, level lattice**; this bends "
        "only the physical motion, so that the real blocks come out straight. X is never "
        "touched, and the result is clamped to the Y travel so that a bad coefficient cannot "
        "drive the carriage past a soft limit.")
    rep.p(
        "The correction was flashed and tuned on the rig rather than left on paper: the serial "
        "log shows it running at 0.150 cm per column in the morning session of 3 September 2026 "
        "and re-tuned to **0.100 cm per column** for the afternoon session, with the per-cell "
        "correction logged as it is applied "
        "(`X-rail skew: Y 0 -> 20 steps (0.100 cm, col skew)`). "
        "[[VALUE NEEDED: the residual Y error re-measured AFTER the 0.10 cm/column compensation "
        "was applied. The figures in the table above were taken before it; the residual has "
        "never been measured, and it is the single most valuable missing number in this "
        "report.]]")

    rep.h3("4.2.6 Z heights and block levels")
    rep.p(
        "Everything the build knows about height falls out of two measurements and is computed "
        "at run time and not hard-coded, so re-measuring the rig is a one-line change.")
    rep.table(
        "The Z / block-level calibration.",
        ["Quantity", "Value", "Derived as"],
        [
            ["Z travel, steps", "1,350", "Bottom switch (pin 28) to top switch (pin 29). "
                                         "Calibration only; the switch is what stops the axis."],
            ["Z travel, cm", "26.5", "Tape-measured."],
            ["Scale", "50.9434 steps/cm", "1,350 / 26.5, computed at run time"],
            ["Block height", "1.5 cm = 76.42 steps", "One stack level"],
            ["Fixed margin", "+0.10 cm", "Added once to any level >= 1. Level 0 ignores every "
                                         "margin, because ground is a physical switch and "
                                         "cannot drift."],
            ["Per-level margin", "0.00 cm", "For an error that accumulates up the stack. Not "
                                            "needed at the shipped calibration."],
            ["Build ceiling", "25.0 cm", "Deliberately below the 26.5 cm travel, so there is "
                                         "always clearance to fly a block over the tallest "
                                         "possible tower."],
            ["Highest level", "16 (24.0 cm)", "floor(25.0 / 1.5), leaving 2.5 cm of headroom"],
        ],
        widths=[3.4, 3.6, 8.0], size=9)
    rep.code(
        "target_cm    = level * (BLOCK_HEIGHT_CM + Z_MARGIN_PER_LEVEL_CM) + Z_MARGIN_FIXED_CM\n"
        "target_steps = round(target_cm * zStepsPerCm()) + Z_MARGIN_FIXED_STEPS")
    rep.p(
        "The two margins answer two different errors and must not be confused. If a placed block "
        "ends up 1.52 cm high instead of 1.50, the error is **per level** and accumulates up the "
        "stack. If every level is uniformly a little low or high because of claw geometry, a "
        "switch tripping early or a lip on the block, that is a **constant** error. The shipped "
        "calibration carries +0.10 cm of fixed margin and no per-level term, which says that the "
        "block height itself is right and the whole stack sits slightly low.")
    rep.note(
        "The firmware source now carries `Z_MARGIN_FIXED_CM = 0.10`, while the machine's own "
        "boot report from the logged 3 September session prints `fixed 0.000 cm`. The margin was "
        "introduced after that session and the board has not been re-flashed since the log was "
        "taken. **The sixteen builds analysed in Chapter 5 ran with no fixed Z "
        "margin.** The same log shows the gripper closing at 50 degrees where the source now "
        "says 52, and the tool offsets all reading 0.000 where the source now carries "
        "(+0.9, -0.3) for CW. Every one of those is a source change made after the log; none of "
        "them affects the timings the chapter reports.")

    # ------------------------------------------------------------------
    rep.h2("4.3 Vision and Positioning")

    rep.h3("4.3.1 The pipeline, in order")
    rep.p(
        "One process owns the camera, and every frame passes through the same fixed sequence "
        "before anything is asked of it:")
    rep.numbered([
        "**Capture** at 1296 x 972 through Picamera2, into a non-blocking latest-frame pump so "
        "that a slow analysis can never stall the video.",
        "**Frame orientation**: the configured flip and rotation, applied first so everything "
        "downstream shares one convention.",
        "**Colour correction**: the saved gain/offset/saturation transform, applied once here "
        "and never inside an individual detector, so every tool in the system sees identical "
        "pixels (Section 3.4.3).",
        "**Lens correction**: the fisheye remap table, followed by the framing crop and zoom "
        "(Section 3.4.2).",
        "**Detection**, on a background worker at a lower rate than the video, with the main "
        "loop drawing the last completed result instead of waiting.",
        "**Mapping**: the saved workspace homography turns a pixel into physical centimetres and "
        "then into a `[col, row]` cell.",
    ])
    rep.p(
        "The Pi picks the cell. **The firmware alone turns a cell into safe step targets**, and "
        "the Pi never needs a motor step to draw or select one.")
    rep.figure("Vision pipeline: capture, orientation, colour correction, lens correction, "
               "detection, and the pixel-to-centimetre-to-cell mapping.",
               placeholder="Block diagram of the six pipeline stages, with the background "
                           "analysis worker drawn off the main loop.")

    rep.h3("4.3.2 Block detection: three layers")
    rep.p(
        "There are three things in this system that find blocks. They share a segmentation front "
        "end and then diverge completely, and confusing them is the main way to get a wrong "
        "answer.")
    rep.table(
        "The three detection layers.",
        ["Layer", "Answers", "Runs", "May write a calibration"],
        [
            ["1. Segmentation", "What warm, block-shaped things are in this frame?",
             "every analysed frame", "no"],
            ["2. Live overlay", "Which of those are really blocks, and where do I draw them?",
             "every analysed frame", "no"],
            ["3. Calibration", "Where is the machine's grid, in pixels?",
             "once, deliberately", "**yes**"],
        ],
        widths=[3.4, 6.6, 3.2, 3.0], size=9)
    rep.p(
        "**Layer 1** segments warm material by **red-minus-blue and red-minus-green** exceeding "
        "thresholds, never by brightness: the work surface is overexposed in the captures this "
        "was tuned on, so a brightness cutoff selects the table and not the blocks. The mask "
        "is opened with a 3x3 kernel and closed with a 5x5, both deliberately small, because a "
        "large close joins neighbouring blocks together before the splitting step has a chance "
        "at them. A contour then becomes blocks by one of three paths, tried in order: straight "
        "through if it is already one standard-sized rectangle; a **touching-block split** that "
        "connects the two deepest convexity defects and cuts the component in two; or a "
        "**compound decomposition** that fits ideal block-sized rectangles into a merged "
        "component. What layer 1 returns is a hypothesis, not an answer, and it cannot be "
        "anything else: a rail and a block are the same shape.")
    rep.p(
        "**Layer 2** is where a hypothesis becomes an overlay. It rejects, then rectifies: "
        "duplicate detections are collapsed by intersection-over-union (the compound "
        "decomposition proposes overlapping rectangles, so a block joined to its neighbour by a "
        "shadow yields a third rectangle straddling the seam); anything whose box runs off the "
        "frame is dropped, which is what removes the aluminium rails at the frame edge; anything "
        "further than 0.34 cells from an integer lattice site is dropped, which is what removes "
        "the holder's two thin wooden offcuts beside [0,0]; and every survivor is redrawn with "
        "the population's median size and the lattice's shared bearing.")
    rep.p(
        "Two rules keep layer 2 honest and both are asserted by tests. **The measured centre is "
        "never snapped to the lattice.** Sharing a size and a bearing is what makes a full board "
        "read as one grid; snapping the positions too would draw a prettier grid and hide a "
        "misplaced block, which is the one thing this overlay exists to show. And **the lattice "
        "filter must not fire on a partial view**: below six detections, or when the recovered "
        "lattice would reject more than 30 % of what it saw, everything is kept, because a "
        "lattice fitted to four blocks is not the board's lattice.")
    rep.figure("The detector on a real frame. Left: ten blocks scattered on the surface, "
               "deliberately off the lattice. Right: the same frame through layer 2, with all "
               "ten found and squared to a shared size, their measured centres marked. Nothing "
               "else in the frame is claimed as a block: the aluminium rails at the edges, the "
               "cable runs, the screwdriver and the phone are all rejected.",
               image="fig-detection-pair.png", width_cm=15.0)

    rep.h3("4.3.3 Grid calibration from the printed target")
    rep.p(
        "The printed A2 target described in Section 3.4.4 is the calibration route presented here. What "
        "follows is how the fit works, and every gate it has to pass.")
    rep.defs([
        ("What it does", "Recovers the four corners of the machine's holder envelope in "
                         "normalised image coordinates, so that a pixel can be converted to a "
                         "physical position and then to a grid cell."),
        ("Inputs", "One camera frame containing the printed sheet, laid with the centre of its "
                   "[0,0] block on the holder home point; the active grid mode; and the block "
                   "and gap geometry from the configuration."),
        ("Outputs", "A `workspace_map.json` holding four normalised corners, the physical grid "
                    "geometry the fit was made against, and the camera projection identity it is "
                    "valid for."),
    ])
    rep.p("**Typical workflow:**")
    rep.numbered([
        "The frame is white-balanced first, driving its bright quantile to neutral. Without this "
        "the green ink is not green (Section 3.4.3).",
        "Two hue windows segment the two inks, on hue plus a saturation floor and not on "
        "brightness. The inks stay far apart in hue (green at 58 to 115 in OpenCV's 0 to 179 "
        "scale, magenta at 130 to 178, with nothing in between) and the saturation floor of 32 "
        "sits between the rig's green ink at 48 and its white paper at 15.",
        "Each blob becomes a rotated rectangle. Broad aspect, area and colour-purity checks "
        "decide which rectangles may vote on the median size and the long-axis direction; "
        "rejected blobs are still drawn, for diagnosis.",
        "Multiple breadth-first walks hand out integer lattice indices, hopping from cell to "
        "cell using *that cell's own* measured size times the known pitch-to-block ratio. Each "
        "connected hypothesis is fitted provisionally, and other blobs close to its integer grid "
        "sites are then recovered, which bridges a missed local hop without inventing an "
        "occluded cell.",
        "A homography is fitted from integer indices to cell centres, every cell is re-scored "
        "against the footprint the fit predicts **for it**, and the fit is repeated on the "
        "survivors.",
        "Every strongly supported mode-sized window (7 x 6 vertical, 3 x 10 horizontal) is "
        "retained, swept across both axes, ordered by distance from the image's bottom-left "
        "corner and capped at sixteen. The operator selects one and saves.",
    ])
    rep.p(
        "**Validation and constraints.** Colour parity, measured aspect ratio, mean residual and "
        "maximum residual are **hard acceptance gates**, not status readouts: a fit that fails "
        "any of them is refused rather than reported with a warning. A window needs at least "
        "95 % physical coverage with every row and column supported, so one underlit edge cell "
        "does not move the calibration but a clipped strip cannot pass. Partial cells, clipped "
        "by the edge of the paper or the edge of the frame, are excluded from the fit entirely "
        "and not down-weighted, because their centres and their sizes are both wrong. And a "
        "refusal always still draws what it found, in green for blobs that joined a lattice and "
        "red for those that did not, with the count and the stage in the corner: a blank window "
        "would make 'the sheet is out of shot', 'the colours are wrong' and 'the code never ran' "
        "look identical, which is precisely how the first live attempt was reported.")
    rep.p(
        "Which axis is machine X is never inferred from the image. The explicit mode decides it: "
        "vertical maps 2.2 cm to X, horizontal maps 6.0 cm to X, and the detected short and long "
        "lattice axes follow that declared geometry whichever way round the sheet was "
        "photographed. The complete 7 x 6 or 3 x 10 count is then cross-checked against the "
        "machine grid before calibration, so a partial sheet never causes an orientation guess.")
    rep.p(
        "When the gantry itself hides part of the sheet, an evidence-assisted variant of the "
        "same route pools accepted observations across several manually confirmed frames. It "
        "will fill an **interior** hole from the fitted geometry, and it will never fill an "
        "outer boundary: saving requires at least two accepted frames, at least four "
        "previously-verified cells of overlap between them, at least 60 % of the map physically "
        "observed, all four corner regions present, every outer edge supported, a merged "
        "residual of at most 2 px mean and 6 px maximum, and a repeated-cell spread of at most "
        "3 px proving the camera and the paper did not move.")

    rep.h3("4.3.4 From pixels to a cell")
    rep.p(
        "The saved map is deliberately small: four envelope corners plus the grid geometry, not "
        "a per-cell table. A consumer loads it, spaces the cells evenly between those corners, "
        "and can then answer both directions of the question: which cell is under this pixel, "
        "and which polygon on the image is this cell. The browser carries a TypeScript port of "
        "the same arithmetic for the local hover highlight, while the Python implementation "
        "stays authoritative for what is actually selected, because the browser is never trusted.")
    rep.p(
        "A saved map is only adopted by a consumer whose **projection** (lens profile, "
        "flip and rotation, correction on or off, framing region of interest) matches the one "
        "embedded in the map. A mismatch is refused with a sentence naming what changed, and a "
        "map saved with no projection at all is refused by everything: it writes successfully "
        "and is then silently ignored, which looks exactly like it worked. A map on disk also "
        "does not reach a running console by itself, because calibration normally happens in a "
        "separate process; there is an explicit reload action for that, and a map that is "
        "present but refused must surface its reason, since 'no calibration saved' and 'the "
        "camera moved' need opposite responses from an operator and silence is "
        "indistinguishable from both.")

    # ------------------------------------------------------------------
    rep.h2("4.4 Main System Operation")

    rep.h3("4.4.1 The fourteen-phase build cycle")
    rep.p(
        "One `B col row level` is one complete pick-and-place cycle. Every phase is announced "
        "before it runs, and every phase that can fail bails out immediately rather than "
        "carrying on with an unknown position.")
    rep.table(
        "The fourteen build phases. Phases 1 to 11 place the block; 12 to 14 park the rig.",
        ["#", "`phase` id", "`action`", "What the machine does"],
        [
            ["1", "`raise_clear`", "move", "Raise Z into the top switch, clear of everything "
                                           "already built."],
            ["2", "`home_feeder`", "move", "Home X and Y to the feeder cell [0,0]. Its centre "
                                           "**is** home, so there is no move afterwards."],
            ["3", "`neutralise_claw`", "rotate", "Return the claw to neutral before picking up. "
                                                 "Normally a no-op, because phase 14 already "
                                                 "did; it also corrects a manual jog."],
            ["4", "`open_claw`", "release", "Open the jaws, while still clear above the block."],
            ["5", "`lower_to_ground`", "move", "Lower Z into the bottom switch. **This also "
                                               "re-zeroes Z.**"],
            ["6", "`grip`", "grip", "Close the claw. The block is now held."],
            ["7", "`lift_block`", "move", "Raise Z into the top switch: carry height."],
            ["8", "`move_to_target`", "move", "Home, then move Y to the row and X to the column, "
                                              "with the X-rail skew compensation applied."],
            ["9", "`rotate_to_grid`", "rotate", "Apply the active grid's placement rotation, "
                                                "still above the stack."],
            ["10", "`lower_to_level`", "move", "Lower Z to the target block level."],
            ["11", "`release`", "release", "Open the claw. **The block is placed.** This is the "
                                           "one phase announced twice, with a `done` at the "
                                           "instant the jaws open."],
            ["12", "`park_clear`", "park", "Raise Z clear of the block just placed. This must "
                                           "happen before any X/Y move, or the claw would drag "
                                           "through the stack it just added to."],
            ["13", "`park_home`", "park", "Return X and Y to the origin."],
            ["14", "`park_rotation`", "park", "Return the claw to neutral, if this build turned "
                                              "it."],
        ],
        widths=[0.8, 4.0, 1.7, 8.5], size=9)
    rep.p(
        "Parking is not decoration. It leaves the machine in exactly the state a build expects "
        "to start from, so the rig is never left hanging over a stack with an open claw and the "
        "next `B` finds its first two phases already satisfied. It is also the one part of the "
        "cycle whose failures are treated differently: the block is already down by phase 12, so "
        "a parking failure cannot turn a good placement into a failed one, but it does leave "
        "the rig somewhere unknown, so the command's terminal result is downgraded from `OK` to "
        "`HELD`. Placed but not parked is not a success.")
    rep.figure("The fourteen-phase build cycle, drawn against the machine's axes: the pick at "
               "the feeder, the carry at top-switch height, the placement at the target level, "
               "and the park.",
               placeholder="Sequence diagram or annotated side elevation of the rig with the "
                           "fourteen phases numbered along the tool path.")

    rep.h3("4.4.2 The feed cycle")
    rep.p(
        "One `FEED <id>` is one complete dosing operation on the Uno, and it is a state machine "
        "rather than a sequence of delays, so that a stop command remains available throughout.")
    rep.table(
        "The feeder state machine.",
        ["State", "Belt", "Sensor sampled", "Leaves when"],
        [
            ["`closing`", "stopped", "-", "500 ms have elapsed"],
            ["`opening_stage_1`", "stopped", "-", "500 ms (gate at 90 degrees)"],
            ["`opening_stage_2`", "stopped", "-", "500 ms (gate at 160 degrees)"],
            ["`waiting_for_exit`", "stopped", "exit, every 100 ms",
             "a block is detected, or 10 s timeout"],
            ["`moving_to_stage`", "running", "stage, every 100 ms",
             "a block is detected, or 15 s timeout"],
            ["`aligning`", "stopped", "-", "350 ms (the aligner nudges and returns)"],
            ["`verifying_stage`", "stopped", "stage, read once after settling",
             "block still present -> success; block gone -> the belt resumes"],
            ["`block_ready`", "stopped", "-", "terminal success"],
        ],
        widths=[3.4, 2.0, 3.6, 6.0], size=9)
    rep.p("Three moments in that sequence are the whole reason the feeder exists:")
    rep.bullets([
        "**Before the container opens**, the stage sensor is read. If it already sees a block, "
        "the request is refused outright with `stage_occupied` and nothing moves. The pickup "
        "point is a single-owner resource, and an in-flight transaction is never cancelled and "
        "replaced, because its first block may already have left the hopper.",
        "**The instant the exit sensor fires**, the container is shut again, before the belt "
        "starts, so a second block cannot follow the first out. This is what turns a gate into a "
        "doser.",
        "**After the aligner has moved**, the stage sensor is read a second time. Only if the "
        "block is still there is `@id OK state=block_ready result=staged` emitted. If it has "
        "gone, the belt resumes instead of the feeder reporting a success it cannot see.",
    ])
    rep.p(
        "This is **sensor-stopped staging, not a fixed belt-duration guess**, and the two "
        "observations also distinguish an empty or blocked hopper path from a block that left "
        "the hopper and never arrived. The four terminal failures are `stage_occupied`, "
        "`exit_timeout` (no block seen leaving within 10 s), `stage_timeout` (a released block "
        "did not reach the pickup sensor within 15 s) and `cancelled`, and each names a different "
        "physical problem for the operator.")

    rep.h3("4.4.3 The guard stack")
    rep.p(
        "Every production placement passes through five layers, outermost first. Each one can "
        "refuse, and none of them can be skipped by the browser.")
    rep.numbered([
        "**The HTTP route** refuses a request that is not explicitly confirmed, one whose command "
        "string does not match the server's own computed command, a stale camera frame, a build "
        "that is already running, a locked session, or either board not being connected.",
        "**The build worker** refuses a second build on the worker thread. One at a time, and "
        "off the event loop, so a blocking multi-minute call cannot stall the web service.",
        "**The safety state** refuses everything while the session is locked, or when no cell is "
        "selected. This layer holds the selection, the level and the mode, and converts any "
        "exception from below into a session lock.",
        "**The two-board handoff** refuses when its own lock is set, or when another placement "
        "already owns the pickup point.",
        "**The serial clients** refuse an overlapping transaction, a board that is not "
        "connected, or a board whose identity does not match the configuration.",
    ])
    rep.p(
        "Above all five sits the rule that the browser is a mirror. It sends a request and "
        "renders what the server reports; every guard is re-checked on the Pi, and a greyed-out "
        "button in the interface is a courtesy, never the safety mechanism.")

    rep.h3("4.4.4 The two-board handoff")
    rep.p(
        "One placement is **one indivisible operation owned by the Pi**: stage exactly one block "
        "on the Uno, then, only on its exact terminal success, place it with the Mega.")
    rep.code(
        "Pi (CellOrchestrator)              Uno (belt_v1)            MEGA (build_test_v1)\n"
        "  phase=feeding\n"
        "  feed(timeout=45s) ---- FEED <id> -->\n"
        "                     <-- @id RECV cmd=FEED\n"
        "                     <-- @id ACK cmd=FEED accepted=1\n"
        "                     <-- @id STATE state=closing ... verifying_stage\n"
        "                     <-- @id EVENT phase=...           (progress only)\n"
        "                     <-- @id OK state=block_ready result=staged   <- the ONLY success\n"
        "  phase=ready_for_pick\n"
        "  phase=placing\n"
        "  build(col,row,level) ------------------- B <col> <row> <level> -->\n"
        "                                       <-- @seq RECV cmd=B ...\n"
        "                                       <-- @seq STEP step=n/14 phase=... status=begin\n"
        "                                       <-- @seq OK col=... row=... level=...  <- PLACED\n"
        "  phase=complete  ->  BuildResult(PLACED)")
    rep.p("The rules enforced on that sequence are absolute:")
    rep.bullets([
        "**Only** a terminal `@id OK state=block_ready result=staged` whose `id` matches the "
        "request authorises the `B`. `ACK`, `STATE`, `SENSOR` and `EVENT` are progress and never "
        "success. A terminal with the wrong id is ignored.",
        "A malformed success, meaning anything other than `result=staged`, is treated as a **failure**, "
        "not as permission.",
        "On any feeder error, timeout, disconnect or reset before the `OK`: **no `B` is sent**, "
        "the orchestrator locks and the result is `ABORTED`.",
        "After the `B` has been sent, **any** non-placed Mega result also locks, including a "
        "`SAFE` rejection, which is entirely safe for a bare gantry but not for the cell, "
        "because a block is already staged and feeding another would double-load the pickup "
        "point.",
        "One `FEED` at a time. The next one never starts until the previous `B` has returned a "
        "terminal `PLACED`.",
    ])
    rep.table(
        "Result and lock behaviour.",
        ["Outcome", "Result", "Session", "Recovery"],
        [
            ["Uno staged, Mega `OK`", "`placed`", "READY, selection cleared", "continue"],
            ["Uno error / timeout / reset before `B`", "`aborted`", "**LOCKED**",
             "inspect the pickup area, restart the service"],
            ["Uno `OK`, then Mega `SAFE` / rejected", "`aborted`", "**LOCKED**",
             "a block is staged; inspect, then restart"],
            ["Uno `OK`, then Mega `HELD` / timeout / cable loss", "`aborted`", "**LOCKED**",
             "machine state unknown; inspect, then restart"],
            ["Operator stop during the feed", "`aborted` (`cancelled`)", "**LOCKED**",
             "inspect, then restart"],
        ],
        widths=[5.4, 2.8, 3.2, 3.6], size=9)
    rep.p(
        "The lock is deliberately sticky: a new service process is the required recovery. "
        "Nothing is auto-retried, because a retried `FEED` or `B` risks a double-load or a "
        "duplicate placement, and neither of those announces itself.")
    rep.p(
        "Stop has two meanings depending on where the operation is. While the Uno owns it "
        "(feeding or staging), stop actively sends the Uno a `STOP`, the feed waiter observes a "
        "terminal `cancelled`, and the session locks for inspection. Once the Mega is moving, "
        "stop is **stop after the current block**, because the Mega does not read serial inside "
        "its build cycle. The interface says exactly that, in those words, and never offers a "
        "control that implies otherwise.")

    # ------------------------------------------------------------------
    rep.h2("4.5 Additional Operating Modes")

    rep.h3("4.5.1 Browser click-to-build")
    rep.defs([
        ("What it does", "Lets an operator place one block by tapping a cell on the live camera "
                         "image."),
        ("Inputs", "A tap on the camera view, a level from a stepper control, and two "
                   "confirmations."),
        ("Outputs", "One complete guarded feed-then-place operation, and a terminal result."),
        ("Typical workflow", "1. Tap a cell. This selects it; nothing moves. 2. The panel shows "
                             "the exact command, `B 3 2 1`. 3. Tap BUILD, then CONFIRM. 4. The "
                             "server sends one correlated `FEED`, then the `B`. 5. The result is "
                             "PLACED (green, selection cleared), REJECTED (amber, nothing moved, "
                             "selection kept) or ABORTED (red, session locked)."),
        ("Validation and constraints", "BUILD is disabled unless both boards are connected. "
                                       "Every mutation is refused while a build is running. A "
                                       "stale camera frame blocks selection and build. There is "
                                       "no cancel and no retry control, because the machine "
                                       "cannot honour either."),
    ])
    rep.figure("The browser operator console: live camera view with the grid overlay, the "
               "selected cell and its exact command, the level stepper, and the status rail.",
               placeholder="Screenshot of the console on a phone or tablet, with a cell selected "
                           "and the command line visible.")

    rep.h3("4.5.2 The 3D Build Studio")
    rep.p(
        "The Studio is the flagship of the software side and the normal entry point for building "
        "a structure. It is a design environment, a physics validator, a compiler and an "
        "execution runner, all against the machine's real lattice.")
    rep.defs([
        ("What it does", "Lets a person design a 3D structure block by block on the machine's "
                         "own grid, tells them immediately whether it is physically buildable, "
                         "compiles it to an ordered command program, and then runs that program "
                         "against the rig one guarded block at a time."),
        ("Inputs", "Mouse or touch placement in a live 3D scene; the machine's grid geometry, "
                   "imported directly from the same configuration file the Pi reads, so there is "
                   "no second copy of the geometry anywhere."),
        ("Outputs", "A saved `rigmodel/1` design in the browser's own library; a compiled "
                    "program of `B col row level` commands separated by `R` and `RR` latches; "
                    "and, after a run, a Markdown run report."),
    ])
    rep.p("**The validator** answers three physical questions before anything is compiled:")
    rep.bullets([
        "**Support**: does the block rest on something, and is that support a centre-of-mass "
        "toppling test rather than a contact-ratio shortcut?",
        "**Collision**: does it overlap a block already placed, in machine space and not in "
        "grid indices, so that a horizontal block spanning two vertical columns is checked "
        "correctly?",
        "**Reachability**: is the cell inside the active grid, and is the level inside the "
        "firmware's build ceiling?",
    ])
    rep.p(
        "**The compiler** is the intellectual core. `B col row level` carries no orientation, so "
        "a mixed-orientation model is a partial order that has to be sorted into same-mode runs, "
        "each run costing a homing move for its latch. It runs in four named steps:")
    rep.numbered([
        "**Support graph**: block id to the ids it rests on, from machine-space footprint "
        "overlap at the matching base and top heights. A horizontal span depends on every "
        "vertical stack under it.",
        "**Ordering**: Kahn's algorithm, with the ready set re-sorted on every pop by a "
        "comparator chain: by level (bottom-up, so a block can never precede its support), then "
        "by the currently latched mode (stateful, recomputed against the mode the emitter would "
        "be in by then), then by the author's own order wherever that is still legal, then by "
        "cell, then by id so that ties cannot exist.",
        "**Emission**: a one-variable latch state machine that emits a mode command only on an "
        "actual change, annotated with its cost.",
        "**Summary**: blocks, latches, levels and a time estimate.",
    ])
    rep.p(
        "Two properties of the compiler are enforced by tests and not asserted in prose. "
        "**It is deterministic**: the same model compiles twenty times to byte-identical output, "
        "and the program depends only on the author's order and not on the internal array order. "
        "And **an invalid model compiles to nothing at all** (an empty program, zeroed "
        "statistics and the diagnostics) rather than to a half-program, because a half-program "
        "is the single most dangerous artefact this codebase could produce.")
    rep.figure("The 3D Build Studio: the design scene on the machine's lattice, the level "
               "scrubber, the diagnostics panel and the compiled program view.",
               placeholder="Screenshot of the Studio with a multi-level, mixed-orientation "
                           "model open and its compiled program visible alongside.")

    rep.h3("4.5.3 The live digital twin")
    rep.p(
        "Beside the camera view sits a 3D twin of the rig that mirrors the real build as it "
        "happens. The whole of it is one pure function from the server's state to a picture, and "
        "the component simply draws what that function returns, which is what makes the twin's "
        "behaviour testable against recorded server sessions and not only observable.")
    rep.p("Two rules define it:")
    rep.bullets([
        "**It never invents state.** A block is drawn as placed because the server reported a "
        "terminal placed result for it, and for no other reason. There is no optimistic "
        "placement.",
        "**After an abort it stops.** A locked session freezes the animation, desaturates every "
        "block, drops the target marker and demotes everything unconfirmed to a ghost. The "
        "machine's real state is unknown after an abort, and a twin still cheerfully rendering "
        "the plan is at its most misleading exactly when misleading is most expensive.",
    ])
    rep.p(
        "The twin is **phase-driven**, from the firmware's own `STEP` lines, and it deliberately "
        "carries no descent timer of its own. An earlier version interpolated a looping "
        "1.6-second descent from the browser's clock and returned a height nobody had measured; "
        "it looped, so a forty-second build showed twenty-five descents that had never happened. "
        "What replaced it says only what the firmware said. The carried block has exactly two "
        "heights, travel and zero, and it drops to zero on the release event, which is a fact. "
        "The one animation a clock drives is the placement descent, and it is fenced four ways: "
        "it starts from the moment the phase event arrived, its duration is the machine's own "
        "`ms=` arithmetic, it is clamped short of the cell so it **cannot** reach it, and with no "
        "`ms=` it does nothing at all rather than guessing. If Z jams, the block glides down, "
        "stops just short and sits there visibly not landing, which is the truth.")
    rep.figure("The live digital twin beside the camera view during a build, showing the "
               "carried block, the current phase and the confirmed placements.",
               placeholder="Screenshot of the twin panel mid-build, ideally with the camera "
                           "view of the same moment beside it.")

    rep.h3("4.5.4 The execution runner")
    rep.p(
        "The runner takes a compiled program and dispatches **one guarded request at a time**, "
        "waiting for the durable terminal result before the next. It offers STEP (one block), "
        "RUN (continuous) and DRY RUN (the whole program with no API traffic at all, for "
        "rehearsal), shows the current command, the blocks placed against the total, the elapsed "
        "time and an estimate from measured cycle time, and exports a Markdown run report of "
        "the session.")
    rep.p(
        "It never relaxes a safety rule. A `HELD` result locks the run; a `SAFE` rejection pauses "
        "it and keeps it resumable; a lost socket pauses and resumes on the next phase event "
        "and not on a timer; and 'STOP AFTER THIS BLOCK' becomes 'CANCEL FEED' while the "
        "feeder still owns the operation, because during that window a stop genuinely can act. "
        "The panel's next-block colour line is a preview only, and never implies that a second "
        "feed is already running.")

    rep.h3("4.5.5 Commissioning and simulation modes")
    rep.defs([
        ("Full simulation",
         "The entire software chain (web service, orchestrator, both serial clients and camera) "
         "runs against a protocol-level fake Mega, a protocol-2 fake Uno with failure, reset and "
         "cancel controls, and a mock camera that renders blocks at real grid cells. No hardware "
         "at all. This is how the console and the Studio are developed and rehearsed, and how "
         "the runner's cycle-time constant was measured."),
        ("Desktop click-to-build",
         "The original OpenCV tool the browser console replaced. It still works, and it is the "
         "fastest way to drive the rig from the machine it is plugged into: click a cell on the "
         "camera view, choose a level, confirm the displayed command."),
        ("Serial commissioning consoles",
         "One per board. A direct line to the Mega for homing, jogging, grid reports and single "
         "builds, and one to the Uno for status, feed, belt direction and the container gate. "
         "These are the tools the commissioning checklists are written against."),
        ("Standalone calibration tools",
         "Camera Studio, which owns the lens, colour, sensor and framing settings and writes "
         "them to disk; the printed-sheet detector on its own; the evidence-assisted collector; "
         "and the placed-block calibrator with a hardware-free dry-run mode."),
    ])
    rep.p(
        "The mock mode deserves one more sentence, because it is the reason the software could "
        "be developed at all. The rig is a shared, slow, physically hazardous resource that "
        "takes half a minute to answer a question. A protocol-level fake that speaks exactly the "
        "same acknowledgement grammar turns that half a minute into a millisecond, and it is why "
        "the two-board handoff, the session-lock behaviour and the whole browser stack could be "
        "tested exhaustively without ever risking the machine.")
