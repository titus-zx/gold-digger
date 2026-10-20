# IDX Investment Monitor (research / paper trading)

Capital default: IDR 50,000,000. Intended investment horizon: less than one year. Watchlist: BMRI, BBCA, BBRI, BBNI, TLKM. Sector concentration is high; allocations are hypothetical ceilings, not advice.

## Run

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m idx_monitor.cli --prices data/idx_daily.csv --capital 50000000 --out results/idx
```

Input CSV: `date,ticker,open,high,low,close,volume` (one completed daily candle per ticker/date, IDR/share, raw non-adjusted prices). Do not use incomplete daily bars. Output: latest_signals.csv and paper_report.json.

## Execution assumptions

Signals use completed day D, executed at next available day's OPEN (D+1). Long-only; 100-share lots; default fees 0.15% buy and 0.25% sell; no leverage. A BUY_CANDIDATE requires close above EMA20 above EMA50, RSI14 between 45 and 70, and volume at least 80% of its 20-day average. RISK_OFF requires close below EMA50 and RSI14 below 40. Signals are technical-only, not verified fundamental valuation or news analysis. No trade is executed if the signal is WATCH.

## Important limitations

Historical backtest is illustrative, not predictive. No live provider, corporate action adjustment, dividends, tax modeling, market suspension/limit-up/limit-down simulation, spread, liquidity, foreign-flow, valuation, MSCI/news ingestion, or guaranteed execution. A next-open fill may be impossible on an illiquid/limit-locked day. Missing dates/tickers can distort mark-to-market; supply complete consistent histories. For reliable performance evaluation add adjusted-data corporate action handling, walk-forward validation, benchmark comparison, drawdown and stress tests before using with real money. No brokerage integration or real orders.
