# Data ingestion and XAUUSD dashboard

## IDX
A background `idx-sync` service refreshes 2 years of **unofficial Yahoo Finance** daily OHLCV for BMRI.JK, BBCA.JK, BBRI.JK, BBNI.JK and TLKM.JK every six hours. Network access is required. Data may be delayed, inaccurate, adjusted, incomplete, rate-limited or unavailable; check exchange timestamps and validate before any investment decision. This is not an official IDX market feed. On failed sync, the previous CSV is preserved. Logs: `docker compose logs -f idx-sync`. Data stored in `./data/idx_daily.csv`.

## XAUUSD
The existing `forecaster.py` trains a multi-horizon 1/4/8/24h classifier on **real UTC hourly candles**, and writes `report.json` and `predictions_*h.csv`. The new dashboard **reads** that report; it does not invent a live forecast or train automatically. Example (on host with Python dependencies installed):

```bash
python forecaster.py --xau data/xau_h1.csv --out results/gold
```

CSV columns: `time,open,high,low,close`. Use candle-close timestamps in UTC. To run inside Docker without installing Python locally:

```bash
mkdir -p results/gold
docker compose run --rm --no-deps --user "$(id -u):$(id -g)" gold-digger python forecaster.py --xau /app/data/xau_h1.csv --out /app/results/gold
```

Save input CSV at `./data/xau_h1.csv`. The report is shown at `/gold` and JSON at `/api/gold`. Models are research-only; do not treat forecasts as guaranteed or real-time. Public access: the app has **no authentication**. Protect it with Cloudflare Access or another identity-aware proxy before exposing the hostname publicly.

## Secure public hostname using Cloudflare Access

In Cloudflare Zero Trust, navigate to **Access → Applications → Add an application → Self-hosted**, set the hostname to `gold.mastitus.my.id`, and create an **Allow** policy restricted to your own verified identity (email/IdP). Configure a login method and test in an incognito window. Ensure **all paths**, including `/api/status`, `/api/gold`, and `/health`, require authentication. Do not add a public Bypass policy. A Cloudflare proxy DNS record alone does **not** provide authentication. If a tunnel is used, keep the origin private. This Cloudflare configuration must be performed in your account; it cannot be applied by repository changes alone.

## Deployment checks

```bash
git pull --ff-only origin main
docker compose up -d --build
docker compose ps
docker compose logs --tail=50 idx-sync
curl -i http://127.0.0.1:8080/health
curl -s http://127.0.0.1:8080/api/status
curl -s http://127.0.0.1:8080/api/gold
```

The `idx-sync` service refreshes on startup, then every six hours. The XAUUSD dashboard is not automatically trained: supply real hourly XAUUSD candles and rerun `forecaster.py` as required. Never publish trading signals without reviewing their data timestamp and model test metrics.
