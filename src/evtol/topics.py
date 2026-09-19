"""Event-bus topic constants — the bus is the API surface of the rig.

"The event bus is the API… nobody SSHes in to poke servos ad hoc."

All five JSON topics frozen (name-level) by the plan; payload schemas are
DRAFT pending the day-1 contract freeze — see docs/CONTRACTS.md §3.
Broker technology (MQTT / Redis pub/sub / WebSocket) is TBD at the freeze;
publishers/subscribers must only depend on these topic strings + JSON
payloads, never on a broker-specific API.
"""

from __future__ import annotations

# --- The five topics (exact strings are contractual) -------------------------

# Rig telemetry: joint states, camera health, sensor reads (E-stop, IR
# break-beam, FSR), wind/lighting tags. Published continuously.
TOPIC_RIG_STATE = "/rig/state"

# Hard-interlock state machine: relay permissive, continuity, isolation.
# A False permissive must deny motion BEFORE it ever allows it.
TOPIC_RIG_INTERLOCK = "/rig/interlock"

# Cosmos monitor verdicts — including the hand-in-workspace veto that
# aborts motion. Target ≥25 Hz on the Orin edge node (desktop GPU fallback).
TOPIC_MONITOR_VERDICT = "/monitor/verdict"

# Permit reasoner output — PermitDecision JSON (see token_factory.py and
# docs/CONTRACTS.md §4). The refusal beat lives here.
TOPIC_PERMIT_DECISION = "/permit/decision"

# Turnaround clock — the 15–20 min → <2 min thesis metric.
TOPIC_CLOCK_TURNAROUND = "/clock/turnaround"

ALL_TOPICS: tuple[str, ...] = (
    TOPIC_RIG_STATE,
    TOPIC_RIG_INTERLOCK,
    TOPIC_MONITOR_VERDICT,
    TOPIC_PERMIT_DECISION,
    TOPIC_CLOCK_TURNAROUND,
)
