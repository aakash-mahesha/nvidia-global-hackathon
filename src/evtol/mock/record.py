"""Record everything on the bus to a replayable file.

    python -m evtol.mock.record --out mock_bags/nominal.jsonl --duration 55

One JSON object per line:

    {"t": 12.482, "topic": "/rig/state", "payload": {...}}

`t` is seconds since recording began, NOT wall-clock — so a replay reproduces
the original spacing wherever and whenever it runs. The payload is the
message exactly as it arrived, already validated by the bus.

Files are `.jsonl`, deliberately not `.bag`: `.gitignore` excludes `*.bag`,
and these need to be committed so CI can replay them (docs/CONTRACTS.md §5
requires three recorded bags shipped with the mock).

Lines are flushed as they are written, so Ctrl-C at any point still leaves a
valid, replayable file rather than a truncated one.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from collections import Counter
from functools import partial
from pathlib import Path
from typing import TextIO

from evtol.bus import Bus
from evtol.messages import BusMessage
from evtol.topics import ALL_TOPICS

log = logging.getLogger(__name__)

DEFAULT_DURATION_S = 55.0  # one full mock cycle (52 s) plus margin


class Recorder:
    def __init__(self, handle: TextIO, clock=time.monotonic) -> None:
        self._handle = handle
        self._clock = clock
        self._started = clock()
        self.counts: Counter[str] = Counter()

    def on_message(self, topic: str, message: BusMessage) -> None:
        line = {
            "t": round(self._clock() - self._started, 4),
            "topic": topic,
            "payload": message.model_dump(by_alias=True, mode="json"),
        }
        self._handle.write(json.dumps(line) + "\n")
        # Flush per line: a recording interrupted halfway is still usable.
        self._handle.flush()
        self.counts[topic] += 1

    def attach(self, bus: Bus) -> None:
        for topic in ALL_TOPICS:
            # partial binds the topic — Bus hands the handler a decoded model
            # and nothing else, so the recorder would otherwise not know which
            # channel a message arrived on.
            bus.subscribe(topic, partial(self.on_message, topic))


def record(out: Path, duration_s: float) -> Counter:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        recorder = Recorder(handle)
        with Bus(client_id="rig-mock-recorder") as bus:
            recorder.attach(bus)
            log.info("recording %s for %.0fs — ctrl-C to stop early", out, duration_s)
            deadline = time.monotonic() + duration_s
            try:
                while time.monotonic() < deadline:
                    time.sleep(0.1)
            except KeyboardInterrupt:
                log.info("stopped early")
    return recorder.counts


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", type=Path, required=True, help="output .jsonl path")
    ap.add_argument("--duration", type=float, default=DEFAULT_DURATION_S,
                    help=f"seconds to record (default {DEFAULT_DURATION_S:.0f}, one full cycle)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    counts = record(args.out, args.duration)

    total = sum(counts.values())
    if total == 0:
        log.warning(
            "recorded NOTHING — is the publisher running? "
            "`python -m evtol.mock.publisher`"
        )
        return
    log.info("wrote %d messages to %s", total, args.out)
    for topic in ALL_TOPICS:
        log.info("  %-22s %5d", topic, counts[topic])


if __name__ == "__main__":
    main()
