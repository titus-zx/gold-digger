"""Poll daily price data, preserving previous CSV if a refresh fails."""
import os
import time
from datetime import datetime, timezone
from .data_sync import sync

if __name__ == "__main__":
    interval = max(3600, int(os.environ.get("IDX_SYNC_SECONDS", "21600")))
    path = os.environ.get("IDX_DATA", "/app/data/idx_daily.csv")
    while True:
        try:
            count = sync(path)
            print(f"{datetime.now(timezone.utc).isoformat()} updated {count} rows", flush=True)
        except Exception as exc:
            print(f"{datetime.now(timezone.utc).isoformat()} sync failed: {exc}", flush=True)
        time.sleep(interval)
