# CONTRACTS.md — interface freeze (DRAFT)

> **Status: DRAFT — pending the day-1 freeze (W1.1, Saturday).** "The single
> highest-leverage hour of the project." Once frozen, changes are joint
> decisions only and get a CHANGELOG entry.
>
> Everything below is pre-filled from the execution plan; fields marked
> **TBD** are the gaps the plan leaves open and must be resolved at the
> freeze.

Owners: dataset schema A2+B1 · policy I/O B1 · event bus A2 · permit
decision B2 · rig mock A2 (ships by Sunday).

---

## 1. Dataset schema — LeRobot v3 only

- **Format: LeRobot v3 exclusively — never mix v2.1 paths.** Applies to
  teleop capture, sim demos (30–50 in W2.1), real demos (50–80 in W3.1),
  and the public SO-101 v3 dataset used for pipeline rehearsal.
- **Cameras (fixed names):** `wrist`, `overhead`. Tape-mark the two camera
  positions at §4a step 3; names must match the LeIsaac/Isaac Sim scene.
- **Episode metadata — mandatory tags on EVERY episode:**
  - `wind` — anemometer reading (m/s) + fan setting; sim episodes carry the
    simulated wind value.
  - `lighting` — smart-bulb scene / lux level tag.
  - `site`, `rig_id`, `operator` — **TBD**: exact key names at freeze.
  - `task` — e.g. `charge_mate`; plus `success` label for eval.
- fps / resolution: **TBD** at freeze (must match camera hardware + policy
  input contract).
- Upload: every episode auto-uploads to Nebius object storage
  (`EVDATA_BUCKET`) on capture; local `LEROBOT_DATASET_ROOT` is a cache.

## 2. Policy I/O — learned approach tier

- Policy: `nvidia/GR00T-N1.7-3B` (backbone `nvidia/Cosmos-Reason2-2B` —
  separate HF gate). Fallback if gate pending: open policy (ACT or ungated
  checkpoint) to keep the pipeline rehearsed.
- **Actions are state-relative chunks**, emitted at **5–10 Hz**.
  Chunk length: **TBD** at freeze.
- **Servo tier interpolates to 200 Hz** — deterministic fine-align →
  insert → latch-verify interfaces; written against sim first (W1.4) so
  porting to hardware is "a wiring job, not a coding job."
- Serving endpoint shape: **TBD** at freeze (request/response fields,
  batching, latency budget).
- Inputs: `wrist` + `overhead` frames + joint state + task string per the
  dataset schema.

## 3. Event bus topics

The bus is the API — nobody SSHes in to poke servos ad hoc. Broker tech
**TBD** (MQTT / Redis pub/sub / WebSocket); `EVENT_BUS_URL` in `.env`.
Constants live in `src/evtol/topics.py`.

| Topic | Publisher → subscribers | Payload (DRAFT) |
|-------|------------------------|-----------------|
| `/rig/state` | rig → all | joint states, sensor reads (E-stop, IR, FSR), cam health, wind/lighting tags, `ts` |
| `/rig/interlock` | interlock FSM → console, policy gate | `{permissive, continuity, isolation, estop, reasons[], ts}` — permissive must deny before it allows |
| `/monitor/verdict` | Cosmos monitor → interlock/console | `{ok, hazard, veto, confidence, latency_ms, ts}` — hand-in-workspace veto |
| `/permit/decision` | reasoner → console, interlock | the §4 PermitDecision object |
| `/clock/turnaround` | console → displays | `{t_start, t_now, elapsed_s, phase, ts}` — the 15–20 min → <2 min metric |

## 4. Permit decision — Token Factory / Nemotron

Field list **frozen by the plan** (schema in `src/evtol/token_factory.py`):

```json
{
  "authorized": false,
  "profile": "string — named operating envelope",
  "limits": {"<key>": "number/string — envelope the interlock enforces"},
  "reasons": ["human-readable justification, incl. refusal reasons"],
  "refusal_code": "MACHINE_READABLE_CODE — REQUIRED when authorized=false",
  "inputs_digest": "sha256 of canonicalized inputs",
  "model_id": "Token Factory model ID that produced this"
}
```

- Model: `PERMIT_MODEL_ID` — placeholder `nvidia/nemotron-3-super-120b-a12b`;
  **TBD**: final SKU at freeze (never-cut: "Token Factory cited with model
  IDs").
- Fail-closed: unparseable/invalid output ⇒ refusal, never authorization.
- `limits` key set and `refusal_code` enum: **TBD** at freeze (seed from
  B2's corpus: CCS vs GEACS procedure, BMS fault codes, ambient/wind
  limits, NOTAM, site emergency plan + contradiction cases).

## 5. Rig mock spec

Ships Sunday (W1.2) so Site 2 "builds the entire console against this and
never blocks on hardware."

- Publisher emitting **all five §3 topics** from replay + synthetic data;
  same topics/schema as the real bus — console must not know the difference.
- Ships with **3 recorded bag files** (nominal run, wind run, abort beat —
  **TBD**: confirm contents at freeze).
- Must be drivable over Tailscale by stable name (W1.3 acceptance).
- CI replays the mock alongside smoke tests.
