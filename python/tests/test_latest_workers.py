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
analysis.submit(np.full((2, 2, 3), 1, np.uint8), 1, 4)
check("analysis worker starts the active request", entered.wait(1.0))
analysis.submit(np.full((2, 2, 3), 2, np.uint8), 2, 4)
analysis.submit(np.full((2, 2, 3), 3, np.uint8), 3, 4)
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
check("stale analysis is rejected after a map-generation change",
      not result.is_current(5))
check("a capture sequence cannot be analyzed twice",
      not analysis.submit(np.full((2, 2, 3), 3, np.uint8), 3, 4))
check("duplicate analysis request is counted",
      analysis.snapshot().duplicate_count == 1)
check("analysis reports replaced work", result.replaced_count >= 1,
      str(result.replaced_count))
check("analysis worker shuts down cleanly", analysis.stop())

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
