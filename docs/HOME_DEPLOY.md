# Gold Digger on generic Linux (systemd + Docker)

This is a read-only, local-only Web UI. It **does not fetch IDX market data**. Paper trades are simulations from completed daily OHLCV CSV candles, not live orders.

## Prerequisites

- Linux with systemd, Git, curl, flock (util-linux), Docker Engine and Docker Compose v2 plugin
- A dedicated non-root account allowed to run Docker (Docker group is effectively root access; only grant to a trusted account)
- Outbound HTTPS access to github.com and ghcr.io; no inbound router port needed
- Docker daemon enabled at boot: `sudo systemctl enable --now docker`
- GHCR image access: make the package public or `echo "$GHCR_TOKEN" | docker login ghcr.io -u YOUR_USER --password-stdin` with a **read:packages** token. Never commit secrets.

## Install

```bash
git clone https://github.com/titus-zx/gold-digger.git
cd gold-digger
mkdir -p data
# Put real completed IDX daily candles in data/idx_daily.csv
# CSV header: date,ticker,open,high,low,close,volume
docker compose config --quiet
docker compose pull
docker compose up -d
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

GitHub Actions tests and publishes `ghcr.io/titus-zx/gold-digger:main`. The local timer checks every five minutes (after image publication), fast-forwards the tracked checkout, validates Compose, pulls the new image and restarts the service only if the image changed. It checks /health and attempts rollback to the previous image on failure.

```bash
chmod +x deploy/install-systemd.sh
./deploy/install-systemd.sh
sudo systemctl start gold-digger-update.service
systemctl list-timers gold-digger-update.timer
sudo journalctl -u gold-digger-update.service -n 100 --no-pager
```

Disable old cron updater before installing the timer to avoid duplicate updates: `crontab -e` and remove the earlier gold-digger home-update entry. Do not put secrets or mutable local configuration into tracked files. If Git has local tracked changes, auto-update intentionally fails instead of overwriting them. The updater needs a trusted checkout and Docker access.

**Timing:** this is pull-based deployment with a maximum ~5 minute polling delay *after* the GitHub image build. The machine must be online. A GitHub workflow failure prevents new image publication.

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
- `unauthorized` pulling GHCR: verify package visibility or login with a read:packages token.
- `manifest unknown`: wait for GitHub Actions build to complete.
- `address already in use`: change host port in compose.yaml and corresponding updater health URL.
- Web UI says `awaiting_data`: supply `data/idx_daily.csv`; no market data provider is included.
- Container unhealthy: check `docker compose logs`, input format, memory, and port.
- SSH tunnel fails: confirm sshd, key authentication, VPN/LAN reachability and local port availability.
- Non-systemd distro: run `deploy/home-update.sh` from a trusted user cron/system scheduler, avoiding overlapping jobs (script uses flock).

## Limits

Paper trading ignores dividends, corporate actions, trading halts, limit moves, slippage and market liquidity. Never treat historical results as guaranteed returns. Existing XAUUSD CLI is unchanged. The dashboard has no login; keep it private.
