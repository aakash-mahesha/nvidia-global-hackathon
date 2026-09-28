"""Synthetic /rig/state — a fake arm on a real broker.

Deliberately NOT random numbers. The joints follow a scripted trajectory
through the real phase sequence with smooth acceleration, so that watching
the stream you can tell APPROACH from INSERT from RETRACT. That distinction
is the whole point: B2 cannot build a console worth looking at against noise,
and "the arm hesitated before latching" is not a thing you can see in random
data.

Wind is modelled as a slow sine plus gusts, and it perturbs the joints
slightly — standing in for the sprung target moving under the fan. A1's real
displacement-vs-wind measurements (EXECUTION-PLAN A1-2.5) replace the made-up
gain here once they exist.

    python -m evtol.mock.publisher                      # 20 Hz, default wind
    python -m evtol.mock.publisher --wind 9.5 --rate 20 # a windy run
    python -m evtol.mock.publisher --once               # one message, for CI
"""

from __future__ import annotations

import argparse
import itertools
import logging
import math
import random
import time
from dataclasses import dataclass

from evtol.bus import Bus
from evtol.messages import (
    Ambient,
    CameraHealth,
    Joints,
    Phase,
    RigState,
    Sensors,
    TcpPose,
    now_ts,
)
from evtol.topics import TOPIC_RIG_STATE

log = logging.getLogger(__name__)

DEFAULT_RATE_HZ = 20.0
DEFAULT_WIND_MS = 3.4
DEFAULT_SITE = "site1"
DEFAULT_RIG_ID = "rig-01"

# One mate attempt, as (phase, duration_s, joint target). The arm interpolates
# smoothly from the previous target to this one over the phase's duration.
# Joint order is JOINT_NAMES: shoulder_pan, shoulder_lift, elbow_flex,
# wrist_flex, wrist_roll, gripper.
SCRIPT: tuple[tuple[Phase, float, tuple[float, ...]], ...] = (
    (Phase.IDLE, 3.0, (0.00, -0.20, 0.30, 0.00, 0.00, 0.00)),
    (Phase.PERMIT_WAIT, 3.0, (0.00, -0.20, 0.30, 0.00, 0.00, 0.00)),
    (Phase.APPROACH, 14.0, (0.14, -0.88, 1.20, 0.05, -0.31, 0.03)),
    (Phase.FINE_ALIGN, 8.0, (0.15, -0.95, 1.28, 0.06, -0.30, 0.03)),
    (Phase.INSERT, 8.0, (0.15, -1.02, 1.36, 0.07, -0.30, 0.03)),
    (Phase.LATCH_VERIFY, 4.0, (0.15, -1.03, 1.37, 0.07, -0.30, 0.00)),
    (Phase.MATED, 4.0, (0.15, -1.03, 1.37, 0.07, -0.30, 0.00)),
    (Phase.RETRACT, 8.0, (0.00, -0.20, 0.30, 0.00, 0.00, 0.00)),
)

CYCLE_S = sum(duration for _, duration, _ in SCRIPT)


def _smoothstep(x: float) -> float:
    """Ease-in-ease-out on [0,1]. Real servos do not start at full speed."""
    x = min(max(x, 0.0), 1.0)
    return x * x * (3.0 - 2.0 * x)


@dataclass
class RigSimulator:
    """Generates a plausible RigState for any point in time.

    Stateless with respect to wall-clock: `state_at(t)` is a pure function of
    the seconds elapsed since the run began, which is what makes replay
    deterministic and CI repeatable.
    """

    base_wind_ms: float = DEFAULT_WIND_MS
    site: str = DEFAULT_SITE
    rig_id: str = DEFAULT_RIG_ID
    run_id: str = "run-mock-001"
    seed: int = 0

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        self._counter = itertools.count()

    # --- the scripted motion ------------------------------------------------

    def _phase_at(
        self, t: float
    ) -> tuple[Phase, float, float, tuple[float, ...], tuple[float, ...]]:
        """-> (phase, progress 0..1, duration_s, start joints, target joints).

        `duration_s` is returned because velocity is the rate of change of the
        interpolation, and the interpolation is spread across the whole phase:
        without dividing by the duration the reported velocity is out by a
        factor of however many seconds the phase lasts.
        """
        elapsed = t % CYCLE_S
        previous = SCRIPT[-1][2]
        for phase, duration, target in SCRIPT:
            if elapsed < duration:
                return phase, elapsed / duration, duration, previous, target
            elapsed -= duration
            previous = target
        phase, duration, target = SCRIPT[-1]
        return phase, 1.0, duration, previous, target

    def _wind_at(self, t: float) -> float:
        """Slow sine plus gusts. Never negative."""
        swell = 0.8 * math.sin(t * 0.17)
        gust = 0.5 * self._rng.random()
        return max(0.0, self.base_wind_ms + swell + gust)

    def state_at(self, t: float) -> RigState:
        phase, progress, duration, start, target = self._phase_at(t)
        ease = _smoothstep(progress)
        wind = self._wind_at(t)

        # Wind nudges the arm off its commanded path. The gain is invented;
        # replace it with A1's measured displacement-vs-wind curve (A1-2.5).
        jitter = wind * 0.0015

        position = [
            a + (b - a) * ease + self._rng.gauss(0.0, jitter)
            for a, b in zip(start, target)
        ]
        # Velocity from the derivative of smoothstep, so it peaks mid-move and
        # goes to zero at both ends — which is what a real servo trace looks like.
        # The `/ duration` is load-bearing: smoothstep runs over the phase, not
        # over one second, so without it the reported rad/s is out by a factor
        # of the phase length (14x during APPROACH).
        speed = 6.0 * progress * (1.0 - progress) / duration
        velocity = [(b - a) * speed for a, b in zip(start, target)]

        # Force ramps only while the connector is being pushed in, then HOLDS.
        # Ramping again during LATCH_VERIFY would say the connector unseated
        # and was inserted a second time — the latch closing is a catch
        # engaging, not another push.
        if phase is Phase.INSERT:
            force_n = round(9.5 * ease, 3)
        elif phase in (Phase.LATCH_VERIFY, Phase.MATED):
            force_n = 9.8
        else:
            force_n = 0.0

        mated = phase == Phase.MATED
        latched = phase in (Phase.LATCH_VERIFY, Phase.MATED) and progress > 0.5

        return RigState(
            ts=now_ts(),
            seq=next(self._counter),
            site=self.site,
            rig_id=self.rig_id,
            run_id=self.run_id if phase is not Phase.IDLE else None,
            phase=phase,
            joints=Joints(
                position_rad=[round(p, 5) for p in position],
                velocity_rad_s=[round(v, 5) for v in velocity],
                # Gain chosen so the fastest joint peaks around 0.5 rather than
                # pinning at 1.0 — a moving arm, not a straining one. 0.05 is
                # the baseline holding torque.
                torque_norm=[round(min(1.0, abs(v) * 6 + 0.05), 4) for v in velocity],
            ),
            tcp_pose=self._tcp_for(position),
            sensors=Sensors(
                estop_engaged=False,
                beam_broken=False,
                fsr_n=force_n,
                latch_closed=latched,
                continuity=mated,
                # See docs/DECISIONS.md O-004: hardcoded True here because the
                # mock has no deadman. On real hardware this MUST come from a
                # physical switch or the field means nothing.
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

    def _fan_setting(self) -> int:
        """Discrete fan step the anemometer reading corresponds to."""
        for step, threshold in enumerate((1.5, 4.0, 7.0, 10.0)):
            if self.base_wind_ms < threshold:
                return step
        return 4

    @staticmethod
    def _tcp_for(position: list[float]) -> TcpPose:
        """A crude forward-kinematics stand-in.

        Not real FK — the mock's job is plausible motion, not an accurate
        SO-101 model. Replace with real kinematics when the servo tier lands.
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


def run(
    rate_hz: float = DEFAULT_RATE_HZ,
    wind_ms: float = DEFAULT_WIND_MS,
    once: bool = False,
    verbose: bool = False,
) -> None:
    sim = RigSimulator(base_wind_ms=wind_ms)
    period = 1.0 / rate_hz
    started = time.monotonic()

    with Bus(client_id="rig-mock") as bus:
        log.info("publishing %s at %.0f Hz (wind %.1f m/s) — ctrl-C to stop",
                 TOPIC_RIG_STATE, rate_hz, wind_ms)
        last_phase = None
        while True:
            t = time.monotonic() - started
            state = sim.state_at(t)
            bus.publish(TOPIC_RIG_STATE, state)

            if verbose or state.phase is not last_phase:
                log.info(
                    "t=%6.1fs  %-12s  wind %4.1f m/s  j0=%+.3f  force %4.1f N",
                    t, state.phase.value, state.ambient.wind_ms,
                    state.joints.position_rad[0], state.sensors.fsr_n,
                )
                last_phase = state.phase

            if once:
                return
            # Sleep to the next slot rather than for a fixed period, so the
            # rate does not drift under load.
            time.sleep(max(0.0, (started + math.ceil(t / period) * period + period) - time.monotonic()))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rate", type=float, default=DEFAULT_RATE_HZ, help="publish rate, Hz")
    ap.add_argument("--wind", type=float, default=DEFAULT_WIND_MS, help="base wind, m/s")
    ap.add_argument("--once", action="store_true", help="publish one message and exit")
    ap.add_argument("-v", "--verbose", action="store_true", help="log every message")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        run(rate_hz=args.rate, wind_ms=args.wind, once=args.once, verbose=args.verbose)
    except KeyboardInterrupt:
        log.info("stopped")


if __name__ == "__main__":
    main()
