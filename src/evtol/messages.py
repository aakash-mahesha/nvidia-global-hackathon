"""Typed payloads for the five event-bus topics — the single definition.

`docs/BUS-PAYLOADS.md` describes these shapes for humans; this module is what
the code actually enforces. The rig, the rig mock, the console, the Cosmos
monitor and the permit reasoner all import from here, so a field can only be
spelled one way and a typo fails at the boundary instead of silently
producing an empty dashboard three days later.

    from evtol.messages import RigState, MODEL_FOR_TOPIC, decode
    state = decode(TOPIC_RIG_STATE, raw_bytes)   # validated or raises

Status: PROPOSED until the payload contract is ratified (docs/DECISIONS.md
O-015). Field names follow docs/BUS-PAYLOADS.md exactly.

Two conventions worth knowing before editing:

* **Units live in the field name** — `wind_ms`, `position_rad`, `force_n`,
  `latency_ms`. Never a bare `wind` or `angle`. On this project a
  degrees/radians mix-up means driving a connector into a socket at the wrong
  angle, so the naming is load-bearing, not cosmetic.
* **`extra="forbid"`** — an unrecognised field is an error, not a shrug. This
  deliberately trades forward-compatibility for catching mistakes: adding a
  field (a MINOR schema bump) requires subscribers to be redeployed. With
  trunk-based daily merges that is cheap, and it means a mistyped safety
  field can never be silently ignored.
* **Safety-bearing booleans are `strict=True`.** Pydantic would otherwise
  helpfully coerce the string "yes" into `True` — which means a permit
  reasoner answering sloppily gets its permit GRANTED, and a publisher
  sending `"permissive": "true"` gets motion ALLOWED. Both are silent
  fail-opens. JSON has real booleans; a publisher on a safety bus that sends
  anything else is broken and must be rejected, not guessed at. Found by
  `tests/test_permit_failclosed.py`.
"""
# messages.py asks "is this message well-formed?" 

from __future__ import annotations

import json
import time
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from evtol.topics import (
    TOPIC_CLOCK_TURNAROUND,
    TOPIC_MONITOR_VERDICT,
    TOPIC_PERMIT_DECISION,
    TOPIC_RIG_INTERLOCK,
    TOPIC_RIG_STATE,
)

SCHEMA_VERSION = "1.0"

# Joint order — must be IDENTICAL here, in the recorded LeRobot v3 dataset
# (CONTRACTS.md §1) and in the policy's action vector (§2). Three places, one
# order; if they ever disagree the arm moves the wrong joint.
# LeRobot SO-101 convention. See docs/DECISIONS.md O-001.
JOINT_NAMES: tuple[str, ...] = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
)

# Camera names are contractual (CONTRACTS.md §1) and must match the
# LeIsaac/Isaac Sim scene as well as the tape-marked physical positions.
CAMERA_NAMES: tuple[str, ...] = ("wrist", "overhead")

# A gap longer than this on /rig/interlock must be read by EVERY subscriber as
# permissive=False. Without it a crashed ESP32 reads as permission, and the
# contract's "permissive must deny before it allows" is not actually true.
# See docs/DECISIONS.md O-005. Enforced by evtol.safety.SafetyWatchdog.
INTERLOCK_HEARTBEAT_TIMEOUT_S = 1.5

# The monitor runs at >=25 Hz, so this is ~12 missed frames. A STALE "all
# clear" is the dangerous direction: it is a verdict about a moment that has
# already passed, and the hand it did not see entered the workspace since.
MONITOR_STALE_TIMEOUT_S = 0.5


# --- Enums (UPPER_SNAKE strings, never ints — a log line should be readable) -


class Phase(str, Enum):
    """Where a mate attempt is. Shared by /rig/state and /clock/turnaround."""

    IDLE = "IDLE"
    PERMIT_WAIT = "PERMIT_WAIT"
    APPROACH = "APPROACH"
    FINE_ALIGN = "FINE_ALIGN"
    INSERT = "INSERT"
    LATCH_VERIFY = "LATCH_VERIFY"
    MATED = "MATED"
    RETRACT = "RETRACT"
    ABORT = "ABORT"
    FAULT = "FAULT"


class Hazard(str, Enum):
    """What the Cosmos monitor saw. HAND_IN_WORKSPACE is the abort beat."""

    HAND_IN_WORKSPACE = "HAND_IN_WORKSPACE"
    PERSON_IN_ZONE = "PERSON_IN_ZONE"
    OBSTRUCTION = "OBSTRUCTION"
    CABLE_SNAG = "CABLE_SNAG"
    INLET_OCCLUDED = "INLET_OCCLUDED"
    CAMERA_DEGRADED = "CAMERA_DEGRADED"


class InterlockReason(str, Enum):
    """Every reason `permissive` can be False. A denial must always say why."""

    ESTOP_ENGAGED = "ESTOP_ENGAGED"
    BEAM_BROKEN = "BEAM_BROKEN"
    WARDEN_ABSENT = "WARDEN_ABSENT"
    CONTINUITY_OPEN = "CONTINUITY_OPEN"
    ISOLATION_FAULT = "ISOLATION_FAULT"
    PERMIT_NOT_GRANTED = "PERMIT_NOT_GRANTED"
    MONITOR_VETO = "MONITOR_VETO"
    MONITOR_STALE = "MONITOR_STALE"
    OVERFORCE = "OVERFORCE"
    HEARTBEAT_LOST = "HEARTBEAT_LOST"
    POWER_FAULT = "POWER_FAULT"


class RefusalCode(str, Enum):
    """Machine-readable refusal reasons (docs/DECISIONS.md O-007).

    MODEL_OUTPUT_INVALID is the fail-closed path: unparseable or
    schema-invalid model output becomes a REFUSAL, never an authorisation —
    and that refusal still has to publish a code.
    """

    WIND_LIMIT_EXCEEDED = "WIND_LIMIT_EXCEEDED"
    AMBIENT_OUT_OF_RANGE = "AMBIENT_OUT_OF_RANGE"
    BMS_FAULT_ACTIVE = "BMS_FAULT_ACTIVE"
    PROCEDURE_MISMATCH = "PROCEDURE_MISMATCH"
    SOURCE_CONTRADICTION = "SOURCE_CONTRADICTION"
    NOTAM_ACTIVE = "NOTAM_ACTIVE"
    INTERLOCK_NOT_READY = "INTERLOCK_NOT_READY"
    WARDEN_ABSENT = "WARDEN_ABSENT"
    INSUFFICIENT_SOURCES = "INSUFFICIENT_SOURCES"
    MODEL_OUTPUT_INVALID = "MODEL_OUTPUT_INVALID"


class Outcome(str, Enum):
    """How a run ended. None while it is still going."""

    MATED = "MATED"
    ABORTED = "ABORTED"
    REFUSED = "REFUSED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


def now_ts() -> float:
    """Unix epoch seconds, UTC. Stamp as close to the measurement as possible."""
    return time.time()


# --- Base --------------------------------------------------------------------


class BusMessage(BaseModel):
    """Common envelope on every topic.

    `schema` is the wire field name, but `schema` is a reserved attribute on
    pydantic's BaseModel, so the Python attribute is `schema_version` and the
    alias carries the wire name. Always serialise with `by_alias=True` — the
    `encode()` helper below does.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: str = Field(
        default=SCHEMA_VERSION,
        alias="schema",
        description="MAJOR.MINOR — bump MINOR for additive fields, MAJOR to break readers",
    )
    ts: float = Field(default_factory=now_ts, description="Unix epoch seconds, UTC")


# --- /rig/state --------------------------------------------------------------


class Joints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    names: list[str] = Field(default_factory=lambda: list(JOINT_NAMES))
    position_rad: list[float]
    velocity_rad_s: list[float]
    torque_norm: list[float]

    @model_validator(mode="after")
    def _same_length(self) -> "Joints":
        n = len(self.names)
        for field in ("position_rad", "velocity_rad_s", "torque_norm"):
            if len(getattr(self, field)) != n:
                raise ValueError(
                    f"joints.{field} has {len(getattr(self, field))} values "
                    f"but there are {n} joint names"
                )
        return self


class TcpPose(BaseModel):
    """Tool-centre-point pose — where the connector actually is."""

    model_config = ConfigDict(extra="forbid")

    x_m: float
    y_m: float
    z_m: float
    rx_rad: float
    ry_rad: float
    rz_rad: float


class Sensors(BaseModel):
    model_config = ConfigDict(extra="forbid")

    estop_engaged: bool = Field(strict=True)
    beam_broken: bool = Field(strict=True)
    fsr_n: float = Field(description="force-sensitive resistor reading, newtons")
    latch_closed: bool = Field(strict=True)
    continuity: bool = Field(strict=True)
    warden_present: bool = Field(
        strict=True,
        description="a human at site 1 with a hand near the E-stop. Needs a real "
        "physical source (deadman / presence switch) or it is theatre — see "
        "docs/DECISIONS.md O-004"
    )


class CameraHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    fps: float
    last_frame_ts: float


class Ambient(BaseModel):
    """Conditions. Mirrored onto every recorded episode's metadata."""

    model_config = ConfigDict(extra="forbid")

    wind_ms: float
    fan_setting: int
    lux: float
    temp_c: float


class RigState(BusMessage):
    """Rig -> everyone, 20 Hz. The raw truth about the hardware."""

    seq: int = Field(description="monotonic; lets a subscriber detect QoS-0 drops")
    site: str
    rig_id: str
    run_id: Optional[str] = Field(default=None, description="None when idle")
    phase: Phase
    joints: Joints
    tcp_pose: TcpPose
    sensors: Sensors
    cameras: dict[str, CameraHealth]
    ambient: Ambient

    @field_validator("cameras")
    @classmethod
    def _camera_names_are_contractual(
        cls, v: dict[str, CameraHealth]
    ) -> dict[str, CameraHealth]:
        expected = set(CAMERA_NAMES)
        if set(v) != expected:
            raise ValueError(
                f"cameras must be exactly {sorted(expected)}, got {sorted(v)} — "
                "these names are fixed by CONTRACTS.md §1 and must match the "
                "Isaac Sim scene and the tape-marked physical positions"
            )
        return v


# --- /rig/interlock ----------------------------------------------------------


class InterlockState(BusMessage):
    """Interlock FSM (ESP32) -> console, policy gate.

    Published on every change PLUS a 1 Hz heartbeat. The heartbeat matters:
    silence must be distinguishable from "everything is fine". Subscribers
    treat a gap > INTERLOCK_HEARTBEAT_TIMEOUT_S as permissive=False.
    """

    site: str
    rig_id: str
    run_id: Optional[str] = None
    permissive: bool = Field(
        strict=True,
        description="True means every condition was checked and all passed — "
        "never a default, never an assumption",
    )
    continuity: bool = Field(strict=True)
    isolation: bool = Field(strict=True)
    estop_engaged: bool = Field(strict=True)
    warden_present: bool = Field(strict=True)
    reasons: list[InterlockReason] = Field(default_factory=list)
    source: str = Field(description="which interlock board published this, e.g. 'esp32-01'")
    fw_version: str

    @model_validator(mode="after")
    def _denial_must_explain_itself(self) -> "InterlockState":
        if self.permissive and self.reasons:
            raise ValueError(
                f"permissive=True but reasons={[r.value for r in self.reasons]} — "
                "a permit cannot carry denial reasons"
            )
        if not self.permissive and not self.reasons:
            raise ValueError(
                "permissive=False with no reasons — every denial must say why, "
                "or the console cannot tell the operator what to fix"
            )
        return self


# --- /monitor/verdict --------------------------------------------------------


class MonitorVerdict(BusMessage):
    """Cosmos monitor -> interlock, console. >=25 Hz.

    A veto LATCHES: recovery requires an explicit operator reset, not merely
    the next frame coming back clear. Auto-clearing would turn a person
    reaching in into a stutter-stop-start, which is worse than not stopping.
    See docs/DECISIONS.md O-006.
    """

    seq: int
    rig_id: str
    run_id: Optional[str] = None
    ok: bool = Field(strict=True)
    veto: bool = Field(strict=True)
    hazard: Optional[Hazard] = None
    confidence: float = Field(ge=0.0, le=1.0)
    frame_ts: float = Field(description="capture time of the frame this verdict is about")
    latency_ms: float = Field(description="what the model reports it took")
    model_id: str
    device: str = Field(description="'orin-nano-super' or the desktop-GPU fallback")

    @model_validator(mode="after")
    def _verdict_is_self_consistent(self) -> "MonitorVerdict":
        if self.veto and self.hazard is None:
            raise ValueError("veto=True requires a hazard — the operator must be told what stopped it")
        if self.ok and (self.veto or self.hazard is not None):
            raise ValueError(
                f"ok=True but veto={self.veto} hazard={self.hazard} — contradictory verdict"
            )
        return self

    @property
    def end_to_end_latency_ms(self) -> float:
        """Measured latency: frame capture -> verdict published.

        `latency_ms` is what the model CLAIMS. This is what it actually took.
        Publishing both means the honest edge-latency number the plan requires
        falls out of the logs rather than needing a separate experiment.
        """
        return (self.ts - self.frame_ts) * 1000.0


# --- /permit/decision --------------------------------------------------------


class PermitDecision(BusMessage):
    """Nemotron reasoner (Token Factory) -> console, interlock.

    Field list frozen by the plan. THE single definition — `token_factory.py`
    imports this rather than keeping its own copy, so the two cannot drift.

    `refusal_code` is a first-class output: on authorized=False it must carry
    a machine-readable code. The video's refusal beat depends on it.
    """

    request_id: str
    run_id: Optional[str] = None
    authorized: bool = Field(
        strict=True,
        description="strict: a model answering \"yes\" instead of true must NOT be "
        "coerced into an authorisation — that is a silent fail-open",
    )
    profile: str = Field(description="named operating envelope, e.g. 'NOMINAL', 'HIGH_WIND'")
    limits: dict[str, Any] = Field(
        default_factory=dict,
        description="the envelope the deterministic tier ENFORCES. Every key must be "
        "a number something actually checks — an unenforced limit is decoration "
        "(docs/DECISIONS.md O-008)",
    )
    reasons: list[str] = Field(default_factory=list)
    refusal_code: Optional[RefusalCode] = None
    inputs_digest: str = Field(description="sha256 of the canonicalized inputs")
    model_id: str
    latency_ms: Optional[float] = None

    @model_validator(mode="after")
    def _refusal_carries_a_code(self) -> "PermitDecision":
        if not self.authorized and self.refusal_code is None:
            raise ValueError(
                "authorized=False requires a refusal_code — the refusal path is a "
                "first-class output, not an error case"
            )
        if self.authorized and self.refusal_code is not None:
            raise ValueError(
                f"authorized=True but refusal_code={self.refusal_code} — contradictory decision"
            )
        return self


# --- /clock/turnaround -------------------------------------------------------


class TurnaroundClock(BusMessage):
    """Console -> displays, 1 Hz while a run is active.

    The clock starts when the operator REQUESTS a mate, including the permit
    wait — not at first motion. On a refusal the permit wait is the entire
    run, and the headline metric is the whole pitch, so excluding reasoning
    time would make the number dishonest.
    """

    run_id: str
    t_start: float
    t_now: float
    elapsed_s: float
    phase: Phase
    phase_started_s: float = Field(description="seconds into the run when this phase began")
    target_s: float
    stopped: bool
    outcome: Optional[Outcome] = None

    @model_validator(mode="after")
    def _stopped_iff_outcome(self) -> "TurnaroundClock":
        if self.stopped and self.outcome is None:
            raise ValueError("stopped=True requires an outcome")
        if not self.stopped and self.outcome is not None:
            raise ValueError(f"outcome={self.outcome} set while stopped=False")
        return self


# --- Topic <-> model ---------------------------------------------------------

MODEL_FOR_TOPIC: dict[str, type[BusMessage]] = {
    TOPIC_RIG_STATE: RigState,
    TOPIC_RIG_INTERLOCK: InterlockState,
    TOPIC_MONITOR_VERDICT: MonitorVerdict,
    TOPIC_PERMIT_DECISION: PermitDecision,
    TOPIC_CLOCK_TURNAROUND: TurnaroundClock,
}


def encode(message: BusMessage) -> bytes:
    """Model -> bytes for publishing. Always by_alias, so `schema` goes on the wire."""
    return message.model_dump_json(by_alias=True).encode("utf-8")


def decode(topic: str, payload: bytes | str) -> BusMessage:
    """Bytes off the bus -> validated model.

    Raises on an unknown topic or an invalid payload. That is the point:
    bad data is rejected where it enters the system, not three functions
    later when something divides by a string.
    """
    model = MODEL_FOR_TOPIC.get(topic)
    if model is None:
        raise ValueError(
            f"no model registered for topic {topic!r} — "
            f"known topics: {sorted(MODEL_FOR_TOPIC)}"
        )
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    return model.model_validate(json.loads(payload))
