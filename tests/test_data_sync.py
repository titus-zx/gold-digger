import unittest
from unittest.mock import patch
from tempfile import TemporaryDirectory
from pathlib import Path
import pandas as pd
from idx_monitor.data_sync import normalize_download, sync
from idx_monitor.gold import gold_dashboard

class DataSyncTests(unittest.TestCase):
    def test_normalize(self):
        frame = pd.DataFrame({"Open":[10]*70,"High":[12]*70,"Low":[9]*70,"Close":[11]*70,"Volume":[100]*70},index=pd.date_range("2026-07-01",periods=70,name="Date"))
        rows = normalize_download(frame, "BMRI")
        self.assertEqual(rows.iloc[0].ticker,"BMRI")
        self.assertEqual(rows.iloc[0].close,11)
    def test_sync_uses_unadjusted_prices(self):
        with TemporaryDirectory() as d:
            frame = pd.DataFrame({"Open":[100]*70,"High":[105]*70,"Low":[95]*70,"Close":[102]*70,"Volume":[1000]*70},index=pd.date_range("2026-06-01",periods=70,name="Date"))
            with patch("yfinance.download",return_value=frame) as download:
                count = sync(Path(d)/"prices.csv")
                self.assertEqual(count, 350)
                self.assertFalse(download.call_args.kwargs["auto_adjust"])
                self.assertEqual(pd.read_csv(Path(d)/"prices.csv").iloc[0]["open"], 100)
    def test_atomic_sync_preserves_existing_on_failure(self):
        with TemporaryDirectory() as d:
            path = Path(d)/"prices.csv"
            path.write_text("original")
            with patch("yfinance.download",side_effect=RuntimeError("network unavailable")):
                with self.assertRaises(RuntimeError):
                    sync(path)
            self.assertEqual(path.read_text(),"original")
    def test_gold_missing(self):
        with TemporaryDirectory() as d:
            self.assertEqual(gold_dashboard(d)["status"],"awaiting_model")

if __name__=="__main__":
    unittest.main()
