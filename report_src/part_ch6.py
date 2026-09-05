"""Chapter 6, References and Appendices."""


def chapter_6(rep):
    rep.h1("6. Conclusion and Future Work")

    rep.h2("6.1 Conclusion")
    rep.p(
        "This project set out to build a machine that constructs a human-designed 3D block "
        "structure with no human placing a block by hand, and that confirms every physical "
        "transition with a sensor or a camera rather than with a timer. The result is a complete "
        "robotic cell: a CoreXY gantry with an added Z axis and a rotating mechanical claw, a "
        "separate feeder that doses one block at a time and proves it twice, an overhead vision "
        "system that maps camera pixels to grid cells, and a browser software chain in which a "
        "person designs a structure, compiles it, and watches a live digital twin mirror the "
        "real build from the machine's own telemetry.")
    rep.p(
        "The machine works. Sixteen complete pick-and-place cycles were executed on hardware and "
        "all sixteen completed, at 19.8 to 32.2 seconds per block, with the fixed part of the "
        "cycle repeating to within 0.18 s across every one of them. A five-level stack was built "
        "one command at a time on a single cell, and the descent shortened by 0.160 s per level "
        "against the 0.145 s the block height predicts, which is the machine measuring its own geometry. "
        "Both grid orientations ran on hardware. The vision system finds all 29 blocks on a full "
        "board while correctly rejecting the aluminium rails and the two wooden offcuts that "
        "look exactly like blocks, and the grid fit selects its own model on held-out prediction "
        "error and not on training error. The software is covered by 492 browser tests and "
        "68 Python protocol tests.")
    rep.p("Measured against the objectives of Section 1.3:")
    rep.numbered([
        "**Reach and place on every cell, at any level. Met.** 41 buildable vertical cells and "
        "29 horizontal, at levels 0 to 16 by the firmware ceiling. Levels 0 to 4 and columns 0 "
        "to 5 were exercised on hardware.",
        "**Two block orientations. Met.** Two separately calibrated grids, latched by a command "
        "that moves nothing; both were exercised on hardware.",
        "**A feeder with confirmation at both ends. Met in design and in firmware**, with both "
        "sensors, all four terminal failures and the two-stage gate implemented and "
        "commissioned. The full feed-to-place chain on hardware is the one piece of evidence "
        "this report could not produce from the logs (Section 5.6.2).",
        "**Vision detection and pixel-to-cell mapping. Met.** 29 of 29 detection with correct "
        "rejection of non-blocks, a 0.85 px mean fit residual, and 0.27 cm of mapping error "
        "through the saved format.",
        "**Browser operation. Met.** Live camera view, tap to select, two-tap confirm, from a "
        "phone on the local network.",
        "**Design, validate and compile a structure. Met.** The Studio validates support, "
        "collision and toppling, and compiles deterministically to an ordered program with "
        "minimal mode latches.",
        "**The safety model. Met in software**, at five independent layers, with `SAFE` and "
        "`HELD` as separate protocol kinds so that the dangerous retry cannot be written by "
        "accident. **Not met in hardware**: there is no emergency stop, and that gap is stated "
        "throughout and not hidden.",
        "**Cycle time under 45 s. Met.** 26.1 s mean and 32.2 s worst case, for a direct gantry "
        "build.",
    ])

    rep.p(
        "What the project demonstrates best is not any one of those. It is the discipline "
        "underneath them: a design in which no part of the system is allowed to assume what "
        "another part has actually done. The feeder does not report success because time passed; "
        "it reports success because a sensor saw a block and then saw it again after the aligner "
        "moved. The gantry does not tell the Pi it is fine; it narrates each of its fourteen "
        "phases before running it and predicts how long the slow ones will take. The twin does "
        "not animate a placement; it draws what the firmware said and stops short of the cell "
        "until the release event arrives. And when the machine cannot prove what physically "
        "happened, it locks and asks for a person rather than retrying.")
    rep.p(
        "The honest limits are equally clear, and they are limits of the hardware rather than of "
        "the approach. There is no emergency stop and no way to interrupt a motion. The steppers "
        "are open-loop and cannot detect a stall. The lens is tuned by eye and not "
        "calibrated. Placement supervision, the layer that would let the camera notice a block "
        "that never arrived, is fully designed and not built. Several measurements that would "
        "have made this report stronger were never taken, and they are marked as such and not filled in with plausible numbers.")

    rep.h2("6.2 Future Work")

    rep.h3("6.2.1 Safety, first")
    rep.numbered([
        "**A hardwired emergency stop.** A real path that removes hazardous motion energy "
        "independently of Python, USB, the event loop and firmware parsing: a latching mushroom "
        "button in series with a contactor on the 12 V motor rail, with a defined restart "
        "procedure. Every other item on this list is optional; this one is not.",
        "**Make stop observable during motion.** The gantry's blocking loops would have to "
        "become a cooperatively serviced state machine, or poll a dedicated hardware stop input "
        "inside every pulse loop. A serial stop command alone is not enough, because the "
        "firmware does not read serial while it moves.",
        "**A communications watchdog.** A lease from the Pi that the firmware requires to keep "
        "moving, so that a crashed master or a pulled cable brings the machine to a defined safe "
        "state rather than leaving it to finish whatever it was told last. The requirement is "
        "that the safe state is genuinely safe, not merely a reset mid-carry.",
        "**Electrical protection.** A fuse in the 12 V line sized to the supply, "
        "reverse-polarity protection at the input, and flyback protection on the servo rail.",
    ])

    rep.h3("6.2.2 Closing the loop on placement")
    rep.p(
        "The single most valuable feature that is designed and not built is **placement "
        "supervision**. The rig places a block and forgets it, so nothing in the system can "
        "notice when the board stops matching the plan. The detection half already exists and "
        "already labels every detection with an integer cell; three things are missing:")
    rep.bullets([
        "**A server-side ledger** of what has been placed, which cell it went to and which level: "
        "the cumulative record that `last_result` and a selection cannot provide.",
        "**A rule for when it is safe to look.** The gantry occludes part of the surface, so a "
        "comparison made mid-cycle would report blocks missing that are simply behind the arm. "
        "The park state at the end of every build is the natural moment, and it is already a "
        "known, repeatable position.",
        "**A firmware verb that can retrieve a block from a cell.** `B` picks from the feeder "
        "and places; there is no pick-from-cell, so at present the machine can notice a wrong "
        "placement and can do nothing about it. A `P col row level` verb would make the "
        "supervision actionable rather than advisory.",
    ])

    rep.h3("6.2.3 Measurement and calibration")
    rep.numbered([
        "**A proper checkerboard or ChArUco lens calibration**, photographed at several "
        "positions and angles, replacing the by-eye tuning. This is what would turn the vision "
        "system from visually straight into measurement-grade, and it is a prerequisite for "
        "taking the camera's word about anything metric.",
        "**Widen the saved calibration format** to carry a per-cell table instead of four "
        "envelope corners. That is the one change that removes the 0.27 cm mid-grid flattening "
        "error, and it touches every consumer of the format.",
        "**Take the measurements this report had to leave open**: absolute placement accuracy "
        "against a commanded cell, homing repeatability with a dial indicator, the residual Y "
        "error after the skew compensation, a pick-and-place success rate over a run of a "
        "hundred placements.",
        "**Fix the camera rather than the matrix.** The colour correction has reached its useful "
        "limit at 0.669 similarity; a lens with less veiling glare, or simply a longer lens "
        "further away, would do more than another iteration of the fit.",
    ])

    rep.h3("6.2.4 Protocol and software")
    rep.numbered([
        "**Controller-supplied command ids.** The Mega should echo an id the Pi chose rather than incrementing its own counter, and the Pi's waiter should reject a terminal "
        "acknowledgement that does not match. That single change removes the late-acknowledgement "
        "class of bug entirely and lets the prose fallback be deleted.",
        "**A structured response for every command**, not only for `B`. `S`, `G`, `0` and `0+` "
        "are still completed by matching human prose and a quiet-line heuristic, which breaks "
        "the day someone rewords a message.",
        "**One command arbiter for every public send**, so that a raw serial write cannot bypass "
        "the in-flight lock, plus an operating-system-level exclusive open so that a second "
        "process cannot silently take a board.",
        "**Discard an overlong command line until the next terminator**, so that the tail of a "
        "too-long command can never become an executable command.",
    ])

    rep.h3("6.2.5 Capability")
    rep.numbered([
        "**Closed-loop or stall-detecting motion.** Encoders on X, Y and Z, or driver "
        "stall detection, would turn the one failure the machine cannot currently see into one "
        "it can. It would also allow the re-home before every move to be dropped, which is worth "
        "about a third of the cycle time.",
        "**Painted blocks and a colour-sorting feeder.** The supply is currently bare wood in "
        "one uniform colour, and both the detector and the Studio already carry colour "
        "handling that nothing exercises: the Studio can assign a colour per block and "
        "preview which one must be staged next, while the feeder stages whatever is at the "
        "bottom of the hopper. Painting the supply and adding a sorting stage would turn "
        "colour into a real design dimension instead of unused capability.",
        "**A faster serial link.** 9600 baud is the reason telemetry is limited to one line per "
        "phase. Raising it, in all three places that define it together, would allow "
        "throttled continuous position reporting and a twin that shows real motion and not "
        "phase transitions.",
        "**A larger workspace, and a taller one.** The current envelope is a table-sized "
        "compromise. The frame stock and the CoreXY layout would both support a considerably "
        "larger machine, and the build ceiling of 25 cm is set by the Z travel rather than by "
        "anything fundamental.",
        "**Plan projection onto the live camera.** Drawing the compiled program's remaining "
        "blocks onto the real camera image, in place, would make the design and the machine the "
        "same picture, and it is a small amount of work on top of a homography that already "
        "exists.",
        "**Session evidence.** A timeline of every build with its timestamp, command, result, "
        "duration and a camera thumbnail; a time-lapse export made from a frame saved at every "
        "placement; and a run report exported as a document. All three are close to free, "
        "because the frames and the events already flow through the pipeline.",
    ])


def references(rep):
    rep.h1("References")
    rep.p("Sources are listed in the order they are first referred to in the report.")
    items = [
        "Greg06, \"Automated Chessboard\", Instructables, 1 March 2022. "
        "https://www.instructables.com/Automated-Chessboard/. The CoreXY X/Y table and the "
        "limit-switch homing scheme this project's gantry is a modified version of.",

        "G. Bradski, \"The OpenCV Library\", Dr. Dobb's Journal of Software Tools, 2000, and "
        "the OpenCV fisheye camera model documentation. The lens correction, the homography fit "
        "and the contour operations used by the block detector.",

        "R. Hartley and A. Zisserman, \"Multiple View Geometry in Computer Vision\", 2nd ed., "
        "Cambridge University Press, 2004. The direct linear transform, its normalisation and "
        "the conditioning measure used as a calibration gate in Section 5.4.2.",

        "A. B. Kahn, \"Topological sorting of large networks\", Communications of the ACM, "
        "5(11), 1962. The ordering algorithm used by the Studio's compiler.",

        "Toshiba, \"TB6600 Stepper Motor Driver\" application data, and Allegro MicroSystems, "
        "\"A4988 DMOS Microstepping Driver with Translator and Overcurrent Protection\". The "
        "gantry and feeder motor drivers.",

        "Raspberry Pi Ltd., \"Raspberry Pi 5 Product Brief\" and \"Picamera2 Library Manual\". "
        "The master controller and the only supported camera interface on the Pi 5's CSI bus.",

        "[[VALUE NEEDED: add any lecture notes, textbooks or standards your department expects "
        "to see cited, and re-format this list into your institution's required citation style "
        "(IEEE, APA or whichever applies).]]",
    ]
    for i, it in enumerate(items, 1):
        rep.reference(i, it)
    rep.note(
        "The reference project's Micro-Max chess engine is **not** used anywhere in this "
        "project, and no other third-party source code was incorporated beyond the libraries "
        "listed above.")


def appendices(rep):
    rep.h1("Appendices")

    # ---- A ----
    rep.h2("Appendix A: Bill of Materials")
    rep.table(
        "Compute and control.",
        ["Item", "Qty", "Note"],
        [
            ["Raspberry Pi 5, 8 GB RAM", "1", "Master controller"],
            ["Arduino MEGA 2560", "1", "Gantry controller"],
            ["Arduino Uno", "1", "Feeder controller"],
            ["Raspberry Pi camera module, OV5647, 160 deg fisheye, + ribbon", "1",
             "DORHEA module"],
        ],
        widths=[8.4, 1.4, 5.2], size=9)
    rep.table(
        "Motion, actuators and sensors.",
        ["Item", "Qty", "Note"],
        [
            ["NEMA17 stepper motor", "4", "2 CoreXY, 1 Z, 1 feeder belt"],
            ["TB6600 stepper driver", "3", "The three gantry axes"],
            ["A4988 stepper driver", "1", "Feeder belt"],
            ["28BYJ-48 stepper motor, 5 V", "1", "Claw rotation"],
            ["ULN2003 driver board", "1", "For the 28BYJ-48"],
            ["Hobby servo", "3", "Gripper, container gate, aligner"],
            ["Micro limit switch", "4", "X home, Y home, Z bottom, Z top"],
            ["HC-SR04 ultrasonic sensor", "1", "Container exit"],
            ["IR obstacle sensor", "1", "Pickup stage, active-low by default"],
        ],
        widths=[8.4, 1.4, 5.2], size=9)
    rep.table(
        "Mechanical.",
        ["Item", "Qty", "Note"],
        [
            ["Linear rail + linear motion bearing", "1", "1.5 m x 15 mm; carries the Z axis"],
            ["Aluminium profile", "3.6 m", "Cut from 6 m stock: 4 legs at 15 cm, 3 members "
                                            "along X at 30 cm, 2 along Y at 60 cm, 2 for the "
                                            "feeder at 30 cm, 1 for the Z column at ~30 cm"],
            ["GT2 timing pulley", "~9", "Drive and idler pulleys, CoreXY and Z"],
            ["GT2 timing belt", "5 m", "Plus 1 m of additional belt"],
            ["Belt sheet", "1", "The conveyor surface"],
            ["Castor wheel", "8", "X/Y guidance, on 3D-printed carriages"],
            ["3D-printed parts", "many", "Carriages, the claw, the conveyor parts, mounts"],
            ["Wooden blocks, 2.2 x 6.0 x 1.5 cm",
             "30", "Bare wood, one uniform colour"],
        ],
        widths=[8.4, 1.4, 5.2], size=9)
    rep.table(
        "Electrical and power.",
        ["Item", "Qty", "Note"],
        [
            ["Switched-mode power supply, 12 V / 15 A", "1", "Motor rail"],
            ["LM2596 adjustable buck converter, 4-40 V in, 1.25-37 V out, 3 A, with display",
             "1", "Set to 5 V"],
            ["Raspberry Pi 5 official USB-C power supply", "1", "The Pi only"],
            ["Resistors and capacitors, assorted", "1 lot",
             "A4988 current reference and local decoupling"],
            ["Connectors, cropped M/M jumper leads, heat-shrink", "1 lot", "All signal wiring"],
        ],
        widths=[8.4, 1.4, 5.2], size=9)
    rep.p(
        "[[VALUE NEEDED: this bill of materials is the working list from the repository and is "
        "not costed, and it is missing several items you will want in the submitted version: "
        "the camera support structure, the build surface / holder material, the block stock, "
        "fasteners, and the 3D-printing filament. Add a cost column if your department requires "
        "one.]]")

    # ---- B ----
    rep.h2("Appendix B: Pin Mappings")
    rep.p(
        "Both tables are taken directly from the firmware sources and not from any "
        "documentation of them.")
    rep.table(
        "Arduino MEGA 2560 gantry controller: pin map.",
        ["Pin", "Direction", "Connected to", "Function"],
        [
            ["2", "output", "TB6600 #1 DIR", "Motor 1 direction (CoreXY)"],
            ["3", "output", "TB6600 #1 STEP", "Motor 1 step pulse"],
            ["4", "output", "TB6600 #1 EN", "Motor 1 enable, **active LOW**"],
            ["6", "output", "Gripper servo signal", "Claw jaws: OPEN 0 deg, CLOSE 54 deg"],
            ["8", "output", "TB6600 #2 DIR", "Motor 2 direction (CoreXY)"],
            ["9", "output", "TB6600 #2 STEP", "Motor 2 step pulse"],
            ["10", "output", "TB6600 #2 EN", "Motor 2 enable, active LOW"],
            ["11", "output", "TB6600 #3 DIR", "Z direction"],
            ["12", "output", "TB6600 #3 STEP", "Z step pulse (no enable line fitted; the driver "
                                               "is permanently enabled)"],
            ["28", "input, pull-up", "Z bottom limit switch", "Z home / GROUND reference, NC"],
            ["29", "input, pull-up", "Z top limit switch", "Z far-end stop, NC"],
            ["30", "input, pull-up", "X limit switch", "X home / zero, NC"],
            ["31", "input, pull-up", "Y limit switch", "Y home / zero, NC"],
            ["36", "output", "ULN2003 IN2 (green)", "Claw rotation stepper"],
            ["37", "output", "ULN2003 IN4 (red)", "Claw rotation stepper"],
            ["38", "output", "ULN2003 IN1 (black)", "Claw rotation stepper"],
            ["39", "output", "ULN2003 IN3 (blue)", "Claw rotation stepper"],
            ["USB", "serial", "Raspberry Pi", "9600 8N1"],
        ],
        widths=[1.4, 2.6, 4.4, 6.6], size=9)
    rep.note(
        "The stepper library is constructed in the order **IN1, IN3, IN2, IN4**, which is pins 38, 39, "
        "36 and 37, and which is the correct coil order for most 28BYJ-48 and ULN2003 boards and is "
        "not the same as pin order. Wiring it in numerical order produces a motor that buzzes "
        "and does not turn.")
    rep.table(
        "Arduino Uno feeder controller: pin map.",
        ["Pin", "Direction", "Connected to", "Function"],
        [
            ["2", "output", "A4988 DIR", "Belt direction"],
            ["3", "output", "A4988 STEP", "Belt step pulse (ENABLE is tied to ground)"],
            ["4", "output", "Exit HC-SR04 TRIG", "Container-exit sensor trigger"],
            ["5", "input", "Exit HC-SR04 ECHO", "Container-exit sensor echo"],
            ["6", "output", "Alignment servo signal", "Rest 90 deg, nudge 120 deg"],
            ["8", "input", "Stage IR OUT", "Pickup-point presence sensor, active-low by default"],
            ["12", "output", "Container servo signal",
             "Closed 20 deg, stage 1 at 90 deg, open 160 deg"],
            ["USB", "serial", "Raspberry Pi", "9600 8N1, protocol 2"],
        ],
        widths=[1.4, 2.6, 4.4, 6.6], size=9)

    # ---- C ----
    rep.h2("Appendix C: Serial Protocols")

    rep.h3("C.1 Gantry (MEGA) acknowledgement lines")
    rep.code(
        "@<seq> <KIND> [reason text | key=value ...]\n"
        "\n"
        "@0  BOOT  fw=build_test_v1\n"
        "@0  READY grid=6x5 mode=vertical\n"
        "@n  RECV  cmd=B col=3 row=5 level=0\n"
        "@n  STEP  step=8 total=14 phase=move_to_target action=move \\\n"
        "          text=Move_XY_to_the_target_cell status=begin\n"
        "@n  STEP  step=11 total=14 phase=release action=release \\\n"
        "          text=Open_the_claw_and_release status=done\n"
        "@n  ERR   expected: B <col> <row> <level>\n"
        "@n  SAFE  cell out of range\n"
        "@n  HELD  Z never reached the ground switch\n"
        "@n  OK    col=3 row=5 level=0")
    rep.p(
        "`OK`, `ERR`, `SAFE` and `HELD` are terminal; `BOOT`, `READY`, `RECV` and `STEP` are "
        "not. Sequence 0 means nobody asked. Every ack literal is stored in flash rather than "
        "SRAM. A `BUSY` kind is reserved and understood by the Pi's parser but is not emitted, "
        "because the firmware runs one command at a time and never sees a second.")

    rep.h3("C.2 A complete build transaction")
    rep.code(
        "@12 RECV cmd=B col=3 row=5 level=0\n"
        "@12 STEP step=1  total=14 phase=raise_clear      action=move    status=begin ms=2570\n"
        "@12 STEP step=2  total=14 phase=home_feeder      action=move    status=begin\n"
        "@12 STEP step=3  total=14 phase=neutralise_claw  action=rotate  status=begin\n"
        "@12 STEP step=4  total=14 phase=open_claw        action=release status=begin\n"
        "@12 STEP step=5  total=14 phase=lower_to_ground  action=move    status=begin ms=2570\n"
        "@12 STEP step=6  total=14 phase=grip             action=grip    status=begin\n"
        "@12 STEP step=7  total=14 phase=lift_block       action=move    status=begin ms=2570\n"
        "@12 STEP step=8  total=14 phase=move_to_target   action=move    status=begin\n"
        "@12 STEP step=9  total=14 phase=rotate_to_grid   action=rotate  status=begin\n"
        "@12 STEP step=10 total=14 phase=lower_to_level   action=move    status=begin ms=2386\n"
        "@12 STEP step=11 total=14 phase=release          action=release status=begin\n"
        "@12 STEP step=11 total=14 phase=release          action=release status=done\n"
        "@12 STEP step=12 total=14 phase=park_clear       action=park    status=begin ms=2570\n"
        "@12 STEP step=13 total=14 phase=park_home        action=park    status=begin\n"
        "@12 STEP step=14 total=14 phase=park_rotation    action=park    status=begin\n"
        "@12 OK col=3 row=5 level=0")
    rep.p(
        "The `text=` field is omitted above for width; on the wire every `STEP` line also "
        "carries the underscored human label.")

    rep.h3("C.3 Feeder (Uno) protocol 2")
    rep.code(
        "@0 READY firmware=belt_v1 protocol=2 board=uno\n"
        "\n"
        "> FEED 42\n"
        "@42 RECV   cmd=FEED\n"
        "@42 SENSOR sensor=stage detected=0\n"
        "@42 ACK    cmd=FEED accepted=1\n"
        "@42 STATE  state=closing\n"
        "@42 EVENT  phase=container_closing\n"
        "@42 STATE  state=opening_stage_1\n"
        "@42 STATE  state=opening_stage_2\n"
        "@42 STATE  state=waiting_for_exit\n"
        "@42 STATE  state=moving_to_stage\n"
        "@42 SENSOR sensor=exit distance_cm=7.4 detected=1\n"
        "@42 EVENT  phase=exit_detected_container_closed_belt_running distance_cm=7.4\n"
        "@42 STATE  state=aligning\n"
        "@42 SENSOR sensor=stage detected=1\n"
        "@42 STATE  state=verifying_stage\n"
        "@42 STATE  state=block_ready\n"
        "@42 SENSOR sensor=stage detected=1\n"
        "@42 EVENT  phase=block_ready\n"
        "@42 OK     state=block_ready result=staged")
    rep.p(
        "Only the final `OK` is permission to pick the block up. `ACK`, `STATE`, `SENSOR` and "
        "`EVENT` are progress telemetry. The four terminal failures are `stage_occupied`, "
        "`exit_timeout`, `stage_timeout` and `cancelled`.")

    # ---- D ----
    rep.h2("Appendix D: Firmware Constants")
    rep.table(
        "The gantry firmware's physical constants. These live only in the sketch and are "
        "deliberately not copied into the Pi's configuration, because nothing can push them "
        "over serial.",
        ["Constant", "Value", "Meaning"],
        [
            ["`SOFT_LIMIT_X_TRAVEL`", "4,550 steps", "X travel cap"],
            ["`SOFT_LIMIT_Y_TRAVEL`", "7,600 steps", "Y travel cap"],
            ["`X_TRAVEL_CM`", "22.8 cm", "Measured holder displacement over that cap"],
            ["`Y_TRAVEL_CM`", "38.0 cm", "The same, for Y"],
            ["`Z_TRAVEL_STEPS`", "1,350 steps", "Switch to switch; calibration only"],
            ["`Z_TRAVEL_CM`", "26.5 cm", "Switch to switch, tape-measured"],
            ["`BLOCK_HEIGHT_CM`", "1.5 cm", "One stack level"],
            ["`MAX_BUILD_HEIGHT_CM`", "25.0 cm", "Build ceiling; highest level 16"],
            ["`Z_MARGIN_FIXED_CM`", "+0.12 cm", "Added once at any level >= 1"],
            ["`Z_MARGIN_PER_LEVEL_CM`", "0.00 cm", "Cumulative per-level trim"],
            ["`STEP_DELAY` / `STEP_DELAY_Z`", "575 us / 950 us", "Step half-periods"],
            ["`DIR_SETTLE_MS`", "5 ms", "After a direction change"],
            ["`LIMIT_CONFIRM_US`", "200 us", "Switch confirmation time"],
            ["`SERVO_OPEN_ANGLE` / `SERVO_CLOSE_ANGLE`", "0 deg / 54 deg", "Claw jaws"],
            ["`SERVO_SETTLE_MS`", "600 ms", "After every commanded servo move in a build"],
            ["`AUX_STEPPER_STEPS_PER_REV`", "2,048", "28BYJ-48 output revolution"],
            ["`AUX_STEPPER_SPEED_RPM`", "10", "Claw rotation speed"],
            ["`BUILD_PHASE_PAUSE_MS`", "250 ms", "Settle between build phases"],
            ["`BUILD_STEP_COUNT`", "14", "Phases per build"],
            ["`SKEW_Y_PER_COL_CM`", "0.115 / 0.13 cm", "Vertical / horizontal Y skew per column, build motion only"],
            ["`BUILD_PLACEMENT_OFFSET_X_CM`", "0.0 / -0.4 cm", "Vertical / horizontal fixed X correction, build motion only"],
            ["`TOOL_OFFSET_CW_*`", "(+0.9, -0.3) cm", "The pickup-rotate swing"],
            ["`EN_ACTIVE_LEVEL`", "LOW", "TB6600 enable polarity in this wiring"],
        ],
        widths=[5.4, 3.2, 6.4], size=9)

    # ---- E ----
    rep.h2("Appendix E: Grid Geometry")
    rep.p("The lattice, in one line, for both modes:")
    rep.code(
        "pitch     = block + gap\n"
        "centre(i) = trim + error_offset + shift + i * pitch\n"
        "\n"
        "holder target = desired block centre - tool offset(rotation)\n"
        "\n"
        "target_cm    = level * (BLOCK_HEIGHT_CM + Z_MARGIN_PER_LEVEL_CM) + Z_MARGIN_FIXED_CM\n"
        "target_steps = round(target_cm * zStepsPerCm()) + Z_MARGIN_FIXED_STEPS\n"
        "\n"
        "axisCorrection_cm = BUILD_PLACEMENT_OFFSET_<AXIS>_CM[mode]\n"
        "                  + SKEW_<AXIS>_PER_COL_CM[mode] * col\n"
        "                  + SKEW_<AXIS>_PER_ROW_CM[mode] * row\n"
        "                  + SKEW_<AXIS>_PER_COLROW_CM[mode] * col * row")
    rep.table(
        "Complete grid geometry, both modes, at the shipped calibration.",
        ["Mode", "Axis", "Block (cm)", "Gap (cm)", "Pitch (cm)", "Trim (cm)", "Cells",
         "Footprint (cm)", "Centres (cm)", "Block edges (cm)"],
        [
            ["vertical", "X", "2.2", "1.6", "3.8", "0.0", "7", "25.00", "0.00 - 22.80",
             "-1.10 - 23.90"],
            ["vertical", "Y", "6.0", "1.6", "7.6", "0.0", "6", "44.00", "0.00 - 38.00",
             "-3.00 - 41.00"],
            ["horizontal", "X", "6.0", "1.6", "7.6", "+1.9", "3", "21.20", "1.90 - 17.10",
             "-1.10 - 20.10"],
            ["horizontal", "Y", "2.2", "1.6", "3.8", "+1.9", "10", "36.40", "1.90 - 36.10",
             "0.80 - 37.20"],
        ],
        widths=[1.8, 0.8, 1.2, 1.0, 1.2, 1.0, 0.9, 2.1, 2.6, 2.6], size=8.5)
    rep.p(
        "Cell counts are counts; the firmware's `S` command and its internal tables speak in "
        "highest indices, which is one less. Cell [0,0] is the feeder in both modes and is never "
        "built on, so the buildable counts are 41 and 29. Edge overhang budgets are 1.1 / 3.0 cm "
        "for vertical and 3.0 / 1.1 cm for horizontal, and they are what the geometry check "
        "measures the block **edges** against; they move nothing.")

    # ---- F ----
    rep.h2("Appendix F: Experimental Data")
    rep.p(
        "The complete build-timing data set analysed in Chapter 5 is reproduced in Table 5.11 "
        "(all sixteen builds) and Table 5.9 (per-phase statistics). The raw sources are the two "
        "append-only log files the service writes on every run:")
    rep.defs([
        ("`logs/build.log`", "One clearly separated section per build: the request, the job "
                             "handoff, the board's `RECV`, every firmware phase with the ETA the "
                             "firmware predicted beside the time the phase actually took, and "
                             "the settled result with the total elapsed. Every timestamp in a "
                             "section is relative to that build's start, so the section reads as "
                             "a stopwatch."),
        ("`logs/serial.log`", "Every line to and from either Arduino, each stamped with the wall "
                              "clock and the gap since the previous serial line, tagged "
                              "`[MEGA/GANTRY]` or `[UNO/FEEDER]`. A stall on the cable or a slow "
                              "phase shows up directly as a large delta in the second column."),
    ])
    rep.p("One complete build section, verbatim from `logs/build.log`:")
    rep.code(
        "BUILD  2026-09-03 13:53:14  B 3 2 4\n"
        "  selection=(3, 2)  level=4  mode=vertical\n"
        "    +0.00s  request accepted by /api/build\n"
        "    +0.00s  build job thread started\n"
        "    +0.14s  board RECV seq=5\n"
        "    +0.41s  phase 1/14 begin raise_clear [move]  firmware-ETA 0.19s\n"
        "            phase 1 raise_clear took 0.43s  (firmware ETA 0.19s, +0.24s)\n"
        "    +0.84s  phase 2/14 begin home_feeder [move]\n"
        "            phase 2 home_feeder took 0.58s\n"
        "    +1.41s  phase 3/14 begin neutralise_claw [rotate]\n"
        "            phase 3 neutralise_claw took 0.41s\n"
        "    +1.82s  phase 4/14 begin open_claw [release]\n"
        "            phase 4 open_claw took 0.93s\n"
        "    +2.75s  phase 5/14 begin lower_to_ground [move]  firmware-ETA 2.39s\n"
        "            phase 5 lower_to_ground took 2.91s  (firmware ETA 2.39s, +0.53s)\n"
        "    +5.66s  phase 6/14 begin grip [grip]\n"
        "            phase 6 grip took 0.95s\n"
        "    +6.62s  phase 7/14 begin lift_block [move]  firmware-ETA 2.57s\n"
        "            phase 7 lift_block took 2.89s  (firmware ETA 2.57s, +0.32s)\n"
        "    +9.51s  phase 8/14 begin move_to_target [move]\n"
        "            phase 8 move_to_target took 7.12s\n"
        "   +16.63s  phase 9/14 begin rotate_to_grid [rotate]\n"
        "            phase 9 rotate_to_grid took 0.39s\n"
        "   +17.02s  phase 10/14 begin lower_to_level [move]  firmware-ETA 1.80s\n"
        "            phase 10 lower_to_level took 2.26s  (firmware ETA 1.80s, +0.45s)\n"
        "   +19.28s  phase 11/14 begin release [release]\n"
        "            phase 11 release took 0.71s\n"
        "   +19.99s  phase 11/14 release confirmed\n"
        "   +20.12s  phase 12/14 begin park_clear [park]  firmware-ETA 1.99s\n"
        "            phase 12 park_clear took 2.25s  (firmware ETA 1.99s, +0.26s)\n"
        "   +22.37s  phase 13/14 begin park_home [park]\n"
        "            phase 13 park_home took 7.04s\n"
        "   +29.41s  phase 14/14 begin park_rotation [park]\n"
        "            phase 14 park_rotation took 0.43s\n"
        "   +29.84s  RESULT PLACED\n"
        "   +29.84s  build finished, total 29.84s")
    rep.p(
        "[[VALUE NEEDED: any measured data tables you take after this report is drafted, "
        "placement accuracy trials, homing repeatability trials, feeder-sensor readings, "
        "and a pick-and-place success count) belong here as additional tables in this "
        "appendix.]]")
