# Home Docker deployment

## Requirements
Linux machine with Docker Engine and Docker Compose plugin, outbound HTTPS to GitHub/GHCR. Repository's GHCR package must be public, or run `echo "$GHCR_TOKEN" | docker login ghcr.io -u YOUR_GITHUB_USER --password-stdin` with a read:packages token. Do not put tokens in Compose or commit them.

## First installation

```bash
git clone https://github.com/titus-zx/gold-digger.git
cd gold-digger
mkdir -p data
# Add completed daily OHLCV data to data/idx_daily.csv
docker compose pull
docker compose up -d
curl http://127.0.0.1:8080/health
```

Browse `http://localhost:8080` on the home machine. By default the service is bound to loopback only; for access from another device use an SSH tunnel (`ssh -L 8080:localhost:8080 user@home-server`) or Tailscale Serve with access controls. Do not expose this unauthenticated dashboard to the public internet.

## Auto-deploy on GitHub push

The GitHub Actions workflow tests and publishes `ghcr.io/titus-zx/gold-digger:main` after every push to main. On the home server, run the following once from the repository directory:

```bash
chmod +x deploy/home-update.sh
(crontab -l 2>/dev/null; echo "*/5 * * * * GOLD_DIGGER_HOME=$PWD /bin/bash $PWD/deploy/home-update.sh >> $PWD/deploy.log 2>&1") | crontab -
```

This polls GHCR every five minutes; actual update occurs after GitHub Actions finishes building. This is near-automatic, not instant. If the repo's Compose file changes, update it separately using `git pull --ff-only`; the image updater only refreshes the container image. For safer production use, pin digest releases and promote after tests, not a mutable main tag.

## Data and limitations

The UI is read-only and uses a mounted CSV. Columns: `date,ticker,open,high,low,close,volume`. Provide a reliable adjusted-for-corporate-actions historical feed before interpreting paper P&L. CSV updates show on page refresh. No market data acquisition is bundled. No real brokerage orders. Paper trading assumes next-session open execution and ignores suspensions, price limits, dividends and slippage. Existing XAUUSD script is unchanged.
