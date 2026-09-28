"""Tests for the fail-closed permit path.

`CONTRACTS.md` §4: "unparseable/invalid output => refusal, never
authorization." A reasoner that fails open is worse than no reasoner, because
the console shows a green permit that nothing actually justified.

None of these touch the network or a model. That is the point — the
fail-closed half is deliberately independent of the prompt and the corpus, so
it can be finished and proven before either exists.
"""

from __future__ import annotations

import json

import pytest

from evtol.messages import PermitDecision, RefusalCode
from evtol.token_factory import PermitInputs, parse_permit_response

MODEL_ID = "nvidia/nemotron-3-super-120b-a12b"
REQUEST_ID = "req-2026-09-27-0007"


@pytest.fixture
def inputs() -> PermitInputs:
    return PermitInputs(
        request="begin_charge_mate",
        rig_state={"phase": "PERMIT_WAIT"},
        ambient={"wind_ms": 11.4},
        sources=[{"doc": "SP-04", "version": "3.2"}],
    )


def parse(raw, inputs: PermitInputs) -> PermitDecision:
    return parse_permit_response(
        raw, inputs=inputs, model_id=MODEL_ID, request_id=REQUEST_ID
    )


VALID_REFUSAL = {
    "authorized": False,
    "profile": "HIGH_WIND",
    "limits": {},
    "reasons": ["Anemometer 11.4 m/s exceeds the 8.0 m/s cap in SP-04 3.2."],
    "refusal_code": "WIND_LIMIT_EXCEEDED",
    "inputs_digest": "whatever-the-model-claims",
    "model_id": "some-other-model",
}

VALID_AUTHORISATION = {
    "authorized": True,
    "profile": "NOMINAL",
    "limits": {"max_wind_ms": 8.0, "max_insert_force_n": 12.0},
    "reasons": ["Wind 3.4 m/s is within the 8.0 m/s cap."],
    "refusal_code": None,
    "inputs_digest": "whatever",
    "model_id": "whatever",
}


# --- The happy paths still have to work --------------------------------------


def test_valid_refusal_is_preserved(inputs):
    d = parse(json.dumps(VALID_REFUSAL), inputs)
    assert d.authorized is False
    assert d.refusal_code is RefusalCode.WIND_LIMIT_EXCEEDED
    assert "11.4 m/s" in d.reasons[0]


def test_valid_authorisation_is_preserved(inputs):
    d = parse(json.dumps(VALID_AUTHORISATION), inputs)
    assert d.authorized is True
    assert d.refusal_code is None
    assert d.limits["max_insert_force_n"] == 12.0


# --- Everything that can go wrong becomes a refusal ---------------------------


@pytest.mark.parametrize(
    "raw,label",
    [
        (None, "no response at all"),
        ("", "empty string"),
        ("   \n ", "whitespace only"),
        ("not json", "plain text"),
        ("{'authorized': false}", "python dict repr, not JSON"),
        ('{"authorized": false,', "truncated JSON"),
        ('"just a string"', "JSON, but not an object"),
        ("[1, 2, 3]", "JSON array"),
        ("{}", "empty object, every field missing"),
        ('{"authorized": false}', "refusal with no refusal_code"),
        ('{"authorized": false, "profile": "X", "refusal_code": "TOO_WINDY"}', "invented code"),
        ('{"authorized": true, "profile": "X", "refusal_code": "NOTAM_ACTIVE"}', "contradictory"),
        ('{"authorized": "yes", "profile": "X"}', "authorized is not a bool"),
        ('{"authorized": false, "profile": "X", "refusal_code": "NOTAM_ACTIVE", "limits": 5}', "limits not an object"),
    ],
)
def test_bad_output_becomes_a_refusal(raw, label, inputs):
    d = parse(raw, inputs)
    assert d.authorized is False, f"failed open on: {label}"
    assert d.refusal_code is RefusalCode.MODEL_OUTPUT_INVALID, label
    assert d.reasons, "a refusal must explain itself"


def test_nothing_ever_raises(inputs):
    """The wrapper is the last line of defence; it must not add a failure mode."""
    for raw in (None, "", "{", "null", "true", '{"authorized": {}}', "\x00"):
        assert parse(raw, inputs).authorized is False


# --- The model does not get to describe itself -------------------------------


def test_inputs_digest_is_ours_not_the_models(inputs):
    """A decision cannot claim to be about conditions we did not send."""
    d = parse(json.dumps(VALID_REFUSAL), inputs)
    assert d.inputs_digest == inputs.digest()
    assert d.inputs_digest != VALID_REFUSAL["inputs_digest"]


def test_model_id_is_ours_not_the_models(inputs):
    """"Token Factory cited with model IDs" is a never-cut item — that
    citation has to come from configuration, not from the response."""
    d = parse(json.dumps(VALID_REFUSAL), inputs)
    assert d.model_id == MODEL_ID
    assert d.model_id != VALID_REFUSAL["model_id"]


def test_refusal_stamps_digest_and_model_too(inputs):
    """Even the fallback refusal must be attributable and reproducible."""
    d = parse("garbage", inputs)
    assert d.inputs_digest == inputs.digest()
    assert d.model_id == MODEL_ID
    assert d.request_id == REQUEST_ID


def test_digest_changes_with_inputs():
    a = PermitInputs(request="begin_charge_mate", ambient={"wind_ms": 3.4})
    b = PermitInputs(request="begin_charge_mate", ambient={"wind_ms": 11.4})
    assert a.digest() != b.digest()


def test_decision_is_publishable(inputs):
    """The fallback refusal must survive the bus, not just exist in memory."""
    from evtol.messages import decode, encode
    from evtol.topics import TOPIC_PERMIT_DECISION

    d = parse("garbage", inputs)
    assert decode(TOPIC_PERMIT_DECISION, encode(d)) == d
