import json
import lzma
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from idx_monitor.gold import gold_dashboard
from idx_monitor.gold_sync import decode_month, download, refresh
from idx_monitor.web import render_gold


class GoldSyncTests(unittest.TestCase):
    def test_provider_layout_scale_and_completed_close_timestamps(self):
        payload = lzma.compress(b''.join(struct.pack('>5If', h * 3600,
                              2000000, 2001000, 1999000, 2002000, 1.) for h in (0, 1)))
        rows = decode_month(payload, pd.Timestamp('2026-09-01', tz='UTC'),
                            pd.Timestamp('2026-09-01T01:30Z'))
        self.assertEqual(rows, [(pd.Timestamp('2026-09-01T01:00Z'), 2000., 2002., 1999., 2001.)])

    def test_reject_invalid_ohlc_and_truncated_archive(self):
        now = pd.Timestamp('2026-09-02', tz='UTC')
        for raw in (b'bad', struct.pack('>5If', 0, 2000000, 2001000, 1999000, 1998000, 1.)):
            with self.assertRaises(ValueError):
                decode_month(lzma.compress(raw), now.replace(day=1), now)

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
