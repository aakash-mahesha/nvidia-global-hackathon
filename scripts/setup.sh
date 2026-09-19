#!/usr/bin/env bash
# ============================================================================
# setup.sh — idempotent bootstrap for the eVTOL Charging (arm) project.
#
# Checks for (and where possible installs) the CLI tooling the plan needs:
#   npa        — Nebius Physical AI CLI (github.com/nebius/nebius-physical-ai,
#                Python 3.10+). Owns all GPU compute on Nebius Cloud.
#   ngc        — NVIDIA NGC CLI (pull Isaac Sim / GR00T / Cosmos containers).
#   hf / huggingface-cli — Hugging Face CLI (gated model downloads).
#
# Then prints the exact MANUAL commands for the steps that need interactive
# credentials. Safe to re-run. Guides, never gates: missing creds or CLIs
# produce instructions, not hard failures.
#
# Usage:  bash scripts/setup.sh
# ============================================================================
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

info()  { printf '  [info] %s\n' "$*"; }
ok()    { printf '  [ OK ] %s\n' "$*"; }
warn()  { printf '  [WARN] %s\n' "$*"; }
manual(){ printf '  [TODO] %s\n' "$*"; }
hr()    { printf '%s\n' '------------------------------------------------------------'; }

echo "eVTOL Charging (arm) — setup"
hr

# --------------------------------------------------------------------------
# 0. Python version — npa needs 3.10+
# --------------------------------------------------------------------------
echo "[0] Python"
if command -v python3 >/dev/null 2>&1; then
    PYVER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
        ok "python3 $PYVER (>= 3.10 required by npa)"
    else
        warn "python3 $PYVER found but npa requires >= 3.10 — install a newer Python first"
    fi
else
    warn "python3 not found — install Python 3.10+ before anything else"
fi

# --------------------------------------------------------------------------
# 1. npa — Nebius Physical AI CLI
# --------------------------------------------------------------------------
echo "[1] npa (Nebius Physical AI)"
if command -v npa >/dev/null 2>&1; then
    ok "npa already installed: $(command -v npa)"
elif command -v pipx >/dev/null 2>&1; then
    info "installing npa via pipx from github.com/nebius/nebius-physical-ai ..."
    if pipx install "git+https://github.com/nebius/nebius-physical-ai"; then
        ok "npa installed via pipx"
    else
        warn "pipx install failed — try manually:"
        manual "pipx install git+https://github.com/nebius/nebius-physical-ai"
    fi
elif command -v pip3 >/dev/null 2>&1 || python3 -m pip --version >/dev/null 2>&1; then
    info "installing npa via pip (user site) from github.com/nebius/nebius-physical-ai ..."
    if python3 -m pip install --user "git+https://github.com/nebius/nebius-physical-ai"; then
        ok "npa installed via pip --user (ensure ~/.local/bin is on PATH)"
    else
        warn "pip install failed — clone the repo and install manually:"
        manual "git clone https://github.com/nebius/nebius-physical-ai && pip install -e nebius-physical-ai"
    fi
else
    warn "no pip/pipx found — cannot install npa automatically"
    manual "git clone https://github.com/nebius/nebius-physical-ai && pip install -e nebius-physical-ai"
fi

if command -v npa >/dev/null 2>&1; then
    if [ -f "$HOME/.npa/credentials" ]; then
        ok "npa credentials present (~/.npa/credentials)"
    else
        warn "npa not configured yet"
        manual "npa configure        # interactive: IAM token + project (docs/SETUP.md step 4)"
    fi
fi

# --------------------------------------------------------------------------
# 2. ngc — NVIDIA NGC CLI
# --------------------------------------------------------------------------
echo "[2] ngc (NVIDIA NGC CLI)"
if command -v ngc >/dev/null 2>&1; then
    ok "ngc already installed: $(command -v ngc)"
else
    warn "ngc CLI not found — no pip package; manual install required:"
    manual "Download 'NGC CLI' zip for your OS: https://org.ngc.nvidia.com/setup/installers"
    manual "unzip, put 'ngc' on PATH, then: ngc config set   # paste NGC_API_KEY"
fi

# --------------------------------------------------------------------------
# 3. Hugging Face CLI
# --------------------------------------------------------------------------
echo "[3] Hugging Face CLI"
if command -v hf >/dev/null 2>&1 || command -v huggingface-cli >/dev/null 2>&1; then
    ok "HF CLI present: $(command -v hf 2>/dev/null || command -v huggingface-cli)"
elif python3 -m pip --version >/dev/null 2>&1; then
    info "installing huggingface_hub via pip (user site) ..."
    if python3 -m pip install --user "huggingface_hub"; then
        ok "HF CLI installed (ensure ~/.local/bin is on PATH)"
    else
        warn "install failed — try: python3 -m pip install huggingface_hub"
    fi
else
    warn "no pip — install manually: python3 -m pip install huggingface_hub"
fi

# --------------------------------------------------------------------------
# 4. Tailscale (remote rig access)
# --------------------------------------------------------------------------
echo "[4] tailscale (remote rig access)"
if command -v tailscale >/dev/null 2>&1; then
    ok "tailscale installed: $(command -v tailscale)"
else
    warn "tailscale not installed (only needed on the rig host + operator laptops)"
    manual "brew install tailscale   # macOS    |   https://tailscale.com/download for others"
fi

# --------------------------------------------------------------------------
# 5. Python deps (light core only — heavy ML deps are requirements-ml.txt,
#    installed later on the GPU workbench, not on laptops)
# --------------------------------------------------------------------------
echo "[5] Python core deps"
if python3 -m pip --version >/dev/null 2>&1; then
    info "installing requirements.txt (light core) ..."
    python3 -m pip install --user -r requirements.txt \
        && ok "core deps installed" \
        || warn "pip install failed — try inside a venv: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
else
    warn "pip unavailable — skipping requirements.txt"
fi

# --------------------------------------------------------------------------
# MANUAL STEPS — interactive credentials, cannot be scripted
# --------------------------------------------------------------------------
hr
echo "MANUAL STEPS (interactive — see docs/SETUP.md for full detail):"
hr
cat <<'EOF'
  1. cp .env.example .env          # then fill in every var per docs/SETUP.md
  2. npa configure                 # Nebius IAM token + project → ~/.npa/credentials
  3. huggingface-cli login         # or: hf auth login  — paste HF_TOKEN
                                     #   (must have accepted GR00T-N1.7-3B,
                                     #    Cosmos-Reason2-2B, Cosmos3-Super gates)
  4. docker login nvcr.io          # username: $oauthtoken  password: NGC_API_KEY
  5. tailscale up                  # on the rig host; or:
                                     #   tailscale up --authkey="$TAILSCALE_AUTHKEY"
  6. python3 scripts/check_credentials.py   # verify everything is green
EOF
hr
echo "setup.sh done. Re-run any time — it is idempotent."
