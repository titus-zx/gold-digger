# Gold Digger — XAUUSD Intraday Forecasting

Research-only Python pipeline for 1, 4, 8 and 24-hour XAUUSD directional forecasts (BEARISH / NEUTRAL / BULLISH), with probabilities, rule-based baseline, logistic regression, gradient boosting, chronological train/validation/test, calibration, and CSV reports.

## Run
```bash
pip install -r requirements.txt
python forecaster.py --xau data/xau_h1.csv --out results
```

CSV columns: `time,open,high,low,close`. Timestamps **must be UTC candle-close timestamps**, sorted hourly; do not fabricate missing market-close bars. Optional `--dxy data/dxy_h1.csv`.

Predictions use only completed candles. Models train on the first 60%, calibrate/select on the next 20%, and report on the last 20%. Results are **not** verified trading performance. Prices, spreads, slippage, news and data-provider differences can materially change results. Never use this tool as the sole basis for financial decisions.
