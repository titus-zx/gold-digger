"""Read existing XAUUSD forecast reports, without retraining or changing forecaster."""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

def gold_dashboard(folder):
    folder = Path(folder)
    report = folder / "report.json"
    if not report.is_file():
        return {"status":"awaiting_model", "message":"Waiting for the first successful XAUUSD sync and model training; inspect gold-sync logs.", "forecasts":[]}
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
    metadata = data.get("metadata", {})
    stamp = metadata.get("data_as_of_utc")
    stale = False
    if stamp:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(stamp)
        stale = age.total_seconds() > 6 * 3600
    return {"status": "stale" if stale else ("ok" if forecasts else "awaiting_model"),
            "metadata": metadata, "forecasts": forecasts,
            "message": "Data is over six hours old; market may be closed or sync delayed." if stale
                       else "Forecasts are saved model results, not live quotes."}
