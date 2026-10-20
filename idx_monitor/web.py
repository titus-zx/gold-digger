"""Read-only local web dashboard for IDX research results."""
import csv
import html
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

DATA = Path(os.environ.get("IDX_DATA", "/app/data/idx_daily.csv"))
HOST = os.environ.get("WEB_HOST", "0.0.0.0")
PORT = int(os.environ.get("WEB_PORT", "8080"))
CAPITAL = float(os.environ.get("IDX_CAPITAL", "50000000"))

def dashboard():
    from .core import WATCHLIST, load_prices, signals, paper_trade
    if not DATA.is_file():
        return {"status": "awaiting_data", "message": "Place completed daily IDX OHLCV CSV at data/idx_daily.csv", "capital": CAPITAL, "signals": [], "trades": [], "equity_curve": []}
    raw = load_prices(DATA)
    raw = raw[raw.ticker.isin(WATCHLIST)]
    if raw.empty:
        raise ValueError("CSV contains no supported watchlist tickers")
    latest = signals(raw).groupby("ticker").tail(1)
    result = paper_trade(raw, initial_cash=CAPITAL)
    columns = ["date", "ticker", "close", "ema20", "ema50", "rsi14", "signal"]
    rows = []
    for _, r in latest.iterrows():
        row = {k: (str(r[k].date()) if k == "date" else r[k]) for k in columns}
        for k in ("close", "ema20", "ema50", "rsi14"):
            row[k] = round(float(row[k]), 2) if row[k] == row[k] else None
        rows.append(row)
    return {"status": "ok", "capital": CAPITAL, "signals": rows, **result}

def render(state):
    esc = lambda x: html.escape(str(x), quote=True)
    rows = "".join("<tr>" + "".join(f"<td>{esc(r.get(k, '-'))}</td>" for k in ("ticker","date","close","rsi14","signal")) + "</tr>" for r in state["signals"])
    trades = "".join("<tr>" + "".join(f"<td>{esc(t.get(k, '-'))}</td>" for k in ("date","ticker","side","shares","price")) + "</tr>" for t in state.get("trades", [])[-20:])
    equity = state.get("final_equity", state["capital"])
    message = esc(state.get("message", "Research-only simulation; no real trades executed."))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="300"><title>Gold Digger • IDX Monitor</title><style>
body{{font:15px system-ui,sans-serif;background:#0b1220;color:#e8edf6;margin:0;padding:28px;max-width:1100px;margin:auto}}h1{{margin-bottom:5px}}small,.muted{{color:#9caec6}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px;margin:24px 0}}.card{{background:#172338;border:1px solid #2b3a51;border-radius:14px;padding:18px}}.value{{font-size:25px;font-weight:700}}table{{border-collapse:collapse;width:100%;background:#172338;border-radius:12px;overflow:hidden}}td,th{{padding:12px;text-align:left;border-bottom:1px solid #2b3a51}}th{{color:#a8bed7}}section{{margin:30px 0;overflow-x:auto}}a{{color:#77b8ff}}.warn{{padding:12px;background:#3b3020;border-radius:8px}}
</style></head><body><h1>Gold Digger <span class="muted">/ IDX Monitor</span></h1><small>Daily signals • Long-only paper trading • Not investment advice</small>
<div class="grid"><div class="card">Starting capital<div class="value">Rp {state['capital']:,.0f}</div></div><div class="card">Paper equity<div class="value">Rp {equity:,.0f}</div></div><div class="card">Cash<div class="value">Rp {state.get('cash',state['capital']):,.0f}</div></div><div class="card">Executed paper trades<div class="value">{len(state.get('trades',[]))}</div></div></div>
<p class="warn">{message}</p><section><h2>Latest signals</h2><table><thead><tr><th>Ticker</th><th>As of</th><th>Close</th><th>RSI14</th><th>Signal</th></tr></thead><tbody>{rows or '<tr><td colspan="5">No data yet</td></tr>'}</tbody></table></section>
<section><h2>Recent simulated trades</h2><table><thead><tr><th>Date</th><th>Ticker</th><th>Side</th><th>Shares</th><th>Price</th></tr></thead><tbody>{trades or '<tr><td colspan="5">No trades yet</td></tr>'}</tbody></table></section><p class="muted">Source: local CSV only. No live exchange feed. Auto-refresh every 5 minutes. <a href="/api/status">JSON API</a></p></body></html>"""

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            body, code, typ = b"ok", 200, "text/plain"
        elif path in ("/", "/api/status"):
            try:
                state = dashboard()
                if path == "/api/status":
                    body, typ = json.dumps(state, allow_nan=False).encode(), "application/json"
                else:
                    body, typ = render(state).encode(), "text/html; charset=utf-8"
                code = 200
            except (ValueError, OSError, KeyError) as exc:
                body, code, typ = json.dumps({"error": str(exc)}).encode(), 422, "application/json"
        else:
            body, code, typ = b"Not found", 404, "text/plain"
        self.send_response(code)
        self.send_header("Content-Type", typ)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
        self.end_headers()
        self.wfile.write(body)

if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
