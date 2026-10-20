"""XAUUSD H1 ingestion and atomic forecast publication.

Default: unofficial free TradingView OANDA feed. Optional: Dukascopy bid.

JSON delta format follows dukascopy-node's data-normaliser and url-generator.
Missing hours are kept missing rather than padded with flat candles.
"""
import argparse
import json
import math
import os
from pathlib import Path
import tempfile
import time

from curl_cffi import requests
import pandas as pd

SOURCE = "Dukascopy XAU/USD spot bid"
BASE = "https://jetta.dukascopy.com/v1/candles/hour/XAU-USD/BID"


def decode_month(payload, month, now):
    data = json.loads(payload)
    columns = ("times", "opens", "highs", "lows", "closes", "volumes")
    if not all(isinstance(data.get(key), list) for key in columns):
        raise ValueError("Malformed Dukascopy candle columns")
    length = len(data["times"])
    if any(len(data[key]) != length for key in columns):
        raise ValueError("Mismatched Dukascopy candle columns")
    if data.get("shift") != 3600000:
        raise ValueError("Expected Dukascopy H1 candles")
    multiplier = float(data["multiplier"])
    if not math.isfinite(multiplier) or multiplier <= 0:
        raise ValueError("Invalid Dukascopy price multiplier")
    stamp = pd.Timestamp(data["timestamp"], unit="ms", tz="UTC")
    start = pd.Timestamp(month)
    end = start + pd.offsets.MonthBegin(1)
    # Each price column is an independent delta stream in integer price units.
    units = [round(float(data[key]) / multiplier) for key in ("open", "high", "low", "close")]
    rows = []
    for values in zip(*(data[key] for key in columns)):
        delta, *prices, volume = values
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
            raise ValueError("Non-finite Dukascopy candle value")
        if delta < 0 or delta != int(delta) or any(price != int(price) for price in prices):
            raise ValueError("Invalid Dukascopy candle delta")
        stamp += pd.Timedelta(hours=delta)
        units = [value + change for value, change in zip(units, prices)]
        opened, high, low, closed = [round(value * multiplier, 8) for value in units]
        if stamp < start or stamp >= end or stamp != stamp.floor("h"):
            raise ValueError("Invalid H1 timestamp in Dukascopy response")
        if min(opened, closed, low, high) <= 0 or not low <= min(opened, closed) <= max(opened, closed) <= high:
            raise ValueError("Invalid OHLC in Dukascopy response")
        close_time = stamp + pd.Timedelta(hours=1)
        if close_time <= now and volume > 0:
            rows.append((close_time, opened, high, low, closed))
    return rows


def fetch_month(month):
    current = pd.Timestamp.now(tz="UTC").normalize().replace(day=1)
    active = month == current
    suffix = f"?from={month.value // 1_000_000}" if active else f"/{month.year}/{month.month}"
    cache = Path(os.environ.get("GOLD_DATA", "/app/data/xau_h1.csv")).parent / "gold-cache" / f"{month:%Y-%m}.json"
    if not active and cache.is_file():
        return cache.read_bytes()
    for attempt in range(3):
        try:
            response = requests.get(BASE + suffix, impersonate="chrome", timeout=20,
                                    headers={"Referer":"https://www.dukascopy.com/",
                                             "Origin":"https://www.dukascopy.com"})
            if response.status_code != 200:
                raise ValueError(f"Dukascopy returned HTTP {response.status_code}")
            payload = response.content
            # Validate before caching; never cache a challenge/error response.
            decode_month(payload, month, pd.Timestamp.now(tz="UTC"))
            if not active:
                cache.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=cache.parent, delete=False) as handle:
                    pending = Path(handle.name)
                    handle.write(payload)
                pending.replace(cache)
            return payload
        except (requests.RequestsError, ValueError):
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def download(now=None, months=12, fetch=fetch_month):
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    current = now.normalize().replace(day=1)
    rows = []
    for offset in range(months - 1, -1, -1):
        month = current - pd.offsets.MonthBegin(offset)
        print(f"{pd.Timestamp.now(tz='UTC')} fetching XAUUSD {month:%Y-%m}", flush=True)
        rows.extend(decode_month(fetch(month), month, now))
    frame = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"])
    frame = frame.sort_values("time").reset_index(drop=True)
    if len(frame) < 1600 or frame.time.duplicated().any():
        raise ValueError("Insufficient or duplicate XAUUSD history")
    if now - frame.time.iloc[-1] > pd.Timedelta(days=4):
        raise ValueError("XAUUSD source is more than four days old")
    return frame


def refresh(data_path, results_path, now=None, fetch=fetch_month, trainer=None, provider=None):
    from forecaster import run
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    provider = provider or os.environ.get("GOLD_PROVIDER", "tradingview")
    if provider == "tradingview":
        from .tradingview import gold_history, SOURCE as TV_SOURCE
        frame = gold_history(now=now)
        source, symbol, price_type = TV_SOURCE, "OANDA:XAUUSD", "provider quote"
    elif provider == "dukascopy":
        frame = download(now=now, fetch=fetch)
        source, symbol, price_type = SOURCE, "XAUUSD", "bid"
    else:
        raise ValueError("GOLD_PROVIDER must be tradingview or dukascopy")
    print(f"{pd.Timestamp.now(tz='UTC')} training XAUUSD on {len(frame)} candles", flush=True)
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
        report["metadata"] = {"source": source, "price_type": price_type, "symbol": symbol,
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
    retry = max(30, int(os.environ.get("GOLD_RETRY_SECONDS", "60")))
    while True:
        delay = interval
        try:
            rows = refresh(os.environ.get("GOLD_DATA", "/app/data/xau_h1.csv"),
                           os.environ.get("GOLD_RESULTS", "/app/results/gold"))
            print(f"{pd.Timestamp.now(tz='UTC')} gold updated {rows} rows", flush=True)
        except Exception as exc:
            print(f"{pd.Timestamp.now(tz='UTC')} gold sync failed: {exc}", flush=True)
            delay = retry
            if args.once:
                raise
        if args.once:
            return
        time.sleep(delay)


if __name__ == "__main__":
    main()
