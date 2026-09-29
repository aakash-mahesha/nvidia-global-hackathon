"""The rig mock — all five topics, one timeline, three scenarios.

Deliberately NOT five independent publishers. Every message is derived from a
single clock and a single phase script, so the channels always tell the same
story: the permit is answered before the interlock changes, the interlock
changes before the arm moves, the clock starts when the permit is requested.
Independent timers would drift within a minute and produce a run that could
never happen on real hardware — and the console would be built against it.

Motion is scripted rather than random for the same reason. Watching the
stream you can tell APPROACH from INSERT from RETRACT, which is what makes a
console worth building; and it is what made four of this file's own bugs
visible (velocity out by 14x, torque saturating, force re-ramping at a phase
boundary, the latch reopening during MATED).

    python -m evtol.mock.publisher                      # nominal, 20 Hz
    python -m evtol.mock.publisher --scenario wind      # the refusal beat
    python -m evtol.mock.publisher --scenario abort     # the abort beat
    python -m evtol.mock.publisher --rate 2 -v          # slow enough to read
    python -m evtol.mock.publisher --once               # one of each, for CI

Scenarios live in `scenarios.py`. Wind is a slow sine plus gusts, perturbing
the joints slightly — standing in for the sprung target moving under the fan.
A1's measured displacement-vs-wind curve (EXECUTION-PLAN A1-2.5) replaces the
invented gain once it exists.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import logging
import math
import random
import time
from dataclasses import dataclass, field
from typing import Optional

from evtol.bus import Bus
from evtol.messages import (
    Ambient,
    CameraHealth,
    Hazard,
    InterlockReason,
    InterlockState,
    Joints,
    MonitorVerdict,
    PermitDecision,
    Phase,
    RigState,
    Sensors,
    TcpPose,
    TurnaroundClock,
    now_ts,
)
from evtol.mock.scenarios import MAX_WIND_MS, NOMINAL, SCENARIOS, Scenario
from evtol.topics import (
    TOPIC_CLOCK_TURNAROUND,
    TOPIC_MONITOR_VERDICT,
    TOPIC_PERMIT_DECISION,
    TOPIC_RIG_INTERLOCK,
    TOPIC_RIG_STATE,
)

log = logging.getLogger(__name__)

DEFAULT_RATE_HZ = 20.0          # /rig/state
MONITOR_RATE_RATIO = 1.25       # /monitor/verdict runs faster: 25 Hz vs 20 Hz
HEARTBEAT_HZ = 1.0              # /rig/interlock and /clock/turnaround
DEFAULT_SITE = "site1"
DEFAULT_RIG_ID = "rig-01"
TARGET_TURNAROUND_S = 120.0

MOCK_MODEL_ID = "nvidia/nemotron-3-super-120b-a12b"
MOCK_MONITOR_MODEL = "nvidia/Cosmos3-Edge"
MOCK_MONITOR_DEVICE = "orin-nano-super"
MOCK_FIRMWARE = "0.3.1"
MOCK_INTERLOCK_SOURCE = "esp32-01"

# Phases in which the arm is permitted to move. ABORT is deliberately absent:
# a vetoed run holds position, it does not retract itself.
MOVING_PHASES = frozenset(
    {Phase.APPROACH, Phase.FINE_ALIGN, Phase.INSERT, Phase.LATCH_VERIFY,
     Phase.MATED, Phase.RETRACT}
)


def _smoothstep(x: float) -> float:
    """Ease-in-ease-out on [0,1]. Real servos do not start at full speed."""
    x = min(max(x, 0.0), 1.0)
    return x * x * (3.0 - 2.0 * x)


@dataclass
class RigSimulator:
    """Produces all five topic payloads for any point in time.

    `*_at(t)` is a pure function of seconds since the run began (aside from
    seeded noise), which is what makes replay deterministic and CI repeatable.
    """

    scenario: Scenario = NOMINAL
    wind_ms: Optional[float] = None    # overrides the scenario's wind
    site: str = DEFAULT_SITE
    rig_id: str = DEFAULT_RIG_ID
    seed: int = 0

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        self._state_seq = itertools.count()
        self._verdict_seq = itertools.count()
        self._base_wind = (
            self.wind_ms if self.wind_ms is not None else self.scenario.wind_ms
        )

    # --- where we are -------------------------------------------------------

    def cycle_of(self, t: float) -> int:
        return int(t // self.scenario.cycle_s)

    def into_cycle(self, t: float) -> float:
        return t % self.scenario.cycle_s

    def run_id_at(self, t: float) -> Optional[str]:
        """None before the attempt starts — there is no run between attempts."""
        if self.into_cycle(t) < self.scenario.run_start_s:
            return None
        return f"run-mock-{self.cycle_of(t):03d}"

    def phase_at(self, t: float) -> Phase:
        return self._segment(t)[0]

    def _segment(
        self, t: float
    ) -> tuple[Phase, float, float, float, tuple[float, ...], tuple[float, ...]]:
        """-> (phase, progress 0..1, duration_s, segment_start_s, from, to).

        `duration_s` is returned because velocity is the rate of change of the
        interpolation, and the interpolation is spread across the whole
        segment: without dividing by the duration the reported velocity is out
        by a factor of however many seconds the segment lasts.

        `segment_start_s` is returned rather than looked up by phase, because
        a scenario may use the same phase twice (the wind run is IDLE both
        before and after the refusal).
        """
        script = self.scenario.script
        elapsed = self.into_cycle(t)
        previous = script[-1][2]
        start = 0.0
        for phase, duration, target in script:
            if elapsed < duration:
                return phase, elapsed / duration, duration, start, previous, target
            elapsed -= duration
            start += duration
            previous = target
        phase, duration, target = script[-1]
        return phase, 1.0, duration, start - duration, previous, target

    def _wind_at(self, t: float) -> float:
        """Slow sine plus gusts. Never negative."""
        swell = 0.8 * math.sin(t * 0.17)
        gust = 0.5 * self._rng.random()
        return max(0.0, self._base_wind + swell + gust)

    def _fan_setting(self) -> int:
        """The physical dial, which does not move while the anemometer wanders."""
        for step, threshold in enumerate((1.5, 4.0, 7.0, 10.0)):
            if self._base_wind < threshold:
                return step
        return 4

    def vetoed_at(self, t: float) -> bool:
        """Has the monitor vetoed by this point in the cycle?

        LATCHING: once it fires it stays true for the rest of the run. A hand
        leaving the frame must not restart the arm — auto-clearing turns a
        person reaching in into a stutter-stop-start (docs/DECISIONS.md O-006).
        """
        veto_at = self.scenario.veto_at_s
        return veto_at is not None and self.into_cycle(t) >= veto_at

    # --- /rig/state ---------------------------------------------------------

    def rig_state_at(self, t: float) -> RigState:
        phase, progress, duration, _start, origin, target = self._segment(t)
        ease = _smoothstep(progress)
        wind = self._wind_at(t)

        # Wind nudges the arm off its commanded path. The gain is invented;
        # replace it with A1's measured displacement-vs-wind curve (A1-2.5).
        jitter = wind * 0.0015

        position = [
            a + (b - a) * ease + self._rng.gauss(0.0, jitter)
            for a, b in zip(origin, target)
        ]
        # Velocity from the derivative of smoothstep, so it peaks mid-move and
        # goes to zero at both ends. The `/ duration` is load-bearing:
        # smoothstep runs over the segment, not over one second.
        speed = 6.0 * progress * (1.0 - progress) / duration
        velocity = [(b - a) * speed for a, b in zip(origin, target)]

        # Force ramps only while the connector is being pushed in, then HOLDS.
        # Ramping again during LATCH_VERIFY would say the connector unseated
        # and was inserted a second time.
        if phase is Phase.INSERT:
            force_n = round(9.5 * ease, 3)
        elif phase in (Phase.LATCH_VERIFY, Phase.MATED):
            force_n = 9.8
        else:
            force_n = 0.0

        return RigState(
            ts=now_ts(),
            seq=next(self._state_seq),
            site=self.site,
            rig_id=self.rig_id,
            run_id=self.run_id_at(t),
            phase=phase,
            joints=Joints(
                position_rad=[round(p, 5) for p in position],
                velocity_rad_s=[round(v, 5) for v in velocity],
                # Gain chosen so the fastest joint peaks around 0.5 rather than
                # pinning at 1.0 — a moving arm, not a straining one.
                torque_norm=[round(min(1.0, abs(v) * 6 + 0.05), 4) for v in velocity],
            ),
            tcp_pose=self._tcp_for(position),
            sensors=Sensors(
                estop_engaged=False,
                # The hand that triggers the abort also breaks the beam. The
                # two sensors see the same event, which is the point of having
                # both — vision alone is not a safety device.
                beam_broken=self.vetoed_at(t),
                fsr_n=force_n,
                # The latch closes partway through LATCH_VERIFY and STAYS
                # closed. Testing `progress > 0.5` alone would reopen it for
                # the first half of MATED, because progress resets at every
                # segment boundary.
                latch_closed=(
                    phase is Phase.MATED
                    or (phase is Phase.LATCH_VERIFY and progress > 0.5)
                ),
                continuity=phase is Phase.MATED,
                # docs/DECISIONS.md O-004: hardcoded True because the mock has
                # no deadman. On real hardware this MUST come from a physical
                # switch or the field means nothing.
                warden_present=True,
            ),
            cameras={
                "wrist": CameraHealth(ok=True, fps=29.8, last_frame_ts=now_ts() - 0.03),
                "overhead": CameraHealth(ok=True, fps=30.1, last_frame_ts=now_ts() - 0.02),
            },
            ambient=Ambient(
                wind_ms=round(wind, 2),
                fan_setting=self._fan_setting(),
                lux=480.0,
                temp_c=21.5,
            ),
        )

    @staticmethod
    def _tcp_for(position: list[float]) -> TcpPose:
        """A crude forward-kinematics stand-in.

        Not real FK — the mock's job is plausible motion, not an accurate
        SO-101 model. Replace when the servo tier lands.
        """
        pan, lift, elbow = position[0], position[1], position[2]
        reach = 0.16 + 0.10 * math.cos(lift) + 0.06 * math.cos(elbow)
        return TcpPose(
            x_m=round(reach * math.cos(pan), 4),
            y_m=round(reach * math.sin(pan), 4),
            z_m=round(0.26 + 0.10 * math.sin(lift), 4),
            rx_rad=round(position[3], 4),
            ry_rad=round(1.5708 + position[4] * 0.1, 4),
            rz_rad=round(position[5], 4),
        )

    # --- /rig/interlock -----------------------------------------------------

    def interlock_at(self, t: float) -> InterlockState:
        """Permissive only once the permit is granted, and never after a veto.

        Before the permit the board denies with PERMIT_NOT_GRANTED, which is
        what makes the reasoner a precondition for motion rather than advice
        the rig is free to ignore.
        """
        phase = self.phase_at(t)
        vetoed = self.vetoed_at(t)
        reasons: list[InterlockReason] = []
        if vetoed:
            reasons.append(InterlockReason.MONITOR_VETO)
        elif phase not in MOVING_PHASES:
            reasons.append(InterlockReason.PERMIT_NOT_GRANTED)

        return InterlockState(
            ts=now_ts(),
            site=self.site,
            rig_id=self.rig_id,
            run_id=self.run_id_at(t),
            permissive=not reasons,
            continuity=phase is Phase.MATED,
            isolation=True,
            estop_engaged=False,
            warden_present=True,
            reasons=reasons,
            source=MOCK_INTERLOCK_SOURCE,
            fw_version=MOCK_FIRMWARE,
        )

    def interlock_key(self, t: float) -> tuple:
        """What counts as a CHANGE worth publishing between heartbeats."""
        s = self.interlock_at(t)
        return (s.permissive, tuple(s.reasons), s.continuity, s.estop_engaged)

    # --- /monitor/verdict ---------------------------------------------------

    def verdict_at(self, t: float) -> MonitorVerdict:
        vetoed = self.vetoed_at(t)
        frame_age = 0.030 + self._rng.random() * 0.010
        ts = now_ts()
        return MonitorVerdict(
            ts=ts,
            seq=next(self._verdict_seq),
            rig_id=self.rig_id,
            run_id=self.run_id_at(t),
            ok=not vetoed,
            veto=vetoed,
            hazard=Hazard.HAND_IN_WORKSPACE if vetoed else None,
            confidence=round(0.94 + self._rng.random() * 0.05, 3),
            frame_ts=ts - frame_age,
            latency_ms=round(frame_age * 1000, 1),
            model_id=MOCK_MONITOR_MODEL,
            device=MOCK_MONITOR_DEVICE,
        )

    # --- /permit/decision ---------------------------------------------------

    def permit_at(self, t: float) -> PermitDecision:
        """Published once per run, at the moment the reasoner answers.

        The decision follows from the NUMBERS: the wind scenario refuses
        because its wind is above the procedure's cap, not because a flag was
        set. Every limit on an authorisation is one the deterministic tier is
        expected to enforce (docs/DECISIONS.md O-008) — an unenforced limit is
        decoration.
        """
        sc = self.scenario
        run_id = f"run-mock-{self.cycle_of(t):03d}"
        wind = round(self._wind_at(t), 2)
        digest = hashlib.sha256(f"{run_id}:{wind}".encode()).hexdigest()

        if sc.authorized:
            reasons = [
                f"Wind {wind} m/s is within the {MAX_WIND_MS} m/s cap in SP-04 3.2.",
                "BMS reports no active faults; CCS preconditions satisfied.",
                "No NOTAM affecting pad 1 for the current window.",
            ]
            limits = {
                "max_wind_ms": MAX_WIND_MS,
                "max_approach_speed_ms": 0.05,
                "max_insert_force_n": 12.0,
                "max_attempt_s": 120,
            }
        else:
            reasons = [
                f"Anemometer reads {wind} m/s. Site procedure SP-04 3.2 caps "
                f"automated mating at {MAX_WIND_MS} m/s.",
                "No provision in the procedure permits an exception at this wind speed.",
            ]
            limits = {}

        return PermitDecision(
            ts=now_ts(),
            request_id=f"req-mock-{self.cycle_of(t):04d}",
            run_id=run_id,
            authorized=sc.authorized,
            profile=sc.profile,
            limits=limits,
            reasons=reasons,
            refusal_code=sc.refusal_code,
            inputs_digest=f"sha256:{digest}",
            model_id=MOCK_MODEL_ID,
            latency_ms=round(2400 + self._rng.random() * 900, 1),
        )

    # --- /clock/turnaround --------------------------------------------------

    def clock_at(self, t: float) -> Optional[TurnaroundClock]:
        """None before the attempt starts.

        Once stopped the clock is a RECORD of the finished run, not live
        telemetry — so the phase freezes too. Letting `phase` keep tracking the
        rig while `elapsed_s` is frozen produces the contradiction "RETRACT
        started at 41 s, in a run that lasted 37 s".
        """
        sc = self.scenario
        into = self.into_cycle(t)
        if into < sc.run_start_s:
            return None

        ts = now_ts()
        stopped = into >= sc.stop_at_s
        at = sc.stop_at_s if stopped else into
        phase, _prog, _dur, seg_start, _o, _tg = self._segment(
            self.cycle_of(t) * sc.cycle_s + min(at, sc.cycle_s - 1e-6)
        )

        return TurnaroundClock(
            ts=ts,
            run_id=f"run-mock-{self.cycle_of(t):03d}",
            t_start=ts - (into - sc.run_start_s),
            t_now=ts,
            elapsed_s=round(at - sc.run_start_s, 2),
            phase=phase,
            phase_started_s=round(max(0.0, seg_start - sc.run_start_s), 2),
            target_s=TARGET_TURNAROUND_S,
            stopped=stopped,
            outcome=sc.outcome if stopped else None,
        )


def _interlock_summary(state: InterlockState) -> str:
    """Say what actually changed, not just the permissive flag.

    `continuity` flipping at MATED and again at RETRACT is a real change, but
    reporting only `permissive` made those read as a redundant "PERMISSIVE"
    repeat when it had been permissive for thirty seconds.
    """
    if not state.permissive:
        return "DENIED (" + ", ".join(r.value for r in state.reasons) + ")"
    flags = [
        name
        for name, on in (("continuity", state.continuity), ("isolation", state.isolation))
        if on
    ]
    return "PERMISSIVE" + (f" [{', '.join(flags)}]" if flags else "")


@dataclass
class _Scheduler:
    """Fires each topic at its own rate off one monotonic clock."""

    periods: dict[str, float]
    _next: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._next = {topic: 0.0 for topic in self.periods}

    def due(self, topic: str, t: float) -> bool:
        if t < self._next[topic]:
            return False
        # Advance from the scheduled time, not from now, so the rate does not
        # drift under load.
        self._next[topic] = max(t, self._next[topic] + self.periods[topic])
        return True


def run(
    scenario: Scenario = NOMINAL,
    rate_hz: float = DEFAULT_RATE_HZ,
    wind_ms: Optional[float] = None,
    once: bool = False,
    verbose: bool = False,
) -> None:
    sim = RigSimulator(scenario=scenario, wind_ms=wind_ms)
    scheduler = _Scheduler(
        {
            TOPIC_RIG_STATE: 1.0 / rate_hz,
            TOPIC_MONITOR_VERDICT: 1.0 / (rate_hz * MONITOR_RATE_RATIO),
            TOPIC_RIG_INTERLOCK: 1.0 / HEARTBEAT_HZ,
            TOPIC_CLOCK_TURNAROUND: 1.0 / HEARTBEAT_HZ,
        }
    )
    tick = min(0.01, 1.0 / (rate_hz * MONITOR_RATE_RATIO) / 2)
    started = time.monotonic()
    last_interlock_key: Optional[tuple] = None
    last_permit_cycle = -1
    last_phase: Optional[Phase] = None
    last_veto = False

    with Bus(client_id="rig-mock") as bus:
        log.info(
            "scenario '%s' — %s", scenario.name, scenario.description,
        )
        log.info(
            "cycle %.0fs; /rig/state %.1f Hz, /monitor/verdict %.1f Hz, "
            "interlock + clock %.1f Hz; wind %.1f m/s — ctrl-C to stop",
            scenario.cycle_s, rate_hz, rate_hz * MONITOR_RATE_RATIO,
            HEARTBEAT_HZ, sim._base_wind,
        )
        while True:
            t = time.monotonic() - started
            phase = sim.phase_at(t)

            if scheduler.due(TOPIC_RIG_STATE, t) or once:
                state = sim.rig_state_at(t)
                bus.publish(TOPIC_RIG_STATE, state)
                if verbose or phase is not last_phase:
                    log.info(
                        "t=%6.1fs  %-12s  wind %4.1f m/s  j0=%+.3f  force %4.1f N",
                        t, phase.value, state.ambient.wind_ms,
                        state.joints.position_rad[0], state.sensors.fsr_n,
                    )

            if scheduler.due(TOPIC_MONITOR_VERDICT, t) or once:
                verdict = sim.verdict_at(t)
                bus.publish(TOPIC_MONITOR_VERDICT, verdict)
                if verdict.veto and not last_veto:
                    log.info("t=%6.1fs  monitor   -> VETO (%s)", t, verdict.hazard.value)
                last_veto = verdict.veto

            # Permit BEFORE interlock. The interlock changing is a CONSEQUENCE
            # of the permit; publishing them the other way round shows a
            # console the effect before the cause.
            cycle = sim.cycle_of(t)
            if (sim.into_cycle(t) >= scenario.permit_at_s and cycle != last_permit_cycle) or once:
                decision = sim.permit_at(t)
                bus.publish(TOPIC_PERMIT_DECISION, decision)
                log.info(
                    "t=%6.1fs  permit    -> %s (%s)%s",
                    t,
                    "AUTHORIZED" if decision.authorized else "REFUSED",
                    decision.profile,
                    "" if decision.authorized else f" {decision.refusal_code.value}",
                )
                if not decision.authorized:
                    log.info("           %s", decision.reasons[0])
                last_permit_cycle = cycle

            # Interlock: heartbeat, PLUS immediately on any change. Silence
            # must be distinguishable from "everything is fine", and a change
            # must not wait up to a second to be seen.
            key = sim.interlock_key(t)
            if scheduler.due(TOPIC_RIG_INTERLOCK, t) or key != last_interlock_key or once:
                interlock = sim.interlock_at(t)
                bus.publish(TOPIC_RIG_INTERLOCK, interlock)
                if key != last_interlock_key and last_interlock_key is not None:
                    log.info("t=%6.1fs  interlock -> %s", t, _interlock_summary(interlock))
                last_interlock_key = key

            if scheduler.due(TOPIC_CLOCK_TURNAROUND, t) or once:
                clock = sim.clock_at(t)
                if clock is not None:
                    bus.publish(TOPIC_CLOCK_TURNAROUND, clock)

            last_phase = phase
            if once:
                return
            time.sleep(tick)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--scenario", choices=sorted(SCENARIOS), default="nominal",
                    help="which run to play (default: nominal)")
    ap.add_argument("--rate", type=float, default=DEFAULT_RATE_HZ,
                    help="/rig/state rate in Hz; the monitor scales with it, "
                         "interlock and clock stay at 1 Hz")
    ap.add_argument("--wind", type=float, default=None,
                    help="override the scenario's base wind, m/s")
    ap.add_argument("--once", action="store_true", help="publish one of each and exit")
    ap.add_argument("-v", "--verbose", action="store_true", help="log every /rig/state")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        run(
            scenario=SCENARIOS[args.scenario],
            rate_hz=args.rate,
            wind_ms=args.wind,
            once=args.once,
            verbose=args.verbose,
        )
    except KeyboardInterrupt:
        log.info("stopped")


if __name__ == "__main__":
    main()
