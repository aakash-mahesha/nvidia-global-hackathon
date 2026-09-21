# Task plan — W1–W5, buffer W6

**Companion to `eVTOL_4dev_2team_plan.html`. Task-level layer, not a replacement.**

The HTML plan stays authoritative for team structure (§2), the interface
freeze (§3), the working rhythm (§5), the remote-rig protocol (§6), risk
triggers and pre-agreed responses (§7), the cut list (§8) and filming
strategy (§9). This document only expands **§4** — what each person does each
week, in what order, and how you know it is done.

Created **Mon 21 Sep 2026**.

## Assumptions

- **Arm ordered Mon 28 Sep (express), arrives Fri 2 Oct — end of W2.**
  Drop-dead order date **Wed 30 Sep**; past that, see the contingency table.
- **W6 is buffer, not work.** Five working weeks, W1–W5.
- Submission **Mon 26 Oct**, hard freeze 27 Oct.
- The thesis metric (15–20 min → <2 min) is **not** claimed up front. Build
  the system, measure what it actually does, report that number.

Weeks run **Saturday → Friday**. Every week ends with a **Friday gate**
(30 min, all four): hit the exit criteria or invoke the cut list.

| Week | Dates | Weekend block | Theme |
|------|-------|---------------|-------|
| W1 | Sat 19 – Fri 25 Sep | *already gone* | Unblock latency. Freeze contracts. Ship the mock. |
| W2 | Sat 26 Sep – Fri 2 Oct | Sat 26 / Sun 27 | Build the whole system in sim. **Arm lands Fri 2 Oct.** |
| W3 | Sat 3 – Fri 9 Oct | Sat 3 / Sun 4 | Arrival checklist on the block, then the arm goes live. |
| W4 | Sat 10 – Fri 16 Oct | Sat 10 / Sun 11 | Real data, curves, ablation, rehearsal shoot. |
| W5 | Sat 17 – Fri 23 Oct | Sat 17 / Sun 18 | Freeze metrics, shoot, edit. |
| W6 | Sat 24 – Thu 29 Oct | — | **Buffer only.** Submit Mon 26 Oct. |

## Who is who

Fill this in — the tasks below are addressed to these four labels. Per the
HTML plan §2, one assignment is not negotiable: **whoever is physically
nearest the arm owns A1**, at the site with bench space, a printer and an
outlet that can stay wired for six weeks.

| Lane | Name | Site | Second |
|------|------|------|--------|
| A1 · Hardware / electrical | | 1 | A2 |
| A2 · On-robot software | | 1 | B1 |
| B1 · ML / Nebius / GPU cost | | 2 | A2 |
| B2 · Agent, console, video | | 2 | B1 |

## Capacity discipline

**1E = one 3-hour evening.** Weeks with a weekend block give each person
~7E; W1 has no block left, so ~5E. Every task below is budgeted to fit
inside that. If a week's tasks exceed the budget, that is the signal to cut
scope — not to work later. The HTML plan's core finding still holds: ~480
person-hours total, for a plan originally scoped at roughly double.

---

## W1 · Mon 21 – Fri 25 Sep — unblock latency, freeze contracts

*5 evenings left, no weekend block. ~1.5E shared + ~3.5E lane work each.
This week removes blockers; it does not build features.*

### Shared — all four

| ID | Task | When | Done when |
|----|------|------|-----------|
| S1.1 | Accept HF gates: `nvidia/GR00T-N1.7-3B`, `nvidia/Cosmos-Reason2-2B`, `nvidia/Cosmos3-Super` (plus `Cosmos3-Edge`, `Cosmos3-Super-Image2Video`) | **tonight** | `check_credentials.py` shows OK, or pending **with a date** |
| S1.2 | NGC account + API key; `docker login nvcr.io` | tonight | an `nvcr.io` pull succeeds |
| S1.3 | Token Factory API key | tonight | `GET /models` returns 200 |
| S1.4 | Claim hackathon + Builder credits | tonight | balance visible in the console |
| S1.5 | **Contract freeze session** — resolve every TBD | **Tue 22, 2h** | DRAFT banner removed, `docs/CONTRACTS.md` committed |
| S1.6 | Book the 19:00–22:00 EST window + the five Friday gates | tonight | invites accepted by all four |

`Cosmos-Reason2-2B` is a **separate gate** from GR00T — GR00T N1.7 loads it
as a backbone at inference, so missing it produces a 401 even with the GR00T
gate accepted.

S1.5 must settle all of: fps / resolution · `site` / `rig_id` / `operator`
key names · action chunk length · serving endpoint shape · broker technology
for `EVENT_BUS_URL` · the `limits` key set · the `refusal_code` enum · the
three bag-file contents · the real `PERMIT_MODEL_ID` (placeholder today).

### B1 — critical path, front-load Mon/Tue

| ID | Task | Dep | Done when | E |
|----|------|-----|-----------|---|
| B1-1.1 | Team tenant + project; invite the other three; create the episode bucket; **fill and commit `.env.shared`** | — | the other three run `npa configure`, select the team project, and `check_credentials.py` sources `NEBIUS_PROJECT_ID` + `EVDATA_BUCKET` from `.env.shared` | 1.5 |
| B1-1.2 | `npa configure`, `npa health preflight`, `npa health access` | B1-1.1 | preflight exits 0 | 0.5 |
| B1-1.3 | **Three smoke tests PASS** | B1-1.2 | all three green — *the only agenda item until they are* | 1.0 |
| B1-1.4 | Service account for nightly jobs + CI | B1-1.1 | a job runs as the SA, not as a person | 0.5 |

> **B1-1.1 blocks three people.** `.env.shared` is empty today, so no one can
> run cloud work until it is filled. Target **Wed 23** at the latest.

### A2

| ID | Task | Dep | Done when | E |
|----|------|-----|-----------|---|
| A2-1.1 | Rig mock publisher — all five topics, JSON per the frozen schema | S1.5 | B2 subscribes from site 2 and sees all five | 1.5 |
| A2-1.2 | Three bag files: nominal run, wind run, abort beat | A2-1.1 | each replays deterministically through the mock | 1.0 |
| A2-1.3 | Tailscale on the rig host; both sites reach it by stable name | — | B2 drives the mock over the tailnet, no port forwarding | 1.0 |

### B2

| ID | Task | Dep | Done when | E |
|----|------|-----|-----------|---|
| B2-1.1 | Source corpus: CCS vs GEACS procedure, BMS fault codes, ambient/wind limits, NOTAM, site emergency plan | — | five documents in the repo, each version-stamped | 1.0 |
| B2-1.2 | At least three seeded contradiction cases | B2-1.1 | each names its expected `refusal_code` | 0.5 |
| B2-1.3 | Implement `request_permit()` including fail-closed parsing | S1.5, B2-1.1 | a contradiction returns `authorized=false` with a `refusal_code`, **and malformed model output also returns a refusal** | 1.5 |
| B2-1.4 | Repo hygiene: the dead `plans/` link in README; resolve the CHANGELOG question (see Open questions) | — | README has no broken links | 0.5 |

### A1

| ID | Task | Dep | Done when | E |
|----|------|-----|-----------|---|
| A1-1.1 | Finalise the BOM, second vendor for anything low-stock | — | every line item has a vendor and a lead time | 1.0 |
| A1-1.2 | **Order bench-interlock parts + filming kit now** — cheap, fast, and they unblock W2 | — | tracking numbers posted | 0.5 |
| A1-1.3 | Start printing: fuselage, CCS2 inlet, fiducial ring, **plus one spare of each** | — | first inlet and ring off the bed | 1.0 |
| A1-1.4 | Stage the arm order — cart built, express selected, ready to fire Mon 28 | A1-1.1 | cart screenshot in the channel | 0.5 |
| A1-1.5 | Second on A2's mock (bus-factor rule) | A2-1.1 | A1 has run the mock once | 0.5 |

**Gate Fri 25 Sep** — 3 smoke tests PASS · `.env.shared` filled and committed
· contracts frozen, DRAFT banner gone · rig mock live over Tailscale ·
**reasoner refuses a seeded contradiction with a `refusal_code`** · HF gates
approved or pending-with-a-date · BOM final and arm order staged.

---

## W2 · Sat 26 Sep – Fri 2 Oct — build the whole system in simulation

*Weekend block Sat 26 / Sun 27. ~7E each. Assume no arm until Friday.*

### A1

| ID | Task | Dep | Done when | E |
|----|------|-----|-----------|---|
| A1-2.1 | **Place the arm order — Mon 28, express.** Drop-dead Wed 30 | A1-1.4 | tracking number in the channel | 0.5 |
| A1-2.2 | **Bench the entire interlock chain** — ESP32 + E-stop + IR break-beam + FSR + relay permissive, wired to a dummy load (LED or 12 V fan standing in for servo power) | A1-1.2 | each sensor independently trips the relay, **and permissive is proven to deny before it is proven to allow** | 2.5 |
| A1-2.3 | ESP32 publishes real `/rig/interlock` messages onto the bus | A1-2.2, S1.5 | A2's FSM consumes real hardware messages, not just mock ones | 1.0 |
| A1-2.4 | Build the sprung mount + box fan + anemometer | A1-1.3 | the inlet visibly deflects under the fan | 1.5 |
| A1-2.5 | **Characterise displacement vs. wind speed; hand the numbers to B1** | A1-2.4 | at least five (m/s, mm) pairs plus a spring-constant estimate delivered | 1.0 |
| A1-2.6 | Build the film set: two tripods, two LED panels, mic, **tape-mark the wide and tight camera positions**; shoot pad test footage | A1-1.2 | B2 has reviewed a test clip for framing and audio | 0.5 |

> A1-2.2 and A1-2.5 are the two highest-value items anyone does this week.
> The first makes the interlock a known-good subsystem *before* arrival night
> instead of arrival night's main risk. The second calibrates Isaac Sim to the
> real pad instead of guessed values, which is what makes the sim-trained
> policy transfer.

### A2

| ID | Task | Dep | Done when | E |
|----|------|-----|-----------|---|
| A2-2.1 | Deterministic tier in sim: fiducial fine-align → insert → latch-verify | B1-2.1 | **20/20 mates in sim** from randomised start poses | 3.0 |
| A2-2.2 | Interlock FSM unit-tested against the mock **and** A1's bench harness | A1-2.3 | denies on each of estop / continuity / isolation; tests run in CI | 1.5 |
| A2-2.3 | Servo tier: 5–10 Hz action chunks → 200 Hz interpolation | S1.5 | a recorded chunk sequence plays at 200 Hz inside the contract latency budget | 1.5 |
| A2-2.4 | **Write the arrival checklist** | — | reviewed by all four; due Fri 2 Oct | 0.5 |
| A2-2.5 | Cosmos monitor spike — webcam on the empty pad, hand enters frame | S1.2 | a hand produces a veto verdict on `/monitor/verdict` | 0.5 |

### B1

| ID | Task | Dep | Done when | E |
|----|------|-----|-----------|---|
| B1-2.1 | Isaac Sim scene: SO-101 + printed inlet geometry, cameras named `wrist` / `overhead` per contract | B1-1.3 | scene loads, both cameras render | 2.0 |
| B1-2.2 | Sprung target + wind disturbance, parameterised from A1's measurements | A1-2.5 | **sim displacement matches the measured values within ~20%** | 1.5 |
| B1-2.3 | LeIsaac browser teleop into the scene | B1-2.1 | site 2 teleops the sim arm from a browser | 1.0 |
| B1-2.4 | Record **30–50 sim demos** in LeRobot v3, wind + lighting tags on every episode | B1-2.3 | episodes land in `EVDATA_BUCKET` and load with `lerobot` | 1.5 |
| B1-2.5 | Rehearse the full cloud path on a **public SO-101 v3 dataset**: download → fine-tune → eval → serve | B1-1.3 | a checkpoint serves and returns action chunks | 1.0 |

### B2

| ID | Task | Dep | Done when | E |
|----|------|-----|-----------|---|
| B2-2.1 | **Console v1 on the mock**: permit state, monitor status, turnaround clock, incident record | A2-1.2 | runs a full nominal bag end to end with no rig | 3.5 |
| B2-2.2 | Reasoner publishes to `/permit/decision` on the frozen bus schema | B2-1.3 | the console renders a live decision | 1.0 |
| B2-2.3 | **Shoot the refusal beat at full resolution — bank it** | B2-2.1 | clip in shared storage with a slate | 1.0 |
| B2-2.4 | Storyboard v1 | — | reviewed at the Friday gate | 1.0 |
| B2-2.5 | `FEEDBACK.md` — first real entries (npa ergonomics, Token Factory, HF gate turnaround) | — | three dated entries | 0.5 |

**Gate Fri 2 Oct** — a policy trained and evaluated end to end on Nebius ·
30–50 sim demos in v3 · deterministic tier 20/20 in sim · **interlock proven
deny-before-allow on the bench** · console v1 demoable · **refusal beat in the
can** · arrival checklist written · **arm delivered**.

---

## W3 · Sat 3 – Fri 9 Oct — the arm goes live

*Weekend block Sat 3 / Sun 4 is the arrival checklist: all four, A1 + A2
hands-on, B1 + B2 on the call. Nothing in it is design work — design was done
in sim.*

### Arrival checklist — one sitting

| # | Step | Done when |
|---|------|-----------|
| AC-1 | Assemble arm, PSU, hub; servo IDs and limits set; wrist cam mounted | the arm holds a commanded pose |
| AC-2 | E-stop, IR break-beam and FSR each verified **independently** on the real load; permissive proven to **deny** before it is proven to allow | three separate trip logs — *a re-verification, since A1 proved the chain on the bench in W2* |
| AC-3 | Mount the inlet on the sprung mount; align the fiducial ring; position fan + anemometer *(camera positions already taped in W2)* | fiducial detected from the overhead camera |
| AC-4 | **Static mate 20/20** with the deterministic tier ported from sim | 20 consecutive successful mates |
| AC-5 | First 10 teleop demos recorded and uploaded **the same evening** | 10 episodes in `EVDATA_BUCKET` |
| AC-6 | **Shoot the first takes in final framing** | clips in shared storage with slates |

### Rest of W3

| Who | Work | Done when |
|-----|------|-----------|
| **A1** | Warden for every rig slot · batch all physical changes into one sitting · build the wind ladder · fit spares as needed | every slot has a named warden; the change list is empty at week end |
| **A2** | Learned → deterministic handoff on the real rig · Cosmos monitor on the Orin with the hand-in-workspace veto · serving endpoint per the frozen contract | handoff completes a full mate; monitor ≥25 Hz, or the desktop-GPU fallback is used and edge latency reported honestly as a number |
| **B1** | Fine-tune GR00T on the sim demos · Jobs eval fan-out across wind × lighting · nightly cron with the hard kill-timer · daily spend report | **a sim success-vs-wind curve exists** |
| **B2** | Console v2 on live telemetry · storyboard **locked** · rough assembly of the already-banked beats | the console drives a real run; rough assembly is playable |
| **All** | Data collection begins — first 20–30 demos with the fan on, run as booked rig slots. **Every slot is also a filming take.** | episodes uploaded the same evening |

**Gate Fri 9 Oct** — interlocks verified on hardware · static mate 20/20 ·
learned approach + handoff succeeds at the lowest wind setting with the
monitor able to veto · sim success-vs-wind curve exists · ≥30 real demos
captured.

---

## W4 · Sat 10 – Fri 16 Oct — real data, curves, ablation

*Weekend block Sat 10 / Sun 11 is the data-collection marathon: 50–80 demos
with the fan on, run as booked slots so the arm is recording for the whole
window and nobody is idle waiting for it.*

| Who | Work | Done when |
|-----|------|-----------|
| **A1** | Warden for all slots · **wind ladder**: push success rate up the anemometer range · rehearse the abort beat (hand entering the workspace) | success rate recorded at each fan setting |
| **A2** | Full run: approach → handoff → latch → permissive green · p50/p95 time-to-mate · monitor false-abort and missed-hazard counts | all three metrics reported as numbers |
| **B1** | Fine-tune on real data **initialised from the sim-trained policy**, not from scratch · Cosmos augmentation · nightly fan-out on cron · **two-arm ablation only** (GR00T vs GR00T + Cosmos augmentation) · demos-to-threshold with and without augmentation · sim-vs-real curve comparison | ablation has numbers; a real success-vs-wind curve exists |
| **B2** | Console v2 driving a live run · **rehearsal shoot Thu 15 Oct — mandatory**, even if the robot is only half working · cut into a rough edit · same-day upload discipline with one-line slates | rough cut exists; remote-directing problems (audio, framing, feed lag, who says "action") are logged and fixed |

**Gate Fri 16 Oct** — real success-vs-wind curve · console driving a live run
· ablation numbers · rough cut exists · rehearsal shoot done.

---

## W5 · Sat 17 – Fri 23 Oct — freeze, shoot, edit

*Weekend block Sat 17 / Sun 18 is the main shoot.*

| Who | Work |
|-----|------|
| **All, Mon 19** | **Metrics frozen.** Abort beat and refusal beat rehearsed until repeatable. |
| **A1** | Runs the abort beat and safety; warden for the shoot. **Do not disassemble the rig** — camera positions, lighting and mount geometry unchanged since W4. |
| **A2** | Runs the robot for every take. Nobody at site 1 also has to think about the edit. |
| **B2** | **Directs live over the rig feed.** Captures every screen beat at site 2 at full resolution — console, permit refusal, success-vs-wind curve — not filmed off a monitor. Assembles nightly, so by Friday you know exactly which beat is missing. |
| **B1** | Final numbers for the README: model IDs, Nebius endpoints, Token Factory model ID, **the measured turnaround time**. Final GPU spend report. |
| **All** | Compliance sweep: README model / Nebius / Token Factory sections with real IDs · `FEEDBACK.md` dated · pre-existing-work statement finalised, including the printed-part origin TODO · Apache-2.0 · Devpost registration and city association. |

**Gate Fri 23 Oct** — two clean runs back to back · **≥1 minute of hardware
footage in the can** · edit well advanced · compliance checklist green.

---

## W6 · Sat 24 – Thu 29 Oct — buffer

Edit, re-shoot **only** the beats that failed, final compliance pass.
**Submit Mon 26 Oct.** Nothing new is built after 27 Oct. If a beat is still
missing on Sat 24, ship the video without it rather than pushing into the
freeze.

---

## Arm-arrival contingencies

| Scenario | Trigger | Response |
|----------|---------|----------|
| **Planned** | Arm arrives Fri 2 Oct | Run this plan as written. |
| **Amber** | Arm arrives 3–10 Oct | Arrival checklist moves to whichever evening it lands; W3 compresses but holds. No scope change. |
| **Orange** | Arm arrives 11–16 Oct | Drop the wind *ladder* to a single wind setting. Drop Cosmos augmentation breadth. Real demos compress to ~30, fine-tuned from the sim policy. Hardware footage = static mates + one full run. |
| **Red** | No working arm by Fri 16 Oct | **Sim + deterministic demo.** The video leans on the console, the refusal beat, the monitor veto and the sim success-vs-wind curve, and states honestly that hardware validation was not reached. Decided at the Fri 16 gate, in the open — not in W5. |

## What this changes from the HTML plan

1. **A1 has named work in every week.** The HTML assigns A1 nothing after W1.
   Here A1 builds the entire pad minus the arm — bench interlock chain,
   sprung target, wind characterisation, film set — converting two weeks of
   waiting into arrival-night insurance and sim fidelity.
2. **Filming starts at AC-6, not in W5.** Two of the three never-cut beats
   (the reasoner's refusal, the monitor veto) do not need the arm at all, and
   the hardware minute then accumulates across three weeks instead of
   depending on one weekend that might not survive a slip.
3. **A1's wind measurements feed B1's sim parameters** (A1-2.5 → B1-2.2).
   This is the one cross-site dependency the HTML does not have, and it is
   what makes the sim-trained policy likely to transfer to the real pad.

## Standing rules (unchanged, repeated because they bind daily)

- Fixed window **19:00–22:00 EST**, five evenings plus one weekend block.
  10-minute open at 19:00, all four, one agenda item.
- **Last 20 minutes of every evening is integration** against the mock or the
  rig. A 3-hour evening cannot absorb a two-week merge.
- **Thirty-minute rule.** Stuck for 30 minutes → pull in the second person.
- **Trunk-based, small PRs, merged the same evening.** No branch survives
  overnight. CI runs the smoke tests plus a rig-mock replay.
- **Safety, non-negotiable:** the arm does not move unless a human at site 1
  is physically present with a hand near the E-stop. Remote operators
  command; only the local warden energises.
- **GPU cost (B1):** preemptible VMs only · `bash scripts/teardown.sh` after
  **every** session · hard kill-timer on every scheduled job · spend reported
  daily.
- **Rig slots** booked in the shared calendar, minimum 45 minutes, named
  warden and named driver, goal declared at the start and a two-line result
  at the end.
- **The sim stays current all six weeks.** It is not scaffolding thrown away
  in W3 — it is the fallback that keeps four people working on the evening
  the arm is in pieces.

## Cut list — agreed now, in this order

1. Rotors-running stretch claim *(already not the thesis)*
2. Third ablation arm — ACT *(already cut)*
3. Console polish beyond permit state + clock + incident record
4. Cosmos augmentation sweep breadth
5. Wind **ladder** → a single wind setting
6. Scheduler and post-event report

**Never cut:** the interlocks · the live abort beat · the reasoner's refusal
beat · one minute of hardware footage · Token Factory cited with model IDs ·
Apache-2.0 repo + `FEEDBACK.md`.

## Open questions

- **Lane names.** The "Who is who" table is unfilled.
- **`CHANGELOG.md` is gitignored**, but the contract freeze and the Friday
  gates are both specified to record decisions there. Either commit it or
  move decision records into `docs/`. Resolve at the W1 freeze (S1.5).
- **`PERMIT_MODEL_ID`** is still the placeholder
  `nvidia/nemotron-3-super-120b-a12b`. "Token Factory cited with model IDs"
  is on the never-cut list, so this must be pinned at S1.5.
- **Printed-part origin** — the README pre-existing-work statement has a TODO
  on whether the fuselage / inlet / fiducial designs are authored in-window
  or prior art. Needed before submission.
