import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from idx_monitor.history import record_gold, resolve_gold, read_history, feedback, record_idx
from idx_monitor.web import render_history


class HistoryTests(unittest.TestCase):
    def report(self, stamp, prediction='BULLISH', model='logistic', symbol='OANDA:XAUUSD'):
        return {'metadata':{'source':'test feed','symbol':symbol}, **{
            f'{h}h': {'model':model,'model_version':'original-version',
                      'latest_forecast':{'as_of_utc':stamp,'direction':prediction,
                                         'p_bearish':.1,'p_neutral':.2,'p_bullish':.7},
                      'forecast_snapshot':{'base_price':100.,'band':1.,'features':{'rsi':55.},
                        'candidate_probabilities':{'logistic':[.1,.1,.8],'boosting':[.8,.1,.1]}}}
            for h in (1,4,8,24)}}

    def test_n0_n1_n2_are_persisted_and_original_predictions_never_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'history.sqlite'
            record_gold(db,self.report('2026-10-20T00:00Z'),'2026-10-20T00:05Z')
            # A later model on the same candle must not rewrite the original.
            record_gold(db,self.report('2026-10-20T00:00Z','BEARISH','boosting'),'2026-10-20T00:10Z')
            self.assertEqual(read_history(db,'gold')['total'],4)
            frame=pd.DataFrame({'time':pd.to_datetime(['2026-10-20T01:00Z','2026-10-20T02:00Z']), 'close':[98.,103.]})
            resolve_gold(db,frame,'test feed','OANDA:XAUUSD','2026-10-20T01:05Z')
            first=next(row for row in read_history(db,'gold')['recent'] if row['horizon']=='1h')
            self.assertEqual(first['prediction'],'BULLISH')
            self.assertEqual(first['model'],'logistic')
            self.assertEqual(first['snapshot']['features'],{'rsi':55.})
            self.assertEqual(first['actual'],'BEARISH')
            self.assertFalse(first['correct'])
            record_gold(db,self.report('2026-10-20T01:00Z'),'2026-10-20T01:05Z')
            resolve_gold(db,frame,'test feed','OANDA:XAUUSD','2026-10-20T02:05Z')
            state=read_history(db,'gold')
            self.assertEqual(state['resolved'],2)
            self.assertEqual(state['accuracy'],.5)
            self.assertEqual(state['total'],8)
            # Revised provider data cannot rewrite a previously scored outcome.
            frame['close']=110.
            resolve_gold(db,frame,'test feed','OANDA:XAUUSD','2026-10-20T02:10Z')
            first=next(row for row in read_history(db,'gold')['recent'] if row['as_of'].startswith('2026-10-20T00') and row['horizon']=='1h')
            self.assertEqual(first['actual_price'],98.)

    def test_missing_target_future_prices_and_other_feeds_are_not_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'history.sqlite'
            record_gold(db,self.report('2026-10-20T00:00Z'),'2026-10-20T00:05Z')
            frame=pd.DataFrame({'time':pd.to_datetime(['2026-10-20T02:00Z','2026-10-20T04:00Z']), 'close':[110.,110.]})
            resolve_gold(db,frame,'test feed','another feed','2026-10-20T02:00Z')
            self.assertEqual(read_history(db,'gold')['waiting_data'],0)
            resolve_gold(db,frame,'test feed','OANDA:XAUUSD','2026-10-20T02:00Z')
            state=read_history(db,'gold')
            self.assertEqual(state['resolved'],0)
            self.assertEqual(state['waiting_data'],1)
            self.assertEqual(state['pending'],3)
            # A late arriving exact candle can resolve it on the next poll.
            frame=pd.DataFrame({'time':pd.to_datetime(['2026-10-20T01:00Z']), 'close':[100.5]})
            resolve_gold(db,frame,'test feed','OANDA:XAUUSD','2026-10-20T03:00Z')
            self.assertEqual(read_history(db,'gold')['resolved'],1)

    def test_forecasts_issued_after_target_are_not_scored(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'history.sqlite'
            record_gold(db,self.report('2026-10-20T00:00Z'),'2026-10-20T06:00Z')
            frame=pd.DataFrame({'time':pd.to_datetime(['2026-10-20T01:00Z','2026-10-20T04:00Z']), 'close':[110.,110.]})
            resolve_gold(db,frame,'test feed','OANDA:XAUUSD','2026-10-20T07:00Z')
            state=read_history(db,'gold')
            self.assertEqual(state['expired'],2)
            self.assertEqual(state['scored'],0)

    def test_feedback_needs_30_observable_outcomes_and_uses_candidate_losses(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'history.sqlite'
            start=pd.Timestamp('2026-10-01T00:00Z')
            for i in range(30):
                stamp=start+pd.Timedelta(hours=i)
                record_gold(db,self.report(stamp.isoformat()),stamp+pd.Timedelta(minutes=5))
            frame=pd.DataFrame({'time':pd.date_range(start+pd.Timedelta(hours=1),periods=30,freq='h'), 'close':[98.]*30})
            cutoff=start+pd.Timedelta(hours=31)
            resolve_gold(db,frame,'test feed','OANDA:XAUUSD',cutoff)
            self.assertEqual(feedback(db,'test feed','OANDA:XAUUSD',cutoff-pd.Timedelta(minutes=1)),{})
            scores=feedback(db,'test feed','OANDA:XAUUSD',cutoff)
            self.assertEqual(scores['1h']['samples'],30)
            self.assertEqual(scores['1h']['preferred_model'],'boosting')
            self.assertNotIn('4h',scores)  # Only 27 outcomes for 4h.

    def test_idx_uses_next_trading_session_and_watch_abstains(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'idx.sqlite'
            def prices(dates,closes):
                return pd.DataFrame({'date':pd.to_datetime(dates),'ticker':'BBCA','source':'test feed','feed':'IDX:BBCA',
                                     'close':closes,'open':closes,'high':closes,'low':closes,'volume':1000.,
                                     'signal':'BUY_CANDIDATE','rsi14':55.,'ema20':99.,'ema50':98.})
            friday=prices(['2026-10-16'],[100.])
            with patch('idx_monitor.core.signals',side_effect=lambda frame:frame):
                record_idx(db,friday,'2026-10-16T11:00Z')
                monday=prices(['2026-10-16','2026-10-19'],[100.,105.])
                monday.loc[1,'signal']='WATCH'
                record_idx(db,monday,'2026-10-19T11:00Z')
                tuesday=prices(['2026-10-16','2026-10-19','2026-10-20'],[100.,105.,90.])
                record_idx(db,tuesday,'2026-10-20T11:00Z')
            state=read_history(db,'idx')
            self.assertEqual(state['resolved'],2)
            self.assertEqual(state['scored'],1)
            self.assertEqual(state['accuracy'],1.)
            monday=next(row for row in state['recent'] if row['prediction']=='ABSTAIN')
            self.assertEqual(monday['actual'],'BEARISH')
            self.assertIsNone(monday['correct'])
            self.assertIn('Published predictions',render_history(state))
            self.assertNotIn('<script>',render_history({'recent':[{'symbol':'<script>','snapshot':{}}]}))
