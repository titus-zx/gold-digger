import unittest
import numpy as np
import pandas as pd
from idx_monitor.core import load_prices, signals, paper_trade

class MonitorTests(unittest.TestCase):
    def sample(self):
        dates = pd.bdate_range("2025-01-01", periods=130)
        close = np.linspace(3000, 4500, len(dates))
        return pd.DataFrame({"date": dates, "ticker": "BMRI", "open": close, "high": close+30, "low": close-30, "close": close, "volume": 1000000})

    def test_signals_no_future_dependency(self):
        data = self.sample()
        before = signals(data.iloc[:100]).iloc[-1]
        after = signals(data).iloc[99]
        self.assertEqual(before.signal, after.signal)
        self.assertAlmostEqual(before.ema20, after.ema20)

    def test_cash_lots_and_equity(self):
        result = paper_trade(self.sample(), initial_cash=50_000_000, weights={"BMRI": .2})
        self.assertGreaterEqual(result["cash"], 0)
        self.assertEqual(result["shares"]["BMRI"] % 100, 0)
        self.assertTrue(all(t["shares"] % 100 == 0 for t in result["trades"]))

    def test_invalid_prices(self):
        data = self.sample()
        data.loc[0, "high"] = 1
        path = "/tmp/idx_bad_prices.csv"
        data.to_csv(path, index=False)
        with self.assertRaises(ValueError):
            load_prices(path)

    def test_invalid_weights(self):
        with self.assertRaises(ValueError):
            paper_trade(self.sample(), weights={"BMRI": 1.2})

if __name__ == "__main__":
    unittest.main()
