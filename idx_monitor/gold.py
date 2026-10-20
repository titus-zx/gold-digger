"""Read existing XAUUSD forecast reports, without retraining or changing forecaster."""
import json
import math
from pathlib import Path

def gold_dashboard(folder):
    folder = Path(folder)
    report = folder / "report.json"
    if not report.is_file():
        return {"status":"awaiting_model", "message":"Run forecaster.py against real hourly XAUUSD candles to create results/gold/report.json", "forecasts":[]}
    data = json.loads(report.read_text(encoding="utf-8"))
    forecasts = []
    for horizon in ("1h","4h","8h","24h"):
        item = data.get(horizon, {})
        latest = item.get("latest_forecast")
        if not latest:
            continue
        row = {"horizon":horizon, "model":str(item.get("model","-")), "accuracy":item.get("test",{}).get("accuracy"), **latest}
        for key in ("p_bearish","p_neutral","p_bullish","accuracy"):
            if row.get(key) is not None:
                value = float(row[key])
                row[key] = round(value,4) if math.isfinite(value) else None
        forecasts.append(row)
    return {"status":"ok" if forecasts else "awaiting_model", "forecasts":forecasts}
