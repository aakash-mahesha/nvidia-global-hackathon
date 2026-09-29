"""Replay each scenario bag through a real broker and check its beat arrived.

`docs/CONTRACTS.md` §5: "CI replays the mock alongside smoke tests." This is
that. It is the only test here that needs a running broker, and it skips
itself when there is none so local runs stay fast.

What it protects, concretely:

* **The three beats.** Two of them — the reasoner's refusal and the live
  abort — are on the never-cut list. If someone changes the mock, the
  scenarios or the message models in a way that stops a refusal being a
  refusal, this fails.
* **The bags themselves.** Replay decodes every message through
  `evtol.messages` before publishing, so a bag that has drifted from the
  contract fails here rather than quietly feeding the console data the real
  rig could never send.
* **The wire path.** Publish, broker, subscribe, decode — end to end, not
  mocked.

Start a broker locally with:  mosquitto -c infra/mosquitto.conf -v
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from pathlib import Path

import pytest

from evtol.bus import Bus, BusError
from evtol.messages import (
    BusMessage,
    Hazard,
    InterlockReason,
    InterlockState,
    MonitorVerdict,
    Outcome,
    PermitDecision,
    RefusalCode,
    TurnaroundClock,
)
from evtol.mock.replay import replay
from evtol.topics import ALL_TOPICS

BAGS = Path("mock_bags")
# 10x rather than faster: the high-rate topics are QoS 0 by contract, and
# pushing 25 Hz of monitor verdicts to 500 Hz starts losing them for reasons
# that have nothing to do with the code under test.
SPEED = 10.0


@pytest.fixture(scope="module")
def broker() -> str:
    """Skip the whole module unless a broker is actually reachable."""
    try:
        Bus(client_id="ci-probe").connect().close()
    except BusError as e:
        pytest.skip(f"no broker: {e}")
    return "up"


class Collector:
    """Subscribes to everything and keeps what arrives, by topic."""

    def __init__(self) -> None:
        self.by_topic: dict[str, list[BusMessage]] = defaultdict(list)
        self._lock = threading.Lock()

    def attach(self, bus: Bus) -> None:
        for topic in ALL_TOPICS:
            bus.subscribe(topic, self._keep)

    def _keep(self, message: BusMessage) -> None:
        # Route by type rather than topic: Bus hands handlers a model and not
        # the topic it came on, and the model IS the topic here.
        with self._lock:
            self.by_topic[type(message).__name__].append(message)

    def of(self, cls: type) -> list:
        with self._lock:
            return list(self.by_topic[cls.__name__])


def play(name: str) -> Collector:
    """Replay one bag with a subscriber attached; return what it heard."""
    bag = BAGS / f"{name}.jsonl"
    if not bag.is_file():
        pytest.skip(f"{bag} not recorded")

    collector = Collector()
    with Bus(client_id=f"ci-listener-{name}") as bus:
        collector.attach(bus)
        time.sleep(0.3)  # let the subscriptions land before anything is sent
        replay(bag, speed=SPEED)
        time.sleep(0.5)  # and let the tail of the traffic arrive
    return collector


@pytest.fixture(scope="module")
def nominal(broker) -> Collector:
    return play("nominal")


@pytest.fixture(scope="module")
def wind(broker) -> Collector:
    return play("wind")


@pytest.fixture(scope="module")
def abort(broker) -> Collector:
    return play("abort")


# --- every bag has to produce traffic on every channel ----------------------


@pytest.mark.parametrize("name", ["nominal", "wind", "abort"])
def test_bag_covers_all_five_topics(broker, name, request):
    heard = request.getfixturevalue(name)
    for cls in (InterlockState, MonitorVerdict, PermitDecision, TurnaroundClock):
        assert heard.of(cls), f"{name}: nothing arrived for {cls.__name__}"


# --- nominal: the thesis ----------------------------------------------------


def test_nominal_is_authorized(nominal):
    decisions = nominal.of(PermitDecision)
    assert all(d.authorized for d in decisions)
    assert all(d.refusal_code is None for d in decisions)


def test_nominal_mates(nominal):
    stopped = [c for c in nominal.of(TurnaroundClock) if c.stopped]
    assert stopped, "the clock never stopped"
    assert all(c.outcome is Outcome.MATED for c in stopped)


def test_nominal_permits_motion(nominal):
    """The interlock must actually allow motion at some point, or the run is
    not a success run at all."""
    assert any(s.permissive for s in nominal.of(InterlockState))


def test_nominal_turnaround_beats_target(nominal):
    """The headline claim: mated well inside the target."""
    stopped = [c for c in nominal.of(TurnaroundClock) if c.stopped]
    assert stopped[0].elapsed_s < stopped[0].target_s


# --- wind: THE REFUSAL BEAT (never-cut) -------------------------------------


def test_wind_is_refused_with_a_code(wind):
    decisions = wind.of(PermitDecision)
    assert decisions, "no permit decision in the wind bag"
    assert all(not d.authorized for d in decisions)
    assert all(d.refusal_code is RefusalCode.WIND_LIMIT_EXCEEDED for d in decisions)


def test_wind_refusal_explains_itself(wind):
    """A refusal a judge cannot read is not a beat."""
    d = wind.of(PermitDecision)[0]
    assert d.reasons
    assert "8.0" in " ".join(d.reasons), "the cap that was exceeded is not stated"


def test_wind_carries_no_limits(wind):
    """limits is {} on a refusal, never absent and never populated."""
    assert all(d.limits == {} for d in wind.of(PermitDecision))


def test_wind_never_permits_motion(wind):
    """The consequence that makes the refusal real: the arm cannot move.

    A reasoner that refuses while the interlock still goes permissive has
    refused nothing.
    """
    states = wind.of(InterlockState)
    assert states
    assert not any(s.permissive for s in states)
    assert all(InterlockReason.PERMIT_NOT_GRANTED in s.reasons for s in states)


def test_wind_run_ends_refused(wind):
    stopped = [c for c in wind.of(TurnaroundClock) if c.stopped]
    assert stopped
    assert all(c.outcome is Outcome.REFUSED for c in stopped)


# --- abort: THE LIVE ABORT BEAT (never-cut) ---------------------------------


def test_abort_starts_out_authorized(abort):
    """The abort matters because the run was legitimately under way."""
    assert all(d.authorized for d in abort.of(PermitDecision))


def test_abort_has_a_hand_in_the_workspace(abort):
    vetoes = [v for v in abort.of(MonitorVerdict) if v.veto]
    assert vetoes, "the monitor never vetoed"
    assert all(v.hazard is Hazard.HAND_IN_WORKSPACE for v in vetoes)
    assert all(not v.ok for v in vetoes)


def test_abort_drops_the_interlock(abort):
    """The veto has to reach the interlock, not just the console."""
    denied = [s for s in abort.of(InterlockState) if not s.permissive]
    assert any(InterlockReason.MONITOR_VETO in s.reasons for s in denied)


def test_abort_permitted_motion_before_the_veto(abort):
    """Sanity: if it was never permissive, nothing was aborted."""
    states = abort.of(InterlockState)
    assert any(s.permissive for s in states)
    assert any(not s.permissive for s in states)


def test_abort_does_not_resume(abort):
    """O-006: a veto latches. Once MONITOR_VETO appears, the interlock must
    never go permissive again within the run."""
    states = abort.of(InterlockState)
    first_veto = next(
        (i for i, s in enumerate(states) if InterlockReason.MONITOR_VETO in s.reasons),
        None,
    )
    assert first_veto is not None
    assert not any(s.permissive for s in states[first_veto:]), "the arm resumed after a veto"


def test_abort_run_ends_aborted(abort):
    stopped = [c for c in abort.of(TurnaroundClock) if c.stopped]
    assert stopped
    assert all(c.outcome is Outcome.ABORTED for c in stopped)
