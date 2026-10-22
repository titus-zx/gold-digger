"""Best-effort daily IDX import: free TradingView by default, optional Yahoo."""
import argparse
import os
import logging
from pathlib import Path
import pandas as pd

TICKERS = ("BMRI", "BBCA", "BBRI", "BBNI", "TLKM")
def normalize_download(frame, ticker):
    if frame is None or frame.empty:
        raise ValueError(f"No data for {ticker}")
    d = frame.copy()
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(0)
    d = d.rename(columns=str.lower)
    needed = ("open", "high", "low", "close", "volume")
    if any(c not in d.columns for c in needed):
        raise ValueError(f"Missing OHLCV for {ticker}")
    d = d.reset_index()
    d.columns = d.columns.str.lower()
    date_col = "date" if "date" in d.columns else "datetime"
    if date_col not in d.columns:
        raise ValueError("Missing date")
    d["date"] = pd.to_datetime(d[date_col]).dt.strftime("%Y-%m-%d")
    d["ticker"] = ticker
    d = d[["date", "ticker", *needed]].dropna()
    d = d[(d[["open","high","low","close"]] > 0).all(axis=1) & (d.volume >= 0)]
    valid = (d["high"] >= d[["open", "close", "low"]].max(axis=1) - 1e-6) & (d["low"] <= d[["open", "close"]].min(axis=1) + 1e-6)
    rejected = int((~valid).sum())
    if rejected:
        logging.warning("%s: discarded %d invalid OHLC rows", ticker, rejected)
    d = d.loc[valid].copy()
    if len(d) < 60:
        raise ValueError(f"Insufficient valid rows for {ticker}: {len(d)}")
    return d

def sync(destination, period="2y", provider=None):
    provider = provider or os.environ.get("IDX_PROVIDER", "tradingview")
    if provider not in ("tradingview", "yahoo"):
        raise ValueError("IDX_PROVIDER must be tradingview or yahoo")
    frames = []
    for ticker in TICKERS:
        if provider == "tradingview":
            from .tradingview import get_bars, completed_idx, SOURCE
            data = completed_idx(get_bars(f"IDX:{ticker}", "1D", 500))
            source, feed = SOURCE, f"IDX:{ticker}"
        else:
            import yfinance as yf
            data = yf.download(f"{ticker}.JK", period=period, interval="1d",
                               auto_adjust=False, progress=False, threads=False)
            source, feed = "Yahoo Finance unofficial", f"{ticker}.JK"
        normalized = normalize_download(data, ticker)
        normalized["source"], normalized["feed"] = source, feed
        frames.append(normalized)
    result = pd.concat(frames, ignore_index=True).sort_values(["ticker","date"])
    result = result.drop_duplicates(["ticker","date"], keep="last")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(".tmp")
    result.to_csv(tmp, index=False)
    from .history import record_idx
    record_idx(destination.parent / 'idx_history.sqlite', result, pd.Timestamp.now(tz='UTC'))
    os.replace(tmp, destination)
    return len(result)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="/app/data/idx_daily.csv")
    p.add_argument("--period", default="2y")
    args = p.parse_args()
    print(f"Imported {sync(args.out, args.period)} IDX rows")
