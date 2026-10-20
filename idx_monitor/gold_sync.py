"""Dukascopy spot XAU/USD bid H1 ingestion and atomic forecast publication.

BI5 layout and scale follow dukascopy-node v1.46.3 decompressor,
data-normaliser, and instrument metadata (XAUUSD decimalFactor=1000).
"""
import argparse
import json
import lzma
import math
import os
from pathlib import Path
import struct
import tempfile
import time
from urllib.request import urlopen

import pandas as pd

SOURCE = "Dukascopy XAU/USD spot bid"
BASE = "https://datafeed.dukascopy.com/datafeed/XAUUSD"


def decode_month(payload, month, now):
    start = pd.Timestamp(month)
    end = start + pd.offsets.MonthBegin(1)
    raw = lzma.decompress(payload)
    if not raw or len(raw) % 24:
        raise ValueError("Empty or malformed Dukascopy H1 archive")
    rows = []
    for seconds, opened, closed, low, high, volume in struct.iter_unpack(">5If", raw):
        stamp = start + pd.Timedelta(seconds=seconds)
        if seconds % 3600 or stamp >= end:
            raise ValueError("Invalid H1 timestamp in Dukascopy archive")
        if not math.isfinite(volume) or volume <= 0:
            continue  # No traded volume: do not treat market-closure placeholders as bars.
        # Provider timestamps identify candle OPEN; models require candle CLOSE.
        close_time = stamp + pd.Timedelta(hours=1)
        if close_time > now:
            continue
        if min(opened, closed, low, high) <= 0 or not low <= min(opened, closed) <= max(opened, closed) <= high:
            raise ValueError("Invalid OHLC in Dukascopy archive")
        rows.append((close_time, opened / 1000, high / 1000, low / 1000, closed / 1000))
    return rows


def fetch_month(month):
    url = f"{BASE}/{month.year}/{month.month - 1:02d}/BID_candles_hour_1.bi5"
    with urlopen(url, timeout=30) as response:
        return response.read()


def download(now=None, months=12, fetch=fetch_month):
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    current = now.normalize().replace(day=1)
    rows = []
    for offset in range(months - 1, -1, -1):
        month = current - pd.offsets.MonthBegin(offset)
        rows.extend(decode_month(fetch(month), month, now))
    frame = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"])
    frame = frame.sort_values("time").reset_index(drop=True)
    if len(frame) < 1600 or frame.time.duplicated().any():
        raise ValueError("Insufficient or duplicate XAUUSD history")
    if now - frame.time.iloc[-1] > pd.Timedelta(days=4):
        raise ValueError("XAUUSD source is more than four days old")
    return frame


def refresh(data_path, results_path, now=None, fetch=fetch_month, trainer=None):
    from forecaster import run
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    frame = download(now=now, fetch=fetch)
    data_path, results_path = Path(data_path), Path(results_path)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.mkdir(parents=True, exist_ok=True)
    # Train in isolation; readers continue to see the last successful report.
    with tempfile.TemporaryDirectory(dir=results_path) as staging:
        staging = Path(staging)
        csv_path = staging / "xau_h1.csv"
        frame.to_csv(csv_path, index=False)
        (trainer or run)(argparse.Namespace(xau=csv_path, dxy=None, out=staging,
                                          threshold_atr=.25, min_prob=.50))
        report_path = staging / "report.json"
        report = json.loads(report_path.read_text())
        if any(not report.get(f"{h}h", {}).get("latest_forecast") for h in (1, 4, 8, 24)):
            raise ValueError("Training did not produce all four forecast horizons")
        report["metadata"] = {"source": SOURCE, "price_type": "bid", "symbol": "XAUUSD",
                              "generated_at_utc": now.isoformat(),
                              "data_as_of_utc": frame.time.iloc[-1].isoformat(),
                              "rows": len(frame)}
        report_path.write_text(json.dumps(report, indent=2, allow_nan=False))
        # CSV and report are each replaced atomically on their destination filesystem.
        with tempfile.NamedTemporaryFile(dir=data_path.parent, delete=False) as handle:
            pending = Path(handle.name)
        try:
            frame.to_csv(pending, index=False)
            pending.replace(data_path)
        finally:
            pending.unlink(missing_ok=True)
        for artifact in staging.iterdir():
            if artifact.name not in ("report.json", "xau_h1.csv"):
                artifact.replace(results_path / artifact.name)
        report_path.replace(results_path / "report.json")
    return len(frame)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    interval = max(3600, int(os.environ.get("GOLD_SYNC_SECONDS", "21600")))
    while True:
        try:
            rows = refresh(os.environ.get("GOLD_DATA", "/app/data/xau_h1.csv"),
                           os.environ.get("GOLD_RESULTS", "/app/results/gold"))
            print(f"{pd.Timestamp.now(tz='UTC')} gold updated {rows} rows", flush=True)
        except Exception as exc:
            print(f"{pd.Timestamp.now(tz='UTC')} gold sync failed: {exc}", flush=True)
            if args.once:
                raise
        if args.once:
            return
        time.sleep(interval)


if __name__ == "__main__":
    main()
