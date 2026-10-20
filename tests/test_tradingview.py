import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import pandas as pd

from idx_monitor.tradingview import encode, unpack, get_bars, completed_idx, gold_history
from idx_monitor.data_sync import sync


class TradingViewTests(unittest.TestCase):
    def idx(self):
        frame = pd.DataFrame({'time':pd.to_datetime(['2026-10-19T02:00Z','2026-10-20T02:00Z']),
                              'open':[100.,101.], 'high':[105.,106.], 'low':[95.,96.],
                              'close':[102.,103.], 'volume':[1000.,1001.]})
        frame.attrs.update(currency_code='IDR', timezone='Asia/Bangkok', bar_close_time=1792489199)
        return frame

    def test_idx_excludes_open_session_and_delayed_close(self):
        for stamp, count in [('2026-10-20T07:00Z',1),('2026-10-20T09:45Z',1),('2026-10-20T10:00Z',2)]:
            result = completed_idx(self.idx(), now=stamp)
            self.assertEqual(len(result),count)
            self.assertEqual(result.index[0],'2026-10-19')

    def test_protocol_handles_fragmented_frames_heartbeat_and_updates(self):
        def msg(method,params):
            return encode(json.dumps({'m':method,'p':params}).encode())
        raw = msg('symbol_resolved',['cs','symbol_1',{'currency_code':'USD'}])
        bars = msg('timescale_update',['cs',{'s1':{'s':[{'v':[1792454400,2000,2002,1999,2001,10]}]}}])
        completed = msg('series_completed',['cs','s1','streaming','s1'])
        class Socket:
            def __init__(self):
                self.packets=iter([encode(b'~h~1'),raw[:10],raw[10:]+bars+completed]); self.sent=[]; self.closed=False
            def recv(self): return next(self.packets)
            def send(self,value): self.sent.append(value)
            def settimeout(self,value): pass
            def close(self): self.closed=True
        socket=Socket()
        with patch('idx_monitor.tradingview.create_connection',return_value=socket):
            result=get_bars('OANDA:XAUUSD','60',5)
        self.assertEqual(result.iloc[0].close,2001.)
        self.assertEqual(str(result.time.dt.tz),'UTC')
        self.assertTrue(socket.closed)
        self.assertIn('"adjustment": "none"', ''.join(socket.sent).replace('\\"','"'))
        self.assertIn(encode(b'~h~1').decode(),socket.sent)
        self.assertEqual(unpack(raw[:10]),([],raw[:10]))

    def test_partial_response_is_not_accepted(self):
        class Socket:
            closed=False
            def send(self,_): pass
            def settimeout(self,_): pass
            def recv(self): return ''
            def close(self): self.closed=True
        socket=Socket()
        with patch('idx_monitor.tradingview.create_connection',return_value=socket):
            with self.assertRaisesRegex(ValueError,'disconnected'):
                get_bars('IDX:BBCA','1D',500)
        self.assertTrue(socket.closed)

    def test_gold_uses_completed_utc_close_times_and_rejects_corrupt_prices(self):
        times=pd.date_range(end='2026-10-20T07:00Z',periods=1700,freq='h')
        frame=pd.DataFrame({'time':times,'open':2000.,'high':2002.,'low':1999.,'close':2001.})
        frame.attrs['currency_code']='USD'
        with patch('idx_monitor.tradingview.get_bars'):
            result=gold_history(now='2026-10-20T07:30Z',fetch=lambda *args:frame)
        self.assertEqual(len(result),1699)
        self.assertEqual(result.time.iloc[-1],pd.Timestamp('2026-10-20T07:00Z'))
        frame.loc[0,'high']=1
        with self.assertRaisesRegex(ValueError,'OHLC'):
            gold_history(now='2026-10-20T07:30Z',fetch=lambda *args:frame)

    def test_default_idx_provider_records_source_and_preserves_csv_on_failure(self):
        times=pd.date_range('2026-01-01',periods=100,tz='UTC')
        frame=pd.DataFrame({'time':times,'open':100.,'high':105.,'low':95.,'close':102.,'volume':1000.})
        frame.attrs.update(currency_code='IDR',timezone='Asia/Bangkok')
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'idx.csv'
            with patch('idx_monitor.tradingview.get_bars',return_value=frame) as fetch:
                self.assertEqual(sync(path),500)
                self.assertEqual(fetch.call_count,5)
            saved=path.read_bytes()
            self.assertIn('TradingView unofficial free',path.read_text())
            with patch('idx_monitor.tradingview.get_bars',side_effect=TimeoutError('offline')):
                with self.assertRaises(TimeoutError): sync(path)
            self.assertEqual(path.read_bytes(),saved)
