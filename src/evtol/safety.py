"""The safety layer — what to do when a safety message is late, stale or absent.

`evtol.messages` stops a *malformed* safety message from being believed. This
module stops a *missing* one from being ignored, which is the more dangerous
failure: a subscriber that stops receiving looks exactly like a rig where
everything is fine.

Three rules, all fail-closed:

1. **Silence is denial** (docs/DECISIONS.md O-005). `/rig/interlock` carries a
   1 Hz heartbeat. A gap beyond INTERLOCK_HEARTBEAT_TIMEOUT_S means the board
   is gone, and a gone board must read as `permissive: false`. Without this,
   a crashed ESP32 reads as permission and the contract's "permissive must
   deny before it allows" is not actually true.

2. **A stale all-clear is not an all-clear.** `/monitor/verdict` runs at
   >=25 Hz. An `ok: true` from 2 seconds ago is a statement about a moment
   that has passed, and the hand it did not see has entered the workspace
   since.

3. **A veto latches** (docs/DECISIONS.md O-006). Recovery requires an explicit
   operator reset, not merely the next frame coming back clear. Auto-clearing
   turns a person reaching in into a stutter-stop-start, which is worse than
   not stopping at all.

Usage — the watchdog is the thing anything with a motor asks before moving:

    watchdog = SafetyWatchdog()
    watchdog.attach(bus)                # subscribes to both safety topics

    state = watchdog.evaluate()
    if not state.permitted:
        stop(state.reasons)             # always a non-empty list

Deliberately **pull-based**: `evaluate()` recomputes freshness from the clock
at the moment it is called, so correctness does not depend on a background
thread having run recently. A watchdog whose own timer can starve is not a
watchdog.

Ages are measured from **local arrival time**, not from the `ts` inside the
message. The question is "when did I last hear from it", and answering that
with the publisher's clock would make safety depend on an ESP32 being
NTP-synced.
"""

# safety.py asks "when did I last hear anything, and is it recent enough to still be true?"

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from evtol.messages import (
    INTERLOCK_HEARTBEAT_TIMEOUT_S,
    MONITOR_STALE_TIMEOUT_S,
    InterlockReason,
    InterlockState,
    MonitorVerdict,
)
from evtol.topics import TOPIC_MONITOR_VERDICT, TOPIC_RIG_INTERLOCK

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SafetyState:
    """The answer to "may the arm move right now?", with its justification."""

    permitted: bool
    reasons: list[InterlockReason] = field(default_factory=list)
    interlock_age_s: Optional[float] = None
    monitor_age_s: Optional[float] = None
    veto_latched: bool = False

    def __post_init__(self) -> None:
        if not self.permitted and not self.reasons:
            raise ValueError("a denial must always say why")
        if self.permitted and self.reasons:
            raise ValueError(f"permitted with reasons {self.reasons}")

    def describe(self) -> str:
        """One line for a log or a console banner."""
        if self.permitted:
            return "PERMITTED"
        return "DENIED: " + ", ".join(r.value for r in self.reasons)


class SafetyWatchdog:
    """Tracks the two safety topics and decides whether motion is allowed.

    interlock_timeout_s — gap on /rig/interlock that counts as the board being
                          gone. Default from the contract (1.5 s = one missed
                          heartbeat plus margin).
    monitor_timeout_s   — age beyond which an `ok` verdict is no longer
                          trusted.
    require_monitor     — if True (default) motion is denied until the monitor
                          has been heard from at all. Set False ONLY as a
                          deliberate, stated choice — e.g. bench work before
                          the Cosmos monitor exists. It disables rule 2
                          entirely, which is exactly the protection that stops
                          an arm moving while nothing is watching for hands.
    clock               — injectable for tests; monotonic, never wall-clock,
                          so an NTP step cannot make a stale message look fresh.
    """

    def __init__(
        self,
        interlock_timeout_s: float = INTERLOCK_HEARTBEAT_TIMEOUT_S,
        monitor_timeout_s: float = MONITOR_STALE_TIMEOUT_S,
        require_monitor: bool = True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.interlock_timeout_s = interlock_timeout_s
        self.monitor_timeout_s = monitor_timeout_s
        self.require_monitor = require_monitor
        self._clock = clock

        self._interlock: Optional[InterlockState] = None
        self._interlock_at: Optional[float] = None
        self._verdict: Optional[MonitorVerdict] = None
        self._verdict_at: Optional[float] = None
        self._veto_latched = False

        if not require_monitor:
            log.warning(
                "SafetyWatchdog: require_monitor=False — motion is permitted with "
                "NOTHING watching the workspace for hands. Bench use only."
            )

    # --- inputs -------------------------------------------------------------

    def on_interlock(self, message: InterlockState) -> None:
        self._interlock = message
        self._interlock_at = self._clock()

    def on_verdict(self, message: MonitorVerdict) -> None:
        self._verdict = message
        self._verdict_at = self._clock()
        if message.veto:
            if not self._veto_latched:
                log.warning("monitor VETO latched: %s", message.hazard)
            self._veto_latched = True

    def attach(self, bus) -> None:
        """Subscribe to both safety topics on an `evtol.bus.Bus`."""
        bus.subscribe(TOPIC_RIG_INTERLOCK, self.on_interlock)
        bus.subscribe(TOPIC_MONITOR_VERDICT, self.on_verdict)

    def reset_veto(self) -> None:
        """Clear a latched veto. An OPERATOR action — never call this on a timer.

        The whole point of latching (O-006) is that a human confirms the
        workspace is clear. Calling this automatically reintroduces exactly
        the stutter-start the latch exists to prevent.
        """
        if self._veto_latched:
            log.info("monitor veto cleared by operator")
        self._veto_latched = False

    # --- the decision -------------------------------------------------------

    def evaluate(self) -> SafetyState:
        """May the arm move right now? Recomputed from the clock on every call."""
        now = self._clock()
        reasons: list[InterlockReason] = []

        interlock_age = None if self._interlock_at is None else now - self._interlock_at
        monitor_age = None if self._verdict_at is None else now - self._verdict_at

        # Rule 1 — silence is denial.
        if self._interlock is None or interlock_age is None:
            reasons.append(InterlockReason.HEARTBEAT_LOST)
        elif interlock_age > self.interlock_timeout_s:
            reasons.append(InterlockReason.HEARTBEAT_LOST)
        elif not self._interlock.permissive:
            # The board said no and told us why. Pass its reasons through
            # rather than inventing our own.
            reasons.extend(self._interlock.reasons)

        # Rule 3 — a latched veto outlives the frame that caused it.
        if self._veto_latched:
            reasons.append(InterlockReason.MONITOR_VETO)

        # Rule 2 — a stale all-clear is not an all-clear.
        if self.require_monitor and not self._veto_latched:
            if self._verdict is None or monitor_age is None:
                reasons.append(InterlockReason.MONITOR_STALE)
            elif monitor_age > self.monitor_timeout_s:
                reasons.append(InterlockReason.MONITOR_STALE)
            elif not self._verdict.ok:
                reasons.append(InterlockReason.MONITOR_VETO)

        # De-duplicate while keeping order, so the console shows a stable list.
        seen: set[InterlockReason] = set()
        ordered = [r for r in reasons if not (r in seen or seen.add(r))]

        return SafetyState(
            permitted=not ordered,
            reasons=ordered,
            interlock_age_s=interlock_age,
            monitor_age_s=monitor_age,
            veto_latched=self._veto_latched,
        )

    @property
    def permitted(self) -> bool:
        """Shorthand for `evaluate().permitted`."""
        return self.evaluate().permitted
