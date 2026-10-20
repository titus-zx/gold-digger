"""Daily IDX signals. All decisions use completed daily candles only."""
from dataclasses import dataclass
import numpy as np
import pandas as pd

WATCHLIST = ("BMRI", "BBCA", "BBRI", "BBNI", "TLKM")
WEIGHTS = {"BMRI": .20, "BBCA": .15, "BBRI": .15, "BBNI": .10, "TLKM": .10}
CAPITAL = 50_000_000
LOT_SIZE = 100

def load_prices(path):
    df = pd.read_csv(path, parse_dates=["date"])
    required = {"date", "ticker", "open", "high", "low", "close", "volume"}
    if not required.issubset(df):
        raise ValueError(f"Missing columns: {sorted(required - set(df))}")
    if df[["date", "ticker"]].duplicated().any():
        raise ValueError("Duplicate ticker/date")
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="raise")
    if (df[["open", "high", "low", "close"]] <= 0).any().any() or (df.volume < 0).any():
        raise ValueError("Invalid price or volume")
    if ((df.high < df[["open", "close", "low"]].max(axis=1)) | (df.low > df[["open", "close"]].min(axis=1))).any():
        raise ValueError("Invalid OHLC range")
    return df.sort_values(["ticker", "date"]).reset_index(drop=True)

def signals(df):
    out = []
    for ticker, g in df.groupby("ticker", sort=True):
        g = g.copy().sort_values("date")
        g["ema20"] = g.close.ewm(span=20, adjust=False).mean()
        g["ema50"] = g.close.ewm(span=50, adjust=False).mean()
        delta = g.close.diff()
        gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
        g["rsi14"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
        g["volume20"] = g.volume.rolling(20).mean()
        g["return20"] = g.close.pct_change(20)
        g["signal"] = "WATCH"
        ready = g.index[g["volume20"].notna() & g["rsi14"].notna()]
        for i in ready:
            row = g.loc[i]
            if row.close > row.ema20 > row.ema50 and 45 <= row.rsi14 <= 70 and row.volume >= row.volume20 * .8:
                g.loc[i, "signal"] = "BUY_CANDIDATE"
            elif row.close < row.ema50 and row.rsi14 < 40:
                g.loc[i, "signal"] = "RISK_OFF"
        out.append(g)
    return pd.concat(out).sort_values(["date", "ticker"]).reset_index(drop=True)

@dataclass
class PaperAccount:
    cash: float = float(CAPITAL)
    fee_buy: float = .0015
    fee_sell: float = .0025

def paper_trade(df, initial_cash=CAPITAL, weights=None, fee_buy=.0015, fee_sell=.0025):
    """Next-day OPEN execution; long-only, whole IDX lots, no margin, no same-day close leakage."""
    weights = dict(WEIGHTS if weights is None else weights)
    if sum(weights.values()) > 1 + 1e-9 or min(weights.values(), default=0) < 0:
        raise ValueError("Weights must be nonnegative and total <= 1")
    if initial_cash <= 0 or min(fee_buy, fee_sell) < 0:
        raise ValueError("Invalid cash or fees")
    df = signals(df)
    cash = float(initial_cash)
    shares = {ticker: 0 for ticker in weights}
    trades, equity = [], []
    grouped = {ticker: g.set_index("date").sort_index() for ticker, g in df.groupby("ticker")}
    dates = sorted(df.date.unique())
    for date in dates:
        for ticker, weight in weights.items():
            g = grouped.get(ticker)
            if g is None or date not in g.index:
                continue
            idx = g.index.get_loc(date)
            if not isinstance(idx, (int, np.integer)) or idx == 0:
                continue
            prev, today = g.iloc[idx-1], g.iloc[idx]
            if (pd.Timestamp(today.name) - pd.Timestamp(prev.name)).days > 7:
                continue
            price = float(today.open)
            if prev.signal == "RISK_OFF" and shares[ticker]:
                qty = shares[ticker]
                cash += qty * price * (1-fee_sell)
                shares[ticker] = 0
                trades.append({"date": str(pd.Timestamp(date).date()), "ticker": ticker, "side": "SELL", "shares": qty, "price": price})
            elif prev.signal == "BUY_CANDIDATE" and not shares[ticker]:
                budget = min(cash, initial_cash * weight)
                lots = int(budget // (LOT_SIZE * price * (1+fee_buy)))
                if lots:
                    qty = lots * LOT_SIZE
                    cash -= qty * price * (1+fee_buy)
                    shares[ticker] = qty
                    trades.append({"date": str(pd.Timestamp(date).date()), "ticker": ticker, "side": "BUY", "shares": qty, "price": price})
        marked = sum(qty * float(grouped[t].loc[:date].iloc[-1].close) for t, qty in shares.items() if qty and t in grouped and len(grouped[t].loc[:date]))
        equity.append({"date": str(pd.Timestamp(date).date()), "cash": round(cash, 2), "equity": round(cash+marked, 2)})
    return {"cash": round(cash, 2), "shares": shares, "trades": trades, "equity_curve": equity, "final_equity": equity[-1]["equity"] if equity else cash}
