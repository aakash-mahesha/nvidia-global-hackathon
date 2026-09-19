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
from pydantic import BaseModel, Field

from evtol.config import Settings, load_settings

# --- Permit decision schema (frozen field list from the plan) ----------------


class PermitDecision(BaseModel):
    """The reasoner's output, published verbatim on /permit/decision.

    refusal_code is a FIRST-CLASS output: on authorized=False it must carry
    a machine-readable code (e.g. "WIND_LIMIT_EXCEEDED", "SOURCE_CONTRADICTION")
    — the video's refusal beat depends on it.
    """

    authorized: bool = Field(description="permit granted / refused")
    profile: str = Field(description="named operating envelope, e.g. 'nominal', 'high-wind'")
    limits: dict[str, Any] = Field(
        default_factory=dict,
        description="numeric envelope the interlock tier enforces "
        "(max wind m/s, approach speed, force caps, timeout) — field set TBD at freeze",
    )
    reasons: list[str] = Field(
        default_factory=list, description="human-readable justification, incl. refusal reasons"
    )
    refusal_code: Optional[str] = Field(
        default=None, description="machine-readable refusal code; REQUIRED when authorized=False"
    )
    inputs_digest: str = Field(
        description="sha256 of the canonicalized inputs the decision was made on"
    )
    model_id: str = Field(description="Token Factory model that produced this decision")


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
