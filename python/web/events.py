"""The console's outbound event stream: ids, priority, replay, coalescing.

WHAT THIS IS FOR
----------------
`/api/events` used to carry one thing — a whole state snapshot, re-sent about
twenty times a second because the camera driver notified on every frame — and
the serial log rode along behind it as a full 200-line replay each time a
single new line arrived. Two consequences, both bad once the firmware started
reporting build phases in real time:

* a build phase could wait behind a backlog of camera geometry, so the UI
  learned that the claw had gripped a block some frames after it happened;
* a reconnect had to work out what was new by comparing TEXT, because nothing
  on the wire said which lines it had already seen.

So this module splits the stream in two, by what the fact IS rather than by
where it came from:

**Durable events** — `serial`, `build_step`, `build_result`. Each is delivered
exactly once, in order, and kept in a bounded replay buffer so a reconnecting
client can ask for everything after the last id it saw. These are facts about
the machine. Losing one loses information that nothing else will repeat.

**The state snapshot** — coalesced. Each subscriber holds exactly ONE pending
state, overwritten by every newer one, because a state snapshot is a complete
description of now: an older one has no value once a newer one exists. A slow
phone therefore costs itself stale geometry and nothing else.

Durable events are always sent before the pending state. That ordering is the
whole point: **camera geometry can never delay a build phase.**

EVERY EVENT CARRIES AN ID AND A TIMESTAMP. The id is monotonic and assigned
here, at publish, so ordering is decided in one place. Ids may have GAPS in
what a given client receives — coalesced states and heartbeats consume ids
without being replayable — so a client must deduplicate with `>` on the id it
has, never assume `previous + 1`.

THREADING. Everything here belongs to the asyncio loop. The serial reader is a
separate thread, so `web/app.py` forwards its callbacks with
`loop.call_soon_threadsafe`, which preserves their order. Nothing in this file
takes a lock, because nothing in this file is entered from two threads.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


#: Event types that are durable: delivered once each, kept for replay.
DURABLE_TYPES = frozenset({"serial", "feeder", "build_step", "build_result"})

#: The coalescing type. Only the newest pending one survives per client.
STATE_TYPE = "state"

#: How many durable events the server keeps for reconnecting clients. A build
#: is ~14 phases plus its prose, so this holds several builds' worth — long
#: enough that a phone that loses Wi-Fi crossing a room misses nothing.
REPLAY_CAP = 500

#: Per-client durable backlog. Larger than the replay buffer on purpose: this
#: is the queue for a client that is connected but slow, and dropping a serial
#: line from it would be dropping a fact. Overflow is recorded rather than
#: hidden — see `Subscriber.dropped`.
CLIENT_QUEUE_CAP = 2000


def now_ms() -> int:
    """Wall-clock milliseconds, the unit every event's `at` is in."""
    return int(time.time() * 1000)


@dataclass(frozen=True)
class Event:
    """One thing that happened, with the id and time it happened at."""

    event_id: int
    type: str
    at: int
    payload: dict = field(default_factory=dict)

    @property
    def durable(self) -> bool:
        return self.type in DURABLE_TYPES

    def to_json(self) -> dict[str, Any]:
        """The wire form: type/event_id/at at the top level, payload flattened.

        Flattened rather than nested because every consumer wants
        `message.step`, not `message.payload.step`, and a nested payload would
        make `type` and `event_id` look like metadata about a different object.
        """
        return {"type": self.type, "event_id": self.event_id, "at": self.at,
                **self.payload}


class Subscriber:
    """One connected WebSocket's view of the stream.

    Holds a durable queue and a single coalescing state slot. `next_batch()`
    drains the durable queue FIRST and only then offers the pending state, so
    a backlog of camera snapshots can never sit in front of a build phase.
    """

    def __init__(self, cap: int = CLIENT_QUEUE_CAP):
        self._cap = int(cap)
        self._durable: deque[Event] = deque()
        self._state: Event | None = None
        self._wake = asyncio.Event()
        #: Durable events discarded because this client could not keep up.
        #: Never silently zero: a client that sees this go up has lost facts.
        self.dropped = 0

    def offer(self, event: Event) -> None:
        """Queue one event. Durable events stack up; state overwrites."""
        if event.type == STATE_TYPE:
            self._state = event
        else:
            if len(self._durable) >= self._cap:
                self._durable.popleft()
                self.dropped += 1
            self._durable.append(event)
        self._wake.set()

    def offer_all(self, events) -> None:
        for event in events:
            self.offer(event)

    @property
    def pending(self) -> bool:
        return bool(self._durable) or self._state is not None

    def take(self) -> Event | None:
        """The next event to send: every durable one before the state."""
        if self._durable:
            return self._durable.popleft()
        state, self._state = self._state, None
        return state

    async def wait(self, timeout: float) -> bool:
        """Wait for something to send. False means the timeout won — heartbeat."""
        if self.pending:
            return True
        self._wake.clear()
        try:
            await asyncio.wait_for(self._wake.wait(), timeout)
        except (asyncio.TimeoutError, TimeoutError):
            return False
        return True


class EventHub:
    """Assigns event ids, fans out to subscribers, and keeps the replay buffer."""

    def __init__(self, replay_cap: int = REPLAY_CAP,
                 client_cap: int = CLIENT_QUEUE_CAP):
        self._next_id = 0
        self._replay: deque[Event] = deque(maxlen=int(replay_cap))
        self._subscribers: set[Subscriber] = set()
        self._client_cap = int(client_cap)

    # -- ids ------------------------------------------------------

    @property
    def last_event_id(self) -> int:
        """The id most recently assigned. 0 before anything has been published."""
        return self._next_id

    def _assign(self, type_: str, payload: dict) -> Event:
        self._next_id += 1
        return Event(event_id=self._next_id, type=type_, at=now_ms(),
                     payload=dict(payload))

    # -- publishing -----------------------------------------------

    def publish(self, type_: str, payload: dict | None = None) -> Event:
        """Assign an id, remember it if durable, and hand it to every client."""
        event = self._assign(type_, payload or {})
        if event.durable:
            self._replay.append(event)
        for subscriber in self._subscribers:
            subscriber.offer(event)
        return event

    def mint(self, type_: str, payload: dict | None = None) -> Event:
        """Assign an id WITHOUT fanning out or storing it.

        For the frames one socket owes only itself: its opening state snapshot
        and its heartbeats. They still get ids, from the same counter, so a
        client never sees an id go backwards — but sending them to everybody
        would be sending each client somebody else's connection.
        """
        return self._assign(type_, payload or {})

    def publish_state(self, state: dict) -> Event:
        """Publish a coalescing state snapshot.

        Not stored for replay: a snapshot describes NOW, so replaying an old
        one on reconnect would be replaying a lie. A new connection is sent the
        current state directly instead.
        """
        return self.publish(STATE_TYPE, {"state": state})

    # -- subscribing ----------------------------------------------

    def subscribe(self) -> Subscriber:
        subscriber = Subscriber(self._client_cap)
        self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: Subscriber) -> None:
        self._subscribers.discard(subscriber)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    # -- replay ---------------------------------------------------

    def replay_since(self, after_id: int | None) -> list[Event]:
        """Durable events newer than `after_id`, oldest first.

        `None` — a client with no history — gets the whole buffer, so a page
        opened mid-build sees the phases that have already happened rather
        than starting blank. An `after_id` older than the buffer gets the same
        thing: everything that is left, which is the honest answer.
        """
        if after_id is None:
            return list(self._replay)
        return [event for event in self._replay if event.event_id > int(after_id)]

    @property
    def oldest_replay_id(self) -> int | None:
        return self._replay[0].event_id if self._replay else None
