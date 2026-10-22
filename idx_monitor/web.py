"""Read-only local web dashboard for IDX research results."""
import csv
import html
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from .gold import gold_dashboard
from .history import read_history
import math

DATA = Path(os.environ.get("IDX_DATA", "/app/data/idx_daily.csv"))
GOLD_RESULTS = Path(os.environ.get("GOLD_RESULTS", "/app/results/gold"))
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
    source = ", ".join(sorted(raw.source.dropna().unique())) if "source" in raw else "Legacy local CSV"
    return {"status": "ok", "history":read_history(DATA.parent / "idx_history.sqlite", "idx"), "source": source, "capital": CAPITAL, "signals": rows, **result}

def render(state):
    esc = lambda x: html.escape(str(x), quote=True)
    rows = "".join("<tr>" + "".join(f"<td>{esc(r.get(k, '-'))}</td>" for k in ("ticker","date","close","rsi14","signal")) + "</tr>" for r in state["signals"])
    trades = "".join("<tr>" + "".join(f"<td>{esc(t.get(k, '-'))}</td>" for k in ("date","ticker","side","shares","price")) + "</tr>" for t in state.get("trades", [])[-20:])
    equity = state.get("final_equity", state["capital"])
    curve = state.get("equity_curve", [])
    points = [float(p["equity"]) for p in curve if p.get("equity") is not None]
    chart = ""
    if len(points) > 1:
        lo, hi = min(points), max(points)
        coords = " ".join(
            f"{i * 800 / (len(points)-1):.1f},{170-(value-lo)*150/(hi-lo or 1):.1f}"
            for i, value in enumerate(points)
        )
        chart = f'<section><h2>Simulated equity curve</h2><svg viewBox="0 0 800 190" role="img" aria-label="Paper equity curve" style="width:100%;background:#172338"><polyline points="{coords}" stroke="#63b7f4" stroke-width="3" fill="none"/></svg></section>'

    message = esc(state.get("message", "Research-only simulation; no real trades executed."))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="300"><title>Gold Digger • IDX Monitor</title><style>
body{{font:15px system-ui,sans-serif;background:#0b1220;color:#e8edf6;margin:0;padding:28px;max-width:1100px;margin:auto}}h1{{margin-bottom:5px}}small,.muted{{color:#9caec6}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px;margin:24px 0}}.card{{background:#172338;border:1px solid #2b3a51;border-radius:14px;padding:18px}}.value{{font-size:25px;font-weight:700}}table{{border-collapse:collapse;width:100%;background:#172338;border-radius:12px;overflow:hidden}}td,th{{padding:12px;text-align:left;border-bottom:1px solid #2b3a51}}th{{color:#a8bed7}}section{{margin:30px 0;overflow-x:auto}}a{{color:#77b8ff}}.warn{{padding:12px;background:#3b3020;border-radius:8px}}
</style></head><body><nav><a href="/">IDX Monitor</a> | <a href="/gold">XAUUSD Forecast</a></nav><h1>Gold Digger <span class="muted">/ IDX Monitor</span></h1><small>Daily signals • Long-only paper trading • Not investment advice</small>
<div class="grid"><div class="card">Starting capital<div class="value">Rp {state['capital']:,.0f}</div></div><div class="card">Paper equity<div class="value">Rp {equity:,.0f}</div></div><div class="card">Cash<div class="value">Rp {state.get('cash',state['capital']):,.0f}</div></div><div class="card">Executed paper trades<div class="value">{len(state.get('trades',[]))}</div></div></div>
<p class="warn">{message}</p><section><h2>Latest signals</h2><table><thead><tr><th>Ticker</th><th>As of</th><th>Close</th><th>RSI14</th><th>Signal</th></tr></thead><tbody>{rows or '<tr><td colspan="5">No data yet</td></tr>'}</tbody></table></section>
{render_history(state.get("history", {}), "idx")}{chart}<section><h2>Recent simulated trades</h2><table><thead><tr><th>Date</th><th>Ticker</th><th>Side</th><th>Shares</th><th>Price</th></tr></thead><tbody>{trades or '<tr><td colspan="5">No trades yet</td></tr>'}</tbody></table></section><p class="muted">Source: {esc(state.get("source", "Local CSV"))}. Completed daily candles. Auto-refresh every 5 minutes. <a href="/api/status">JSON API</a> | <a href="/api/history?kind=idx">Signal history JSON</a></p></body></html>"""


def render_history(history, kind="gold"):
    esc = lambda value: html.escape(str(value), quote=True)
    accuracy = history.get('accuracy')
    accuracy = '-' if accuracy is None else f"{accuracy*100:.1f}%"
    rows = []
    for item in history.get('recent', [])[:40]:
        result = ('Correct' if item.get('correct') else 'Incorrect') if item.get('correct') is not None else '-'
        actual = item.get('actual') or '-'
        change = '-' if item.get('return_pct') is None else f"{item['return_pct']:+.2f}%"
        prediction = item.get('snapshot',{}).get('signal',item.get('prediction','-'))
        values = (item.get('symbol'),item.get('issued_at'),item.get('horizon'),
                  item.get('target_at') or 'Next trading session',prediction,actual,change,
                  item.get('status'),result)
        rows.append('<tr>'+''.join(f'<td>{esc(value)}</td>' for value in values)+'</tr>')
    note = ('IDX WATCH abstains; directional IDX outcomes use a 1% neutral band. Signals are scored only when issued before the next session opens.'
            if kind == 'idx' else 'Gold uses the exact target candle and the neutral price band saved at publication. Missing target candles remain unscored.')
    return f"""<section style="margin:28px 0;overflow-x:auto"><h2>Published predictions vs actual outcomes</h2>
    <p>Saved: {history.get('total',0)} | Resolved: {history.get('resolved',0)} |
    Pending: {history.get('pending',0)} | Missing target data: {history.get('waiting_data',0)} |
    Expired before publication: {history.get('expired',0)}</p>
    <p>Live directional accuracy: {accuracy} ({history.get('scored',0)} scored).
    This measures saved predictions; it is separate from historical model tests.
    {note}</p>
    <table style="width:100%;border-collapse:collapse" border="1" cellpadding="8"><thead><tr>
    <th>Feed</th><th>Issued UTC</th><th>Window</th><th>Target UTC</th><th>Prediction/signal</th>
    <th>Actual</th><th>Return</th><th>Status</th><th>Result</th></tr></thead>
    <tbody>{''.join(rows) or '<tr><td colspan="9">History starts with the next successful sync. No backfilled predictions.</td></tr>'}</tbody></table>
    <p>Original predictions remain unchanged. Source and feed groups are available in the history JSON API.</p></section>"""


def render_gold(state):
    esc = lambda x: html.escape(str(x), quote=True)
    cards = []
    for item in state["forecasts"]:
        def pct(key):
            value = item.get(key)
            return "-" if value is None else f"{float(value)*100:.1f}%"
        probs = "".join(
            f'<p>{label}: <strong>{pct(key)}</strong></p>'
            for key, label in (("p_bearish","Bearish"),("p_neutral","Neutral"),("p_bullish","Bullish"))
        )
        cards.append(
            f'<div class="card"><h2>{esc(item["horizon"])}: {esc(item.get("direction","-"))}</h2>'
            f'<p>As of UTC: {esc(item.get("as_of_utc","-"))}</p>'
            f'<p>Model: {esc(item.get("model","-"))}</p>'
            f'<p>Historical test accuracy ({esc(item.get("test_model", item.get("model","-")))}): {pct("accuracy")}</p>{probs}</div>'
        )
    msg = esc(state.get("message", "Forecasts are saved model results, not live quotes."))
    meta = state.get("metadata", {})
    feedback = meta.get('feedback', {})
    learning = (' | '.join(f"{esc(horizon)}: {esc(item['preferred_model'])} ({item['samples']} resolved predictions)"
                          for horizon,item in feedback.items()) if feedback
                else 'Collecting results: model feedback starts after 30 resolved predictions per window.')
    provenance = " | ".join(f"{label}: {esc(meta.get(key, '-'))}" for key, label in (
        ("source", "Source"), ("symbol", "Feed"), ("data_as_of_utc", "Data UTC"), ("generated_at_utc", "Trained UTC")))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <meta http-equiv="refresh" content="300"><title>XAUUSD | Gold Digger</title>
    <style>body{{font:15px system-ui;background:#0b1220;color:#e8edf6;max-width:1100px;margin:auto;padding:28px}}
    a{{color:#77b8ff}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px}}
    .card{{background:#172338;border:1px solid #2b3a51;border-radius:14px;padding:18px}}</style></head>
    <body><nav><a href="/">IDX Monitor</a> | <a href="/gold">XAUUSD Forecast</a></nav>
    <h1>XAUUSD multi-horizon forecast</h1><p>{msg}</p><p>{provenance}</p><div class="grid">{"".join(cards)}</div>
    <p>Model updates: {learning}</p>{render_history(state.get("history", {}))}<p>Research only; do not treat historical accuracy as a future guarantee.</p>
    <a href="/api/gold">Gold JSON API</a> | <a href="/api/history?kind=gold">Forecast history JSON</a></body></html>"""

class Handler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.respond(head_only=True)

    def do_GET(self):
        self.respond(head_only=False)

    def respond(self, head_only=False):
        path = urlparse(self.path).path
        if path == "/health":
            body, code, typ = b"ok", 200, "text/plain"
        elif path in ("/", "/api/status", "/gold", "/api/gold", "/api/history"):
            try:
                if path == "/api/history":
                    query = parse_qs(urlparse(self.path).query)
                    kind = query.get('kind',['gold'])[0]
                    if kind not in ('gold','idx'):
                        raise ValueError('History kind must be gold or idx')
                    db_path = GOLD_RESULTS / 'history.sqlite' if kind == 'gold' else DATA.parent / 'idx_history.sqlite'
                    state = read_history(db_path, kind, query.get('limit',[100])[0], query.get('offset',[0])[0])
                else:
                    state = gold_dashboard(GOLD_RESULTS) if path in ("/gold", "/api/gold") else dashboard()
                if path in ("/api/status", "/api/gold", "/api/history"):
                    body, typ = json.dumps(state, allow_nan=False).encode(), "application/json"
                elif path == "/gold":
                    body, typ = render_gold(state).encode(), "text/html; charset=utf-8"
                else:
                    body, typ = render(state).encode(), "text/html; charset=utf-8"
                code = 200
            except (ValueError, OSError, KeyError) as exc:
                body, code, typ = json.dumps({"error": str(exc)}).encode(), 422, "application/json"
        else:
            body, code, typ = b"Not found", 404, "text/plain"
        self.send_response(code)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
