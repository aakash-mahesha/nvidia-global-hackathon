# SETUP.md — manual account & credential steps

Everything here needs a human in a browser. Do it **tonight** — HF gate
reviews can take days and block GR00T/Cosmos downloads (Phase 0, P0.2–P0.4).
Each step says where to click and what to copy into `.env`.

After finishing, run:

```bash
python3 scripts/check_credentials.py
```

until the table is all green.

---

## 1. Nebius Cloud account

1. Sign up at **https://console.nebius.com** (hackathon registration should
   land you in the right org — use the hackathon invite link if you have one).
2. Create a **tenant** and a **project** if none exist.
   Copy into `.env`: `NEBIUS_PROJECT_ID` (IAM → Projects → your project ID).

## 2. Hackathon + Builder Program credits ($400+)

1. Redeem the hackathon credit code in the Nebius console (Billing →
   Credits / Promotions).
2. Apply for Builder Program credits if eligible.
   Acceptance: credit balance visible in the console. No `.env` entry —
   but it funds all GPU spend; B1 reports spend daily.

## 3. Nebius IAM token

1. Console → IAM → Service accounts (or Tokens) → create a token with
   project access.
2. Copy into `.env`: `NEBIUS_IAM_TOKEN`.
   (Also acceptable: skip this and let `npa configure` in step 4 write
   `~/.npa/credentials` directly — that's the primary npa auth path.)

## 4. npa configure (Nebius Physical AI CLI)

1. `bash scripts/setup.sh` installs npa if missing (needs Python 3.10+).
2. Run `npa configure` — interactive; enter the IAM token / project.
   It writes `~/.npa/credentials` (never committed; gitignored).
3. Verify: `npa health preflight` — part of the three smoke tests that are
   "the only agenda item until they pass" (W1.5).
   `npa workbench health access` prints every access page still pending.

## 5. Token Factory API key — SEPARATE from the IAM token

1. Token Factory console → API keys → create key.
   Copy into `.env`: `TOKEN_FACTORY_API_KEY`.
2. `TOKEN_FACTORY_BASE_URL` defaults to
   `https://api.tokenfactory.us-central1.nebius.com/v1/` — already set.
3. `PERMIT_MODEL_ID` — the Nemotron SKU the permit reasoner calls.
   Placeholder `nvidia/nemotron-3-super-120b-a12b`; **pin the real model ID
   at the day-1 freeze** (plan doesn't choose Nano/Super/Ultra — joint
   decision, log in CHANGELOG).

## 6. NGC account + API key

1. Create an account at **https://ngc.nvidia.com** →
   **https://org.ngc.nvidia.com** → Setup → **Generate API Key**.
2. Copy into `.env`: `NGC_API_KEY`.
3. `docker login nvcr.io` — username `$oauthtoken`, password = the key.
   Needed for Isaac Sim / GR00T / Cosmos container pulls.
4. Install the NGC CLI zip from org.ngc.nvidia.com/setup/installers,
   then `ngc config set` (paste the key when prompted).

## 7. Hugging Face — account, token, THREE gated repos

1. Account at https://huggingface.co → Settings → Access Tokens → create a
   read token. Copy into `.env`: `HF_TOKEN`.
2. `huggingface-cli login` (or `hf auth login`) — paste the token.
3. **Accept gated terms on each page** — some are manually reviewed and
   take days; acceptance criteria is "approved or pending with a date":
   - https://huggingface.co/nvidia/GR00T-N1.7-3B — the policy
   - https://huggingface.co/nvidia/Cosmos3-Super — "Cosmos 3" generation
     sweeps (also `Cosmos3-Super-Image2Video`; `Cosmos3-Edge` for the Orin
     monitor)
   - https://huggingface.co/nvidia/Cosmos-Reason2-2B — **⚠ separate gate
     the plan misses**: GR00T N1.7 loads this backbone at inference; without
     it you get `GatedRepoError`/401 even with the GR00T gate accepted.
4. `check_credentials.py` (online mode) verifies token validity + each gate.

## 8. Tailscale authkey (remote rig access)

1. https://login.tailscale.com → create tailnet → Settings → Keys →
   **Generate auth key** (reusable, ephemeral OK for the rig host).
2. Copy into `.env`: `TAILSCALE_AUTHKEY` — *or* leave empty and run
   interactive `tailscale up` on the rig host.
3. Goal (W1.3): both sites reach the rig by stable name, no port
   forwarding — proven against the rig mock before hardware lands.

## 9. Remaining `.env` vars

- `EVDATA_BUCKET` — create an object-storage bucket in the Nebius console
  (episodes auto-upload on capture). `NEBIUS_S3_ENDPOINT` = your region's
  S3 endpoint (default eu-north1).
- `EVENT_BUS_URL` — TBD at the day-1 freeze (docs/CONTRACTS.md §3);
  placeholder `mqtt://rig.<tailnet>:1883` once chosen.
- `LEROBOT_DATASET_ROOT` — local LeRobot v3 root (default `./data/lerobot`).
- `JOB_KILL_TIMEOUT` — hard kill-timer seconds for every scheduled job
  (default 3600; nightly jobs fire ~22:30).

## 10. Hackathon registration + "city association"

Register on Devpost and check the portal for the "city association" field
(a week-5 exit item the plan doesn't explain — confirm with organizers).

---

### Standing rules (cross-cutting)

- **Preemptible VMs only.** `bash scripts/teardown.sh` after EVERY session.
- **Hard kill-timer** on every scheduled job — unattended billing is the
  feared failure.
- Safety, non-negotiable: the arm does not move unless a human at Site 1
  is physically present with a hand near the E-stop.
