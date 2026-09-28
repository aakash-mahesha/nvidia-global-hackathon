"""Tests for the safety layer — what happens when safety messages go missing.

`test_messages.py` proves a malformed safety message is not believed. These
prove a *missing* one is not ignored, which is the more dangerous failure: a
subscriber that stops receiving looks exactly like a rig where everything is
fine.

Every test drives a fake clock, so "1.6 seconds passed" is an assertion rather
than a sleep. A test suite that waits for real timeouts stops being run.
"""

from __future__ import annotations

import pytest

from evtol.messages import (
    Hazard,
    InterlockReason,
    InterlockState,
    MonitorVerdict,
)
from evtol.safety import SafetyState, SafetyWatchdog


class FakeClock:
    """Monotonic seconds under test control."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def permitting_interlock(**overrides) -> InterlockState:
    kwargs = dict(
        site="site1",
        rig_id="rig-01",
        permissive=True,
        continuity=True,
        isolation=True,
        estop_engaged=False,
        warden_present=True,
        reasons=[],
        source="esp32-01",
        fw_version="0.3.1",
    )
    kwargs.update(overrides)
    return InterlockState(**kwargs)


def clear_verdict(**overrides) -> MonitorVerdict:
    kwargs = dict(
        seq=1,
        rig_id="rig-01",
        ok=True,
        veto=False,
        hazard=None,
        confidence=0.97,
        frame_ts=1.0,
        latency_ms=34.0,
        model_id="nvidia/Cosmos3-Edge",
        device="orin-nano-super",
    )
    kwargs.update(overrides)
    return MonitorVerdict(**kwargs)


def vetoing_verdict(**overrides) -> MonitorVerdict:
    return clear_verdict(
        ok=False, veto=True, hazard=Hazard.HAND_IN_WORKSPACE, **overrides
    )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def watchdog(clock: FakeClock) -> SafetyWatchdog:
    """A watchdog that has just heard good news from both topics."""
    wd = SafetyWatchdog(clock=clock)
    wd.on_interlock(permitting_interlock())
    wd.on_verdict(clear_verdict())
    return wd


# --- The baseline: the happy path must actually work -------------------------


def test_fresh_and_permitting_allows_motion(watchdog):
    assert watchdog.evaluate().permitted is True


def test_a_brand_new_watchdog_denies(clock):
    """Before anything is heard from, motion is denied — not allowed by default."""
    state = SafetyWatchdog(clock=clock).evaluate()
    assert state.permitted is False
    assert InterlockReason.HEARTBEAT_LOST in state.reasons


# --- Rule 1: silence is denial (O-005) ---------------------------------------


def test_interlock_silence_denies(watchdog, clock):
    """The crashed-ESP32 case. This is the whole reason the module exists."""
    clock.advance(1.6)  # past the 1.5 s heartbeat timeout
    state = watchdog.evaluate()
    assert state.permitted is False
    assert InterlockReason.HEARTBEAT_LOST in state.reasons


def test_interlock_just_inside_the_timeout_still_permits(watchdog, clock):
    """Isolates the interlock timeout: the monitor's shorter 0.5 s window would
    otherwise expire first and deny for a different reason."""
    clock.advance(1.4)
    watchdog.on_verdict(clear_verdict())  # keep the monitor fresh
    assert watchdog.evaluate().permitted is True


def test_heartbeat_refreshes_the_deadline(watchdog, clock):
    """A 1 Hz heartbeat keeps motion alive indefinitely."""
    for _ in range(10):
        clock.advance(1.0)
        watchdog.on_interlock(permitting_interlock())
        watchdog.on_verdict(clear_verdict())
        assert watchdog.evaluate().permitted is True


def test_board_denial_reasons_are_passed_through(watchdog):
    """We report what the board said, not a reason we invented."""
    watchdog.on_interlock(
        permitting_interlock(
            permissive=False,
            estop_engaged=True,
            reasons=[InterlockReason.ESTOP_ENGAGED, InterlockReason.WARDEN_ABSENT],
        )
    )
    state = watchdog.evaluate()
    assert state.permitted is False
    assert InterlockReason.ESTOP_ENGAGED in state.reasons
    assert InterlockReason.WARDEN_ABSENT in state.reasons


# --- Rule 2: a stale all-clear is not an all-clear ---------------------------


def test_stale_monitor_denies(watchdog, clock):
    """An `ok` from 0.6 s ago describes a workspace that has since changed."""
    clock.advance(0.6)  # past the 0.5 s monitor timeout, inside the interlock one
    state = watchdog.evaluate()
    assert state.permitted is False
    assert InterlockReason.MONITOR_STALE in state.reasons
    assert InterlockReason.HEARTBEAT_LOST not in state.reasons


def test_monitor_never_heard_from_denies(clock):
    wd = SafetyWatchdog(clock=clock)
    wd.on_interlock(permitting_interlock())
    state = wd.evaluate()
    assert state.permitted is False
    assert InterlockReason.MONITOR_STALE in state.reasons


def test_require_monitor_false_is_an_explicit_escape_hatch(clock):
    """Bench work before Cosmos exists. Must be opt-in, never the default."""
    wd = SafetyWatchdog(clock=clock, require_monitor=False)
    wd.on_interlock(permitting_interlock())
    assert wd.evaluate().permitted is True


def test_not_ok_verdict_denies(watchdog):
    watchdog.on_verdict(clear_verdict(ok=False, veto=False, hazard=None))
    state = watchdog.evaluate()
    assert state.permitted is False
    assert InterlockReason.MONITOR_VETO in state.reasons


# --- Rule 3: a veto latches (O-006) ------------------------------------------


def test_veto_denies(watchdog):
    watchdog.on_verdict(vetoing_verdict())
    state = watchdog.evaluate()
    assert state.permitted is False
    assert state.veto_latched is True
    assert InterlockReason.MONITOR_VETO in state.reasons


def test_veto_does_not_clear_when_the_hand_leaves(watchdog):
    """The hand leaving the frame must NOT restart the arm on its own.

    Auto-clearing turns someone reaching in into a stutter-stop-start, which
    is worse than not stopping at all.
    """
    watchdog.on_verdict(vetoing_verdict())
    for _ in range(50):  # two seconds of clear frames at 25 Hz
        watchdog.on_verdict(clear_verdict())
    assert watchdog.evaluate().permitted is False
    assert watchdog.evaluate().veto_latched is True


def test_operator_reset_clears_the_veto(watchdog):
    watchdog.on_verdict(vetoing_verdict())
    watchdog.reset_veto()
    watchdog.on_verdict(clear_verdict())
    assert watchdog.evaluate().permitted is True


def test_reset_does_not_override_an_unhappy_interlock(watchdog):
    """Clearing a veto must not paper over a separate denial."""
    watchdog.on_verdict(vetoing_verdict())
    watchdog.on_interlock(
        permitting_interlock(permissive=False, reasons=[InterlockReason.ESTOP_ENGAGED])
    )
    watchdog.reset_veto()
    state = watchdog.evaluate()
    assert state.permitted is False
    assert InterlockReason.ESTOP_ENGAGED in state.reasons


# --- Reporting ---------------------------------------------------------------


def test_reasons_are_deduplicated(watchdog, clock):
    """The console shows a stable list, not the same reason twice."""
    watchdog.on_verdict(vetoing_verdict())
    state = watchdog.evaluate()
    assert len(state.reasons) == len(set(state.reasons))


def test_denial_always_carries_a_reason(clock):
    """Enforced by SafetyState itself — a silent denial is unactionable."""
    with pytest.raises(ValueError, match="must always say why"):
        SafetyState(permitted=False, reasons=[])


def test_permitted_state_cannot_carry_reasons():
    with pytest.raises(ValueError, match="permitted with reasons"):
        SafetyState(permitted=True, reasons=[InterlockReason.ESTOP_ENGAGED])


def test_describe_is_readable(watchdog, clock):
    assert watchdog.evaluate().describe() == "PERMITTED"
    clock.advance(5.0)
    assert "DENIED" in watchdog.evaluate().describe()
    assert "HEARTBEAT_LOST" in watchdog.evaluate().describe()


def test_ages_are_reported(watchdog, clock):
    clock.advance(0.25)
    state = watchdog.evaluate()
    assert state.interlock_age_s == pytest.approx(0.25)
    assert state.monitor_age_s == pytest.approx(0.25)


# --- Multiple simultaneous failures ------------------------------------------


def test_everything_gone_reports_everything(watchdog, clock):
    clock.advance(10.0)
    state = watchdog.evaluate()
    assert state.permitted is False
    assert InterlockReason.HEARTBEAT_LOST in state.reasons
    assert InterlockReason.MONITOR_STALE in state.reasons
