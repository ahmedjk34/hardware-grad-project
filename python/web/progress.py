"""Where the console's build has got to, from the serial stream and nothing else.

`build_state` answers READY / RUNNING / LOCKED — enough to decide whether a
control may be pressed, and nothing more. It cannot tell an operator that the
claw has the block and is on its way, because the whole 40 seconds between
"RUNNING" and "READY" looks identical from outside.

The firmware now says. `buildStep()` prints one `@n STEP` line per phase, and
this class is the only place that turns that stream into the console's answer
to "what is it doing?".

THE RULES IT EXISTS TO ENFORCE
------------------------------
**Nothing here is inferred from a clock.** Every field moves because a serial
line arrived. If the socket goes quiet the phase simply stops advancing, which
is the truth; a progress bar that keeps filling on a timer is lying at exactly
the moment it costs the most.

**Placed means the terminal OK, and only that.** Phase 11 says the jaws opened;
phase 14 says the rig parked. Neither is the answer. `placed` is set from the
BuildJob outcome, which comes from the `@n OK` ack — see `rig/link.py` on why
`BLOCK IS PLACED, BUT PARKING FAILED` is an abort and not a success.

**A released block is a separate fact from a placed one.** The firmware emits
one `status=done` at phase 11, and `release_confirmed` carries it. The command
remains RUNNING through parking; the twin may stop showing the block in the
claw, but must not show it as placed.

**SAFE and HELD stay apart**, here as everywhere: `rejected` is a status a run
can continue from, `aborted`/`locked` is not.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace

from rig.link import ACCEPTED_KIND, SerialProgress
from web.events import now_ms


#: Where a command is. Ordered roughly as they occur, which is also the order
#: they are described in `docs/server-guide.md`.
#:
#:   idle        no command since the service started, or the last one settled
#:   accepted    the console accepted a POST /api/build and sent the B
#:   validating  the board acknowledged the command (RECV); it is checking the
#:               cell, the switches and the Z calibration. Nothing has moved.
#:   running     a phase is executing. Steps 1-11: the block is being fetched,
#:               carried and released.
#:   parking     the block is down and the rig is tidying up (phases 12-14).
#:               Still RUNNING as far as the machine is concerned.
#:   placed      terminal OK. The only status that means the block is there.
#:   rejected    terminal SAFE/ERR. Nothing moved; retrying is safe.
#:   aborted     terminal HELD. Position unknown, claw may be gripping.
#:   locked      the controller locked; a human has to look at the rig.
STATUSES = ("idle", "accepted", "validating", "running", "parking",
            "placed", "rejected", "aborted", "locked")

#: Statuses in which the machine is still working on the command.
ACTIVE_STATUSES = frozenset({"accepted", "validating", "running", "parking"})


@dataclass(frozen=True)
class BuildProgress:
    """The current phase of the current command, as the serial stream told it."""

    command_seq: int | None = None
    step: int | None = None
    total_steps: int | None = None
    phase: str | None = None
    phase_label: str | None = None
    phase_action: str | None = None
    phase_started_at: int | None = None
    #: The firmware's predicted duration for this phase, in milliseconds, or
    #: None when it did not say. Present on the Z moves only. It is a FLOOR:
    #: the real phase can only take longer, never less. Nothing may treat its
    #: expiry as the phase having finished — see `rig/link.py`.
    phase_eta_ms: int | None = None
    status: str = "idle"
    release_confirmed: bool = False
    #: The id of the last event that moved any field above. A client compares
    #: it against the progress it already has, so a state snapshot that
    #: overtook a build_step on the wire cannot roll the UI backwards.
    serial_event_id: int = 0

    @property
    def active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    def as_state_fields(self) -> dict:
        """The `build_*` half of `StateModel`, named as the model names it."""
        data = asdict(self)
        status = data.pop("status")
        release = data.pop("release_confirmed")
        event_id = data.pop("serial_event_id")
        return {f"build_{key}": value for key, value in data.items()} | {
            "build_phase_status": status,
            "build_release_confirmed": release,
            "serial_event_id": event_id,
        }


class BuildProgressTracker:
    """Fold the serial stream into one :class:`BuildProgress`.

    Every method returns the new progress when something changed and ``None``
    when nothing did, so the caller publishes exactly one event per real
    change and a repeated line costs no traffic.
    """

    def __init__(self):
        self._progress = BuildProgress()

    @property
    def progress(self) -> BuildProgress:
        return self._progress

    def _set(self, **changes) -> BuildProgress:
        self._progress = replace(self._progress, **changes)
        return self._progress

    # -- the console's own actions --------------------------------

    def command_accepted(self, event_id: int) -> BuildProgress:
        """A confirmed `POST /api/build` started a job. Nothing has moved yet.

        The phase fields are cleared here rather than left over from the last
        build: a stale `phase=move_to_target` sitting under a fresh `accepted`
        is exactly the kind of half-truth this class exists to prevent.
        """
        return self._set(
            command_seq=None, step=None, total_steps=None, phase=None,
            phase_label=None, phase_action=None, phase_started_at=now_ms(),
            phase_eta_ms=None, status="accepted", release_confirmed=False,
            serial_event_id=event_id,
        )

    # -- the serial stream ----------------------------------------

    def on_ack(self, ack, event_id: int) -> BuildProgress | None:
        """`RECV` only. Terminal kinds settle through :meth:`on_result`.

        The terminal ack is deliberately NOT read here. `Rig.build()` may
        answer from the prose when the ack is missing, and `BuildController`
        is what decides whether an outcome also locks the session — so the
        outcome has exactly one source, and it is not this line.
        """
        if ack.kind != ACCEPTED_KIND:
            return None
        if not self._progress.active:
            # A command nobody here started: a Serial Monitor on the same
            # cable, or a replayed banner. Report it rather than hide it, but
            # do not pretend the console asked for it.
            self._set(status="accepted", release_confirmed=False)
        return self._set(command_seq=ack.seq, status="validating",
                         phase_started_at=now_ms(), serial_event_id=event_id)

    def on_progress(self, progress: SerialProgress, event_id: int) -> BuildProgress:
        """One `@n STEP` line. The only thing that moves the phase."""
        if progress.done:
            # status=done arrives only at phase 11, the confirmed release. The
            # phase itself does not advance: the next `begin` does that.
            return self._set(release_confirmed=True, serial_event_id=event_id)
        return self._set(
            command_seq=progress.seq,
            step=progress.step,
            total_steps=progress.total,
            phase=progress.phase,
            phase_label=progress.label,
            phase_action=progress.action,
            phase_started_at=now_ms(),
            phase_eta_ms=progress.eta_ms,
            status="parking" if progress.parking else "running",
            serial_event_id=event_id,
        )

    # -- the outcome ----------------------------------------------

    def on_result(self, result: str | None, event_id: int, *,
                  locked: bool = False) -> BuildProgress:
        """The BuildJob settled. This is the only route to a terminal status.

        `locked` wins over the result word because it is the more expensive
        fact: a rejection that somehow locked the controller still needs a
        human, and a UI reading `rejected` would offer a CONTINUE button.
        """
        status = "locked" if locked else {
            "placed": "placed", "rejected": "rejected", "aborted": "aborted",
        }.get(str(result) if result is not None else "", "aborted")
        return self._set(status=status, phase_started_at=now_ms(),
                         serial_event_id=event_id)

    def reset(self) -> BuildProgress:
        """Back to idle. Used when a session is deliberately started over."""
        self._progress = BuildProgress()
        return self._progress
