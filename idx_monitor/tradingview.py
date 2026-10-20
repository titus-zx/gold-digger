"""Unofficial, unauthenticated TradingView chart transport; no account credentials.

Framing/session protocol is described by the community tvdatafeed project.
This is best-effort access, not TradingView's official paid MCP service.
"""
import json
import time
import uuid

import certifi
import pandas as pd
from websocket import create_connection

SOURCE = "TradingView unofficial free"


def encode(body):
    return b"~m~" + str(len(body)).encode() + b"~m~" + body


def unpack(buffer):
    """Extract complete length-prefixed messages, keeping any partial tail."""
    messages = []
    while buffer:
        if len(buffer) < 3 and b"~m~".startswith(buffer):
            break
        if not buffer.startswith(b"~m~"):
            raise ValueError("Invalid TradingView frame prefix")
        marker = buffer.find(b"~m~", 3)
        if marker < 0:
            break
        size = int(buffer[3:marker])
        if size < 0 or size > 20_000_000:
            raise ValueError("Invalid TradingView frame size")
        start = marker + 3
        if len(buffer) < start + size:
            break
        messages.append(buffer[start:start+size])
        buffer = buffer[start+size:]
    return messages, buffer


def get_bars(symbol, interval, count, timeout=30):
    if interval not in ("1D", "60") or not 1 <= count <= 5000:
        raise ValueError("Expected daily/H1 interval and 1..5000 bars")
    session = "cs_" + uuid.uuid4().hex[:12]
    ws = create_connection("wss://data.tradingview.com/socket.io/websocket",
                           origin="https://data.tradingview.com", timeout=timeout,
                           sslopt={"ca_certs": certifi.where()})
    def send(method, params):
        ws.send(encode(json.dumps({"m":method, "p":params}, separators=(",", ":")).encode()).decode())
    rows, metadata, pending = {}, {}, b""
    deadline = time.monotonic() + timeout
    try:
        send("set_auth_token", ["unauthorized_user_token"])
        send("chart_create_session", [session, ""])
        send("resolve_symbol", [session, "symbol_1", "=" + json.dumps(
            {"symbol":symbol, "adjustment":"none", "session":"regular"})])
        send("create_series", [session, "s1", "s1", "symbol_1", interval, count])
        while time.monotonic() < deadline:
            ws.settimeout(max(.1, deadline - time.monotonic()))
            packet = ws.recv()
            if not packet:
                raise ValueError(f"TradingView disconnected before completing {symbol}")
            pending += packet.encode() if isinstance(packet, str) else packet
            messages, pending = unpack(pending)
            complete = False
            for body in messages:
                if body.startswith(b"~h~"):
                    ws.send(encode(body).decode())
                    continue
                message = json.loads(body)
                method, params = message.get("m"), message.get("p", [])
                if method in ("symbol_error", "series_error", "critical_error", "protocol_error"):
                    raise ValueError(f"TradingView {method} for {symbol}: {params}")
                if method == "symbol_resolved":
                    metadata.update(params[2])
                elif method in ("timescale_update", "du"):
                    series = params[1].get("s1", {})
                    for item in series.get("s", []):
                        values = item["v"]
                        rows[values[0]] = values[:6] if len(values) >= 6 else values[:5] + [None]
                    metadata.update(series.get("lbs", {}))
                elif method == "series_completed":
                    metadata["update_mode"] = params[2]
                    complete = True
            if complete:
                if not rows:
                    raise ValueError(f"TradingView returned no bars for {symbol}")
                frame = pd.DataFrame(rows.values(), columns=["time", "open", "high", "low", "close", "volume"])
                frame["time"] = pd.to_datetime(frame.time, unit="s", utc=True)
                frame = frame.sort_values("time").reset_index(drop=True)
                frame.attrs.update(metadata)
                frame.attrs["symbol"] = symbol
                return frame
        raise TimeoutError(f"TradingView history timed out for {symbol}")
    finally:
        ws.close()


def completed_idx(frame, now=None):
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    if frame.attrs.get("currency_code") != "IDR":
        raise ValueError("Expected IDR prices for IDX")
    if frame.attrs.get("timezone") not in ("Asia/Jakarta", "Asia/Bangkok"):
        raise ValueError("Unexpected IDX exchange timezone")
    dates = frame.time.dt.tz_convert("Asia/Jakarta").dt.date
    today = now.tz_convert("Asia/Jakarta").date()
    keep = dates < today
    # Latest session close is supplied by TradingView; allow for the delayed feed.
    close = frame.attrs.get("bar_close_time")
    if close is not None:
        keep |= (dates == today) & (now >= pd.Timestamp(close, unit="s", tz="UTC") + pd.Timedelta(minutes=11))
    result = frame.loc[keep].copy()
    result["Date"] = result.time.dt.tz_convert("Asia/Jakarta").dt.strftime("%Y-%m-%d")
    return result.drop(columns="time").set_index("Date")


def gold_history(now=None, symbol="OANDA:XAUUSD", fetch=get_bars):
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    if symbol != "OANDA:XAUUSD":
        raise ValueError("Only the verified OANDA:XAUUSD feed is supported")
    frame = fetch(symbol, "60", 5000).copy()
    if frame.attrs.get("currency_code") != "USD":
        raise ValueError("Expected USD prices for XAUUSD")
    frame["time"] = frame.time + pd.Timedelta(hours=1)
    frame = frame.loc[frame.time <= now, ["time", "open", "high", "low", "close"]]
    prices = frame[["open", "high", "low", "close"]]
    import numpy as np
    if not np.isfinite(prices.to_numpy()).all() or (prices <= 0).any().any():
        raise ValueError("Invalid TradingView XAUUSD price")
    if ((frame.high < prices.max(axis=1)) | (frame.low > prices.min(axis=1))).any():
        raise ValueError("Invalid TradingView XAUUSD OHLC")
    if frame.time.duplicated().any() or len(frame) < 1600:
        raise ValueError("Insufficient or duplicate TradingView XAUUSD history")
    if now - frame.time.max() > pd.Timedelta(days=4):
        raise ValueError("TradingView XAUUSD source is over four days old")
    return frame.reset_index(drop=True)
