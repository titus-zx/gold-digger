import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from idx_monitor.gold import gold_dashboard
from idx_monitor.gold_sync import decode_month, download, refresh
from idx_monitor.web import render_gold


class GoldSyncTests(unittest.TestCase):
    def candle_payload(self):
        return {"timestamp":1788220800000, "multiplier":.001, "shift":3600000,
                "open":2000., "high":2002., "low":1999., "close":2001.,
                "times":[0, 1, 2], "opens":[0, 1000, 2000], "highs":[0, 1000, 2000],
                "lows":[0, 1000, 2000], "closes":[0, 1000, 2000], "volumes":[1., 1., 1.]}

    def test_provider_layout_scale_and_completed_close_timestamps(self):
        rows = decode_month(json.dumps(self.candle_payload()), pd.Timestamp('2026-09-01', tz='UTC'),
                            pd.Timestamp('2026-09-01T01:30Z'))
        self.assertEqual(rows, [(pd.Timestamp('2026-09-01T01:00Z'), 2000., 2002., 1999., 2001.)])

    def test_reject_invalid_ohlc_and_malformed_response(self):
        for key, value in (("high", 1900.), ("times", [0]), ("shift", 60000),
                           ("opens", [0, float('nan'), 0])):
            data = self.candle_payload()
            data[key] = value
            with self.assertRaises(ValueError):
                decode_month(json.dumps(data), pd.Timestamp('2026-09-01', tz='UTC'),
                             pd.Timestamp('2026-09-02', tz='UTC'))

    def test_download_rejects_stale_short_and_duplicate_history(self):
        now = pd.Timestamp('2026-09-20', tz='UTC')
        month = pd.Timestamp('2026-09-01', tz='UTC')
        def candles(count, start=month):
            return [(start + pd.Timedelta(hours=i), 2000., 2002., 1999., 2001.)
                    for i in range(count)]
        for rows in (candles(2), candles(1600, pd.Timestamp('2020-01-01', tz='UTC')),
                     [(now, 2000., 2002., 1999., 2001.)] * 1600):
            with patch('idx_monitor.gold_sync.decode_month', return_value=rows):
                with self.assertRaises(ValueError):
                    download(now=now, months=1, fetch=lambda _: b'fixture')

    def test_delta_decoding_does_not_fill_missing_hours(self):
        rows = decode_month(json.dumps(self.candle_payload()), pd.Timestamp('2026-09-01', tz='UTC'),
                            pd.Timestamp('2026-09-02', tz='UTC'))
        self.assertEqual([row[0].hour for row in rows], [1, 2, 4])
        self.assertEqual(rows[-1][1:], (2003., 2005., 2002., 2004.))

    def test_24h_targets_match_wall_clock_across_daily_session_break(self):
        from forecaster import forward_delta
        times = pd.to_datetime(['2026-09-01T00:00Z', '2026-09-01T01:00Z',
                                '2026-09-01T03:00Z', '2026-09-02T00:00Z',
                                '2026-09-02T01:00Z', '2026-09-02T03:00Z'])
        close = pd.Series([2000., 2001., 2003., 2010., 2021., 2033.], index=times)
        delta = forward_delta(close, 24)
        self.assertEqual(delta.iloc[:3].tolist(), [10., 20., 30.])
        self.assertTrue(delta.iloc[3:].isna().all())
        self.assertTrue(pd.isna(forward_delta(close, 1).iloc[1]))  # Missing 02h stays missing.

    def test_failed_training_preserves_previous_report_and_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / 'data.csv'
            report = root / 'results' / 'report.json'
            report.parent.mkdir()
            data.write_text('original data')
            report.write_text('{"original":true}')
            frame = pd.DataFrame({'time': [pd.Timestamp('2026-09-02', tz='UTC')]})
            def incomplete(args):
                (args.out / 'report.json').write_text('{}')
            with patch('idx_monitor.gold_sync.download', return_value=frame):
                with self.assertRaises(ValueError):
                    refresh(data, report.parent, trainer=incomplete)
            self.assertEqual(data.read_text(), 'original data')
            self.assertEqual(json.loads(report.read_text()), {'original': True})

    def test_publication_and_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = pd.Timestamp.now(tz='UTC').floor('h')
            frame = pd.DataFrame({'time': [now], 'close': [2000.]})
            def trained(args):
                report = {f'{h}h': {'latest_forecast': {'as_of_utc': now.isoformat(),
                          'direction': 'NEUTRAL'}} for h in (1, 4, 8, 24)}
                (args.out / 'report.json').write_text(json.dumps(report))
            with patch('idx_monitor.gold_sync.download', return_value=frame):
                refresh(root / 'data.csv', root / 'results', now=now, trainer=trained)
            state = gold_dashboard(root / 'results')
            self.assertEqual(state['status'], 'ok')
            self.assertEqual(len(state['forecasts']), 4)
            self.assertIn('Dukascopy', render_gold(state))
            report = json.loads((root / 'results/report.json').read_text())
            report['metadata']['data_as_of_utc'] = '2020-01-01T00:00:00+00:00'
            (root / 'results/report.json').write_text(json.dumps(report))
            self.assertEqual(gold_dashboard(root / 'results')['status'], 'stale')
