"""The three runs the mock can play.

`docs/CONTRACTS.md` §5 requires three recorded bags, and they are not an
arbitrary three — each is a distinct ENDING, and two of them are beats on the
never-cut list:

  nominal — the permit is granted, the arm mates. The thesis: turnaround
            under two minutes.
  wind    — wind is over the procedure's cap, the reasoner REFUSES, and the
            arm never moves at all because the interlock is never permissive.
            This is the refusal beat.
  abort   — a normal run until a hand enters the workspace mid-approach. The
            monitor vetoes, the interlock drops, the arm freezes where it is
            and does NOT resume when the hand leaves. This is the abort beat.

Those are also the three things the console has to render: a success, a
refusal BEFORE anything moves, and a stop DURING movement. Anything else is a
variation on one of them.

One engine plays all three. A scenario is data — a phase script, a wind
level, what the reasoner decides, and optionally when the monitor vetoes —
so the runs cannot drift apart the way three separate mock programs would.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from evtol.messages import Outcome, Phase, RefusalCode

# Joint poses, in JOINT_NAMES order: shoulder_pan, shoulder_lift, elbow_flex,
# wrist_flex, wrist_roll, gripper.
IDLE_POSE = (0.00, -0.20, 0.30, 0.00, 0.00, 0.00)
APPROACH_POSE = (0.14, -0.88, 1.20, 0.05, -0.31, 0.03)
ALIGNED_POSE = (0.15, -0.95, 1.28, 0.06, -0.30, 0.03)
INSERTED_POSE = (0.15, -1.02, 1.36, 0.07, -0.30, 0.03)
LATCHED_POSE = (0.15, -1.03, 1.37, 0.07, -0.30, 0.00)

# Where the arm gets to when the approach is interrupted halfway. smoothstep
# at progress 0.5 is exactly 0.5, so this is the pose at the veto — the ABORT
# segment then holds it, which is what "frozen mid-move" has to look like.
INTERRUPTED_POSE = tuple(
    a + (b - a) * 0.5 for a, b in zip(IDLE_POSE, APPROACH_POSE)
)

# (phase, duration_s, joint target at the END of the phase)
Segment = tuple[Phase, float, tuple[float, ...]]

NOMINAL_SCRIPT: tuple[Segment, ...] = (
    (Phase.IDLE, 3.0, IDLE_POSE),
    (Phase.PERMIT_WAIT, 3.0, IDLE_POSE),
    (Phase.APPROACH, 14.0, APPROACH_POSE),
    (Phase.FINE_ALIGN, 8.0, ALIGNED_POSE),
    (Phase.INSERT, 8.0, INSERTED_POSE),
    (Phase.LATCH_VERIFY, 4.0, LATCHED_POSE),
    (Phase.MATED, 4.0, LATCHED_POSE),
    (Phase.RETRACT, 8.0, IDLE_POSE),
)

# Refused: the arm never leaves IDLE. The trailing hold exists so the console
# has time to show the refusal before the next attempt begins.
WIND_SCRIPT: tuple[Segment, ...] = (
    (Phase.IDLE, 3.0, IDLE_POSE),
    (Phase.PERMIT_WAIT, 3.0, IDLE_POSE),
    (Phase.IDLE, 8.0, IDLE_POSE),
)

# Interrupted: the approach is cut short at the veto and the arm holds
# position. It does not retract, and it does not resume — recovery needs an
# operator reset (docs/DECISIONS.md O-006).
ABORT_SCRIPT: tuple[Segment, ...] = (
    (Phase.IDLE, 3.0, IDLE_POSE),
    (Phase.PERMIT_WAIT, 3.0, IDLE_POSE),
    (Phase.APPROACH, 7.0, INTERRUPTED_POSE),
    (Phase.ABORT, 8.0, INTERRUPTED_POSE),
)


@dataclass(frozen=True)
class Scenario:
    """One run, as data. The simulator reads this and nothing else."""

    name: str
    script: tuple[Segment, ...]
    wind_ms: float
    authorized: bool
    profile: str
    outcome: Outcome
    refusal_code: Optional[RefusalCode] = None
    # Seconds into the cycle at which the monitor spots a hand. None means it
    # stays clear for the whole run.
    veto_at_s: Optional[float] = None
    description: str = ""

    @property
    def cycle_s(self) -> float:
        return sum(duration for _, duration, _ in self.script)

    def segment_start(self, index: int) -> float:
        return sum(duration for _, duration, _ in self.script[:index])

    def first_start_of(self, phase: Phase) -> Optional[float]:
        for i, (p, _, _) in enumerate(self.script):
            if p is phase:
                return self.segment_start(i)
        return None

    @property
    def run_start_s(self) -> float:
        """The clock starts when the permit is REQUESTED, not at first motion.

        On a refusal the permit wait IS the whole run, so measuring from first
        motion would report a turnaround of zero for a run that took seconds
        of reasoning — and the headline number is the entire pitch.
        """
        start = self.first_start_of(Phase.PERMIT_WAIT)
        return 0.0 if start is None else start

    @property
    def permit_at_s(self) -> float:
        """When the reasoner answers: the end of PERMIT_WAIT."""
        for i, (phase, duration, _) in enumerate(self.script):
            if phase is Phase.PERMIT_WAIT:
                return self.segment_start(i) + duration
        return 0.0

    @property
    def stop_at_s(self) -> float:
        """When the turnaround clock stops, and why it stopped."""
        if self.veto_at_s is not None:
            return self.veto_at_s
        if not self.authorized:
            return self.permit_at_s
        mated = self.first_start_of(Phase.MATED)
        return self.cycle_s if mated is None else mated


NOMINAL = Scenario(
    name="nominal",
    script=NOMINAL_SCRIPT,
    wind_ms=3.4,
    authorized=True,
    profile="NOMINAL",
    outcome=Outcome.MATED,
    description="permit granted, arm mates, clock stops under target",
)

WIND = Scenario(
    name="wind",
    script=WIND_SCRIPT,
    wind_ms=11.4,
    authorized=False,
    profile="HIGH_WIND",
    outcome=Outcome.REFUSED,
    refusal_code=RefusalCode.WIND_LIMIT_EXCEEDED,
    description="wind over the procedure cap, reasoner refuses, arm never moves",
)

ABORT = Scenario(
    name="abort",
    script=ABORT_SCRIPT,
    wind_ms=4.2,
    authorized=True,
    profile="NOMINAL",
    outcome=Outcome.ABORTED,
    veto_at_s=13.0,  # the instant the ABORT segment begins
    description="hand in the workspace mid-approach, monitor vetoes, arm freezes",
)

SCENARIOS: dict[str, Scenario] = {s.name: s for s in (NOMINAL, WIND, ABORT)}

# The wind cap the reasoner enforces, from the site procedure. WIND sits above
# it and the other two below, so the refusal is a consequence of the numbers
# rather than a flag someone flipped.
MAX_WIND_MS = 8.0
