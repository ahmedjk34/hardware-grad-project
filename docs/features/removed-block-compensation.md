# Removed-block compensation — noticing, and then deciding what to do about it

**Status: the detection half is now BUILT; the compensation half is not.**

[Placement supervision](placement-supervision.md) shipped, and it already
**notices** a removed block: the continuous verdict runs in every quiet window
while the rig is parked, names the exact cell, and **pauses the runner**. It
also turned out not to be an idle-time activity at all — Gate 0 measured the
quiet window opening in **42–47% of frames during a running program**, ~9 usable
windows a minute, so mid-*program* detection needs none of the machinery this
document once assumed.

What is still unbuilt is everything after "noticing": deciding what to do,
re-planning, or re-placing. That is supervision's **M4**, and it is deliberately
off — *a machine that re-places a block a human just deliberately removed is
infuriating*, and there is still no way to tell the two apart.

---

## 0. Do not start here

The detection half of this feature is
[feature-ideas.md §1.4 and Appendix A](../feature-ideas.md#appendix-a--placement-supervision-full-design):
a `PlacementLedger`, a `Supervisor`, the quiet-window interlocks, the hysteresis,
the set-difference classifier and the five verdicts (`VERIFIED`, `MOVED`,
`REMOVED`, `FOREIGN BLOCK`, `BOARD DISAGREES`), with milestones M1–M5 and a full
list of known limits.

**Read [placement-supervision.md](placement-supervision.md) and its
[build record](placement-supervision-progress.md) first — they are the built
code and they correct several of Appendix A's claims.** Do not restate them, do
not re-derive them, and do not implement a second detector beside them. Everything below assumes it exists and adds only
what it deliberately excluded:

> **A.6, Not doing: "Verifying during a build. The firmware is deaf mid-command
> and the arm is in the frame. Supervision is an idle-time activity."**

That exclusion is correct, and the request appears to contradict it. It does not
— because of one reframing.

---

## 1. The reframing that makes this possible

**Mid-*command* is impossible. Mid-*program* is not.**

- A single `B <col> <row> <level>` is one atomic 14-phase pick/place/park. The
  Mega is deaf for its entire duration, the arm crosses the board, and the
  firmware reports phases but takes no input. Nothing can be verified or
  compensated inside it.
- A **program** — a compiled model — is a *sequence* of individually guarded
  builds. [runner.ts](../../web/src/studio/runner.ts) already models exactly this:
  a `cursor`, one op at a time, `settled` between ops, and phases
  `paused` / `stopped-mismatch` / `locked` that stop it. Its own header states
  the rule: *"the driver may execute an effect and feed the result back; it may
  never invent the next command."*

So **"mid-build" means "between two ops of a running program"**, and that gap is
precisely the quiet window Appendix A's D4 already specifies: gantry parked,
scene still, board settled. The machine is *already stopping there* — it stops
after every single block.

Everything in this document hangs off that sentence. If a future reader takes
one thing from this file, take that one.

---

## 2. What exists that this can be built on

| Piece | State | Where |
| --- | --- | --- |
| A program with a cursor, run one op at a time | **exists** | [web/src/studio/runner.ts:70](../../web/src/studio/runner.ts#L70) — `cursor`, `program`, `inFlight`, `pendingConfirm` |
| Runner states that already mean "stop and ask" | **exists** | `paused`, `stopped-mismatch`, `locked`, `pauseReason` |
| A verify step already in the effect vocabulary | **exists** | `{ kind: "verify"; expect; actual }` — today it verifies the *selected command*, not the *board* |
| Per-step camera thumbnails in the run report | **exists** | `run-report.ts`, `runner-driver.ts` — raw evidence images, **not** vision verification |
| An optional `vision_verification` field the UI already reads | **exists, never populated** | [RunnerPanel.tsx](../../web/src/components/RunnerPanel.tsx) — the Python backend never sets it |
| 10 Hz detections off the live feed, off-lattice ones rejected | **exists** | `ConsolePipeline`, `ProcessedFrame.detections`, `block_outline._lattice_filter` |
| those detections **labelled with a cell** | **BUILT** — `rig.supervisor.observe()` does it. Note the original claim, which was wrong: — `_lattice_filter` discards its indices; pixel → cell is `WorkspaceMap.cell_at` and belongs to the supervisor. See [placement-supervision.md §2a](placement-supervision.md#2a-three-things-the-earlier-designs-got-wrong) |
| Support / centre-of-mass maths over a model | **exists** | [web/src/studio/validate.ts](../../web/src/studio/validate.ts) — support ratio, toppling test, `levelCeiling` |
| A twin that refuses to invent state | **exists** | [twin.ts](../../web/src/studio/twin.ts) — and its rules apply to anything built here |
| Server-side record of what has been placed | **BUILT** — `rig/placement_ledger.py` | was Appendix A M1 |
| The supervisor and its verdicts | **BUILT** — `rig/supervisor.py`, published as `SupervisionModel`, rendered on four surfaces, and it pauses the runner on amber | was Appendix A M2–M3 |
| Any plan-repair vocabulary | **does not exist** | this document |
| A firmware verb that retrieves a placed block | **does not exist** | Appendix A M5 |

**Dependency order is not negotiable:** M1 ledger → M2 observer → M3 classifier →
*then* this. A compensation policy on top of a classifier nobody has watched run
for a session is a machine acting on guesses.

---

## 3. The three cases, and they are genuinely different

Somebody takes a block off the board. Where the cursor is decides everything.

### Case 1 — the program is not running (idle)

Appendix A already covers this completely. `REMOVED [a,b]` → the one automatic
repair the machine can perform: re-issue `B a b <level>`. Feed a block, place it
back. Opt-in, rate-limited, one per cell per run (A.1 D8/D9).

**Nothing new is needed here.** The user's "if not, it can do it with the next
build command" is exactly D9's armed-repair path.

### Case 2 — a program is running, and the missing cell is *below or at* the cursor

The interesting case, and the request's actual subject. The block was part of the
plan, it was placed, it settled, and now it is gone while later blocks are still
queued.

The compensation vocabulary — four policies, in increasing ambition:

| Policy | What it does | When it is *legal* |
| --- | --- | --- |
| **P1 — stop and ask** | pause at the current cursor, name the cell, show expected vs observed | always. The fallback for every case below |
| **P2 — repair in line** | insert `B a b level` at the cursor, run it, re-verify, then continue | only when `[a,b]`'s missing level is the **top of that column right now** — i.e. nothing was placed above it. Otherwise you are asking the claw to drop a block into a hole under a stack |
| **P3 — defer to the tail** | append the missing block to the end of the program | only when **no remaining op depends on it** — no later block rests on that column, and the structure is stable without it meanwhile |
| **P4 — abandon the block** | record it, finish the plan without it | only when nothing depends on it *and* the operator says so. Never automatic |

**P2's legality test is the load-bearing one, and it is not "is the cell empty".**
It is a question about the *column*: a level-0 block removed from under a
three-high tower cannot be replaced, because the tower is standing on air that
the claw cannot reach into. The honest answer there is P1, and the operator's job
is to decide whether to dismantle.

**P3's dependency test is `validate.ts`'s support maths, reused.** "Does any
remaining op rest, directly or transitively, on this column?" is the same
question the validator already answers when it rejects an unsupported block.
Reuse it; do not write a second one.

### Case 3 — a program is running, and the missing cell is *ahead* of the cursor

A block the plan has not placed yet cannot have been removed by the plan. Either
it was never there (fine — the plan will fill it) or something occupied that cell
and has now gone (which is a `FOREIGN` story, not a `REMOVED` one).

Verdict: **note it, do not act.** The plan will address that cell in its own time,
and the validator's collision checks are what protect it.

---

## 4. Where the verdict lives — server or client?

| Approach | Argument for | Argument against |
| --- | --- | --- |
| **A. Client runner decides** | it already owns the cursor, the program and the pause states; no new server surface | the client cannot see detections, would have to be *told* the verdict anyway, and `twin.ts`'s rule is that the browser never authors machine state. A reload loses everything |
| **B. Server supervisor decides, runner consumes** | the ledger, the detections and the interlocks are all server-side already; survives a reload; one implementation serves the idle case and the mid-program case identically (Appendix A's D7 makes exactly this argument) | needs a new field on `StateModel` and a new runner event |
| **C. Server decides *and* acts — auto-inserts the repair build** | fewest round trips | the server does not know the program. The program is the browser's. A server that inserts commands into a plan it cannot see is the single worst option here |

**Recommended: B, with the runner owning the *policy* and the server owning the
*verdict*.**

> The server says **what is true about the board**. The runner says **what to do
> about it**. Neither does the other's job.

Concretely: `StateModel` gains a supervision block (verdict, the differing cells,
the mode it was judged in, and the settle evidence). The store folds it into a
new `RunEvent` — `{ type: "board-verdict"; … }` — and the reducer maps it onto
the existing `stopped-mismatch` / `paused` machinery, plus (when the policy and
the legality test both allow it) one extra `build` effect at the cursor.

That keeps every existing guarantee: one command at a time, nothing queued, the
server's guards still authoritative, and the whole decision reachable-state
testable in Vitest exactly as the rest of the reducer is.

### The hybrid worth building

- **B** for the verdict path — always.
- **A**'s instinct kept for one narrow thing: the runner may *pause itself* on a
  verdict without waiting for a server round trip, because pausing is always
  safe. Acting always waits for the server.
- **C** explicitly rejected, and worth writing down as rejected so it is not
  re-proposed.

---

## 5. The traps

1. **Level-blindness is fatal here specifically.** Supervision is level-blind by
   construction (Appendix A D3): the camera is above the board and a block at
   level 1 hides the one under it. Mid-program, the removals that matter most are
   *off the top of stacks* — which is exactly the case that is invisible. **Say
   this on screen.** A feature that claims to notice removals and cannot see the
   commonest one is worse than no feature.
2. **The arm is in the frame more of the time during a program.** The quiet
   window between ops is short. Measure how many settled frames you actually get
   between two builds before designing around `SETTLE_N = 3` of them.
3. **A sparse board disables `_lattice_filter`** (it skips below
   `MIN_LATTICE_BLOCKS` (6) and self-disables past 30 % rejection). This is
   `block_outline`'s concern, not supervision's — `locate()` classifies by
   geometry at any count. Supervision's old `MIN_LATTICE_BLOCKS` mirror (D10,
   no `FOREIGN` on a sparse board) was removed once the holder came off the
   rig; `FOREIGN` / `DISAGREES` are live from block one. See
   [placement-supervision.md](placement-supervision.md) D10.
4. **A mode latch invalidates the observed set.** Two grids, two lattices, two
   registrations. The ledger is keyed by mode; a program with an `R`/`RR` in it
   crosses that boundary mid-run.
5. **Re-verify after any repair.** A repair that is not re-measured is a guess
   with extra steps (Appendix A D8).
6. **Do not persist the twin's `confirmed` set as a substitute for the ledger.**
   [STUDIO.md §10](../STUDIO.md) is explicit that the twin credits only builds it
   watched, on purpose. The ledger is server-side and is the authority.

---

## 6. About "no need to reset after stage 4"

Two separate facts, and they are good news:

- **`B` homes everything itself.** [link.py](../../python/rig/link.py#L479) says so
  outright, and the comms audit's protocol table confirms `B` is a complete
  validated 14-phase pick/place/park. So **resuming a program does not require a
  reset or a re-home.** There is no accumulated position state to restore.
- **What a resume actually needs is agreement**, not motion: the cursor, the
  ledger, and the board must describe the same structure. That is a state
  question, and it is why the ledger is milestone one.

The one thing that genuinely cannot be resumed is a **`LOCKED`** session — an
abort means the claw may be holding a block somewhere unknown, and both
`BuildController` and the twin stop dead there by design. Compensation must never
be a route around that lock.

**"Stage 4" needs defining before any of this is built** — see Q3 below.

---

## 7. The questions — answer every one before writing code

The request said to ask a lot of questions before building this. It is right to.
These are the ones whose answers change the design rather than the wording.

### Scope

1. Is the removal a **human taking a block**, a **block falling**, or **both**?
   A fall changes two cells (a hole and a new occupied cell) and reads as `MOVED`
   or `BOARD DISAGREES`, not `REMOVED`.
2. Is this only for programs run through the Studio runner, or also for
   hand-driven single builds from the console?
3. **What is a "stage"?** A level? A tower? A named checkpoint in a program? A
   mode latch? The phrase "after stage 4" implies a unit the system does not
   currently have a name for, and every resume rule depends on which it is.
4. Does the plan ever *need* the removed block later — as support for something
   above it — or are removals always cosmetic in the models you actually build?

### Physical

5. When a block is removed from under a stack, does the stack stay standing on
   this rig, or does it collapse? The answer decides whether P2 is ever legal
   below the top of a column.
6. How reliable is a re-place onto a cell whose neighbours are already occupied?
   The claw needs clearance — the Studio's `clawMarginMm` is currently an
   **unmeasured guess** of 8 mm.
7. How often does the feeder actually deliver on demand? P2 and P3 both spend a
   block; a rejected build because the feeder was empty is a different failure
   and must not read as a repair failure.
8. Is the board reachable by a human mid-run at all — i.e. is this defending
   against an accident, or demonstrating a capability?

### Policy

9. Default policy per case: P1 for everything until told otherwise? Or P2
   automatic when legal?
10. Rate limits: one repair per cell per run (Appendix A D9), or per program?
11. What happens when a repair is itself rejected or aborted?
12. If the operator removes a block **deliberately**, how do they tell the system
    "that was me, do not put it back"? A machine that re-places a block a human
    just took is infuriating, and D9 exists for this reason.

### UX and honesty

13. Where does the verdict appear — the runner panel, the twin, a banner, or all
    three? Which one is authoritative when they disagree?
14. How is level-blindness communicated? It must be visible before an operator
    starts trusting the feature, not in a footnote afterwards.
15. Does the run report record removals and repairs? (It should — it is thesis
    evidence, and it is the honest account of what the machine did.)

### Safety

16. May compensation ever run without an operator watching? (Recommended answer:
    no, and the E-stop is not fitted — see [feature-ideas.md](../feature-ideas.md) §2.12.)
17. What is the behaviour on `BOARD DISAGREES` mid-program — pause, or stop the
    program entirely?
18. Does a supervision verdict ever LOCK the session, or only pause it? (These
    are different: a lock needs a human and a restart.)

---

## 8. Milestones

| # | Milestone | Depends on | Difficulty |
| --- | --- | --- | --- |
| **R0** | Appendix A M1–M3: ledger, observer, classifier | — | **4 / 5** (already designed) |
| **R1** | Publish the verdict in `StateModel`; runner event; **P1 only** — pause and name the cell | R0 | **3 / 5** |
| **R2** | Column-top legality test + `validate.ts` dependency reuse; **P2** in-line repair, opt-in | R1 | **4 / 5** |
| **R3** | **P3** deferred-to-tail repair with the support-dependency check | R2 | **4 / 5** |
| **R4** | Retrieval (`P <col> <row> <level>`), unlocking `MOVED` repair | R2, hardware | **5 / 5** |

**R1 is the demonstrable milestone**: lift a block off the board mid-program and
the console pauses and names the cell. It is also where the feature is most
defensible in a report — a closed loop between vision and motion, with the
machine declining to guess.

---

## 9. Difficulty

**Overall: 5 / 5 — the hardest of the three features, and the one that must be
built last.**

It is not hard because the code is hard. It is hard because it is the only one of
the three where the software **produces motion from an inference**, on a machine
with no E-stop, no retrieval verb, and a sensor that cannot see the top of a
stack. Every difficulty in it is a correctness-and-honesty difficulty, and the
right instinct throughout is Appendix A's:

> `BOARD DISAGREES` is not a failure of the classifier; it is the classifier
> declining to guess.

---

## 10. Not doing

- **Tracking blocks between frames.** Appendix A D1: twenty-nine identical
  wooden rectangles, a stateless per-frame detector, and occlusion in exactly
  the frames that matter.
- **Re-planning around interference.** The machine repairs or it stops. It does
  not decide to build something else.
- **Verifying inside a `B`.** Impossible, and the reframing in §1 is what makes
  that limitation survivable rather than fatal.
- **Compensating out of a `LOCKED` session.** A lock means a human must look.
