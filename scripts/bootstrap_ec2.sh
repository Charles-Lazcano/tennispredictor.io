#!/usr/bin/env bash
# One-time setup for a fresh EC2 checkout - run this once after `git clone`,
# before starting the site or the cron jobs. Safe to re-run (idempotent).
#
# Usage: bash scripts/bootstrap_ec2.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "[1/5] Finding a Python interpreter >=3.10 (numpy 2.x / scikit-learn 1.7 need it -" \
     "Amazon Linux 2023's default python3 is 3.9, too old)..."
PYBIN=""
for cand in python3.12 python3.11 python3.10; do
    if command -v "$cand" >/dev/null 2>&1; then
        PYBIN="$cand"
        break
    fi
done
if [ -z "$PYBIN" ]; then
    echo "  None found - installing python3.11 via dnf (Amazon Linux 2023)..."
    sudo dnf install -y python3.11 >/dev/null
    PYBIN=python3.11
fi
echo "  Using $PYBIN ($("$PYBIN" --version))"

echo "Creating/updating the virtualenv..."
"$PYBIN" -m venv .venv
source .venv/bin/activate
pip install --upgrade pip >/dev/null
pip install -r requirements.txt

echo "[2/5] Checking for .env..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "  [!] Created .env from .env.example - edit it and set RAPIDAPI_KEY before" \
         "the morning scan runs (true_forward predictions will be skipped without it)."
else
    echo "  .env already exists - leaving it alone."
fi

echo "[3/5] Checking git identity (needed for the daily pipeline's local commits)..."
if [ -z "$(git config user.email || true)" ]; then
    git config user.email "tennis-predictor@localhost"
    git config user.name "tennis-predictor-bot"
    echo "  [!] No git identity was configured - set a local placeholder. Override with" \
         "'git config user.name/user.email' if you want real attribution on this box."
else
    echo "  git identity already configured: $(git config user.name) <$(git config user.email)>"
fi

echo "[4/6] Reconstructing data/master/matches_master.csv..."
# Gitignored (it's just primary+secondary concatenated back together, regenerated
# daily by daily_scan.py itself) - but daily_scan.py's *first* run needs it to
# already exist as its "existing data" baseline to diff new fetches against, and
# there's no dedicated pipeline command that builds it from scratch. Reconstruct
# it here from the two tracked halves rather than leaving that gap for daily_scan
# to hit as a FileNotFoundError on its very first run on a fresh checkout.
if [ -f data/master/matches_master.csv ]; then
    echo "  Already present - skipping (delete it and re-run this script to force a rebuild)."
else
    python - <<'PY'
import pandas as pd
primary = pd.read_csv("data/master/matches_primary_atp250plus.csv", low_memory=False)
secondary = pd.read_csv("data/master/matches_secondary_other.csv", low_memory=False)
master = pd.concat([primary, secondary], ignore_index=True)
master.to_csv("data/master/matches_master.csv", index=False)
print(f"[OK] Reconstructed matches_master.csv: {len(master):,} rows")
PY
fi

echo "[5/6] Rebuilding data/master/matches_with_features.csv..."
# This file is gitignored (regenerable, 76MB+, would bloat history) - app.py needs
# it to start at all. Rebuilt here from the tracked matches_primary_atp250plus.csv.
if [ -f data/master/matches_with_features.csv ]; then
    echo "  Already present - skipping (delete it and re-run this script to force a rebuild)."
else
    python -m pipeline.elo
fi

echo "[6/6] Sanity-checking that app.py's and daily_scan.py's data dependencies are all present..."
python - <<'PY'
from pathlib import Path
required = [
    "data/master/matches_master.csv",
    "data/master/matches_with_features.csv",
    "data/canonical/canonical_players.csv",
    "model_logreg.joblib",
    "feature_columns_gb.csv",
]
missing = [p for p in required if not Path(p).exists()]
if missing:
    raise SystemExit(f"[FAIL] Still missing: {missing}")
print("[OK] All required files present.")
PY

echo
echo "Bootstrap complete. Next steps:"
echo "  - Edit .env and set RAPIDAPI_KEY (if not already set)."
echo "  - Install the daily cron jobs:  bash scripts/install_cron.sh"
echo "  - Start the site:               bash scripts/start_site.sh"
