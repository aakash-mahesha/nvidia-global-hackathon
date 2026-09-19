#!/usr/bin/env python3
"""check_credentials.py — the single "where do I stand" command.

Prints a status table (OK / MISSING / BLOCKED + remediation hint) covering:

  * every env var the project needs (from .env or the environment)
  * HF_TOKEN validity + gated access to the required HF repos
  * Token Factory reachability (GET /models, only when the key is set)
  * npa presence + `npa health preflight` (when npa is installed)
  * NGC CLI presence, tailscale presence, ~/.npa/credentials

Exit code: 0 only when nothing is MISSING or BLOCKED.

  --offline   check local config only (env vars, files, CLIs on PATH);
              no network calls. Used by CI, where real creds never exist —
              the workflow marks this step informational.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants — repo list resolved via the HF API (author=nvidia, search=cosmos)
# on 2026-09-19. "Cosmos 3" maps to the nvidia/Cosmos3-* family.
# ---------------------------------------------------------------------------

# (repo_id, purpose) — every repo whose gate/token the project needs.
HF_REQUIRED_REPOS: list[tuple[str, str]] = [
    ("nvidia/GR00T-N1.7-3B", "learned-approach policy (Isaac-GR00T)"),
    ("nvidia/Cosmos-Reason2-2B", "GR00T backbone — SEPARATE gate the plan misses"),
    ("nvidia/Cosmos3-Super", "Cosmos 3 generation model — sweeps/augmentation"),
]

# Useful but not strictly blocking: edge monitor + image2video variant.
HF_OPTIONAL_REPOS: list[tuple[str, str]] = [
    ("nvidia/Cosmos3-Super-Image2Video", "image→video augmentation variant"),
    ("nvidia/Cosmos3-Edge", "Cosmos monitor target for Orin Nano Super"),
]

# (env var, required?, remediation hint)
# "required" = no sane default — must be a real value before cloud work runs.
ENV_VARS: list[tuple[str, bool, str]] = [
    ("NEBIUS_PROJECT_ID", True, "Nebius console → IAM → Projects (docs/SETUP.md step 3)"),
    ("NEBIUS_IAM_TOKEN", False, "or run `npa configure` — it writes ~/.npa/credentials"),
    ("EVDATA_BUCKET", True, "object-storage bucket for episodes — create in Nebius console"),
    ("NEBIUS_S3_ENDPOINT", False, "has default: https://storage.eu-north1.nebius.cloud"),
    ("TOKEN_FACTORY_API_KEY", True, "Token Factory console → API keys (NOT the IAM token)"),
    ("TOKEN_FACTORY_BASE_URL", False, "has default: https://api.tokenfactory.us-central1.nebius.com/v1/"),
    ("PERMIT_MODEL_ID", False, "placeholder default — pin real Nemotron SKU at day-1 freeze"),
    ("NGC_API_KEY", True, "https://org.ngc.nvidia.com → Setup → API Key"),
    ("HF_TOKEN", True, "https://huggingface.co/settings/tokens + accept gated terms"),
    ("TAILSCALE_AUTHKEY", False, "Tailscale admin → Keys; or interactive `tailscale up`"),
    ("EVENT_BUS_URL", True, "event-bus URL per docs/CONTRACTS.md §3 (tech TBD at freeze)"),
    ("LEROBOT_DATASET_ROOT", False, "has default: ./data/lerobot"),
    ("JOB_KILL_TIMEOUT", False, "has default: 3600s — hard kill-timer on scheduled jobs"),
]

TOKEN_FACTORY_TIMEOUT = 15  # seconds
HF_TIMEOUT = 15
NPA_TIMEOUT = 90

OK, MISSING, BLOCKED = "OK", "MISSING", "BLOCKED"


def load_dotenv(path: Path) -> dict[str, str]:
    """Minimal .env reader (stdlib-only; python-dotenv handles it in src/)."""
    env: dict[str, str] = {}
    if not path.is_file():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip().strip("'\"")
        env[key.strip()] = val
    return env


def http_get(url: str, token: str | None = None) -> tuple[int | None, str]:
    """Return (status_code, body-snippet). status None on network error."""
    req = urllib.request.Request(url, headers={"User-Agent": "evtol-cred-check"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=HF_TIMEOUT) as resp:
            return resp.status, resp.read(512).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:  # noqa: BLE001 — report anything as unreachable
        return None, str(e)


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def add(self, status: str, check: str, detail: str = "") -> None:
        self.rows.append((status, check, detail))
        print(f"  {status:<8} {check:<38} {detail}")

    @property
    def failed(self) -> bool:
        return any(s in (MISSING, BLOCKED) for s, _, _ in self.rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="local config only, no network (CI mode)")
    args = ap.parse_args()
    offline: bool = args.offline

    repo_root = Path(__file__).resolve().parent.parent
    dotenv = load_dotenv(repo_root / ".env")

    def env(name: str) -> str:
        # real environment wins over .env file
        return os.environ.get(name) or dotenv.get(name, "")

    rep = Report()
    print(f"\neVTOL credential check  ({'OFFLINE — local config only' if offline else 'online'})\n")
    print(f"  {'STATUS':<8} {'CHECK':<38} REMEDIATION / DETAIL")
    print(f"  {'-' * 8} {'-' * 38} {'-' * 40}")

    # ---- .env file presence -------------------------------------------------
    if (repo_root / ".env").is_file():
        rep.add(OK, ".env file", "found")
    else:
        rep.add(MISSING, ".env file", "cp .env.example .env then fill it in (docs/SETUP.md)")

    # ---- env vars -----------------------------------------------------------
    for name, required, hint in ENV_VARS:
        if env(name):
            rep.add(OK, f"env:{name}")
        elif required:
            rep.add(MISSING, f"env:{name}", hint)
        else:
            rep.add(MISSING, f"env:{name} (optional)", hint)

    # ---- npa ----------------------------------------------------------------
    npa = shutil.which("npa")
    if npa:
        rep.add(OK, "cli:npa", npa)
    else:
        rep.add(MISSING, "cli:npa", "pipx/pip install github.com/nebius/nebius-physical-ai (scripts/setup.sh)")

    npa_creds = Path.home() / ".npa" / "credentials"
    if npa_creds.is_file():
        rep.add(OK, "~/.npa/credentials", "npa configured")
    else:
        rep.add(MISSING, "~/.npa/credentials", "run `npa configure` (docs/SETUP.md step 4)")

    if npa and npa_creds.is_file() and not offline:
        try:
            r = subprocess.run(["npa", "health", "preflight"], capture_output=True,
                               text=True, timeout=NPA_TIMEOUT)
            if r.returncode == 0:
                rep.add(OK, "npa health preflight")
            else:
                tail = (r.stderr or r.stdout).strip().splitlines()
                rep.add(BLOCKED, "npa health preflight",
                        f"exit {r.returncode}: {tail[-1][:80] if tail else 'no output'}")
        except subprocess.TimeoutExpired:
            rep.add(BLOCKED, "npa health preflight", f"timed out after {NPA_TIMEOUT}s")
        except Exception as e:  # noqa: BLE001
            rep.add(BLOCKED, "npa health preflight", str(e)[:80])
    elif npa and npa_creds.is_file() and offline:
        rep.add(OK, "npa health preflight", "skipped (--offline)")

    # ---- ngc ----------------------------------------------------------------
    ngc = shutil.which("ngc")
    rep.add(OK, "cli:ngc", ngc) if ngc else rep.add(
        MISSING, "cli:ngc", "install NGC CLI zip from org.ngc.nvidia.com/setup/installers")

    # ---- HF CLI + tailscale -------------------------------------------------
    hf_cli = shutil.which("hf") or shutil.which("huggingface-cli")
    rep.add(OK, "cli:hf/huggingface-cli", hf_cli) if hf_cli else rep.add(
        MISSING, "cli:hf/huggingface-cli", "pip install huggingface_hub")

    ts = shutil.which("tailscale")
    rep.add(OK, "cli:tailscale", ts) if ts else rep.add(
        MISSING, "cli:tailscale (rig host only)", "https://tailscale.com/download")

    # ---- network checks (skipped in --offline) -------------------------------
    if offline:
        print("\n  (--offline: skipped HF token validity, gated-repo access,")
        print("   Token Factory reachability, and npa preflight network checks)")
    else:
        hf_token = env("HF_TOKEN")
        if not hf_token:
            rep.add(MISSING, "HF token validity", "set HF_TOKEN first")
            for rid, purpose in HF_REQUIRED_REPOS + HF_OPTIONAL_REPOS:
                rep.add(MISSING, f"HF gate:{rid}", f"needs HF_TOKEN — {purpose}")
        else:
            code, body = http_get("https://huggingface.co/api/whoami-v2", hf_token)
            if code == 200:
                try:
                    who = json.loads(body).get("name", "?")
                except Exception:
                    who = "?"
                rep.add(OK, "HF token validity", f"authenticated as {who}")
            elif code == 401:
                rep.add(BLOCKED, "HF token validity", "401 — token invalid/revoked; recreate at hf.co/settings/tokens")
            else:
                rep.add(BLOCKED, "HF token validity", f"HTTP {code or 'unreachable'} — check network/token")

            for rid, purpose in HF_REQUIRED_REPOS:
                code, _ = http_get(f"https://huggingface.co/api/models/{rid}", hf_token)
                if code == 200:
                    rep.add(OK, f"HF gate:{rid}", purpose)
                elif code in (401, 403):
                    rep.add(BLOCKED, f"HF gate:{rid}",
                            f"accept terms at https://huggingface.co/{rid} ({purpose})")
                else:
                    rep.add(BLOCKED, f"HF gate:{rid}", f"HTTP {code or 'unreachable'} — {purpose}")
            for rid, purpose in HF_OPTIONAL_REPOS:
                code, _ = http_get(f"https://huggingface.co/api/models/{rid}", hf_token)
                if code == 200:
                    rep.add(OK, f"HF gate:{rid} (opt)", purpose)
                else:
                    rep.add(BLOCKED, f"HF gate:{rid} (opt)", f"HTTP {code or 'unreachable'} — {purpose}")

        tf_key = env("TOKEN_FACTORY_API_KEY")
        tf_base = env("TOKEN_FACTORY_BASE_URL") or "https://api.tokenfactory.us-central1.nebius.com/v1/"
        if not tf_key:
            rep.add(MISSING, "Token Factory /models", "set TOKEN_FACTORY_API_KEY (separate from IAM token)")
        else:
            code, _ = http_get(tf_base.rstrip("/") + "/models", tf_key)
            if code == 200:
                rep.add(OK, "Token Factory /models", tf_base)
            elif code in (401, 403):
                rep.add(BLOCKED, "Token Factory /models", f"HTTP {code} — key rejected; recreate in Token Factory console")
            else:
                rep.add(BLOCKED, "Token Factory /models", f"HTTP {code or 'unreachable'} at {tf_base}")

    # ---- summary -------------------------------------------------------------
    counts = {s: sum(1 for r in rep.rows if r[0] == s) for s in (OK, MISSING, BLOCKED)}
    print(f"\n  {counts[OK]} OK · {counts[MISSING]} MISSING · {counts[BLOCKED]} BLOCKED")
    if rep.failed:
        print("  → work through docs/SETUP.md, then re-run this script.\n")
        return 1
    print("  → all green.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
