# eVTOL Charging (arm)

Robotic-arm EV/eVTOL charging-plug mate for the **Nebius × NVIDIA Global
AI Hackathon** (Physical AI track). A SO-101 arm aligns, inserts, and
latches a CCS-style charging connector into a sprung, wind-disturbed
inlet — learned approach (GR00T) + deterministic fine-align/insert/
latch-verify tier, guarded by hard interlocks, a Cosmos-based workspace
monitor, and a Nemotron *permit reasoner* that can refuse.

- Source plan: `eVTOL_4dev_2team_plan.html`
- Execution strategy: `plans/2026-09-19-execution-strategy.md`
- Interface contracts (day-1 freeze): `docs/CONTRACTS.md`
- Manual account/credential setup: `docs/SETUP.md`
- Submission target: **Mon 26 Oct 2026** (hard freeze 27 Oct)

## Quick start

```bash
cp .env.example .env        # fill in per docs/SETUP.md
bash scripts/setup.sh       # installs/checks npa, ngc, hf CLIs (idempotent)
python3 scripts/check_credentials.py   # "where do I stand" status table
```

Safety rule (non-negotiable): **the arm does not move unless a human at
Site 1 is physically present with a hand near the E-stop.** Remote
operator commands; only the local warden energises.

## Models used

| Role | Model | Source | Status |
|------|-------|--------|--------|
| Learned approach policy | `nvidia/GR00T-N1.7-3B` (Isaac-GR00T) | Hugging Face (gated) | TODO: gate accepted? |
| GR00T backbone (separate HF gate!) | `nvidia/Cosmos-Reason2-2B` | Hugging Face (gated) | TODO: gate accepted? |
| Generation sweeps / augmentation | `nvidia/Cosmos3-Super` (+`-Image2Video`) | Hugging Face | TODO |
| Workspace monitor (edge target: Orin) | `nvidia/Cosmos3-Edge` | Hugging Face | TODO |
| Permit reasoner | `PERMIT_MODEL_ID` (placeholder `nvidia/nemotron-3-super-120b-a12b`) | Nebius Token Factory | TODO: pin final model ID |

## Nebius Cloud

All GPU compute (GR00T download/fine-tune/eval/serve, Cosmos generation
sweeps, Isaac Sim sprung-target env, Serverless-Jobs eval fan-out) runs on
Nebius Cloud via the **`npa`** CLI (Nebius Physical AI,
`github.com/nebius/nebius-physical-ai`).

- **Preemptible VMs only.** `npa cleanup` + `npa destroy` in full order
  after *every* session → `scripts/teardown.sh`.
- Hard kill-timer (`JOB_KILL_TIMEOUT`) on every scheduled job.
- Every captured episode auto-uploads to Nebius object storage
  (`EVDATA_BUCKET` / `NEBIUS_S3_ENDPOINT`).

Endpoint / project details: TODO after `npa configure`.

## Token Factory

The Nemotron permit reasoner runs on **Nebius Token Factory** —
OpenAI-compatible API, separate API key from the Nebius Cloud IAM token.

- Base URL: `https://api.tokenfactory.us-central1.nebius.com/v1/`
- Permit model ID: `TODO` (placeholder `nvidia/nemotron-3-super-120b-a12b`,
  freeze at day-1 contract review)
- Output contract: `{authorized, profile, limits, reasons[],
  refusal_code, inputs_digest, model_id}` — see `docs/CONTRACTS.md` §4 and
  `src/evtol/token_factory.py`.

## Pre-existing work statement

This repository was created on **2026-09-19** for the hackathon. All code,
scripts, documentation, contracts, and artifacts in this repo were
authored during the competition window (19 Sep – 26 Oct 2026), except:

- **Third-party open-source components used as-is:** LeRobot (v3 dataset
  format), Isaac Sim / Isaac Lab, LeIsaac (`LightwheelAI/leisaac`), NVIDIA
  Isaac-GR00T (`github.com/NVIDIA/Isaac-GR00T`), and the `npa` SDK
  (`github.com/nebius/nebius-physical-ai`). Each retains its own license.
- **Pre-trained models** listed in "Models used" above — used under their
  respective Hugging Face / NVIDIA license terms; no model weights are
  vendored into this repo.
- **Printed-part designs** (fuselage, CCS2 inlet, fiducial ring): TODO —
  state origin (authored during window vs. prior art) once sourced.

No prior proprietary code, datasets, or trained checkpoints were used.
