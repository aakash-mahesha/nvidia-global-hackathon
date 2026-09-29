"""Replay a recorded bag onto the bus, at the original timing.

    python -m evtol.mock.replay mock_bags/nominal.jsonl
    python -m evtol.mock.replay mock_bags/abort.jsonl --retime
    python -m evtol.mock.replay mock_bags/nominal.jsonl --speed 10   # CI

Every message is re-validated through `evtol.messages.decode` before being
published. A bag that no longer matches the contract fails loudly here rather
than feeding a console something the real rig could never send — which makes
replay a schema regression test as much as a playback tool.

`--retime` shifts every timestamp forward by ONE constant offset, so the
messages look like they were produced now. A single offset is used precisely
because it preserves every internal relationship: `ts - frame_ts` (the
monitor's true end-to-end latency) and `t_now - t_start` (the turnaround
clock) come out unchanged. Without it, a console computing `now - ts` would
show latencies of hours.

Default is verbatim, no retiming: byte-identical playback is what makes CI
comparisons meaningful. Note the safety watchdog is unaffected either way —
it measures arrival time, not the timestamps inside messages.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any, Iterator

from evtol.bus import Bus
from evtol.messages import BusMessage, decode, now_ts
from evtol.topics import ALL_TOPICS

log = logging.getLogger(__name__)

# Field names carrying an absolute epoch timestamp. `--retime` shifts these
# and nothing else; anything ending in `_ts` is covered by the suffix rule.
TIME_FIELDS = frozenset({"ts", "t_start", "t_now"})


def _shift_times(value: Any, offset: float) -> Any:
    """Add `offset` to every timestamp field, recursively."""
    if isinstance(value, dict):
        return {
            k: (v + offset)
            if (k in TIME_FIELDS or k.endswith("_ts")) and isinstance(v, (int, float))
            else _shift_times(v, offset)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_shift_times(v, offset) for v in value]
    return value


def read_bag(path: Path) -> list[dict]:
    """Load and sanity-check a bag. Raises on anything malformed."""
    entries: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{lineno}: not valid JSON — {e}") from e
            for key in ("t", "topic", "payload"):
                if key not in entry:
                    raise ValueError(f"{path}:{lineno}: missing {key!r}")
            if entry["topic"] not in ALL_TOPICS:
                raise ValueError(
                    f"{path}:{lineno}: unknown topic {entry['topic']!r} — "
                    f"known: {sorted(ALL_TOPICS)}"
                )
            entries.append(entry)
    if not entries:
        raise ValueError(f"{path}: empty bag")
    # Recorded in order; replay depends on it.
    if any(b["t"] < a["t"] for a, b in zip(entries, entries[1:])):
        raise ValueError(f"{path}: timestamps are not monotonic")
    return entries


def iter_messages(entries: list[dict], retime: bool) -> Iterator[tuple[float, str, BusMessage]]:
    """-> (relative_time, topic, validated model).

    Decoding here rather than republishing raw bytes is deliberate: a bag
    that drifted from the contract must fail loudly, and going back out
    through `Bus.publish` means replay uses the same per-topic QoS as live
    traffic instead of quietly downgrading the interlock and permit to QoS 0.
    """
    offset = (now_ts() - entries[0]["payload"]["ts"]) if retime else 0.0
    for entry in entries:
        payload = _shift_times(entry["payload"], offset) if retime else entry["payload"]
        message = decode(entry["topic"], json.dumps(payload))
        yield entry["t"], entry["topic"], message


def replay(path: Path, speed: float = 1.0, retime: bool = False, loop: bool = False) -> None:
    entries = read_bag(path)
    span = entries[-1]["t"] - entries[0]["t"]
    log.info(
        "replaying %s — %d messages over %.1fs at %gx%s",
        path, len(entries), span, speed, " (retimed)" if retime else "",
    )

    with Bus(client_id="rig-mock-replay") as bus:
        while True:
            started = time.monotonic()
            for rel_t, topic, message in iter_messages(entries, retime):
                # Sleep until this message's slot, measured from the start of
                # the replay — so playback does not drift under load.
                wait = started + rel_t / speed - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                bus.publish(topic, message)
            if not loop:
                return
            log.info("loop")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("bag", type=Path, help="recorded .jsonl bag")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="playback multiplier; use >1 in CI to avoid real-time waits")
    ap.add_argument("--retime", action="store_true",
                    help="shift all timestamps forward so messages look current")
    ap.add_argument("--loop", action="store_true", help="repeat until interrupted")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        replay(args.bag, speed=args.speed, retime=args.retime, loop=args.loop)
    except KeyboardInterrupt:
        log.info("stopped")


if __name__ == "__main__":
    main()
