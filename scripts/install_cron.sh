#!/usr/bin/env bash
# Installs the two daily scan jobs into this user's crontab - the Linux
# equivalent of TennisPredictorMorningScan / TennisPredictorEveningScan
# (Windows Task Scheduler). Idempotent: safe to re-run, won't duplicate entries.
#
# Usage: bash scripts/install_cron.sh
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MARKER="# tennis-predictor-app daily scan"

MORNING="0 1 * * * cd $APP_DIR && $APP_DIR/.venv/bin/python -m pipeline.daily_scan --fixture-offset-days 0 >> $APP_DIR/logs/morning_scan_stdout.log 2>&1 $MARKER-morning"
EVENING="59 23 * * * cd $APP_DIR && $APP_DIR/.venv/bin/python -m pipeline.daily_scan --skip-predictions >> $APP_DIR/logs/evening_scan_stdout.log 2>&1 $MARKER-evening"

mkdir -p "$APP_DIR/logs"

existing="$(crontab -l 2>/dev/null || true)"
new="$existing"

if ! grep -qF "$MARKER-morning" <<<"$existing"; then
    new="$new"$'\n'"$MORNING"
    echo "[+] Adding 1:00 AM morning scan (true_forward predictions)"
else
    echo "[=] Morning scan already installed - leaving as-is"
fi

if ! grep -qF "$MARKER-evening" <<<"$existing"; then
    new="$new"$'\n'"$EVENING"
    echo "[+] Adding 11:59 PM evening scan (reconciliation only)"
else
    echo "[=] Evening scan already installed - leaving as-is"
fi

printf '%s\n' "$new" | crontab -
echo "[OK] crontab updated. View with: crontab -l"
