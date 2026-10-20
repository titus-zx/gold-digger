import unittest
from unittest.mock import patch
from tempfile import TemporaryDirectory
from pathlib import Path
import pandas as pd
from idx_monitor.data_sync import normalize_download, sync
from idx_monitor.gold import gold_dashboard

class DataSyncTests(unittest.TestCase):
    def test_normalize(self):
        frame = pd.DataFrame({"Open":[10],"High":[12],"Low":[9],"Close":[11],"Volume":[100]},index=pd.DatetimeIndex(["2026-10-19"],name="Date"))
        rows = normalize_download(frame, "BMRI")
        self.assertEqual(rows.iloc[0].ticker,"BMRI")
        self.assertEqual(rows.iloc[0].close,11)
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
