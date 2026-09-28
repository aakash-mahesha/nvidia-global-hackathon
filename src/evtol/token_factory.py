"""Token Factory client wrapper for the Nemotron permit reasoner.

Token Factory is Nebius's OpenAI-compatible model-serving API. The permit
reasoner decides whether a charge-mate attempt may proceed and — the
rubric-critical beat — can REFUSE with a first-class `refusal_code`.

Contract (docs/CONTRACTS.md §4, DRAFT until day-1 freeze):
    {authorized, profile, limits, reasons[], refusal_code,
     inputs_digest, model_id}

The API key is TOKEN_FACTORY_API_KEY — SEPARATE from the Nebius Cloud IAM
token (docs/SETUP.md step 5).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

from evtol.config import Settings, load_settings

# PermitDecision lives in evtol.messages with the other four topic payloads —
# one definition, so the reasoner and the console cannot drift apart. Re-exported
# here because callers of this module reasonably expect to find it.
from evtol.messages import PermitDecision, RefusalCode  # noqa: F401

# --- Reasoner inputs ---------------------------------------------------------


class PermitInputs(BaseModel):
    """Everything the reasoner sees. Exact field set is DRAFT until the
    day-1 freeze; B2's source corpus (CCS vs GEACS procedure, BMS fault
    codes, ambient/wind limits, NOTAM, site emergency plan) feeds `sources`.
    """

    request: str = Field(description="what is being requested, e.g. 'begin_charge_mate'")
    rig_state: dict[str, Any] = Field(default_factory=dict, description="latest /rig/state payload")
    ambient: dict[str, Any] = Field(
        default_factory=dict, description="wind m/s, lighting, temp, NOTAM flags"
    )
    sources: list[dict[str, Any]] = Field(
        default_factory=list, description="relevant source-doc excerpts + versions"
    )

    def digest(self) -> str:
        canonical = json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


# --- Client ------------------------------------------------------------------


def build_client(settings: Optional[Settings] = None) -> OpenAI:
    """OpenAI-compatible client pointed at Token Factory."""
    settings = settings or load_settings(strict=False)
    if not settings.token_factory_api_key:
        raise RuntimeError(
            "TOKEN_FACTORY_API_KEY is not set — create a key in the Token "
            "Factory console (docs/SETUP.md step 5). It is NOT the Nebius "
            "Cloud IAM token."
        )
    return OpenAI(
        base_url=settings.token_factory_base_url,
        api_key=settings.token_factory_api_key,
    )


def parse_permit_response(
    raw: str | None,
    inputs: PermitInputs,
    model_id: str,
    request_id: str,
    run_id: Optional[str] = None,
    latency_ms: Optional[float] = None,
) -> PermitDecision:
    """Turn a raw model response into a PermitDecision. **Never raises.**

    This is the fail-closed half of the reasoner, and it is deliberately
    independent of the prompt, the corpus and the model call — so it can be
    written and tested without any of them.

    Anything that goes wrong — no response, non-JSON, missing fields, an
    invented refusal code, a `limits` value of the wrong type — becomes a
    REFUSAL carrying `MODEL_OUTPUT_INVALID`, never an authorization. A
    reasoner that fails open is worse than no reasoner, because the console
    shows a green permit that nothing actually justified.

    Two fields are stamped from OUR side and the model's own claims are
    discarded:

    * `inputs_digest` — computed from the inputs we actually sent, so the
      decision cannot claim to be about a different set of conditions.
    * `model_id` — taken from configuration, so a response cannot misreport
      which model produced it. "Token Factory cited with model IDs" is on the
      never-cut list; that citation has to be trustworthy.
    """
    def refusal(detail: str) -> PermitDecision:
        return PermitDecision(
            request_id=request_id,
            run_id=run_id,
            authorized=False,
            profile="UNKNOWN",
            limits={},
            reasons=[f"Permit reasoner output could not be validated: {detail}"],
            refusal_code=RefusalCode.MODEL_OUTPUT_INVALID,
            inputs_digest=inputs.digest(),
            model_id=model_id,
            latency_ms=latency_ms,
        )

    if not raw or not raw.strip():
        return refusal("empty response")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        return refusal(f"not valid JSON ({e})")

    if not isinstance(payload, dict):
        return refusal(f"expected a JSON object, got {type(payload).__name__}")

    # Never trust the model's account of what it is or what it was asked.
    payload.update(
        {
            "request_id": request_id,
            "run_id": run_id,
            "inputs_digest": inputs.digest(),
            "model_id": model_id,
            "latency_ms": latency_ms,
        }
    )
    payload.pop("schema", None)
    payload.pop("ts", None)

    try:
        return PermitDecision.model_validate(payload)
    except ValidationError as e:
        first = e.errors()[0] if e.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ())) or "?"
        return refusal(f"{where}: {first.get('msg', e)}")


def request_permit(
    inputs: PermitInputs,
    settings: Optional[Settings] = None,
    client: Optional[OpenAI] = None,
) -> PermitDecision:
    """Ask the Nemotron permit reasoner for a decision.

    Expected call shape (OpenAI-compatible chat completions):
        client.chat.completions.create(
            model=settings.permit_model_id,      # PERMIT_MODEL_ID
            messages=[
                {"role": "system", "content": PERMIT_SYSTEM_PROMPT},
                {"role": "user", "content": inputs.model_dump_json()},
            ],
            response_format={"type": "json_object"},  # structured PermitDecision JSON
            temperature=0,
        )
    The raw model output is then validated as PermitDecision and stamped
    with inputs_digest + model_id. On parse/validation failure the safe
    fallback is a refusal (fail-closed), never an authorization.

    STUB: prompt text + structured-output wiring are finalized at the
    day-1 contract freeze (docs/CONTRACTS.md §4). Until then this raises
    NotImplementedError so callers don't mistake it for a live path.
    """
    raise NotImplementedError(
        "Permit reasoner wiring lands in W1.8 — schema (PermitDecision) and "
        "client (build_client) are ready; prompt + response_format finalization "
        "is a day-1 contract-freeze item (docs/CONTRACTS.md §4)."
    )


PERMIT_SYSTEM_PROMPT = """\
You are the charging-permit reasoner for an eVTOL charging arm.
Decide whether a charge-mate attempt is permitted from ONLY the provided
source documents and telemetry. If sources contradict each other or the
request exceeds stated limits (wind, ambient, procedure), you MUST refuse.
Always answer with JSON matching the PermitDecision schema:
{authorized, profile, limits, reasons[], refusal_code, inputs_digest, model_id}.
On refusal, refusal_code is mandatory. Never invent limits not in the sources.
"""
