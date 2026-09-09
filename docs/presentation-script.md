# Final Presentation — Speaking Script

**Deck:** `Final Presentation Grad Project.pdf` — 40 slides
**Team:** Ahmed Gharib · Mohie Halawa · Khalil Qanabita
**Supervisor:** Dr. Samer Arandi

---

## How to use this

Each slide gives you **[ON SCREEN]** (what the panel is looking at), the **script**
(what to say — written to be spoken, not read), and **[NOTE]** where delivery
matters. Sections 02 and 03 are scripted in the most depth, as requested.

Do not read this aloud word for word. Learn the *spine* of each slide — the one
sentence that must land — and let the rest be yours.

### Timing — target 22 minutes, leaving 8 for questions

| Section | Slides | Target |
| --- | --- | --- |
| Opening — motivation, problem, objectives | 1–5 | 3:00 |
| **01 · System Design** | 6–18 | 5:30 |
| **02 · Vision & Control System** | 19–30 | **7:30** |
| **03 · Testing & Results** | 31–35 | **4:00** |
| 04 · Conclusion & Future Work | 36–40 | 2:00 |

### Suggested split (adjust freely)

- **Speaker A** — slides 1–18 (motivation → system design)
- **Speaker B** — slides 19–30 (vision & control) ← *the technical core*
- **Speaker C** — slides 31–40 (results → conclusion)

Whoever takes section 02 should be the one most comfortable being interrupted —
that is where the questions come.

### Three honesty anchors — say these out loud, do not let them be discovered

1. **Supervision has never seen a real camera frame.** Built, tested across three
   suites, not yet watched on the rig. Slide 30.
2. **The correction verb is written but unflashed.** Slide 30 and slide 38.
3. **The cycle-time numbers were measured on the automatic pick-up path.** Staging
   is currently manual. Slide 33.

A panel forgives a limitation you state. It does not forgive one it finds.

---

# OPENING · Slides 1–5

## Slide 1 — Title

**[ON SCREEN]** Title, three names.

> Good morning. This is *Vision-Assisted Cartesian Robotic System for 3D Block
> Construction*. I'm Ahmed, with Mohie and Khalil, supervised by Dr. Samer Arandi.
>
> Over the next twenty minutes we'll show you a machine that builds block
> structures from a design you draw in a browser — and, more importantly, a
> machine that checks its own work.

**[NOTE]** Fifteen seconds. Don't linger.

## Slide 2 — Table of Contents

> Four parts. How the machine is built, how it sees and decides, what we measured,
> and what we'd do next.

**[NOTE]** Five seconds. Keep moving.

## Slide 3 — Background & Motivation

**[ON SCREEN]** Four bullets on why this project.

> Industrial pick-and-place is a solved problem if all you need is to move a part
> from A to B. It stops being solved the moment the machine has to know whether
> what it just did actually worked.
>
> Most student-scale automation is timing-based. Open the gripper for six hundred
> milliseconds, wait two seconds, assume the block is there. That machine cannot
> tell success from failure — it can only tell you that time passed.
>
> Our goal was the opposite. A machine that confirms every stage rather than
> assuming it.

## Slide 4 — The Problem

**[ON SCREEN]** Five numbered failure modes.

> And the reason that matters is here. Stacking is *sequential*. Block seven has
> to be right, or block eighteen falls off it. A machine that can't detect a
> failure doesn't stop — it turns one silent error into a pile.
>
> Five ways that happens. A block that was never staged — the operator says the
> pickup area is loaded, nothing checks, and the claw closes on nothing. A block
> picked by its corner, because hand-staging makes position a promise rather than
> a measurement. A block that lands off its cell, or gets knocked after it lands.
> Lost steps, which open-loop steppers give you for free and never report. And a
> hand in the workspace, or a USB reset that reboots the board un-homed.
>
> Every one of these leaves the machine's internal model of the world wrong, and
> silently.

**[NOTE]** This slide sets up slide 30. If you rush anything in the opening, don't
rush this — the whole payoff of the talk is "we built the thing that catches
these."

## Slide 5 — Objectives

**[ON SCREEN]** Five numbered objectives.

> So: five objectives. A cell that builds repeatably from a browser-designed
> model. Any addressable cell, any stack level. Both block orientations, standing
> and lying, through a rotating end-effector. Vision that detects, localizes and
> verifies — and checks every placement against a record of what we asked for.
> And a browser platform to design, run and safely operate the whole thing.
>
> I'll flag now that objective four is the one we're proudest of and the one with
> the most honest caveat attached. We'll get there.

**[NOTE]** That last line is a deliberate hook. It buys you credibility early and
makes the slide-30 caveat feel planned rather than confessed.

---

# 01 · SYSTEM DESIGN · Slides 6–18

## Slide 6 — Section divider

> First, what the machine actually is.

## Slide 7 — Two Controllers, One Master

**[ON SCREEN]** Pi column, Mega column, closing paragraph.

> Two controllers. A Raspberry Pi 5 is the sole master — it owns the camera, the
> whole vision pipeline, the web service, the Studio, the as-built ledger, and
> every safety gate in the system.
>
> An Arduino Mega runs the gantry: step generation, homing, limits, the
> grid-to-steps arithmetic for both grids, the servos, and the fourteen-phase
> build cycle.
>
> The line that matters is at the bottom. **The Mega cannot originate a command.**
> It moves only on a message the Pi decided to send, and it announces every phase
> *before* it runs it. So the master's model of the machine is built from what the
> machine said — never from what it was told to do.

**[NOTE]** That last sentence is the architectural thesis of the whole project.
Slow down for it.

## Slide 8 — How One Block Gets Built

**[ON SCREEN]** Five-stage flow, banner underneath.

> End to end, one block. You design in the Studio, on the machine's real lattice.
> The compiler sorts bottom-up, groups by orientation, and emits `B col row level`.
> The operator stages one block at the pickup cell and confirms it. Only then does
> the fourteen-phase cycle run. And then the camera compares the board against the
> ledger and returns a verdict.
>
> Nothing in that chain is advanced by a timer. Every machine stage waits for a
> durable terminal result from the stage before it — and a stage that can't prove
> what happened stops the build instead of continuing.
>
> Staging is the one link a human supplies. Which is exactly why the camera checks
> the result.

**[NOTE]** If a panelist is going to attack the manual-staging decision, they'll do
it here. The answer is on slide 12 and the mitigation is on slide 30 — say
"I'll come to that in two slides" and move on.

## Slide 9 — Mechanical Design

> Four subsystems: the X and Y motion, the Z actuator, and the end-effector.
> Quickly through each.

## Slide 10 — The X/Y Stage: CoreXY

**[ON SCREEN]** CoreXY diagram, travel and step figures.

> CoreXY. Two NEMA17s are fixed to the *frame*, not the moving beam, driving one
> continuous belt path. Same rotation sense and the carriage walks along X;
> opposed senses and it walks along Y. The beam stays light and the envelope stays
> large.
>
> Twenty-two point eight centimetres of X travel, thirty-eight of Y. Two hundred
> steps per centimetre. Four limit switches, all normally closed — homing drives
> each axis into its own switch, and the corner where both are pressed is machine
> zero.
>
> The skeleton and the homing strategy follow an Instructables automated
> chessboard build; Z, the claw, the camera and both controllers are ours on top
> of it.

**[NOTE]** Name the reference out loud. Volunteering your prior art is always
better than being asked about it.

## Slide 11 — Z Axis and End Effector

> Z is one NEMA17 on the moving carriage, on a 15 mm linear rail — 26.5 cm of
> travel. Both ends are switches, and every build re-zeroes Z on the bottom one.
> Neither end is a remembered number, which means accumulated Z error can't
> survive a cycle.
>
> The claw is a single servo, two positions, gripping the block's 2.2 cm face.
> There's no sensor on it at all — hence a fixed 600 ms settle, which is one of
> the few genuinely open-loop things left in the machine.
>
> Rotation is a 28BYJ-48 through a ULN2003, a quarter turn, for the second block
> orientation. The grip centre sits slightly off the rotation axis, so a 90° turn
> swings the block — and we correct that as a per-rotation tool offset, not as a
> grid error. That distinction matters: correcting it in the grid would have been
> right in one mode and wrong in the other.

## Slide 12 — The Pickup Handshake

**[ON SCREEN]** Three numbered points, closing banner.

> This is how a block gets into the claw today.
>
> One reserved cell — `[0,0]`, in both grid modes, never built on. Its centre is
> the home corner, so a pick-up is a plain home with no move afterwards.
>
> The Pi sends `M col row level`. The firmware runs exactly the same validated
> route as a normal build, but it *pauses* after the open claw reaches the ground
> switch, and announces `await_manual_close`.
>
> And then closing is a separate decision. Only an explicit `C` closes the jaws.
> The operator aligns the block against a claw that is already in position — so
> the machine isn't trusting a promise about where the block was.
>
> Nothing here is assumed. The claw goes to a known place first, and a second
> explicit message closes it.

**[NOTE]** If asked *"why not automatic?"* — the honest answer, and it's a good
one: *"We built an automatic feeder. It's on the future-work slide as 'restore
automatic staging'. We took it out because it was the least verified subsystem in
the machine, and we'd rather demonstrate a cell with one honest human link than
one with an unproven automatic one."*

## Slide 13 — Two Grids, Not One Grid With a Flag

**[ON SCREEN]** Two lattices side by side.

> Blocks can stand up or lie down, and those are two different lattices — not one
> lattice with a rotation flag.
>
> They share one envelope, because a block lying down doesn't move a limit switch.
> Standing, it's 7×6 addressable, 41 buildable. Lying, 3×10, 29 buildable. Minus
> one in both cases, because `[0,0]` is the pickup cell and is never built on.
>
> The registration number is the nice part. 6.0 minus 2.2 over 2 is 1.9 — exactly
> the overhang of the rotated face, so horizontal `[0,0]` seats flush against
> vertical `[0,0]`. The two grids agree at the origin by construction, not by
> tuning.

## Slides 14–16 — Bill of Materials

**[NOTE]** Thirty seconds total for all three. Don't read the parts aloud.

> The bill of materials — computing, electrical, mechanical. Worth noting: one
> Mega, one Pi, one camera; three NEMA17s and one small geared stepper; four
> switches. It's a deliberately small parts count.

## Slide 17 — Power Architecture

> One 12 V rail for the three stepper drivers, one 5 V rail off a buck converter
> for the servo and the rotation driver, and one common ground. The Mega is
> powered over USB from the Pi, which is also how they talk.
>
> Fifteen amps looks over-specified until you notice the build cycle moves one
> thing at a time — so instantaneous draw is normally a single stepper plus logic.

## Slide 18 — Wiring

> The wiring diagram is taken directly from the firmware source, so the pin map on
> this slide and the pin map in the sketch cannot disagree.
>
> Motor and sensor runs use connectors rather than solder joints, so a motor can
> be swapped and the whole gantry dismantled for transport. There's no enclosure
> and no cable chain — and the missing cable chain will come back to haunt us in
> section three.

**[NOTE]** That last clause is a deliberate plant for slide 34. It makes the skew
slide feel like a payoff instead of a digression.

---

# 02 · VISION & CONTROL SYSTEM · Slides 19–30

> **This is the core of the talk — 7:30. Slides 20–23 are "how it sees", 24–26 are
> "how it decides", 27–30 are "what the operator gets". Pace yourself: it is easy
> to spend four minutes on the camera and rush supervision, which is the slide
> that wins the talk.**

## Slide 19 — Section divider

> Now the half of the project that isn't mechanical: what the camera sees, how a
> pixel becomes a cell, the protocol that decides when the machine may move — and
> what the camera says about what was built.

## Slide 20 — One Lens, Two Costs

**[ON SCREEN]** Spec table, raw uncorrected frame.

> One camera: a 5-megapixel OV5647 on the Pi's CSI bus, with a 160-degree fisheye,
> mounted rigidly about 50 cm above the surface. We capture at 1296 by 972 — the
> binned full-field mode — because that keeps the entire 23 by 38 centimetre
> workspace in one frame at a per-frame cost we can afford.
>
> That choice buys us the whole board in one look. It costs us two things, and
> you can see both in this raw frame.
>
> First, severe barrel distortion. Those aluminium rails are dead straight on the
> machine and visibly curved in the image. Second — and this one surprised us — a
> colour cast strong enough to be a *functional* fault rather than a cosmetic one.
> It's not that the picture looks wrong. It's that a colour-based detector stops
> working.
>
> And I want to be precise about the lens model: it's tuned by eye against
> straight edges, not checkerboard-calibrated. The saved file literally records
> `source: estimated`. That's a real limitation and it's on our limitations slide.

**[NOTE]** ~55 seconds. Volunteering "tuned, not calibrated" here defuses the most
likely vision question before it's asked.

## Slide 21 — The Vision Pipeline

**[ON SCREEN]** Three columns.

> The pipeline has one fixed route and one process owns the camera.
>
> Colour correction runs *once*, at the captured frame, immediately after
> orientation and before every detector — so every tool in the system sees
> identical pixels. Deliberately, colour is *not* part of the saved projection
> identity: correcting colour must never silently change where the machine thinks
> a cell is.
>
> Detection runs on a background worker at a lower rate than the video, with the
> main loop drawing the last completed result. That's what stops a slow analysis
> from stalling the stream — the operator's live view never freezes because the
> detector is thinking.
>
> And the Pi picks the cell; the firmware turns it into steps. The saved
> homography converts a pixel to physical centimetres and then to a `[col, row]`.
> The Pi never needs a motor step to draw or select a cell.

## Slide 22 — Block Detection

**[ON SCREEN]** Ten off-lattice blocks, all found. Three layers on the right.

> Detection is three layers, and it's built as a hypothesis followed by an answer.
>
> Segmentation finds warm material by red-minus-blue and red-minus-green — never
> by brightness. That's not a preference, it's forced: the work surface is
> overexposed, so a brightness cutoff selects the *table* and not the blocks.
>
> The live overlay then rejects and rectifies — duplicates by intersection-over-
> union, boxes running off the frame which are usually the rails, and anything
> further than about a third of a cell from a lattice site, which is usually a
> wooden offcut.
>
> And calibration is the third layer, run once, deliberately, and the only layer
> allowed to write a calibration.
>
> Two rules keep this honest, and both are asserted by tests. **The measured
> centre is never snapped to the lattice** — snapping would hide the exact
> misplaced block the overlay exists to show you. And **the lattice filter never
> fires on a partial view**: under six detections, or if it would throw away more
> than 30 % of what it saw, we keep everything.
>
> The picture is ten blocks placed deliberately *off* the lattice. All ten found,
> everything else rejected.

**[NOTE]** ~70 seconds. The two honesty rules are the memorable part — they show
you thought about how your own tool could lie to you.

## Slide 23 — Grid Calibration

**[ON SCREEN]** The labelled calibration board photo; four routes; five gates.

> Calibration answers one question: where does the machine's grid sit on the
> camera image.
>
> Four routes to one artefact. Four clicked corners as a fast fallback. A printed
> A2 colour target as the primary route. An evidence-assisted mode that pools
> frames when the gantry is parked over part of the sheet. And — the one on
> screen — placed-block self-calibration, where the rig places its own blocks, so
> the thing being measured is the thing being calibrated.
>
> That's the image you're looking at: every cell labelled, green where a detection
> joined its lattice site, red where the cell is empty, magenta on the reserved
> pickup cell.
>
> And these five are **acceptance gates, not status readouts**. Colour parity,
> measured aspect ratio, mean *and* maximum residual, at least 95 % physical
> coverage, and numerical conditioning. All of them must pass. A calibration that
> fails any one of them is refused — but it still draws what it found, green for
> blobs that joined a lattice and red for those that didn't, so you can see *why*
> it was refused.

**[NOTE]** ~60 seconds. "Gates, not readouts" is the phrase to land. If asked why
placed-block is best: *"because the printed sheet measures the sheet. The blocks
measure the machine."*

## Slide 24 — Control Hierarchy

**[ON SCREEN]** Two columns, and the "why the boundary is drawn there" paragraph.

> The division of labour. The Pi decides *whether*; the Mega decides *how*.
>
> The Pi chooses the target cell, the level and the grid mode, coordinates staging
> then the guarded build, applies every safety gate, owns the session lock, holds
> the as-built record — and decides whether a command may be issued at all. What
> it never does is send a motor step, a direction bit or a delay.
>
> The Mega owns step generation, polarity, homing, limits, the grid-to-steps
> arithmetic for both modes, and everything that can't change without reflashing.
>
> The reason the line is drawn exactly there is at the bottom. The firmware owns
> the step caps, the Z calibration, the servo angles, the pin map — physical facts
> nothing should be able to push over a serial link. A stale copy of those on the
> Pi would be a lie nobody notices until the rig drives into something.
>
> A handful of values genuinely have to exist in both places. So we wrote a test
> that parses the live sketch — two hundred and thirty-seven checks — and fails
> the build if either side has moved.

**[NOTE]** That test is a strong engineering signal. Say the number.

## Slide 25 — The Acknowledgement Protocol

**[ON SCREEN]** Sample lines; eight ack kinds; SAFE vs HELD.

> The serial protocol has one line for the human and one line for the Pi. You can
> see both: a readable "build complete, block placed at 3,5", and `@12 OK col=3
> row=5 level=0`.
>
> Every machine line starts with `@` — a character no other line in the sketch
> begins with — so the Pi's filter is a single string test. It's key-equals-value
> and not JSON, because on an 8-kilobyte AVR at 9600 baud, braces and quotes cost
> SRAM and airtime for nothing.
>
> Eight kinds of acknowledgement, four of them terminal, and exactly one terminal
> ack per command.
>
> The important pair is `SAFE` and `HELD`. `SAFE` means refused on validation —
> nothing moved, and a retry is fine. `HELD` means it failed *part way through* —
> the claw may still be gripping a block and the position is unknown. That needs a
> person.
>
> They're separate *kinds* rather than a flag on one kind, specifically so that
> code on the Pi cannot collapse them into a generic "if not OK, retry". Because
> the retry is the thing that breaks the machine.

**[NOTE]** ~65 seconds. This is a favourite examiner topic — protocol design with a
stated reason. The SRAM justification and the anti-retry argument are both strong.

## Slide 26 — The Fourteen-Phase Build Cycle

**[ON SCREEN]** All fourteen phases; the phase-5 note; the parking note.

> One placement is fourteen phases, and every phase is announced *before* it runs.
>
> Raise clear, home to the pickup cell, neutralise the claw, open the jaws, lower
> into the bottom switch — which re-zeroes Z every single cycle — grip, lift, fly
> to the target, apply the grid's rotation, lower to the level, release, then park:
> raise clear, home X and Y, return the claw to neutral.
>
> Phase five is where the operator enters. In manual staging the claw stops there,
> down and open, and waits for the explicit `C` before phase six closes it.
>
> And phases twelve to fourteen aren't decoration. **Placed but not parked is not
> a success** — if the rig places the block and then fails to park, the terminal
> result is downgraded from `OK` to `HELD`. Because a machine sitting in an
> unknown position with a block somewhere is not a machine that succeeded.

**[NOTE]** ~50 seconds. Don't recite all fourteen names slowly — group them as
above. The parking rule is the point.

## Slide 27 — The Operator Console

**[ON SCREEN]** Console screenshot.

> The browser console. Tap a cell — selection moves nothing, and it shows you the
> exact command it will send, `B 3 2 1`. Then tap BUILD, then CONFIRM: confirm the
> block is staged, and close the claw when the rig says it's in position. Two
> deliberate taps, and the second one is the rig asking, not the interface
> nagging.
>
> Three outcomes. Placed, green, selection cleared. Rejected, amber, nothing
> moved. Aborted, red, session locked.
>
> And there's no cancel and no retry. Not because we didn't get to it — because
> the machine cannot honour either. The gantry doesn't read serial while it moves.
> A cancel button would be a lie, and a greyed-out button is never the safety
> mechanism anyway.

**[NOTE]** "A cancel button would be a lie" is a line worth delivering cleanly.

## Slide 28 — The 3D Build Studio

**[ON SCREEN]** Studio; validator's three questions; compiler's four steps; bond note.

> You design in the browser, in 3D, on the machine's real lattice.
>
> The validator asks three questions. Support — an actual centre-of-mass toppling
> test, not a contact-ratio shortcut. Collision — computed in machine space rather
> than grid indices, so a horizontal block spanning two columns is checked
> correctly. And reachability — inside the active grid, under the firmware's build
> ceiling.
>
> The compiler runs in four steps: build the support graph from footprint overlap,
> order it bottom-up with Kahn's algorithm while grouping same-orientation runs to
> minimise mode latches, emit a mode command only on an actual change, then
> summarise. It's deterministic — twenty compiles, byte-identical output — and an
> invalid model compiles to *nothing at all*, never to a half-program.
>
> And it lays a bond. A course can carry a half-pitch offset on the run axis, so a
> block bridges the joint of the two beneath it, centred, equal overlap each side.
> The Studio, the compiler, the twin and the rig all agree on where that block
> goes. That's the difference between stacking columns and actually laying
> masonry.

**[NOTE]** ~65 seconds. "Never a half-program" and the bond are the two things to
land.

## Slide 29 — The Live Digital Twin

**[ON SCREEN]** Twin; four claims.

> The twin mirrors the build in 3D, and its entire design rule is: it draws what
> the firmware said, and nothing else.
>
> It never invents state. A block is drawn as placed because the server reported a
> terminal placed result for it — and for no other reason. After an abort it
> stops: a locked session freezes the animation, desaturates every block, and
> demotes everything unconfirmed to a ghost.
>
> It's phase-driven, not clock-driven, and that was a real bug we fixed. An
> earlier version interpolated a 1.6-second descent from the browser's clock and
> looped it — so a 40-second build showed twenty-five descents that never
> happened. The twin was telling a story instead of reporting.
>
> Now, if Z jams, the block glides down, stops just short of the cell, and sits
> there visibly not landing. Which is the truth.

**[NOTE]** ~50 seconds. Telling the story of a bug you found *in your own
visualisation* is one of the most credible things in the deck. Don't cut it.

## Slide 30 — Placement Supervision ★

**[ON SCREEN]** Verdict table; quiet-window and NO_VISION notes; correction flow;
the caveat line.

> This is the piece that answers slide four.
>
> The rig places a block and forgets it. Supervision gives it a memory — a ledger
> of every cell it was commanded to fill — a way to look at the board, and the
> discipline to say when the two disagree, without ever guessing.
>
> Seven verdicts. `AGREES` and the run continues. Then four amber verdicts that
> *pause* the run: `NOT_DETECTED`, a commanded cell reads empty. `REMOVED`, cells
> emptied and nothing arrived anywhere. `MOVED`, one cell emptied and a different
> valid cell filled. `DISPLACED`, the same event, but the block landed in a gap
> rather than on a cell. And two red verdicts that *stop* it: `FOREIGN`, something
> on the board that was never commanded, and `DISAGREES`, where both sides changed
> and the change can't be paired one-to-one.
>
> Two design decisions I want to draw out.
>
> **It only looks when the rig is parked.** There's a measured quiet-window gate —
> under one per cent of pixels changing between frames — so the camera never
> judges a board the gantry is still moving over. Those constants were measured on
> the rig, not guessed.
>
> And **"I could not see" is never "nothing is there."** A detector failure or a
> stale frame raises `NO_VISION`, which is deliberately *not* a verdict.
> Collapsing that into "the board is empty" would make the whole feature lie —
> it would report `REMOVED` for a block that's sitting right there.
>
> It can also act, not just report. A CORRECTION button closes the loop: verdict,
> the server re-checks safety, the firmware's pick-from-cell verb, then re-verify.
> It's scoped hard — vertical mode, level zero, axis-aligned, no taller neighbour,
> destination clear — and it refuses a diagonal correction outright, because a
> block shoved into a corner closes two escape corridors at once and there's
> nowhere to get a jaw down.
>
> And the honest part, which is on the slide: this is **built and tested across
> three suites, but it has not yet been watched on a real camera frame** — there's
> no camera on our development machine, and the bench session is the outstanding
> item. The correction verb is written and syntax-checked but **unflashed**. We
> know exactly what's verified and what isn't.

**[NOTE]** ~100 seconds — the longest slide in the deck, and it should be. Deliver
the caveat at normal pace and normal volume; dropping your voice makes it sound
like an admission instead of a statement.

**[Q&A TRAP]** *"So it doesn't actually work?"* → *"The logic works and is
covered by 186 tests across three suites. What hasn't happened is one session
with the camera pointed at the board. That's a scheduling gap, not a design gap —
and it's the first item on our future-work slide."*

---

# 03 · TESTING & RESULTS · Slides 31–35

> **4 minutes. This section's job is to convert claims into evidence. Lead with
> the methodology, because it explains why the numbers should be believed.**

## Slide 31 — Section divider

> Sixteen complete builds on hardware, two reference boards, and over nine hundred
> automated checks across three suites.

## Slide 32 — Testing Methodology

**[ON SCREEN]** Four levels; the closing line.

> We tested at four levels, and the principle was: answer every question at the
> cheapest level that can honestly answer it.
>
> Level one, automated software tests, no hardware — grid arithmetic, protocol
> parsers, the compiler, the twin, the homography. The Python and TypeScript
> implementations of the grid are held against each other by *shared fixtures*, so
> the two can't drift apart.
>
> Level two, protocol-level simulation, still no hardware. A fake Mega speaks the
> same acknowledgement grammar, including failure, reset and lock-out. That's how
> the guarded command path and every terminal-result branch were tested
> exhaustively — including the failure branches you cannot safely produce on a
> real rig.
>
> Level three, firmware host builds. A stub-Arduino harness proves the sketch
> parses and that its output is byte-for-byte the protocol. And the second test
> there is the one I mentioned earlier — it holds the firmware's 237 constants
> against the config file, so a value edited on one side of the machine and not
> the other fails the build.
>
> Level four is the real machine — anything touching motion, limits or Z. Every
> run appends to two logs: a stopwatch per build, and every serial line with the
> gap since the last one.
>
> And the reason for the hierarchy is at the bottom: the rig takes half a minute
> to answer one question, and a wrong answer can drive a claw into a stack. So the
> level-four logs are the primary evidence, and everything above it is rehearsal.

**[NOTE]** ~75 seconds. "A clean compile is not a test of behaviour" is the
underlying attitude — say it if you have room.

## Slide 33 — Cycle Time and Repeatability

**[ON SCREEN]** Five headline figures; the 14-phase bar chart; two explainer cards.

> Sixteen builds on hardware. All sixteen placed.
>
> Mean cycle, twenty-six point one seconds per block. Fastest just under twenty,
> worst case just over thirty-two. Our objective was under forty-five, so we're
> comfortably inside it.
>
> The chart is the mean duration of each of the fourteen phases, with the light
> bar showing minimum to maximum across all sixteen runs.
>
> Two things fall out of it. **Nine of the fourteen phases never move** — they
> have no distance or level dependence at all. Across all sixteen builds those
> nine summed to twelve point five seven seconds, with a standard deviation of
> zero point one eight. Six of them were identical to the 0.01-second logging
> resolution. That's the repeatability claim, and it's measured rather than
> asserted.
>
> **And the variation is travel — nothing else.** Only phases eight and thirteen
> range widely, from about one and a half to eight and a half seconds. Those are
> the two long moves. With no acceleration ramp, a move of N steps takes N times a
> fixed period, so travel time is linear in distance and everything else is
> constant.
>
> One caveat, and it's on the slide. These sixteen builds were measured on the
> automatic pick-up path. Manual staging adds an operator-paced pause inside phase
> five, which the machine deliberately doesn't time — we're not going to report a
> number that's really measuring how fast a human is.

**[NOTE]** ~80 seconds. The caveat is the credibility move. Deliver it as a design
decision ("we're not going to report a number that measures a human"), which is
what it is.

**[Q&A TRAP]** *"Could it be faster?"* → *"About a third of the cycle is those two
travel phases, and there's no acceleration ramp — adding one is on the future-work
slide. The other two-thirds is fixed servo and homing time, which is a hardware
floor, not a software one."*

## Slide 34 — The X-Rail Skew ★

**[ON SCREEN]** Measurement table; two explainer cards.

> This is my favourite result in the project, because it's the whole method in one
> slide: a symptom, a measurement, a physical cause, and a software correction.
>
> The symptom. A block placed with pure Y motion lands exactly where the grid
> says. A placement involving X motion lands off — but off along **Y**. And the
> error grows with how far along X the rig travels. So it isn't a constant offset,
> which is what you'd normally reach for.
>
> So we measured it. Column zero, no X travel, zero error. Column one, 0.115
> centimetres. Column two, 0.230. Column three, 0.345. It's linear in the column
> index — 0.115 times k — with **no row dependence at all**. And that second part
> is the clue that identifies the cause.
>
> Here's why. The arm holder rides the X rod and it isn't supported symmetrically.
> Its own mass, the cable-chain drag, and the belt's side load all pull on *one
> side*. That constant sideways pull bows the rod very slightly out of square with
> Y. So the further the carriage travels along X, the more of that angled rod it
> has crossed, and the more it also drifts along Y.
>
> Re-machining or re-bracing the rod was out of scope for this build. So we cancel
> it in firmware instead: for a build, we command Y to a position offset by
> exactly the drift the slanted rod is going to add — per axis and per grid mode —
> so the two cancel out and the block lands where the ideal grid says it should.

**[NOTE]** ~75 seconds. This slide is a gift in Q&A — it proves you understand the
machine physically, not just as software. If you're running long elsewhere, cut
something else to protect this.

**[Q&A TRAP]** *"Why not fix the mechanics?"* → *"We'd want to. It's a stiffness
problem in a rod we can't easily re-machine at this scale. The compensation is
exact and measured, but it is a correction, not a cure — and it's why 'fix the
camera, not the matrix' appears on our future-work slide as a general principle."*

## Slide 35 — Vision Results

**[ON SCREEN]** Five figures; the fit comparison; two negative results.

> Vision, measured on two reference boards.
>
> Twenty-nine of twenty-nine blocks found on both boards. Thirty-three hypotheses
> reduced to twenty-nine after rejection — so the rejection stage is doing real
> work. Thirty-seven to a hundred and three milliseconds per analysed frame. Mean
> fit residual of 0.85 pixels. And 0.27 centimetres of mapping error on a 2.2
> centimetre block.
>
> The fit was chosen on **held-out prediction, not training error** — similarity
> at 101 pixels, affine 1.38, homography 1.22, homography plus curvature 1.09. And
> we ran an independent geometry check: the view is 17.7 % anisotropic, and two
> independent estimates of that agree to within 4 %.
>
> One point of honesty on the 0.27: that's the saved four-corner *format*
> flattening the fit — not the fit itself. The fit is better than the number we
> ship; improving the storage format is on future work.
>
> And two negative results, which we think are as valuable as the positive ones.
> **Higher resolution finds nothing extra** — twenty-nine of twenty-nine at every
> width from 384 to 1024 pixels, and illumination flattening costs up to nearly
> four seconds a frame to find exactly the same twenty-nine. **And white balance
> is right for the sheet and wrong for the board**: on the printed sheet it takes
> the green mask from zero pixels to eighty-seven thousand, but on a board of
> blocks it pulls the wood toward the surface colour — twenty-eight of twenty-nine
> with it on, twenty-nine with it off.
>
> So we ship it off for the board. That's a setting chosen by measurement, in a
> direction we didn't expect.

**[NOTE]** ~80 seconds. Reporting negative results unprompted is the single
strongest credibility move available to you. Give them full weight.

---

# 04 · CONCLUSION & FUTURE WORK · Slides 36–40

## Slide 36 — Section divider

> Finally: what this proves, what it doesn't, and what we'd do next.

## Slide 37 — Limitations, Stated Plainly

**[ON SCREEN]** Seven limitations; the supervision ceiling note.

> Seven limitations, and they're limits of the hardware rather than of the
> approach.
>
> No hardwired emergency stop — nothing removes motion energy independently of the
> software, so the stop of last resort is the supply, and the machine is run
> attended. No watchdog: if the Pi crashes, the Mega finishes the command it's
> already holding. The lens is tuned, not calibrated. Motion cannot be
> interrupted, because the gantry doesn't read serial while it moves — so software
> stop is stop-after-current-block by construction. Open-loop steppers with no
> stall detection. The claw angle isn't sensed, so the operator is trusted to
> start neutral. And staging isn't verified — the operator confirms a block is at
> the pickup cell, and the machine believes it.
>
> One more, at the bottom, and it's a limit we *enforce* rather than just state.
> Supervision does not judge above level three. A stacked block's apparent
> position shifts under the fisheye, so an absent detection up there is a filter
> artifact, not a missing block. Those cells are drawn hatched and counted as
> unjudged — because reporting them would be the feature lying.

**[NOTE]** ~60 seconds. The last one is the strongest: a limitation the code
actively refuses to cross. Say "enforced, not just stated."

## Slide 38 — Future Work

**[ON SCREEN]** Safety block; three columns.

> One item here is not optional, and it's safety. A hardwired emergency stop — a
> latching mushroom button in series with a contactor on the 12 V motor rail. And
> a stop that's observable during motion, plus a communications watchdog that
> brings the rig to a defined state.
>
> The rest are genuine but optional. Closing the loop on placement: the bench
> session for supervision, flashing and watching the correction verb, the bounded
> automatic repair that's already built and deliberately switched off, lifting the
> level-three ceiling, and restoring automatic staging.
>
> Measuring properly: a real checkerboard or ChArUco calibration, a per-cell table
> in the saved map to remove that 0.27 flattening error — and fixing the camera
> rather than the matrix, because the colour correction is at its limit.
>
> And capability: controller-supplied command ids, encoders or stall detection —
> worth about a third of the cycle time — a faster serial link, and a larger
> workspace.

## Slide 39 — Conclusion

**[ON SCREEN]** Four claims; five statistics.

> Cartesian gantries are a solved problem. What this project demonstrates is the
> layer that student-scale automation usually leaves out: **every physical
> transition confirmed by something other than a clock.**
>
> The camera checks the board against a record of what was commanded, and names
> the cell when they disagree — or says plainly that it could not see. The gantry
> narrates each of its fourteen phases before running it. The twin draws what the
> firmware said, and stops short of the cell until the release event arrives. And
> when the machine cannot prove what happened, it locks and asks for a person
> rather than retrying.
>
> Sixteen of sixteen hardware builds placed. Twenty-six point one seconds mean
> cycle. Five levels on one cell. Twenty-nine of twenty-nine blocks detected. Over
> nine hundred automated checks.
>
> Thank you.

**[NOTE]** ~45 seconds. The thesis sentence is in bold for a reason — it's the one
sentence you want the panel to be able to repeat afterwards. Pause before it.

## Slide 40 — Thank You / Questions

> Thank you — we're happy to take questions.

---

# Q&A PREPARATION

## The five most likely questions

**1. "Why is staging manual? Isn't that the interesting part?"**
> We built an automatic feeder — an Arduino Uno, a conveyor, a hopper gate and two
> sensors. We took it out because it was the least verified subsystem in the
> machine, and it was gating the parts we could prove. Restoring it is on the
> future-work slide. What replaced it isn't nothing: the claw now goes to a known
> position *first*, and a separate explicit message closes it — so the machine
> isn't trusting a promise about where the block was.

**2. "Supervision hasn't run on the rig — so how do you know it works?"**
> We know the logic is correct: it's covered by three test suites, and the
> quiet-window constants that gate it were measured on the real machine. What we
> haven't done is one session with the camera pointed at the board. That's the
> first item on future work. We'd rather tell you that than show you a demo and
> let you assume more than we've earned.

**3. "0.27 cm of error on a 2.2 cm block is over 10%. Is that good enough?"**
> It's good enough to place and stack reliably — sixteen of sixteen. And the
> number is worse than our actual fit: 0.27 is the saved four-corner *format*
> flattening a fit whose residual is 0.85 pixels. Storing a per-cell table instead
> removes most of it, and that's on future work.

**4. "Why no encoders?"**
> Cost and scope. It's on future work, and we've estimated it's worth about a
> third of the cycle time as well as giving us stall detection. What we did
> instead was make position *unnecessary to remember*: every build re-homes, and
> every build re-zeroes Z on the bottom switch, so error can't accumulate across
> cycles.

**5. "What's the single biggest weakness?"**
> No hardwired emergency stop. Everything else on our limitations slide is a
> capability gap; that one is a safety gap, which is why it's the only item on
> future work marked as not optional.

## If you are asked something you don't know

Say so, then say what you *do* know and where the answer would come from. This deck
has spent twenty minutes establishing that you distinguish carefully between
verified and unverified. Guessing once would undo it.

---

# PRE-FLIGHT CHECKLIST

- [ ] **Slide 30 still says "SUPERVISION OVERLAY — SCREENSHOT TO BE ADDED."**
      Either add the screenshot or delete the placeholder box — do not present a
      slide with visible TODO text on it.
- [ ] Rehearse slides 30, 33 and 34 out loud with a timer; they carry the talk.
- [ ] Agree who answers what in Q&A, so three people don't start at once.
- [ ] Decide in advance who takes a hostile question about manual staging.
- [ ] Check the projector renders the bar chart on slide 33 legibly from the back.
- [ ] Have the console open and the rig powered if a live demo is possible — and
      if it is, decide *before* you start what you will do if it fails.
