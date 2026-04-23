#!/usr/bin/env bash
# Cron fallback: rotate all due keys if the systemd service is NOT running.
# Add to crontab (crontab -e):
#   0 * * * * /home/z/Projects/key-rotator/scripts/cron-fallback.sh >> /tmp/key-rotator-cron.log 2>&1

set -euo pipefail

SERVICE="key-rotator.service"
ROTATOR="$HOME/.local/bin/key-rotator"

if systemctl --user is-active --quiet "$SERVICE"; then
    echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') [SKIP] $SERVICE is running — scheduler handles rotation"
    exit 0
fi

echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') [FALLBACK] $SERVICE not running — running key-rotator rotate"
"$ROTATOR" rotate
