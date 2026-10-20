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
docker compose up -d --build
curl -fsS http://127.0.0.1:8080/health
```

The dashboard is bound to localhost at http://127.0.0.1:8080. It works without market data but shows awaiting_data until you provide `data/idx_daily.csv` with `date,ticker,open,high,low,close,volume`.

Docker Compose builds the application image locally from the repository Dockerfile; no GHCR login is needed. Docker still downloads the Python base image and Python packages. The local build uses the host architecture.

## Auto-deploy after push

```bash
chmod +x deploy/install-systemd.sh
./deploy/install-systemd.sh
sudo systemctl start gold-digger-update.service
systemctl list-timers gold-digger-update.timer
sudo journalctl -u gold-digger-update.service -n 100 --no-pager
```

The systemd timer checks GitHub for new commits 10 seconds after the previous check finishes, builds the image locally, and restarts the container. GitHub Actions publication is not required. No incoming firewall ports needed. Disable the older cron updater if previously installed. After pulling an installer update, rerun `./deploy/install-systemd.sh` to apply the timer interval to the host. Builds take additional time; the interval does not guarantee deployment completes within 10 seconds.

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

See [HOME_DEPLOY.md](HOME_DEPLOY.md) for detailed deployment instructions and limits. Paper trading uses historical CSV and does not place real orders.
