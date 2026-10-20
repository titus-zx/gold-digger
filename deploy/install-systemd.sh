#!/usr/bin/env bash
set -euo pipefail
command -v systemctl >/dev/null || { echo "systemd is required"; exit 1; }
command -v docker >/dev/null || { echo "Docker Engine is required"; exit 1; }
docker compose version >/dev/null || { echo "Docker Compose plugin is required"; exit 1; }
command -v flock >/dev/null || { echo "flock (util-linux) is required"; exit 1; }
[[ "$(id -u)" -ne 0 ]] || { echo "Run as regular Docker-capable user, not root"; exit 1; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="$(id -un)"
UNIT="gold-digger-update"
sudo tee "/etc/systemd/system/$UNIT.service" >/dev/null <<EOF
[Unit]
Description=Gold Digger secure home updater
Wants=network-online.target
After=network-online.target docker.service
[Service]
Type=oneshot
User=$USER_NAME
WorkingDirectory=$ROOT
Environment=GOLD_DIGGER_HOME=$ROOT
ExecStart=/bin/bash $ROOT/deploy/home-update.sh
TimeoutStartSec=300
EOF
sudo tee "/etc/systemd/system/$UNIT.timer" >/dev/null <<EOF
[Unit]
Description=Check Gold Digger deployment every 5 minutes
[Timer]
OnBootSec=2min
OnUnitInactiveSec=5min
Persistent=true
Unit=$UNIT.service
[Install]
WantedBy=timers.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now "$UNIT.timer"
echo "Installed. Check: systemctl list-timers $UNIT.timer"
