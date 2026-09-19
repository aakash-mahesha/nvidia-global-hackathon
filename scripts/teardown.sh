#!/usr/bin/env bash
# ============================================================================
# teardown.sh — HARD RULE from the execution plan:
#   "preemptible VMs only, npa cleanup / npa destroy after every session"
#
# Runs npa cleanup then npa destroy IN FULL ORDER. If npa is not installed
# or not configured, this script warns LOUDLY (it does not silently pass —
# GPU resources may still be running and billing from another machine).
#
# Usage:  bash scripts/teardown.sh            # cleanup + destroy
#         bash scripts/teardown.sh --check    # report only, change nothing
# ============================================================================
set -uo pipefail

loud() {
    printf '\n%s\n%s\n%s\n\n' \
        '!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!' \
        "$1" \
        '!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!'
}

CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

# --- npa must exist ---------------------------------------------------------
if ! command -v npa >/dev/null 2>&1; then
    loud "npa CLI NOT FOUND — cannot verify or clean up Nebius resources.
If any session ran on Nebius from another machine, resources may still be
billing RIGHT NOW. Check the Nebius console and/or run scripts/setup.sh,
then re-run this script."
    exit 1
fi

# --- npa must be configured -------------------------------------------------
if [ ! -f "$HOME/.npa/credentials" ]; then
    loud "npa is installed but NOT CONFIGURED (~/.npa/credentials missing).
Cannot verify whether Nebius resources are running. Run 'npa configure'
(docs/SETUP.md step 4) or check the Nebius console manually. Exiting
without action — resources created elsewhere may still be billing."
    exit 1
fi

if [ "$CHECK_ONLY" -eq 1 ]; then
    echo "npa configured — would run: npa cleanup && npa destroy"
    exit 0
fi

echo "=================================================================="
echo " TEARDOWN — cleaning up ALL Nebius session resources"
echo " (preemptible VMs only; nothing here is meant to persist)"
echo "=================================================================="

rc=0

echo ">>> npa cleanup"
if npa cleanup; then
    echo "    npa cleanup: done"
else
    rc=1
    loud "npa cleanup FAILED — resources may still be running.
Investigate before assuming the session is clean."
fi

echo ">>> npa destroy"
if npa destroy; then
    echo "    npa destroy: done"
else
    rc=1
    loud "npa destroy FAILED — cluster resources may still be running.
Check the Nebius console and destroy manually if needed."
fi

if [ "$rc" -eq 0 ]; then
    echo "=================================================================="
    echo " Teardown complete: npa cleanup + npa destroy ran in full order."
    echo "=================================================================="
fi

exit "$rc"
