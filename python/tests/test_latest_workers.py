#!/usr/bin/env python3
"""Latest-only analysis/map workers and bounded snapshot writer."""

from pathlib import Path
import sys
import threading
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera.snapshot_worker import SnapshotWorker  # noqa: E402
from vision.analysis_worker import AnalysisWorker  # noqa: E402
from vision.latest_worker import LatestValueWorker  # noqa: E402


PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print(f"{'ok  ' if condition else 'FAIL'}  {name:58} {detail}")


entered = threading.Event()
release = threading.Event()


def analyze(frame):
    entered.set()
    release.wait(2.0)
    return [int(frame[0, 0, 0])]


analysis = AnalysisWorker(analyze, max_hz=1000)
analysis.start()
source_one = np.full((2, 2, 3), 1, np.uint8)
analysis.submit(source_one, 1, 4, context="frame-one")
check("analysis worker starts the active request", entered.wait(1.0))
analysis.submit(np.full((2, 2, 3), 2, np.uint8), 2, 4)
source_three = np.full((2, 2, 3), 3, np.uint8)
analysis.submit(source_three, 3, 4, context="frame-three")
release.set()
deadline = time.monotonic() + 2.0
result = analysis.snapshot()
while result.source_sequence != 3 and time.monotonic() < deadline:
    time.sleep(0.005)
    result = analysis.snapshot()
check("queued analysis is replaced by the newest sequence",
      result.source_sequence == 3 and result.detections == (3,),
      f"sequence {result.source_sequence}")
check("analysis result is accepted for its map generation",
      result.is_current(4))
check("analysis result retains its exact source image and context",
      result.source is source_three and result.context == "frame-three")
check("stale analysis is rejected after a map-generation change",
      not result.is_current(5))
consumed = analysis.consume()
check("a completed analysis result can be consumed once",
      consumed is not None and consumed.completed_count == result.completed_count)
check("the same completed result cannot be consumed twice",
      analysis.consume() is None)
check("a capture sequence cannot be analyzed twice",
      not analysis.submit(np.full((2, 2, 3), 3, np.uint8), 3, 4))
check("duplicate analysis request is counted",
      analysis.snapshot().duplicate_count == 1)
check("analysis reports replaced work", result.replaced_count >= 1,
      str(result.replaced_count))
check("analysis worker shuts down cleanly", analysis.stop())


# Supervision opts into a stronger one-item completion handoff: pending camera
# requests are still replaceable, but a result that has finished cannot be
# overwritten before it is consumed.
handoff = AnalysisWorker(lambda frame: [int(frame[0, 0, 0])], max_hz=1000,
                         consume_each=True)
handoff.start()
handoff.submit(np.full((2, 2, 3), 7, np.uint8), 7, 1)
deadline = time.monotonic() + 2.0
while handoff.snapshot().source_sequence != 7 and time.monotonic() < deadline:
    time.sleep(0.005)
handoff.submit(np.full((2, 2, 3), 8, np.uint8), 8, 1)
time.sleep(0.03)
check("an unconsumed completion cannot be overwritten",
      handoff.snapshot().source_sequence == 7)
first_handoff = handoff.consume()
check("the held completion is consumed with its evidence",
      first_handoff is not None and first_handoff.detections == (7,))
deadline = time.monotonic() + 2.0
while handoff.snapshot().source_sequence != 8 and time.monotonic() < deadline:
    time.sleep(0.005)
second_handoff = handoff.consume()
check("the pending latest request completes after consumption",
      second_handoff is not None and second_handoff.detections == (8,))
check("the handoff has no duplicate third consumption", handoff.consume() is None)
check("the one-item handoff worker shuts down cleanly", handoff.stop())

writer_entered = threading.Event()
writer_release = threading.Event()


def writer(value):
    writer_entered.set()
    writer_release.wait(2.0)
    return value * 2


snapshots = SnapshotWorker(writer)
check("first snapshot request is accepted", snapshots.submit(5))
check("snapshot writer begins its request", writer_entered.wait(1.0))
check("snapshot writer refuses overlapping requests", not snapshots.submit(6))
writer_release.set()
deadline = time.monotonic() + 2.0
written = snapshots.snapshot()
while written.completed_count < 1 and time.monotonic() < deadline:
    time.sleep(0.005)
    written = snapshots.snapshot()
check("snapshot result is reported", written.result == 10)
check("snapshot worker shuts down cleanly", snapshots.stop())

value_entered = threading.Event()
value_release = threading.Event()


def build(value):
    value_entered.set()
    value_release.wait(2.0)
    return value


values = LatestValueWorker(build)
values.submit(1, "old-active")
check("map worker starts the active generation", value_entered.wait(1.0))
values.submit(2, "old-pending")
values.submit(3, "newest")
value_release.set()
deadline = time.monotonic() + 2.0
latest = values.snapshot()
while latest.generation != 3 and time.monotonic() < deadline:
    time.sleep(0.005)
    latest = values.snapshot()
check("latest map generation replaces stale pending work",
      latest.generation == 3 and latest.value == "newest",
      f"generation {latest.generation}")
check("map worker records a replacement", latest.replaced_count >= 1)
check("map worker shuts down cleanly", values.stop())

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("failed: " + ", ".join(FAILED))
raise SystemExit(1 if FAILED else 0)
