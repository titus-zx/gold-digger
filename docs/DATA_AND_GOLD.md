# Data ingestion and XAUUSD dashboard

## IDX
A background `idx-sync` service refreshes up to 500 bars of **unofficial free TradingView** daily OHLCV for IDX:BMRI, IDX:BBCA, IDX:BBRI, IDX:BBNI and IDX:TLKM every six hours. Network access is required. IDX access is delayed (observed 10 minutes). Only completed sessions are imported, requesting adjustment `none`. Data may be inaccurate, incomplete, rate-limited or unavailable; check exchange timestamps and validate before any investment decision. This is not an official IDX market feed. On failed sync, the previous CSV is preserved. Logs: `docker compose logs -f idx-sync`. Data stored in `./data/idx_daily.csv`.

## XAUUSD
The `gold-sync` service downloads up to 5,000 **unofficial free TradingView OANDA:XAUUSD H1 candles**, trains the existing 1/4/8/24-hour classifiers on startup, and repeats every hour. It uses XAUUSD, not gold futures. No API key is needed. The provider may delay or stop serving archives; no availability guarantee is assumed.

No TradingView login, paid plan, or official MCP connection is used. The application uses an unofficial chart WebSocket transport based on the public community protocol. Availability is best-effort and is not a supported API guarantee. It does not bypass account entitlements. A failed refresh preserves the previous dataset/report, without silently mixing providers. Gold records the full feed symbol and quote type; switching providers retrains the model on that feed.

Set `IDX_PROVIDER=yahoo` or `GOLD_PROVIDER=dukascopy` in `.env` to explicitly select a previous source, then run `docker compose up -d` to recreate the affected services. Dukascopy uses HTTPS JSON H1 data and caches completed months in `data/gold-cache`. Both schedulers retry failures after approximately 60 seconds; successful updates use six hours for IDX and one hour for Gold.

TradingView candle timestamps are candle opens; ingestion converts them to UTC close timestamps and excludes unfinished candles. It validates OHLC ranges, timestamp alignment, duplicate timestamps, at least 1,600 observations, and a latest candle no older than four days (allowing weekends). Zero-volume placeholders are excluded; missing bars are not fabricated. Forecast labels match the exact future UTC timestamp, allowing the 24-hour horizon to cross the daily session break. Training must produce all four horizons before publication. A download or training failure preserves the last successful CSV and forecast report. The dashboard reads `report.json`, published with an atomic file replacement, and shows the source, candle timestamp, and training timestamp. Data older than six hours is marked `stale`, including during market closures.

```bash
mkdir -p data results/gold
docker compose up -d --build
docker compose logs --tail=50 gold-sync
curl -s http://127.0.0.1:8080/api/gold
```

Set `LOCAL_UID` and `LOCAL_GID` in `.env` to the owner of the data/results directories if they differ from 1000. The updater repairs a root-owned `results` mount created by Docker before starting the writer. For a manual deployment with an existing root-owned directory, run `docker compose run --rm --no-deps --user 0:0 gold-sync chown "$(id -u):$(id -g)" /app/results` before creating `results/gold`. The first training run takes longer than a web health check. To run once on the host:

```bash
GOLD_DATA=data/xau_h1.csv GOLD_RESULTS=results/gold python -m idx_monitor.gold_sync --once
```

`GOLD_SYNC_SECONDS` controls the service interval (minimum 3,600 seconds); default 3,600. Forecasts appear at `/gold` and `/api/gold`. Research-only probabilities and historical test accuracy are not verified trading returns. OANDA chart quotes are provider-specific; they are not asserted to be executable bid/ask prices. Spread and costs are excluded.

Manual CSV training remains available:

```bash
python forecaster.py --xau data/xau_h1.csv --out results/gold
```

CSV columns: `time,open,high,low,close`, with UTC candle-close timestamps.

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

The `idx-sync` service refreshes on startup, then every six hours. The `gold-sync` service refreshes and retrains XAUUSD automatically; inspect its logs and `/api/gold` separately from the web health check. Never publish trading signals without reviewing their data timestamp and model test metrics.

## Published predictions and outcomes

See [PREDICTION_HISTORY.md](PREDICTION_HISTORY.md) for persistent live prediction records, actual-outcome evaluation, Gold model feedback and history APIs.
