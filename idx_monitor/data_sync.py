"""Best-effort Yahoo Finance daily IDX data import; unofficial and may be delayed."""
import argparse
import os
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
    if d.empty:
        raise ValueError(f"No valid rows for {ticker}")
    return d

def sync(destination, period="2y"):
    import yfinance as yf
    frames = []
    for ticker in TICKERS:
        data = yf.download(f"{ticker}.JK", period=period, interval="1d",
                           auto_adjust=True, progress=False, threads=False)
        frames.append(normalize_download(data, ticker))
    result = pd.concat(frames, ignore_index=True).sort_values(["ticker","date"])
    result = result.drop_duplicates(["ticker","date"], keep="last")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(".tmp")
    result.to_csv(tmp, index=False)
    os.replace(tmp, destination)
    return len(result)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="/app/data/idx_daily.csv")
    p.add_argument("--period", default="2y")
    args = p.parse_args()
    print(f"Imported {sync(args.out, args.period)} IDX rows")
