# Omarchy (Arch Linux) installation

Omarchy uses pacman and systemd. Gold Digger requires Docker Engine and Docker Compose v2.

## Install prerequisites

```bash
sudo pacman -Syu
sudo pacman -S --needed docker docker-compose git curl util-linux
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
```

Log out and back in before running Docker as your user. Docker group grants root-equivalent privileges. Verify:

```bash
docker info
docker compose version
uname -m
```

## Install Gold Digger

```bash
git clone https://github.com/titus-zx/gold-digger.git
cd gold-digger
mkdir -p data
docker compose pull
docker compose up -d
curl -fsS http://127.0.0.1:8080/health
```

The dashboard is bound to localhost at http://127.0.0.1:8080. It works without market data but shows awaiting_data until you provide `data/idx_daily.csv` with `date,ticker,open,high,low,close,volume`.

If GHCR denies pulling, make the package public or login with a scoped read:packages token using `docker login ghcr.io`. Check GitHub Actions to ensure the image was published. For ARM64, ensure a compatible GHCR image exists; the current GitHub build runs on amd64 and is not configured as a multi-arch build.

## Auto-deploy after push

```bash
chmod +x deploy/install-systemd.sh
./deploy/install-systemd.sh
sudo systemctl start gold-digger-update.service
systemctl list-timers gold-digger-update.timer
sudo journalctl -u gold-digger-update.service -n 100 --no-pager
```

The systemd timer checks for new commits/images every 5 minutes after GitHub Actions publishes them. No incoming firewall ports needed. Disable the older cron updater if previously installed.

## Secure access

For remote access use SSH over a trusted LAN or Tailscale VPN:

```bash
ssh -N -L 8080:127.0.0.1:8080 USER@TAILSCALE_OR_LAN_IP
```

Open http://127.0.0.1:8080 on the client. Never expose this unauthenticated dashboard directly to the internet.

## Troubleshooting

```bash
systemctl status docker
docker compose ps
docker compose logs --tail=100
curl -v http://127.0.0.1:8080/health
sudo journalctl -u gold-digger-update.service -n 100 --no-pager
```

See [HOME_DEPLOY.md](HOME_DEPLOY.md) for detailed limits, image access and rollback behavior. Paper trading uses historical CSV and does not place real orders.
