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
docker compose run --rm --no-deps -v "$PWD/results:/app/results" gold-digger python forecaster.py --xau /app/data/xau_h1.csv --out /app/results/gold
```

Save input CSV at `./data/xau_h1.csv`. The report is shown at `/gold` and JSON at `/api/gold`. Models are research-only; do not treat forecasts as guaranteed or real-time. Public access: the app has **no authentication**. Protect it with Cloudflare Access or another identity-aware proxy before exposing the hostname publicly.
