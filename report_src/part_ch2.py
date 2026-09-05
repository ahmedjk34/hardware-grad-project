"""Chapter 2 — System Requirements and Design."""


def chapter_2(rep):
    rep.h1("2. System Requirements and Design")

    # ------------------------------------------------------------------
    rep.h2("2.1 System Requirements")

    rep.h3("2.1.1 Functional requirements")
    rep.p(
        "The system was designed to eight functional requirements. They are written here as "
        "capability statements, in the order the machine actually exercises them during a build.")
    rep.numbered([
        "**Place a block at any addressable cell, at any stack level.** One command carries the "
        "column, the row and the level, and the firmware turns that into safe step targets "
        "itself. The delivered machine addresses 41 buildable cells standing and 29 lying, at "
        "levels 0 to 16.",
        "**Address the surface as two grids, one per block orientation.** A block measures "
        "2.2 x 6.0 cm in plan and can be laid either way round, and which way round changes how "
        "many cells fit and where they sit. The machine carries two separately calibrated "
        "grids, switched by a latch command that moves nothing.",
        "**Turn the block between pickup and placement.** The claw rotates 90 degrees when the "
        "active grid calls for it, and returns to neutral before the next pickup, so a tracked "
        "angle is never more than one cycle old.",
        "**Dose exactly one block at a time to a fixed pickup point.** A hopper gate that opens "
        "in two stages releases the bottom block of a queued column on its own, and shuts behind "
        "it before the belt starts so a second block cannot follow.",
        "**Confirm the block at both ends of the feed path.** An ultrasonic sensor proves a "
        "block physically left the container; a digital IR sensor proves it arrived at the pickup point, "
        "and is read again after the aligner moves. A feed request arriving while the pickup "
        "point is already occupied is refused before anything opens.",
        "**Find the blocks on the surface from overhead, and know which cell each one is in.** "
        "The camera pipeline detects the wooden blocks, labels every detection with an integer "
        "cell, and converts camera pixels to physical centimetres through a saved calibration.",
        "**Operate from a browser on the local network.** A live camera view, cell selection by "
        "tapping the image, an explicit two-tap confirmation, and a 3D environment in which a "
        "person designs a structure, validates it physically and compiles it to an ordered "
        "command program.",
        "**Never move without proof.** Exactly one terminal result per command; a failure that "
        "moved nothing is reported as a different kind of message from one that may have left a "
        "block in the claw; and the whole chain runs against simulated boards with no hardware "
        "attached, so the software can be developed and rehearsed without the rig.",
    ])

    rep.h3("2.1.2 Performance requirements")
    rep.p(
        "The performance targets came from the machine's own step rates and from what a "
        "demonstration needs to be watchable. The **cycle time** target was under 45 seconds per "
        "block; the delivered machine averages **26.1 s**, with a fastest cycle of 19.8 s and a "
        "worst case of 32.2 s. That figure is dominated by travel and by the Z axis, not by the "
        "gripper: the two X/Y moves and the four Z moves account for roughly 20 of those 26 "
        "seconds, while the entire grip-and-rotate sequence is under 3.")
    rep.p(
        "**Repeatability** mattered more than raw speed, because a stacking machine is only as "
        "good as its worst placement. Nine of the fourteen phases in a build have no distance or "
        "level dependence at all, and across sixteen logged hardware builds those nine summed to "
        "a mean of 12.57 s with a standard deviation of 0.18 s, a spread of 1.4 %; six of them "
        "repeated with identical minimum and maximum to the 0.01 s logging resolution. The "
        "**traverse rate** measures 4.13 cm/s against a nominal 4.36 cm/s, which is 94.7 % of "
        "what the pulse arithmetic predicts, and the Z axis comes out 5.8 % slower than its own "
        "prediction by the same mechanism. Both shortfalls are the per-step limit-switch poll, "
        "and the agreement between two independently measured axes is what makes that "
        "explanation credible.")
    rep.p(
        "For **capacity**, the requirement was to use as much of the envelope as the block "
        "geometry allows and to stack high enough to be worth watching. The machine addresses "
        "the full 22.8 x 38.0 cm holder travel as 41 buildable cells standing or 29 lying, and "
        "the firmware ceiling is level 16 at 24.0 cm, leaving 2.5 cm of clearance to fly a block "
        "over the tallest possible tower.")
    rep.p(
        "For **vision**, the requirement was to find every block on a full board and to map a "
        "cell to better than half a block footprint. Detection finds 29 of 29 on both reference "
        "boards while correctly rejecting the aluminium rails and two wooden offcuts that are "
        "the same shape as blocks, at 37 to 103 ms per analysed frame, and the saved "
        "camera-to-cell mapping carries 1.25 px mean and 2.07 px maximum error, which is 0.27 cm "
        "on a 2.2 cm block."
    )
    rep.h3("2.1.3 Safety and operational requirements")
    rep.p(
        "The safety model of this machine is a software model, and it is built on the fact that "
        "the gantry cannot be interrupted once it is moving. Every rule below follows from that "
        "one physical fact rather than from a general principle.")
    rep.numbered([
        "**One command at a time, never queued.** The gantry firmware does not read serial "
        "inside its build cycle, so a second command sent during a build sits in a 64-byte "
        "hardware buffer and executes late, out of context. The Pi holds a "
        "non-blocking lock and refuses any overlapping operation instead of buffering it.",
        "**A failure of unknown physical outcome locks the session.** An abort, a timeout, a "
        "board reset or a cable loss leaves the claw possibly holding a block at an unknown "
        "position. The controller sets a lock, refuses every further mutation, and the only "
        "recovery is a person inspecting the rig and restarting the service. There is no retry "
        "button, because a retry is the thing that breaks the machine.",
        "**Nothing is auto-retried across the two boards.** Once the feeder has staged a block, "
        "even a perfectly safe gantry rejection locks the cell: a block is already at the "
        "pickup point, so feeding another would double-load it.",
        "**Cell [0,0] is the feeder and is never a build target.** It is refused in the "
        "firmware, in the Pi and in the browser, in all three, because placing a block there "
        "would drop it on the stack the claw picks from.",
        "**Every move is preceded by a re-home.** Position is trusted only immediately after a "
        "physical switch has defined it.",
        "**A build is never started from a stale camera frame or an unhomed axis.** Selection "
        "and build are both refused server-side, and the browser is never trusted to enforce "
        "either.",
        "**Two deliberate taps to move.** Selecting a cell moves nothing and shows the exact "
        "command; a separate confirmation sends it.",
        "**The machine is operated attended.** With no hardwired emergency stop fitted, the "
        "documented procedure is that a person stays with the rig during a run, keeps hands "
        "clear of the gantry envelope while it is powered, and stops it by removing power at "
        "the supply. This is stated plainly rather than dressed up: it is a real limitation "
        "and it is discussed in Sections 3.6 and 5.7.",
    ])

    # ------------------------------------------------------------------
    rep.h2("2.2 Design Constraints")

    rep.h3("2.2.1 Physical constraints")
    rep.p(
        "The machine had to sit on an ordinary table and stay there, and that decision came "
        "before any other. It sets the frame, and the frame sets everything downstream: how far "
        "the gantry can travel, how many cells fit inside that travel, where the feeder can "
        "stand, and how high the camera has to be to see the whole surface at once.")
    rep.p(
        "The frame is built from a single 6 m length of aluminium profile, cut into the pieces "
        "the design needed, and the cut list is the clearest statement of the machine's size:")
    rep.bullets([
        "**4 legs**, 15 cm each, which is what holds the gantry above the build surface.",
        "**3 members along X**, 30 cm each.",
        "**2 members along Y**, 60 cm each.",
        "**2 members for the feeder**, 30 cm each, one on either side of the conveyor.",
        "**1 member for the Z column**, approximately 30 cm.",
    ])
    rep.p(
        "That is about **3.6 m of profile in the finished machine**, with the remainder of the "
        "6 m stock left as offcuts and spares. The 60 cm members along Y and the 30 cm members "
        "along X are the reason the holder travel comes out at 38.0 cm and 22.8 cm: the "
        "difference between the raw member length and the usable travel is the width of the "
        "carriages, the pulley mounts and the end brackets that live at each end of the run.")
    rep.p(
        "**Why the build area is not simply the travel.** It would be easy to assume the "
        "reachable surface is whatever the belts can cover, and it is not. The limit is the "
        "block plus its margins, measured against the travel the frame allows. A cell is a "
        "block footprint plus a uniform 1.6 cm gap, giving a pitch of 3.8 cm across the short "
        "axis and 7.6 cm along the long one, and a cell is only real if the **whole block** fits "
        "on the machine, not just its centre. The firmware checks the block **edges** against a "
        "per-mode overhang budget for exactly this reason, and that check is what fixes the "
        "counts: an eighth vertical column, a seventh vertical row, a fourth horizontal column "
        "and an eleventh horizontal row are each refused, not because the motors cannot get "
        "there, but because the block that would sit at that cell hangs off the machine.")
    rep.p(
        "So the counts in Section 2.4.7 are geometric maxima on this frame and not a paper "
        "choice with room to spare. The vertical grid fills its travel exactly on both axes "
        "(6 x 3.8 = 22.8 and 5 x 7.6 = 38.0), which is what 'the build area is the travel area' "
        "means in practice. Making the machine bigger would mean longer profile, and the table "
        "is what says no.")
    rep.p(
        "Two other physical facts followed from the same decision. The feeder was built as a "
        "**separate module standing alongside the gantry on the left** instead of as a hopper "
        "hung above the build surface, because there is no room above the surface once the "
        "camera is there and because a hopper over the work area would drop blocks into the "
        "structure being built. And the camera had to see the whole surface at once from a "
        "height that still cleared the gantry, which put it about 50 cm up on its own support "
        "structure and made a wide-angle lens unavoidable, with all the distortion and colour "
        "cost that Chapter 3 then has to answer.")
    rep.p(
        "One physical constraint was not designed for and had to be answered afterwards. The arm "
        "holder that rides the X rail is not supported symmetrically: its own mass, the drag of "
        "the cable run and the side load from the belt all pull on one side of it, and that "
        "constant sideways pull leaves the X rail very slightly out of square with Y. The "
        "carriage also drifts along Y in proportion to how far it has travelled along X, and that "
        "drift measures about 0.1 cm of Y per column. Re-machining the rail was out of scope, "
        "so the drift is cancelled in firmware instead; the model and the correction are in "
        "Section 4.2.5.")

    rep.h3("2.2.2 Hardware and electrical constraints")
    rep.bullets([
        "**8 KB of SRAM on the AVR.** The gantry sketch prints a great deal of text, and on AVR "
        "every plain string literal handed to `Serial.print()` is copied into SRAM at boot. "
        "Written naively the sketch needed 9,443 bytes of SRAM, which is 115 % of the chip; it "
        "would not have run. Wrapping every literal in `F()` moved them into flash and brought "
        "SRAM down to 2,099 bytes (26 %), at a cost of about 1.4 KB of program space "
        "(40,590 bytes, 15 % of flash). This is why the serial protocol is terse "
        "`key=value` text and not JSON.",
        "**9600 baud.** The link runs at 9600 8N1, which is roughly 20 ms per line of "
        "telemetry. That is the direct reason the firmware reports one line per build phase "
        "rather than one per motor step: fourteen lines is about 0.3 s of airtime inside a "
        "40-second build, while per-step telemetry would be minutes of it and would starve the "
        "terminal acknowledgement that actually matters.",
        "**Opening the USB port resets the Arduino.** The board comes back un-homed, in its "
        "compiled default grid mode, with no memory of anything the controller had set. There "
        "is no EEPROM in use, so the mode latch, the grid size and any live grid shift have to "
        "be re-pushed on every connection, in that order.",
        "**The gantry is deaf while it moves.** `buildBlock()` runs homing, Z travel and the "
        "servo inside one synchronous function and never calls the serial reader. A build "
        "cannot be cancelled from software, and the interface is not allowed to imply otherwise.",
        "**No encoders anywhere.** Every stepper in the machine is open-loop. Position is a "
        "count, and its only anchor is a limit switch.",
        "**The Pi camera is reachable only through Picamera2.** The Pi 5's CSI camera has no "
        "usable V4L2 path for this sensor, so the vision code carries a Picamera2 backend as "
        "its primary and a V4L2 fallback for development on an ordinary machine.",
    ])

    rep.h2("2.3 Overall System Architecture")
    rep.p(
        "The system follows a strict master-slave architecture with one master and two "
        "independent slaves, chosen so that no part of the machine can move without the master "
        "having decided that it should. **A Raspberry Pi 5 (8 GB) is the sole master.** It owns "
        "the camera, the web server, the orchestration between the two boards and every safety "
        "rule in the system. **An Arduino MEGA 2560 runs the gantry** on its own USB serial "
        "link, and **an Arduino Uno runs the feeder** on a second, entirely separate USB serial "
        "link. The two Arduinos have no wire between them and neither can command the other; "
        "the Pi is the only thing that couples them.")
    rep.p(
        "That isolation is a deliberate safety property rather than a wiring convenience. A "
        "block is only allowed to be picked up because the Pi received one exact terminal "
        "message from the Uno saying a block is staged, and correlated it with the request it "
        "sent. If the boards could talk to each other, that permission could be granted "
        "somewhere the master cannot see.")
    rep.figure("System block diagram: the three controllers, the two independent USB serial "
               "links, the camera, and the browser clients on the local network.",
               placeholder="Block diagram, to be drawn. Suggested division: browser / Pi "
                           "(FastAPI + vision + orchestration) / Uno feeder / Mega gantry, "
                           "with the two serial links drawn as separate arrows and the camera "
                           "on the Pi.")
    rep.defs([
        ("Raspberry Pi 5, 8 GB (the master)",
         "Camera capture and the whole vision pipeline, the FastAPI web service, the Studio, "
         "the two-board orchestration, and every safety gate and session lock. It talks to the "
         "browser over HTTPS and a WebSocket, and to the two boards over two USB serial links."),
        ("Arduino MEGA 2560 (the gantry)",
         "X, Y and Z motion, the claw servo, the rotation stepper, homing, limit enforcement, "
         "the grid geometry and the fourteen-phase build cycle. It answers on its own serial "
         "link at 9600 8N1 with `@`-prefixed acknowledgement lines."),
        ("Arduino Uno (the feeder)",
         "The hopper gate servo, the belt stepper, the alignment servo, the exit ultrasonic "
         "sensor and the stage IR sensor, together with the complete feed state machine. It answers on a second, "
         "entirely separate serial link at 9600 8N1, speaking protocol 2."),
        ("The vision system",
         "An OV5647 fisheye camera on the Pi's CSI bus. Colour correction, lens correction, "
         "block detection, grid calibration and the pixel-to-cell mapping all run in-process on "
         "the Pi."),
        ("The operator interface",
         "Any browser on the local network: the live camera view, cell selection, build "
         "confirmation, the 3D Studio and the digital twin, fed by REST calls and a durable "
         "WebSocket event stream."),
    ])
    rep.p(
        "The browser is treated as an untrusted mirror throughout. It sends requests and renders "
        "whatever the server reports; every guard is re-checked on the Pi, and a disabled button "
        "in the interface is never the thing that keeps the machine safe.")

    # ------------------------------------------------------------------
    rep.h2("2.4 Mechanical Design")

    rep.h3("2.4.1 Overall structure")
    rep.p(
        "The machine is a rectangular aluminium-profile frame carrying a CoreXY gantry over a "
        "flat build surface, with a vertical Z column on the moving carriage, a feeder module "
        "standing alongside the frame on the left, and a camera looking straight down from a "
        "wooden support structure above. Every custom part is 3D-printed and every structural "
        "member is aluminium profile; nothing in the moving assembly is an off-the-shelf "
        "mechanism.")
    rep.bullets([
        "**Holder travel, X: 22.8 cm = 4,550 steps.** The displacement of the holder reference "
        "from the X home switch to the X software cap. This is the number the grid is built on.",
        "**Holder travel, Y: 38.0 cm = 7,600 steps.** The same, for Y.",
        "**Z travel: 26.5 cm = 1,350 steps**, bottom switch to top switch, both physical.",
        "**Observed build footprint: 24.3 x 43 cm.** A separately measured observation of the "
        "surface the machine can reach. It is a record only: it does not replace the travel cap, "
        "and the extra reach is not modelled.",
        "**Wooden platform: 80 x 60 cm**, the base the gantry assembly stands on.",
        "**Feeder module: approximately 100 x 40 cm**, standing to the left of the gantry and "
        "feeding directly to cell [0,0]. The conveyor belt itself is about 30 x 10 cm of that.",
    ])
    rep.note(
        "**On the two sets of dimensions.** An earlier revision of the firmware documentation "
        "records 24.3 cm x 40 cm and 4,750 x 8,250 steps. Those numbers are stale. The live "
        "firmware constants, the configuration file and the machine's own boot report all agree "
        "on **22.8 x 38.0 cm and 4,550 x 7,600 steps**, and that is what this report uses "
        "throughout. The 24.3 x 43 cm figure is a separate measurement of the physically "
        "reachable surface and is kept as a record.")

    rep.h3("2.4.2 The X/Y stage: CoreXY")
    rep.p(
        "The X/Y stage is a CoreXY (H-bot) arrangement carried over from the reference design. "
        "Two NEMA17 motors are fixed to the frame and drive one continuous GT2 belt path through "
        "a set of pulleys, so that neither motor rides on the moving beam. Motion is the sum and "
        "difference of the two shafts instead of one motor per axis:")
    rep.table(
        "CoreXY motor directions, verified on the machine by watching the shafts.",
        ["Motor 1", "Motor 2", "Resulting motion", "End of travel"],
        [
            ["CW", "CW", "X-  (short axis, away from the X switch)", "software cap at 4,550 steps"],
            ["CCW", "CCW", "X+  (toward the X switch)", "physical switch, pin 30"],
            ["CW", "CCW", "Y-  (long axis, toward the Y switch)", "physical switch, pin 31"],
            ["CCW", "CW", "Y+  (away from the Y switch)", "software cap at 7,600 steps"],
        ],
        widths=[2.4, 2.4, 6.6, 4.6], size=9)
    rep.p(
        "Motors turning in the same sense walk the carriage along X; opposed senses walk it "
        "along Y. The advantage over a plain Cartesian layout is exactly the one the reference "
        "design states: keeping both motors off the moving beam makes the beam lighter and "
        "leaves a larger working envelope inside a given frame. The cost is a more complicated "
        "belt path with more pulleys to align, and, in this build, a coupling that is easy to "
        "get backwards: both drivers turn clockwise on an active-high direction pin, which is "
        "not what either datasheet suggests and is the result of one driver's coil wiring being "
        "physically reversed and the other ending up the same way after the machine was rewired. "
        "That is recorded in the firmware next to the constant so it is never 'fixed' in "
        "software without checking the wiring first.")
    rep.p(
        "Both X/Y axes are guided by castor wheels running on the aluminium profile, eight of "
        "them mounted on 3D-printed carriages. The single 1.5 m x 15 mm linear rail and its "
        "linear motion bearing are not used for X or Y: they carry the **Z** axis. Homing is by "
        "limit switch, one per axis, and each switch zeroes its own axis the instant it trips, "
        "so the corner where both are pressed is machine position (0, 0).")
    rep.figure("The X/Y stage: CoreXY belt routing, the two frame-mounted NEMA17 motors, the "
               "castor-wheel carriages and the two homing switches.",
               placeholder="Photograph or annotated CAD view of the gantry from above, with the "
                           "belt path traced and the two limit switches labelled.")

    rep.h3("2.4.3 The Z axis")
    rep.p(
        "The Z axis is a single NEMA17 that is not coupled to the X/Y pair, carrying the claw "
        "assembly up and down a vertical column on the moving carriage. The carriage rides the "
        "15 mm linear rail on its linear motion bearing, which is what gives Z its stiffness "
        "against the side load of a gripped block, and the motor drives it through a GT2 belt "
        "and pulley in the same family as the X/Y transmission. "
        "{{INFERRED: the drive type is not written down anywhere in the repository. It is "
        "deduced from the bill of materials and from the step calibration: 1,350 steps over "
        "26.5 cm is 50.94 steps/cm, and a 20-tooth GT2 pulley at 40 mm per revolution with a "
        "200 step/rev motor at full step gives 50.0 steps/cm, a 1.9 % agreement, which is "
        "tape-measure accuracy. No lead screw pitch fits: a T8 8 mm lead would give 250 "
        "steps/cm. Confirm the pulley tooth count and the microstep setting.}}")
    rep.p(
        "Z is the only axis in the machine with a physical switch at **both** ends. The bottom "
        "switch on pin 28 is the ground reference the stack levels are measured from, and it is "
        "the axis' home: driving into it re-zeroes Z. The top switch on pin 29 is a far-end stop "
        "that halts the axis and reports where the top is without redefining zero. That end used "
        "to be a counted software limit, which only worked while the step count was trustworthy; "
        "replacing it with a switch means 'go to the top' became a seek rather than a move to a "
        "number, so it works even when Z has never been homed.")
    rep.p(
        "One consequence is worth stating because it is where the build cycle's reliability "
        "comes from: **every build re-establishes Z's zero on the physical ground switch before "
        "it picks a block up**, and carries the block at the full height of the top switch. "
        "Neither end of a build's Z travel is a remembered number.")

    rep.h3("2.4.4 The end effector")
    rep.p(
        "The reference design's end effector is an electromagnet under a board, dragging "
        "magnetised flat chess pieces across a plane. That is a good solution for chess and no "
        "solution at all here. In contrast, our blocks are plain wood, so there is nothing to "
        "attract; they "
        "are three-dimensional and have to be lifted and not dragged; and a magnet has no "
        "way to control which way round a piece ends up, which a machine with two block "
        "orientations needs. The end effector is a mechanical claw instead.")
    rep.defs([
        ("What it is", "A 3D-printed two-jaw gripper driven by a single hobby servo on Mega "
                       "pin 6, with exactly two commanded positions: OPEN at 0 degrees and "
                       "CLOSE at 54 degrees. The jaws close on the middle of the block, across "
                       "its 2.2 cm face."),
        ("Rotation", "A 28BYJ-48 stepper through a ULN2003 driver turns the whole claw a "
                     "quarter turn, 512 of its 2,048 steps per output revolution, at 10 rpm. "
                     "That is what gives the machine its second block orientation."),
        ("What it does not have", "Any sensor at all. The servo is commanded and then "
                                  "forgotten; nothing reports when the jaws have arrived, which "
                                  "is why every open and close inside a build waits a fixed "
                                  "600 ms settle time before Z is allowed to move. The claw's "
                                  "rotation angle is likewise not sensed: the firmware tracks "
                                  "it relative to an assumed neutral start and the operator is "
                                  "trusted to begin with the claw physically neutral."),
        ("Why that is acceptable", "The build cycle returns the claw to neutral at the feeder "
                                   "before every pickup and again after every placement, so a "
                                   "tracked angle is only ever one cycle old. A manual jog to "
                                   "an arbitrary angle is explicitly marked uncalibrated and "
                                   "blocks the `G` and mode-latch commands until a build "
                                   "returns the claw to neutral."),
    ])
    rep.p(
        "A mechanical grip introduced one geometric problem the electromagnet never had. The "
        "claw closes on the block's middle, but that middle does not sit on the rotation "
        "stepper's axis: it is offset by roughly (-0.3, +0.6) cm. A 90-degree turn "
        "swings the block's centre **around** that axis rather than spinning it in place, and "
        "the swing is a constant X +0.9 cm, Y -0.3 cm. That is corrected as a tool offset in "
        "Section 3.2.3, and correcting it in the wrong place was one of the real errors of this "
        "project, described in Section 5.7.")
    rep.figure("The claw: 3D-printed jaws, the gripper servo, and the 28BYJ-48 rotation stepper "
               "that gives the second block orientation.",
               placeholder="Close-up photograph or CAD view of the end effector, with the servo "
                           "and the rotation stepper labelled and the grip axis marked.")

    rep.h3("2.4.5 The feeder module")
    rep.p(
        "The feeder is a self-contained module that stands to the left of the gantry frame and "
        "delivers a block to the gantry's cell [0,0]. It exists because the reference design "
        "does not need one: chess pieces are already on the board. A stacking machine consumes "
        "its parts, so something has to supply them, one at a time, in a known place and a known "
        "orientation.")
    rep.p("Physically it is four things in a line:")
    rep.numbered([
        "**The container.** A hopper sized for the block footprint, with vertical elevation so a "
        "column of blocks can queue inside it, closed by a servo-driven gate on Uno pin 12. The "
        "gate does not simply open: it moves in two deliberate stages, 20 degrees closed to 90 "
        "degrees, then 90 to 160 degrees, with a 500 ms settle at each stage. Opening in one "
        "large movement releases blocks in a clump; opening in two lets the column settle "
        "against the gate and release the bottom block on its own.",
        "**The exit sensor.** An HC-SR04 at the container's exit (TRIG 4, ECHO 5) that confirms "
        "a block has physically left the container and is on the belt. As soon as it fires the "
        "container is shut again, so a second block cannot follow the first out.",
        "**The belt.** A GT2-driven conveyor about 30 x 10 cm, built from a belt sheet on "
        "3D-printed rollers and driven by a NEMA17 through an A4988 (DIR 2, STEP 3), running at "
        "a configurable 325 steps/s by default. The belt carries the block from the container "
        "toward the pickup point.",
        "**The stage sensor and the aligner.** A digital IR obstacle sensor at the pickup point "
        "(OUT 8, active-low by default) stops the belt the moment the block arrives, and an alignment servo on pin 6 "
        "nudges the block square, moving from its 90-degree rest to 120 degrees and back after "
        "350 ms. The stage sensor is then read again: only if the block is still there does the "
        "feeder report success.",
    ])
    rep.p(
        "The pickup point is the gantry's vertical cell [0,0], whose centre is the machine's "
        "home corner. Because the lattice is anchored on that corner, a pickup is a plain home "
        "with no move afterwards, and the claw closes on the block's centre without any "
        "additional positioning. The feeder never rotates: it always presents a block standing, "
        "whichever grid mode the gantry is latched into.")
    rep.figure("The feeder module: hopper with its two-stage servo gate, the conveyor belt, "
               "the alignment servo, the exit HC-SR04 and the pickup-stage IR sensor.",
               placeholder="Photograph of the feeder alongside the gantry, with the exit and stage "
                           "sensors and the gate servo labelled, and the pickup point marked.")

    rep.h3("2.4.6 The workpiece and the build surface")
    rep.p(
        "The workpiece is a plain wooden block measuring **6.0 x 2.2 x 1.5 cm**, and the supply "
        "is **30 blocks, all of them bare wood in one uniform colour**. Nothing is painted, so "
        "the vision system has no colour signal to key on and has to separate the blocks from "
        "the work surface on tone alone, which is what Section 4.3.2's red-minus-blue "
        "segmentation exists to do. Twenty-nine of the thirty appear in the vision reference "
        "board used throughout Chapter 5; the thirtieth is the one being carried.")
    rep.p(
        "The build surface is the flat holder under the gantry, and it is registered to the "
        "machine by the machine itself and not by any fixture: **home is defined physically "
        "by where the X and Y limit switches are**, and every grid coordinate is measured from "
        "that corner. There is no separate datum to align and nothing to re-register if the "
        "surface is disturbed, provided the switches have not moved.")

    rep.h3("2.4.7 The two grids")
    rep.p(
        "Because the block can be laid either way round, and because which way round it is laid "
        "changes how many cells fit and where they sit, this machine does not have one grid with "
        "an orientation flag. It has **two complete grids**, each with its own geometry, its own "
        "count and its own calibration:")
    rep.table(
        "The two grids, at the shipped calibration. Gaps are a uniform 1.6 cm on every axis of "
        "both modes; pitch is block plus gap.",
        ["Mode", "Axis", "Block", "Gap", "Pitch", "Cells", "Cell centres (cm)", "Block edges (cm)"],
        [
            ["vertical", "X", "2.2", "1.6", "3.8", "7", "0.00 to 22.80", "-1.10 to 23.90"],
            ["vertical", "Y", "6.0", "1.6", "7.6", "6", "0.00 to 38.00", "-3.00 to 41.00"],
            ["horizontal", "X", "6.0", "1.6", "7.6", "3", "1.90 to 17.10", "-1.10 to 20.10"],
            ["horizontal", "Y", "2.2", "1.6", "3.8", "10", "1.90 to 36.10", "0.80 to 37.20"],
        ],
        widths=[2.4, 1.3, 1.4, 1.2, 1.4, 1.3, 3.4, 3.2], size=9)
    rep.p(
        "The vertical grid fills its travel exactly on both axes (6 x 3.8 = 22.8 and "
        "5 x 7.6 = 38.0), which is not a coincidence to be tuned away: it is what 'the build "
        "area is the travel area' means. Both grids share the same feeder cell at [0,0] and "
        "neither builds on it, so the buildable counts are 7 x 6 - 1 = **41 cells** vertical and "
        "3 x 10 - 1 = **29 cells** horizontal. The lattice mathematics, the +1.9 cm registration "
        "the horizontal grid carries, and why that registration is not a tool offset, are set "
        "out in Section 4.2.3.")
    rep.p(
        "Drawn on top of one another the two grids show what the mode latch actually changes. "
        "The two lattices share one physical envelope and one feeder cell, and a horizontal "
        "column spans two vertical columns plus the gap between them (6.0 = 2.2 + 1.6 + 2.2, so "
        "7.6 = 2 x 3.8), which is why the same surface reads as 7 x 6 cells one way round and "
        "3 x 10 the other.")
    rep.figure("The two grids overlaid on the same build surface: the vertical 7 x 6 lattice "
               "and the horizontal 3 x 10 lattice, sharing one envelope and one feeder cell "
               "at [0,0].",
               placeholder="Overlay drawing or photograph of both grids on the same surface, "
                           "to be supplied.")

    rep.h3("2.4.8 Mechanical problems encountered during construction")
    rep.p(
        "Three mechanical problems were significant enough to change the design, and all three "
        "were answered in firmware rather than by re-making a part.")
    rep.defs([
        ("The slanted X rail",
         "The asymmetrically loaded arm holder leaves the X rail slightly out of square with Y, "
         "so a placement that involves X travel lands off along Y by an amount proportional to "
         "the column index, measured at 0.115 cm per vertical column and 0.13 cm per horizontal "
         "column, with no row dependence at "
         "all. It is corrected by a firmware nudge applied only to the build motion (Section 4.2.5)."),
        ("The pickup-rotate swing",
         "The claw's grip centre is offset from the rotation stepper's axis, so a 90-degree turn "
         "carries the block centre around that axis by X +0.9 cm, Y -0.3 cm. Horizontal "
         "placements landed 1.4 cm too far from the X home switch until this was modelled as a "
         "per-rotation tool offset rather than as a grid error."),
        ("Constant placement error from the tool itself",
         "Beyond the two effects above, the claw geometry and the block's own surface finish "
         "left a residual constant offset in placement. The firmware carries a per-mode "
         "`error_offset` pair exactly for this, applied like a grid trim; both modes currently "
         "ship at zero because the two effects above accounted for what had been measured. "
         "[[VALUE NEEDED: if a residual constant offset was measured and dialled in on the "
         "delivered machine, give the values for each mode and each axis.]]"),
    ])
    rep.p(
        "The block texture itself was a smaller but real problem, in two places: a rough or "
        "slightly cupped face changes where the jaws bite, and the natural wood grain is close "
        "enough in colour to the pale work surface that the vision system cannot separate them "
        "on brightness. The first is absorbed by the constant offsets above; the second is why "
        "block detection segments on red-minus-blue and red-minus-green rather than on "
        "brightness (Section 4.3.2).")

    rep.h2("2.5 Electrical and Control Design")

    rep.h3("2.5.1 Power architecture")
    rep.p(
        "The machine runs from a single 12 V / 15 A switched-mode supply with one LM2596 "
        "adjustable buck converter taking a 5 V rail off it. The split follows the current draw: "
        "everything that moves a stepper runs from 12 V directly, and everything small and "
        "logic-level runs from the 5 V rail.")
    rep.bullets([
        "**The 12 V rail**, straight off the supply, feeds the three TB6600 drivers (the two "
        "CoreXY NEMA17s and the Z NEMA17) and the A4988 driving the feeder belt motor.",
        "**The 5 V rail**, from the LM2596 buck converter, feeds the gripper servo, the "
        "container and alignment servos, the 28BYJ-48 rotation stepper through its ULN2003, "
        "exit HC-SR04, stage IR sensor, and the A4988's logic and reference supply.",
        "**Both Arduinos are powered over USB from the Pi**, which is also how they communicate.",
        "**The Raspberry Pi runs from its own official USB-C supply**, deliberately not from the "
        "buck converter.",
        "**One common ground** is shared by the 12 V supply, the buck converter, both Arduinos, "
        "all four drivers and every sensor.",
    ])
    rep.p(
        "The assorted resistors and capacitors in the bill of materials are used around the "
        "A4988 belt driver, for its current-reference network and for local decoupling on the "
        "motor supply.")
    rep.p(
        "The supply is rated at **15 A**, which is generous for what this machine actually "
        "draws. A NEMA17 of the size used here takes on the order of 1.5 A per phase, the "
        "28BYJ-48 through its ULN2003 takes well under 0.3 A, a hobby servo draws a few "
        "hundred milliamperes while it is moving and almost nothing once it has arrived, and "
        "the feeder sensors draw only a few tens of milliamperes together. Adding the worst case of "
        "every one of those together still leaves most of the supply unused.")
    rep.p(
        "In practice the machine never comes close even to that sum, because **the build "
        "cycle is sequential by construction and very little runs at the same time**. The "
        "fourteen phases move one thing at a time: Z travels while X and Y are stopped, X and "
        "Y traverse while Z is parked at the top switch, the gripper servo moves while nothing "
        "else does, and the rotation stepper turns only between a completed move and the next "
        "one. The feeder belt runs only while the gantry is idle waiting for a block. The "
        "instantaneous draw is usually one stepper plus the logic, so the 15 A rating is sized "
        "for the whole machine and not for any moment it actually reaches.")
    rep.figure("Power distribution schematic: the 12 V supply, the LM2596 buck converter, the "
               "two rails and the common ground.",
               placeholder="Schematic to be drawn, showing the 12 V rail to the three TB6600s "
                           "and the A4988, the 5 V rail to the servos, the ULN2003 and the "
                           "sensors, and the separate Pi supply.")

    rep.h3("2.5.2 Wiring and construction")
    rep.p(
        "Motor and sensor runs are made with connectors instead of being soldered directly to "
        "the boards, so that a motor or a sensor can be swapped without a soldering iron and so "
        "the gantry can be dismantled for transport. The TB6600 drivers take their motor and "
        "signal wiring on screw terminals. The communication wiring between the boards, the "
        "drivers and the sensors is made from cropped male-to-male jumper leads with heat-shrink "
        "over each joint, which keeps the run lengths honest and stops a jumper working loose "
        "against the vibration of the belt. There is no enclosure and no cable chain; cable "
        "management on the moving carriage is by routing and strain relief only, and the drag of "
        "that cable run is one of the contributors to the X-rail skew described in Section 2.2.1.")

    rep.h3("2.5.3 Control architecture")
    rep.p(
        "Control is hierarchical, and the division between the two levels is strict: **the Pi "
        "decides what and whether; each Arduino decides how.**")
    rep.defs([
        ("High level (Raspberry Pi)",
         "Chooses the target cell, the stack level and the grid mode; sequences the feeder "
         "before the gantry; applies every safety gate; owns the session lock; and decides "
         "whether a command may be issued at all. It never sends a motor step. What it sends is "
         "`B col row level` or `FEED id`, and nothing more detailed than that."),
        ("Low level (Arduino MEGA, Arduino Uno)",
         "Turns those commands into motion. The Mega owns step generation, direction polarity, "
         "homing, limit enforcement, the grid-to-steps arithmetic, the servo and stepper timing "
         "and the phase sequence. The Uno owns the feed state machine, the servo angles, the "
         "belt rate, exit-ultrasonic threshold and stage-IR polarity."),
        ("The reason for the split",
         "The firmware owns everything that cannot change without reflashing, which is exactly "
         "the set of numbers that would be dangerous if the Pi held a stale copy: the step "
         "caps, the Z calibration, the pin assignments, the servo angles and the direction "
         "polarity. The configuration file owns what can change without reflashing: the grid "
         "counts, the block and gap geometry, the trims, the serial ports."),
    ])
    rep.p(
        "One consequence of that split is worth stating on its own, because it is the rule that "
        "keeps the two machines honest with each other. **A handful of physical values genuinely "
        "exist twice**, once in the Pi's configuration file and once compiled into the sketch, "
        "because the Arduino has no filesystem and cannot read the configuration at all. Every "
        "one of those pairs is listed explicitly in the repository's contributor notes and "
        "checked by an automated test that **parses the live sketch** and fails if either side "
        "has moved. A value that lives on two machines will eventually drift on one of them, "
        "and that test is the only mechanism in the project that makes the drift loud instead "
        "of silent.")

    rep.p(
        "The two firmwares are isolated from each other by construction. There is no wire "
        "between the Mega and the Uno, neither knows the other exists, and the only thing that "
        "couples them is the Pi's orchestrator. The permission to move the gantry is one exact "
        "message, `@id OK state=block_ready result=staged`, whose `id` matches the request the "
        "Pi sent; a terminal message with the wrong id is ignored, and every other message the "
        "Uno emits is progress telemetry that never counts as success.")

    # ------------------------------------------------------------------
    rep.h2("2.6 System Workflow")
    rep.p(
        "The end-to-end sequence, from a structure that exists only as an idea to a finished "
        "stack, runs in five stages.")
    rep.numbered([
        "**Design.** A person opens the 3D Build Studio in a browser, places blocks in a live 3D "
        "scene on the machine's real lattice, and gets immediate feedback on whether each block "
        "is supported, whether it collides with another, and whether the structure would topple. "
        "The design is saved to the browser's own library as a `rigmodel/1` file.",
        "**Compile.** The Studio turns the model into an ordered command program. The compiler "
        "builds a support graph from footprint overlap, sorts it bottom-up with Kahn's "
        "algorithm, groups blocks of the same orientation together to minimise grid-mode "
        "changes, and emits a deterministic list of `B col row level` commands separated by `R` "
        "and `RR` mode latches. An invalid model compiles to nothing at all rather than to a "
        "half-program.",
        "**Feed.** For each block in the program, the Pi sends `FEED <id>` to the Uno. The Uno "
        "closes the container, opens it in two stages, waits for the exit sensor to confirm a "
        "block has left, shuts the gate behind it, runs the belt, stops on the stage sensor, "
        "nudges the block square, re-reads the stage sensor, and returns exactly one terminal "
        "result.",
        "**Place.** Only on the Uno's correlated terminal success does the Pi send "
        "`B col row level` to the Mega. The Mega runs its fourteen-phase cycle: raise clear, "
        "home to the feeder, neutralise the claw, open, descend to the ground switch, grip, "
        "lift, traverse to the target cell, apply the grid's rotation, descend to the target "
        "level, release, then park by raising Z, homing X/Y and un-rotating the claw. It "
        "narrates every phase back over serial before that phase runs.",
        "**Verify and repeat.** The overhead camera watches the surface throughout and the "
        "digital twin mirrors the build live from the phase telemetry. The runner waits for the "
        "durable terminal result before dispatching the next block, and the loop repeats until "
        "the structure is complete or something refuses.",
    ])
    rep.p(
        "The Studio is the normal entry point for building a structure. The console's "
        "click-to-build path is the same guarded operation with a single cell instead of a "
        "program, and is what is used for commissioning, for calibration and for placing one "
        "block by hand.")
    rep.figure("End-to-end workflow, from a design in the browser to a block on the stack, "
               "showing where each of the five stages is confirmed and not assumed.",
               placeholder="Flow diagram to be drawn: design -> compile -> per block "
                           "(FEED -> staged OK -> B -> 14 phases -> PLACED -> verify) -> repeat, "
                           "with the two confirmation gates highlighted.")
