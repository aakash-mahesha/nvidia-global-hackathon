# BUS-PAYLOADS.md — the five topics, literally

Companion to `docs/CONTRACTS.md` §3, which decides the broker and the rules.
This file fixes the **shape of every message**: real field names, real types,
real plausible values. Topic strings live in `src/evtol/topics.py`.

> **Status: PROPOSED — ratify at the contract freeze.** Everything here is a
> concrete first draft written so the rig mock can be built. Items marked
> **① … ⑨** are the open decisions that need four pairs of eyes. Once
> ratified, this file is normative and changes are joint decisions.

## Rules that apply to every topic

1. **Units live in the field name.** `wind_ms`, `position_rad`, `force_n`,
   `latency_ms`, `elapsed_s`. Never a bare `wind` or `angle`. This is the
   cheapest possible defence against the degrees/radians class of bug, which
   on this project means driving a connector into a socket at the wrong angle.
2. **Every message carries `schema` and `ts`.** `schema` is `"MAJOR.MINOR"` —
   bump MINOR for additive fields, MAJOR for anything that breaks a reader.
   `ts` is **Unix epoch seconds as a float, UTC**, taken as close to the
   measurement as possible.
3. **Nothing is retained.** A reconnecting subscriber sees live state or
   nothing — never a stale snapshot of a rig that has since been powered off.
4. **High-rate topics carry `seq`**, a monotonically increasing integer, so a
   subscriber can detect drops on QoS 0 instead of silently averaging over
   gaps.
5. **`run_id` correlates a single mate attempt** across all five topics. It is
   how the incident record, the turnaround metric and the video slate all
   refer to the same event. Minted by the console when an attempt begins.
6. **Enums are UPPER_SNAKE strings, never integers.** A log line should be
   readable without a lookup table.

---

## 1 · `/rig/state`

Rig → everyone. **20 Hz**, continuous. The raw truth about the hardware.

```json
{
  "schema": "1.0",
  "ts": 1790555567.482,
  "seq": 48213,
  "site": "site1",
  "rig_id": "rig-01",
  "run_id": "run-2026-09-27-003",
  "phase": "APPROACH",
  "joints": {
    "names": ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"],
    "position_rad": [0.142, -0.883, 1.204, 0.051, -0.310, 0.028],
    "velocity_rad_s": [0.010, -0.042, 0.031, 0.002, -0.001, 0.000],
    "torque_norm": [0.12, 0.48, 0.33, 0.05, 0.03, 0.01]
  },
  "tcp_pose": {
    "x_m": 0.2418, "y_m": -0.0312, "z_m": 0.1975,
    "rx_rad": 0.0021, "ry_rad": 1.5701, "rz_rad": -0.0088
  },
  "sensors": {
    "estop_engaged": false,
    "beam_broken": false,
    "fsr_n": 0.0,
    "latch_closed": false,
    "continuity": false,
    "warden_present": true
  },
  "cameras": {
    "wrist":    {"ok": true, "fps": 29.8, "last_frame_ts": 1790555567.449},
    "overhead": {"ok": true, "fps": 30.1, "last_frame_ts": 1790555567.461}
  },
  "ambient": {
    "wind_ms": 3.4,
    "fan_setting": 2,
    "lux": 480,
    "temp_c": 21.5
  }
}
```

**`phase` enum** — also used by `/clock/turnaround`:
`IDLE` · `PERMIT_WAIT` · `APPROACH` · `FINE_ALIGN` · `INSERT` · `LATCH_VERIFY`
· `MATED` · `RETRACT` · `ABORT` · `FAULT`

> **① Joint names and order.** Taken from the LeRobot SO-101 convention. This
> same order must appear in the recorded dataset (`CONTRACTS.md` §1) and in
> the policy's action vector (§2). Three places, one order — fix it here.
>
> **② `site` / `rig_id` / `operator` key names.** `CONTRACTS.md` §1 lists
> these as TBD. Proposed: `site` (`"site1"`/`"site2"`), `rig_id`
> (`"rig-01"`), and `operator` — which appears on *episode metadata*, not on
> this topic, because the bus does not care who is driving.
>
> **③ Camera fps / resolution.** Proposed **30 fps, 640×480** on both
> `wrist` and `overhead`. This is a §1 TBD and must match the real webcams
> and the policy input contract. Only `fps` is reported here; resolution is a
> static property of the dataset, not per-message telemetry.
>
> **④ `warden_present`.** The non-negotiable safety rule — *the arm does not
> move unless a human at site 1 is physically present with a hand near the
> E-stop* — is currently a social convention. This field makes it
> machine-readable. It needs a physical source (a held deadman or a presence
> switch, A1's hardware). **If the team does not want to build that, say so
> explicitly and delete the field** — a rule the system cannot check is worse
> than one it never claimed to.

---

## 2 · `/rig/interlock`

Interlock FSM (ESP32) → console, policy gate. **On every change, plus a 1 Hz
heartbeat.** The heartbeat matters: silence must be distinguishable from
"everything is fine."

Motion denied:

```json
{
  "schema": "1.0",
  "ts": 1790555567.500,
  "site": "site1",
  "rig_id": "rig-01",
  "run_id": "run-2026-09-27-003",
  "permissive": false,
  "continuity": false,
  "isolation": true,
  "estop_engaged": false,
  "warden_present": true,
  "reasons": ["PERMIT_NOT_GRANTED", "CONTINUITY_OPEN"],
  "source": "esp32-01",
  "fw_version": "0.3.1"
}
```

Motion allowed:

```json
{
  "schema": "1.0",
  "ts": 1790555580.118,
  "site": "site1",
  "rig_id": "rig-01",
  "run_id": "run-2026-09-27-003",
  "permissive": true,
  "continuity": true,
  "isolation": true,
  "estop_engaged": false,
  "warden_present": true,
  "reasons": [],
  "source": "esp32-01",
  "fw_version": "0.3.1"
}
```

**`reasons[]` enum** — every reason `permissive` can be false:
`ESTOP_ENGAGED` · `BEAM_BROKEN` · `WARDEN_ABSENT` · `CONTINUITY_OPEN` ·
`ISOLATION_FAULT` · `PERMIT_NOT_GRANTED` · `MONITOR_VETO` ·
`OVERFORCE` · `HEARTBEAT_LOST` · `POWER_FAULT`

> **⑤ Fail-safe reading.** `permissive: true` means *"every condition was
> checked and all passed."* A missing message, a malformed message, or a
> heartbeat gap beyond **1.5 s** must be read by every subscriber as
> `permissive: false`. The contract requirement that permissive "must deny
> before it allows" is only real if absence reads as denial.

---

## 3 · `/monitor/verdict`

Cosmos monitor → interlock, console. **≥25 Hz.**

Clear:

```json
{
  "schema": "1.0",
  "ts": 1790555567.512,
  "seq": 91055,
  "rig_id": "rig-01",
  "run_id": "run-2026-09-27-003",
  "ok": true,
  "veto": false,
  "hazard": null,
  "confidence": 0.97,
  "frame_ts": 1790555567.478,
  "latency_ms": 34.2,
  "model_id": "nvidia/Cosmos3-Edge",
  "device": "orin-nano-super"
}
```

Hand in the workspace — **the abort beat**:

```json
{
  "schema": "1.0",
  "ts": 1790555571.204,
  "seq": 91148,
  "rig_id": "rig-01",
  "run_id": "run-2026-09-27-003",
  "ok": false,
  "veto": true,
  "hazard": "HAND_IN_WORKSPACE",
  "confidence": 0.93,
  "frame_ts": 1790555571.166,
  "latency_ms": 38.1,
  "model_id": "nvidia/Cosmos3-Edge",
  "device": "orin-nano-super"
}
```

**`hazard` enum** (`null` when `ok`):
`HAND_IN_WORKSPACE` · `PERSON_IN_ZONE` · `OBSTRUCTION` · `CABLE_SNAG` ·
`INLET_OCCLUDED` · `CAMERA_DEGRADED`

> **⑥ Why both `frame_ts` and `latency_ms`.** `latency_ms` is what the model
> *claims* it took. `ts - frame_ts` is what it *actually* took end to end.
> Publishing both means the honest edge-latency number the plan requires
> ("report edge latency honestly as a number") falls out of the logs instead
> of needing a separate measurement exercise. `device` carries whether you
> were on the Orin or the desktop-GPU fallback.
>
> **⑦ Veto is latching.** A single `veto: true` aborts the motion. Recovery
> requires an explicit operator reset, **not** simply the next frame coming
> back clear. Otherwise a hand waving through the frame produces a
> stutter-start rather than a stop.

---

## 4 · `/permit/decision`

Nemotron reasoner (Token Factory) → console, interlock. **Once per request.**
Field list is already frozen by the plan; the envelope and `request_id` are
added here.

Refusal — **the refusal beat**:

```json
{
  "schema": "1.0",
  "ts": 1790555560.006,
  "request_id": "req-2026-09-27-0007",
  "run_id": "run-2026-09-27-003",
  "authorized": false,
  "profile": "HIGH_WIND",
  "limits": {},
  "reasons": [
    "Anemometer reads 11.4 m/s. Site procedure SP-04 §3.2 caps automated mating at 8.0 m/s.",
    "Vehicle BMS reports fault 0x2A (cell imbalance); CCS procedure requires clearance before charge initiation."
  ],
  "refusal_code": "WIND_LIMIT_EXCEEDED",
  "inputs_digest": "sha256:9f2b8c1d4e7a6035bb21c0fe884d3a75cc190e2fb6a4d8e31057c92ab4f6e8d1",
  "model_id": "nvidia/nemotron-3-super-120b-a12b",
  "latency_ms": 2840
}
```

Authorisation:

```json
{
  "schema": "1.0",
  "ts": 1790555562.771,
  "request_id": "req-2026-09-27-0008",
  "run_id": "run-2026-09-27-004",
  "authorized": true,
  "profile": "NOMINAL",
  "limits": {
    "max_wind_ms": 8.0,
    "max_approach_speed_ms": 0.05,
    "max_insert_force_n": 12.0,
    "max_attempt_s": 120,
    "max_retries": 3
  },
  "reasons": [
    "Wind 3.4 m/s is within the 8.0 m/s cap in SP-04 §3.2.",
    "BMS reports no active faults. CCS procedure preconditions satisfied.",
    "No NOTAM affecting pad 1 for the current window."
  ],
  "refusal_code": null,
  "inputs_digest": "sha256:4c7e1a90bb35d28f06e4a71cc9d3b5820fe6417a0d9c8b3e25417fa6c08b93de",
  "model_id": "nvidia/nemotron-3-super-120b-a12b",
  "latency_ms": 3102
}
```

> **⑧ `refusal_code` enum** — a §4 TBD. Proposed, seeded from B2's corpus:
>
> | Code | Raised when |
> |------|-------------|
> | `WIND_LIMIT_EXCEEDED` | anemometer above the procedure cap |
> | `AMBIENT_OUT_OF_RANGE` | temperature / lighting / visibility outside stated limits |
> | `BMS_FAULT_ACTIVE` | vehicle battery reports an uncleared fault |
> | `PROCEDURE_MISMATCH` | connector/procedure mismatch, e.g. CCS steps against a GEACS inlet |
> | `SOURCE_CONTRADICTION` | two source documents give irreconcilable limits |
> | `NOTAM_ACTIVE` | an airspace notice covers the pad and window |
> | `INTERLOCK_NOT_READY` | the interlock is not reporting a clean permissive |
> | `WARDEN_ABSENT` | no human present at site 1 (see ④) |
> | `INSUFFICIENT_SOURCES` | the corpus does not cover the request; refuse rather than guess |
> | `MODEL_OUTPUT_INVALID` | **fail-closed**: unparseable or schema-invalid model output |
>
> `MODEL_OUTPUT_INVALID` is the one that must never be skipped. The contract
> requires that a broken model response becomes a refusal, never an
> authorisation, and that refusal still needs a code to publish.
>
> **`limits` is `{}` on refusal, never absent** — one shape for readers.
> `refusal_code` is `null` on authorisation and **mandatory** on refusal.
>
> **⑨ `limits` is the interlock's contract, not advice.** Every key here must
> be a number the deterministic tier actually enforces. If nothing enforces
> `max_retries`, delete it — a limit the system does not apply is theatre,
> and it is exactly the kind of thing a judge asks about.

---

## 5 · `/clock/turnaround`

Console → displays. **1 Hz while a run is active.** This topic exists to
measure the one number the project is about.

Running:

```json
{
  "schema": "1.0",
  "ts": 1790555641.000,
  "run_id": "run-2026-09-27-003",
  "t_start": 1790555567.000,
  "t_now": 1790555641.000,
  "elapsed_s": 74.0,
  "phase": "INSERT",
  "phase_started_s": 61.2,
  "target_s": 120,
  "stopped": false,
  "outcome": null
}
```

Finished:

```json
{
  "schema": "1.0",
  "ts": 1790555678.000,
  "run_id": "run-2026-09-27-003",
  "t_start": 1790555567.000,
  "t_now": 1790555678.000,
  "elapsed_s": 111.0,
  "phase": "MATED",
  "phase_started_s": 104.8,
  "target_s": 120,
  "stopped": true,
  "outcome": "MATED"
}
```

**`outcome` enum** (`null` while running):
`MATED` · `ABORTED` · `REFUSED` · `FAILED` · `TIMEOUT`

The clock starts when the operator requests a mate — **including the permit
wait**, which on the refusal path is the entire run. Measuring from first
motion instead would quietly exclude the reasoning time and make the headline
number dishonest.

---

## What to build from this

- `src/evtol/messages.py` — one pydantic model per topic, so the mock, the
  console, the rig and the monitor all validate against the same definitions
  and drift is impossible rather than merely discouraged.
- `src/evtol/bus.py` — publish/subscribe wrapper that takes and returns those
  models. The only file in the repo that imports an MQTT client.
- `src/evtol/mock/` — the synthetic publisher, which is the first real test of
  whether everything above is actually specifiable.
