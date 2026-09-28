# DECISIONS.md — open decisions and the record of settled ones

Two jobs in one file.

- **§1 Open** — everything still undecided, in one table, with who decides and
  what is blocked until they do. This is the **agenda for the Friday gate**:
  walk the table, close what you can, re-assign the rest.
- **§2 Decided** — dated record of what was chosen and why. This is the
  decision log that `docs/CONTRACTS.md` and the HTML plan keep referring to as
  "the CHANGELOG" — which was gitignored and therefore did not exist. It lives
  here instead, committed, where the other three can read it.

**Rules.** A decision leaves §1 only by appearing in §2 with a date and a
reason. Anything touching `docs/CONTRACTS.md` is a joint decision, never a
unilateral one. Write the reason down even when it feels obvious — in week 5
you will not remember, and "why did we do it this way?" is a question judges
ask.

---

## 1 · Open

Ordered by what is blocked soonest. Owner is who *drives* the decision, not
who decides alone.

| ID | Decision | Owner | Blocks | Recommendation | Needed by |
|----|----------|-------|--------|----------------|-----------|
| O-001 | **Joint names and order** for the SO-101 | A2 + B1 | rig mock · dataset schema · policy action vector | Use the LeRobot SO-101 convention: `shoulder_pan`, `shoulder_lift`, `elbow_flex`, `wrist_flex`, `wrist_roll`, `gripper`. The same order must hold in all three places or the arm moves the wrong joint. | W2 |
| O-002 | **Key names** for `site` / `rig_id` / `operator` | A2 | rig mock · episode metadata | `site: "site1"`, `rig_id: "rig-01"`, `operator` on episode metadata only (the bus does not care who is driving). | W2 |
| O-003 | **Camera fps and resolution** | A1 + B1 | dataset schema · policy input · mock | 30 fps, 640×480 on both `wrist` and `overhead`. Confirm against the webcams actually ordered. | W2 |
| O-004 | **`warden_present` — build it, delete it, or label it** | A1 | the project's central safety claim | Build a physical deadman/presence switch. A field that is hardcoded `true` looks like a safety feature, checks nothing, and will appear in the video. If it is not being built, delete the field and state plainly that the rule is procedural. | W2 |
| O-005 | **What silence means on `/rig/interlock`** | A2 | interlock FSM · console | 1 Hz heartbeat; any gap beyond 1.5 s is read by every subscriber as `permissive: false`. Without this, a crashed ESP32 reads as permission and "deny before allow" is not true. | W2 |
| O-006 | **Does a monitor veto clear itself?** | A2 + A1 | Cosmos monitor · abort beat | No. A veto latches until an explicit operator reset. Auto-clearing turns a person reaching in into a stutter-stop-start, which is worse than not stopping. | W3 |
| O-007 | **`refusal_code` enum** | B2 | permit reasoner · console | Ten codes drafted in `BUS-PAYLOADS.md` §4. Confirm each is something the agent can actually detect from the corpus. `MODEL_OUTPUT_INVALID` is mandatory — the fail-closed path still has to publish a code. | W2 |
| O-008 | **`limits` key set** | B2 + A2 | permit reasoner · deterministic tier | Every key must be a number the deterministic tier genuinely enforces. Delete any that nothing checks — an unenforced limit is decoration, and it is exactly what a judge will ask about. | W2 |
| O-009 | **Action chunk length** | B1 | policy I/O · serving endpoint · servo tier | Open TBD in `CONTRACTS.md` §2. Needed before the serving endpoint is written. | W3 |
| O-010 | **Serving endpoint shape** | B1 | policy serving · on-robot client | Open TBD in `CONTRACTS.md` §2: request/response fields, batching, latency budget. | W3 |
| O-011 | **Contents of the three bag files** | A2 | rig mock · CI replay · console testing | Nominal, wind, abort. Fix the exact beats in each so the console can be tested against a known script. | W2 |
| O-012 | **Final `PERMIT_MODEL_ID`** | B2 + B1 | permit reasoner · README | Placeholder today is `nvidia/nemotron-3-super-120b-a12b`. The plan does not choose between Nano/Super/Ultra. "Token Factory cited with model IDs" is on the never-cut list, so this must be a real pinned SKU. | W3 |
| O-013 | **Who is A1 / A2 / B1 / B2** | all four | every task assignment in `EXECUTION-PLAN.md` | The lane table is unfilled. Per HTML plan §2, whoever is physically nearest the arm owns A1 — that one is not negotiable. | immediately |
| O-014 | **Origin of the printed parts** | A1 | pre-existing-work statement in README | State whether the fuselage / CCS2 inlet / fiducial ring designs were authored in the competition window or are prior art. Required before submission. | W5 |
| O-015 | **Ratify `BUS-PAYLOADS.md` as normative** | all four | mock · console · rig · monitor | The file is currently marked PROPOSED. Once O-001…O-008 are closed, drop the banner and treat changes as joint decisions. | W2 |

---

## 2 · Decided

Newest first.

### D-005 · 2026-09-27 · Decisions are recorded in this file, not a CHANGELOG

**Decision.** `docs/DECISIONS.md` is the decision log. Open decisions in §1,
settled ones in §2.

**Why.** Both the HTML plan and `docs/CONTRACTS.md` instruct that contract
changes and Friday-gate decisions "get a CHANGELOG entry" — but
`CHANGELOG.md` is listed in `.gitignore`, so no such file exists in the repo
and there was nowhere to write a decision down. Open items were also
scattered across three documents (inline markers in `BUS-PAYLOADS.md`, an
Open Questions section in `EXECUTION-PLAN.md`, TBDs in `CONTRACTS.md`), so
nobody could answer "what is still undecided?" without reading all three.

**Consequence.** `CONTRACTS.md` and the HTML plan should be read as pointing
here. This table is the Friday-gate agenda.

### D-004 · 2026-09-27 · Bus payload shapes drafted

**Decision.** All five topics now have literal payload definitions in
`docs/BUS-PAYLOADS.md`: field names, types, units, example values, and the
`phase`, `hazard`, `outcome`, interlock-`reasons` and `refusal_code` enums.
Status is **PROPOSED** until O-015 closes.

**Why.** The contract described payloads in prose, which cannot be coded
against. Writing them out literally is also what surfaced O-004, O-005 and
O-006 — three real gaps found on a laptop instead of on a rig slot in week 3.

**Conventions adopted.** Units in field names (`wind_ms`, `position_rad`,
`force_n`) · `schema` + `ts` on every message · no retained messages ·
`seq` on high-rate topics for drop detection · `run_id` correlating one mate
attempt across all five topics · enums as UPPER_SNAKE strings.

**Notable call:** the turnaround clock starts when the operator requests a
mate, **including the permit wait** — not at first motion. On a refusal the
permit wait is the entire run, and the headline metric is the whole pitch, so
excluding reasoning time would make the number dishonest.

### D-003 · 2026-09-27 · `EVENT_BUS_URL` defaults to a local broker

**Decision.** `.env.shared` carries `mqtt://127.0.0.1:1883` until the rig host
is on Tailscale, then it becomes `mqtt://<rig-host>.<tailnet>.ts.net:1883`. A
personal `.env` overrides it for local work.

**Why.** A fresh clone then works standalone against the rig mock with no
setup, and `check_credentials.py` reports green. The alternative — leaving it
empty — means every new developer hits a MISSING check and has to be told what
to type. Use `127.0.0.1`, not `localhost`: on macOS `localhost` resolves to
IPv6 `::1` and will not match an IPv4 listener.

**Follow-up.** Swap to the tailnet address when A2-1.3 lands. The rig host is
just the machine at site 1 that will drive the arm — it does not need the arm
to exist, so this need not wait for delivery.

### D-002 · 2026-09-27 · Event bus broker is MQTT (mosquitto 2.1)

**Decision.** MQTT, via mosquitto 2.1. Config committed at
`infra/mosquitto.conf`. Closes the `CONTRACTS.md` §3 TBD.

**Why.** Standard for robot and sensor telemetry; installs in one command on
the rig host; reachable from both sites over Tailscale by hostname with no
port forwarding; topic strings map directly onto the five already-frozen
names. Rejected: Redis pub/sub (an extra service doing less), raw WebSockets
(hand-rolling delivery semantics nobody has time to debug).

**Binding constraint.** Publishers and subscribers depend only on topic
strings and JSON payloads, never on a broker-specific API. The client is
wrapped once in `src/evtol/bus.py`; swapping brokers must be a one-file change.

**Proposed, not yet ratified:** QoS 0 for high-rate telemetry, QoS 1 for
anything a decision hangs on, no retained messages anywhere.

### D-001 · 2026-09-21 · Plan restructured to five working weeks plus a buffer

**Decision.** `EXECUTION-PLAN.md` added as a task-level layer under the HTML
plan's §4. W1–W5 are working weeks; W6 is buffer only. Submission Mon 26 Oct.

**Why.** The HTML plan assumed an arm ordered on 18 Sep; it was not. It also
assigns A1 no work after week 1, leaving roughly 60 person-hours — an eighth
of total capacity — idle while waiting for hardware. The revision gives A1 the
whole pad minus the arm (bench interlock chain, sprung target, wind
characterisation, film set) and moves filming from a week-5 activity to
something that starts the first evening the arm moves.

**Notable call:** A1's measured wind-versus-displacement numbers feed B1's
Isaac Sim parameters. This cross-site dependency is not in the HTML plan and
is what makes a sim-trained policy likely to transfer to the real pad.
