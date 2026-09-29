"""Tests for the five bus payloads.

These are contract tests, not unit tests. Each one pins down something
`docs/BUS-PAYLOADS.md` promises, so that if someone changes a field name or
loosens a guard, CI says so before the rig does.

The guards matter more than the round-trips. A malformed safety message that
validates cleanly is worse than one that crashes — it reaches the interlock
and gets acted on.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from evtol.messages import (
    SCHEMA_VERSION,
    Ambient,
    CameraHealth,
    Hazard,
    InterlockReason,
    InterlockState,
    Joints,
    MODEL_FOR_TOPIC,
    MonitorVerdict,
    Outcome,
    PermitDecision,
    Phase,
    RefusalCode,
    RigState,
    Sensors,
    TcpPose,
    TurnaroundClock,
    decode,
    encode,
)
from evtol.topics import (
    ALL_TOPICS,
    TOPIC_CLOCK_TURNAROUND,
    TOPIC_MONITOR_VERDICT,
    TOPIC_PERMIT_DECISION,
    TOPIC_RIG_INTERLOCK,
    TOPIC_RIG_STATE,
)

Z6 = [0.0] * 6


# --- Builders: a VALID message of each type, so every test below mutates one
# thing and asserts that one thing is what breaks. ----------------------------


def a_rig_state(**overrides) -> RigState:
    kwargs = dict(
        seq=1,
        site="site1",
        rig_id="rig-01",
        run_id="run-2026-09-27-003",
        phase=Phase.APPROACH,
        joints=Joints(position_rad=Z6, velocity_rad_s=Z6, torque_norm=Z6),
        tcp_pose=TcpPose(x_m=0.24, y_m=-0.03, z_m=0.19, rx_rad=0.0, ry_rad=1.57, rz_rad=0.0),
        sensors=Sensors(
            estop_engaged=False,
            beam_broken=False,
            fsr_n=0.0,
            latch_closed=False,
            continuity=False,
            warden_present=True,
        ),
        cameras={
            "wrist": CameraHealth(ok=True, fps=30.0, last_frame_ts=1.0),
            "overhead": CameraHealth(ok=True, fps=30.0, last_frame_ts=1.0),
        },
        ambient=Ambient(wind_ms=3.4, fan_setting=2, lux=480.0, temp_c=21.5),
    )
    kwargs.update(overrides)
    return RigState(**kwargs)


def an_interlock(**overrides) -> InterlockState:
    kwargs = dict(
        site="site1",
        rig_id="rig-01",
        permissive=False,
        continuity=False,
        isolation=True,
        estop_engaged=False,
        warden_present=True,
        reasons=[InterlockReason.PERMIT_NOT_GRANTED],
        source="esp32-01",
        fw_version="0.3.1",
    )
    kwargs.update(overrides)
    return InterlockState(**kwargs)


def a_verdict(**overrides) -> MonitorVerdict:
    kwargs = dict(
        seq=91148,
        rig_id="rig-01",
        ok=False,
        veto=True,
        hazard=Hazard.HAND_IN_WORKSPACE,
        confidence=0.93,
        frame_ts=1790555571.166,
        latency_ms=38.1,
        model_id="nvidia/Cosmos3-Edge",
        device="orin-nano-super",
    )
    kwargs.update(overrides)
    return MonitorVerdict(**kwargs)


def a_permit(**overrides) -> PermitDecision:
    kwargs = dict(
        request_id="req-2026-09-27-0007",
        authorized=False,
        profile="HIGH_WIND",
        reasons=["Anemometer reads 11.4 m/s; SP-04 3.2 caps automated mating at 8.0 m/s."],
        refusal_code=RefusalCode.WIND_LIMIT_EXCEEDED,
        inputs_digest="sha256:9f2b8c1d",
        model_id="nvidia/nemotron-3-super-120b-a12b",
    )
    kwargs.update(overrides)
    return PermitDecision(**kwargs)


def a_clock(**overrides) -> TurnaroundClock:
    kwargs = dict(
        run_id="run-2026-09-27-003",
        t_start=1790555567.0,
        t_now=1790555678.0,
        elapsed_s=111.0,
        phase=Phase.MATED,
        phase_started_s=104.8,
        target_s=120.0,
        stopped=True,
        outcome=Outcome.MATED,
    )
    kwargs.update(overrides)
    return TurnaroundClock(**kwargs)


ALL_BUILDERS = [
    (TOPIC_RIG_STATE, a_rig_state),
    (TOPIC_RIG_INTERLOCK, an_interlock),
    (TOPIC_MONITOR_VERDICT, a_verdict),
    (TOPIC_PERMIT_DECISION, a_permit),
    (TOPIC_CLOCK_TURNAROUND, a_clock),
]


# --- The wire format ---------------------------------------------------------


@pytest.mark.parametrize("topic,build", ALL_BUILDERS, ids=lambda x: getattr(x, "__name__", x))
def test_roundtrip_is_lossless(topic, build):
    """Publish -> subscribe must give back exactly what was sent."""
    original = build()
    assert decode(topic, encode(original)) == original


@pytest.mark.parametrize("topic,build", ALL_BUILDERS, ids=lambda x: getattr(x, "__name__", x))
def test_envelope_on_the_wire(topic, build):
    """Every message carries `schema` and `ts`.

    `schema` is a reserved attribute on pydantic's BaseModel, so the Python
    field is `schema_version` with an alias. If someone serialises without
    by_alias=True the wire name silently becomes `schema_version` and every
    other subscriber breaks — this is the test that catches that.
    """
    payload = json.loads(encode(build()))
    assert payload["schema"] == SCHEMA_VERSION
    assert "schema_version" not in payload
    assert isinstance(payload["ts"], float)


def test_every_topic_has_a_model():
    """A topic nobody can decode is a topic nobody can subscribe to."""
    assert set(MODEL_FOR_TOPIC) == set(ALL_TOPICS)


def test_decode_rejects_unknown_topic():
    with pytest.raises(ValueError, match="no model registered"):
        decode("/rig/not-a-real-topic", b"{}")


def test_decode_rejects_unknown_field():
    """extra="forbid": a stray field is an error, not a shrug.

    This is the deliberate trade in messages.py — adding a field means
    redeploying subscribers, in exchange for a mistyped safety field never
    being silently dropped.
    """
    payload = json.loads(encode(an_interlock()))
    payload["permissve"] = True  # the typo that would otherwise go unnoticed
    with pytest.raises(ValidationError):
        decode(TOPIC_RIG_INTERLOCK, json.dumps(payload))


# --- Guards: the invariants that keep a bad message off the bus --------------


def test_refusal_must_carry_a_code():
    """The refusal path is a first-class output, not an error case."""
    with pytest.raises(ValidationError, match="requires a refusal_code"):
        a_permit(refusal_code=None)


def test_authorisation_must_not_carry_a_refusal_code():
    with pytest.raises(ValidationError, match="contradictory decision"):
        a_permit(authorized=True, refusal_code=RefusalCode.WIND_LIMIT_EXCEEDED)


def test_invented_refusal_code_is_rejected():
    """The model cannot make up a code.

    A response saying "TOO_WINDY" instead of "WIND_LIMIT_EXCEEDED" fails
    validation, which the caller turns into MODEL_OUTPUT_INVALID — a refusal.
    Fail-closed, per CONTRACTS.md 4.
    """
    with pytest.raises(ValidationError):
        a_permit(refusal_code="TOO_WINDY")


def test_denial_must_explain_itself():
    """permissive=False with no reasons leaves the operator nothing to fix."""
    with pytest.raises(ValidationError, match="every denial must say why"):
        an_interlock(permissive=False, reasons=[])


def test_permit_cannot_carry_denial_reasons():
    with pytest.raises(ValidationError, match="cannot carry denial reasons"):
        an_interlock(permissive=True, reasons=[InterlockReason.ESTOP_ENGAGED])


def test_permissive_true_with_empty_reasons_is_valid():
    """The happy path still has to work — guards that reject everything are useless."""
    assert an_interlock(permissive=True, continuity=True, reasons=[]).permissive is True


def test_veto_must_name_a_hazard():
    """An abort the operator cannot explain is an abort they will override."""
    with pytest.raises(ValidationError, match="requires a hazard"):
        a_verdict(veto=True, hazard=None)


def test_verdict_cannot_be_ok_and_vetoing():
    with pytest.raises(ValidationError, match="contradictory verdict"):
        a_verdict(ok=True, veto=True)


def test_confidence_is_a_probability():
    with pytest.raises(ValidationError):
        a_verdict(confidence=1.4)


def test_camera_names_are_contractual():
    """`wrist` and `overhead` are fixed by CONTRACTS.md 1 and must match the
    Isaac Sim scene and the tape-marked physical positions."""
    cams = {
        "wrist": CameraHealth(ok=True, fps=30.0, last_frame_ts=1.0),
        "front": CameraHealth(ok=True, fps=30.0, last_frame_ts=1.0),
    }
    with pytest.raises(ValidationError, match="cameras must be exactly"):
        a_rig_state(cameras=cams)


def test_joint_arrays_must_match_joint_names():
    """Five positions for six joints is how you drive the wrong joint."""
    with pytest.raises(ValidationError, match="but there are 6 joint names"):
        Joints(position_rad=[0.0] * 5, velocity_rad_s=Z6, torque_norm=Z6)


def test_clock_stopped_iff_outcome():
    with pytest.raises(ValidationError, match="requires an outcome"):
        a_clock(stopped=True, outcome=None)
    with pytest.raises(ValidationError, match="while stopped=False"):
        a_clock(stopped=False, outcome=Outcome.MATED)


def test_phase_enum_rejects_freetext():
    with pytest.raises(ValidationError):
        a_rig_state(phase="inserting")


# --- No coercion on safety-bearing booleans ----------------------------------
#
# Pydantic's default is to helpfully turn the string "yes" into True. On this
# bus that is a silent fail-open: a reasoner answering sloppily gets its permit
# GRANTED, a board sending "permissive": "true" gets motion ALLOWED. These
# tests pin the strictness so it cannot be loosened by accident.


@pytest.mark.parametrize("truthy", ["yes", "true", "True", "on", "1", 1])
def test_authorized_is_not_coerced(truthy):
    """The bug this suite caught: {"authorized": "yes"} became an authorisation."""
    with pytest.raises(ValidationError):
        a_permit(authorized=truthy, refusal_code=None)


@pytest.mark.parametrize("truthy", ["true", "yes", 1])
def test_permissive_is_not_coerced(truthy):
    with pytest.raises(ValidationError):
        an_interlock(permissive=truthy, reasons=[])


@pytest.mark.parametrize("field", ["ok", "veto"])
def test_verdict_booleans_are_not_coerced(field):
    with pytest.raises(ValidationError):
        a_verdict(**{field: "true"})


def test_sensor_booleans_are_not_coerced():
    """These feed the interlock; a coerced E-stop reading is the worst case."""
    with pytest.raises(ValidationError):
        Sensors(
            estop_engaged="false",  # a string that looks reassuring
            beam_broken=False,
            fsr_n=0.0,
            latch_closed=False,
            continuity=False,
            warden_present=True,
        )


# --- Derived values ----------------------------------------------------------


def test_end_to_end_latency_is_measured_not_claimed():
    """`latency_ms` is what the model reports; this is what it actually took.

    Publishing both is how the honest edge-latency number the plan requires
    falls out of the logs instead of needing a separate experiment.
    """
    v = a_verdict(frame_ts=1000.0, ts=1000.040, latency_ms=12.0)
    assert v.end_to_end_latency_ms == pytest.approx(40.0)
    assert v.latency_ms == 12.0
