"""CLI: python -m idx_monitor.cli --prices data/idx_daily.csv --out results/idx"""
import argparse
import json
from pathlib import Path
from .core import CAPITAL, WATCHLIST, load_prices, signals, paper_trade

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--prices", required=True, help="CSV: date,ticker,open,high,low,close,volume; completed daily bars")
    p.add_argument("--out", default="results/idx")
    p.add_argument("--capital", type=float, default=CAPITAL)
    args = p.parse_args()
    data = load_prices(args.prices)
    data = data[data.ticker.isin(WATCHLIST)]
    if data.empty:
        raise ValueError("No watchlist data")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    enriched = signals(data)
    enriched.groupby("ticker").tail(1).to_csv(out/"latest_signals.csv", index=False)
    result = paper_trade(data, initial_cash=args.capital)
    (out/"paper_report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"final_equity": result["final_equity"], "cash": result["cash"], "trades": len(result["trades"])}, indent=2))

if __name__ == "__main__":
    main()
