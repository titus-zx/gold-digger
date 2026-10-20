#!/usr/bin/env bash
set -euo pipefail
cd "${GOLD_DIGGER_HOME:-$HOME/gold-digger}"
# Run this periodically via systemd timer or cron. No inbound access required.
docker compose pull gold-digger
docker compose up -d --no-deps gold-digger
docker image prune -f --filter "until=168h"
