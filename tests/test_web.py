import unittest
from unittest.mock import patch
from idx_monitor.web import dashboard, render

class WebTests(unittest.TestCase):
    def test_no_data(self):
        with patch("idx_monitor.web.DATA") as data:
            data.is_file.return_value = False
            state = dashboard()
        self.assertEqual(state["status"], "awaiting_data")
        self.assertIn("No data yet", render(state))
    def test_html_escaping(self):
        state = {"capital": 50000000, "signals": [{"ticker": "<script>", "date": "", "close": "", "rsi14": "", "signal": ""}], "trades": [], "equity_curve": []}
        self.assertNotIn("<script>", render(state))
if __name__ == "__main__":
    unittest.main()
