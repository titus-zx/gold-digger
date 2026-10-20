# Gold Digger on generic Linux (systemd + Docker)

This is a read-only Web UI bound to localhost. Background services fetch IDX daily data and XAUUSD hourly data (see [DATA_AND_GOLD.md](DATA_AND_GOLD.md)). Paper trades are simulations from completed daily OHLCV CSV candles, not live orders.

## Prerequisites

- Linux with systemd, Git, curl, flock (util-linux), Docker Engine and Docker Compose v2 plugin
- A dedicated non-root account allowed to run Docker (Docker group is effectively root access; only grant to a trusted account)
- Outbound HTTPS access to GitHub, Docker Hub, Python package indexes, Yahoo Finance and Dukascopy; no inbound router port needed
- Docker daemon enabled at boot: `sudo systemctl enable --now docker`


## Install

```bash
git clone https://github.com/titus-zx/gold-digger.git
cd gold-digger
mkdir -p data results/gold
docker compose config --quiet
docker compose up -d --build
docker compose ps
curl -fsS http://127.0.0.1:8080/health
```

Dashboard on server: http://127.0.0.1:8080. The server binds **only to loopback**; do not expose port 8080 via router/firewall or change bind to 0.0.0.0 without authentication.

## Access from another computer

Preferred: SSH tunnel from laptop (requires reachable SSH over trusted LAN or VPN):
```bash
ssh -N -L 8080:127.0.0.1:8080 USER@HOME_SERVER_IP
```
Then open http://127.0.0.1:8080 on the laptop. For access outside home, install Tailscale on both devices, authenticate them to the same tailnet, and use the server's Tailscale address as the SSH target. Restrict SSH with keys and Tailscale ACLs. Never expose Docker TCP socket publicly.

## Auto-deploy on every main push

The local systemd timer checks GitHub 10 seconds after the previous updater run finishes (`OnUnitInactiveSec=10s`, `AccuracySec=1s`). It fast-forwards the checkout, builds the image locally, starts the services and checks `/health`. With no new commit and all services running, it skips the build. GitHub Actions image publication is not required; the updater does not gate deployment on CI results or automatically roll back.

```bash
chmod +x deploy/install-systemd.sh
./deploy/install-systemd.sh
sudo systemctl start gold-digger-update.service
systemctl list-timers gold-digger-update.timer
sudo journalctl -u gold-digger-update.service -n 100 --no-pager
```

Disable old cron updater before installing the timer to avoid duplicate updates: `crontab -e` and remove the earlier gold-digger home-update entry. Do not put secrets or mutable local configuration into tracked files. If Git has local tracked changes, auto-update intentionally fails instead of overwriting them. The updater needs a trusted checkout and Docker access.

**Timing:** the machine must be online. Fetch and build time are additional to the interval, so deployment is not guaranteed to complete within 10 seconds. Runs do not overlap. Rerun `./deploy/install-systemd.sh` after pulling this change to replace and restart an existing five-minute timer. Verify the effective settings with:

```bash
systemctl cat gold-digger-update.timer
systemctl show gold-digger-update.timer -p TimersMonotonic -p AccuracyUSec
```

## Troubleshooting

```bash
docker compose ps
docker compose logs --tail=100 gold-digger
docker compose config
curl -v http://127.0.0.1:8080/health
sudo systemctl status gold-digger-update.timer
sudo journalctl -u gold-digger-update.service -n 100 --no-pager
docker info
```

- `permission denied /var/run/docker.sock`: use a trusted Docker-capable account; re-login after changing group membership.
- `address already in use`: change host port in compose.yaml and corresponding updater health URL.
- Web UI says `awaiting_data`: inspect `docker compose logs idx-sync`. For XAUUSD, inspect `docker compose logs gold-sync`.
- Container unhealthy: check `docker compose logs`, input format, memory, and port.
- SSH tunnel fails: confirm sshd, key authentication, VPN/LAN reachability and local port availability.
- Non-systemd distro: run `deploy/home-update.sh` from a trusted user cron/system scheduler, avoiding overlapping jobs (script uses flock).

## Limits

Paper trading ignores dividends, corporate actions, trading halts, limit moves, slippage and market liquidity. Never treat historical results as guaranteed returns. Existing XAUUSD CLI is unchanged. The dashboard has no login; keep it private.
