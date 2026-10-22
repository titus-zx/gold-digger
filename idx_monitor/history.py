"""Persistent first-publication ledger. Outcomes never rewrite original predictions."""
from contextlib import contextmanager, closing
import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

SCHEMA = '''
CREATE TABLE IF NOT EXISTS forecasts (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, source TEXT NOT NULL, symbol TEXT NOT NULL,
 as_of TEXT NOT NULL, issued_at TEXT NOT NULL, horizon TEXT NOT NULL,
 target_at TEXT, base_price REAL NOT NULL, band REAL NOT NULL,
 prediction TEXT NOT NULL, model TEXT NOT NULL, model_version TEXT,
 snapshot TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
 actual_at TEXT, actual_price REAL, actual TEXT, correct INTEGER,
 return_pct REAL, resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS forecast_lookup ON forecasts(kind, source, symbol, status);
'''


def utc(value):
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        raise ValueError("History timestamps must include a timezone")
    return stamp.tz_convert('UTC').isoformat()


@contextmanager
def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    try:
        with db:
            yield db
    finally:
        db.close()


def direction(change, band):
    return 'BULLISH' if change > band else 'BEARISH' if change < -band else 'NEUTRAL'


def insert(db, *, kind, source, symbol, as_of, issued_at, horizon, target_at,
           base_price, band, prediction, model, snapshot, model_version=None):
    as_of, issued_at = utc(as_of), utc(issued_at)
    target_at = utc(target_at) if target_at is not None else None
    if not np.isfinite([base_price, band]).all() or base_price <= 0 or band < 0:
        raise ValueError('Invalid forecast reference price/band')
    identity = hashlib.sha256(json.dumps([kind, source, symbol, as_of, horizon]).encode()).hexdigest()
    # Repeated polls of the same candle cannot replace the original prediction.
    status = 'expired' if target_at and target_at <= issued_at else 'pending'
    db.execute('''INSERT OR IGNORE INTO forecasts
        (id,kind,source,symbol,as_of,issued_at,horizon,target_at,base_price,band,
         prediction,model,model_version,snapshot,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (identity,kind,source,symbol,as_of,issued_at,horizon,target_at,float(base_price),float(band),
         prediction,model,model_version,json.dumps(snapshot,allow_nan=False),status))


def resolve_gold(path, frame, source, symbol, now):
    now = utc(now)
    closes = {utc(row.time):float(row.close) for row in frame.itertuples() if utc(row.time) <= now}
    with connect(path) as db:
        for row in db.execute("SELECT * FROM forecasts WHERE kind='gold' AND source=? AND symbol=? AND status IN ('pending','waiting_data')", (source,symbol)).fetchall():
            target = row['target_at']
            if target > now:
                continue
            if target not in closes:
                db.execute("UPDATE forecasts SET status='waiting_data' WHERE id=?",(row['id'],))
                continue
            price = closes[target]
            actual = direction(price-row['base_price'], row['band'])
            db.execute('''UPDATE forecasts SET status='resolved',actual_at=?,actual_price=?,actual=?,
                correct=?,return_pct=?,resolved_at=? WHERE id=?''',
                (target,price,actual,int(actual==row['prediction']),100*(price/row['base_price']-1),now,row['id']))


def record_gold(path, report, issued_at):
    meta = report['metadata']
    with connect(path) as db:
        for horizon in ('1h','4h','8h','24h'):
            item = report[horizon]
            latest = item['latest_forecast']
            snapshot = item.get('forecast_snapshot')
            if snapshot is None:
                continue  # Legacy/manual reports cannot invent feature/threshold snapshots.
            target = pd.Timestamp(latest['as_of_utc']) + pd.Timedelta(hours=int(horizon[:-1]))
            insert(db,kind='gold',source=meta['source'],symbol=meta['symbol'],
                   as_of=latest['as_of_utc'],issued_at=issued_at,horizon=horizon,target_at=target,
                   base_price=snapshot['base_price'],band=snapshot['band'],prediction=latest['direction'],
                   model=item['model'],model_version=item.get('model_version'),
                   snapshot={**snapshot,'probabilities':{key:latest[key] for key in ('p_bearish','p_neutral','p_bullish')}})


def feedback(path, source, symbol, cutoff, minimum=30, window=200):
    """Select candidates using only resolved forecasts observable by cutoff."""
    result = {}
    with connect(path) as db:
        for horizon in ('1h','4h','8h','24h'):
            rows = db.execute('''SELECT actual,snapshot FROM forecasts WHERE kind='gold' AND source=?
                AND symbol=? AND horizon=? AND status='resolved' AND resolved_at<=? AND actual_at<=?
                ORDER BY actual_at DESC LIMIT ?''',(source,symbol,horizon,utc(cutoff),utc(cutoff),window)).fetchall()
            losses = {'logistic':[], 'boosting':[]}
            for row in rows:
                candidates = json.loads(row['snapshot']).get('candidate_probabilities',{})
                label = ('BEARISH','NEUTRAL','BULLISH').index(row['actual'])
                if not all(name in candidates for name in losses):
                    continue
                for name in losses:
                    losses[name].append(float(-np.log(np.clip(candidates[name][label],1e-9,1))))
            samples = len(losses['logistic'])
            if samples >= minimum:
                scores = {name:float(np.mean(values)) for name,values in losses.items()}
                result[horizon] = {'samples':samples,'log_loss':scores,
                                   'preferred_model':min(scores,key=scores.get)}
    return result


def record_idx(path, prices, issued_at):
    from .core import signals
    issued_at = utc(issued_at)
    with connect(path) as db:
        for ticker, group in prices.groupby('ticker'):
            group = group.sort_values('date')
            source = str(group.iloc[-1].get('source','Legacy local CSV'))
            feed = str(group.iloc[-1].get('feed',ticker))
            # Evaluate against the first subsequent completed session, never a fixed calendar day.
            for old in db.execute("SELECT * FROM forecasts WHERE kind='idx' AND source=? AND symbol=? AND status='pending'",(source,feed)).fetchall():
                base_date = pd.Timestamp(old['as_of']).tz_convert('Asia/Jakarta').date()
                future = group.loc[pd.to_datetime(group.date).dt.date > base_date]
                if future.empty:
                    continue
                actual_row = future.iloc[0]
                session_open = pd.Timestamp(actual_row.date).tz_localize('Asia/Jakarta') + pd.Timedelta(hours=9)
                # Only score forecasts issued before the evaluated session opened.
                if pd.Timestamp(old['issued_at']) >= session_open:
                    db.execute("UPDATE forecasts SET status='expired' WHERE id=?",(old['id'],))
                    continue
                price = float(actual_row.close)
                actual = direction(price-old['base_price'],old['band'])
                actual_at = pd.Timestamp(actual_row.date).tz_localize('Asia/Jakarta') + pd.Timedelta(hours=16,minutes=40)
                correct = None if old['prediction']=='ABSTAIN' else int(actual==old['prediction'])
                db.execute('''UPDATE forecasts SET status='resolved',target_at=?,actual_at=?,actual_price=?,
                    actual=?,correct=?,return_pct=?,resolved_at=? WHERE id=?''',
                    (utc(actual_at),utc(actual_at),price,actual,correct,100*(price/old['base_price']-1),issued_at,old['id']))
            row = signals(group).iloc[-1]
            expected = {'BUY_CANDIDATE':'BULLISH','RISK_OFF':'BEARISH','WATCH':'ABSTAIN'}[row.signal]
            as_of = pd.Timestamp(row.date).tz_localize('Asia/Jakarta') + pd.Timedelta(hours=16,minutes=40)
            snapshot = {'signal':row.signal,'rsi14':None if pd.isna(row.rsi14) else float(row.rsi14),
                        'ema20':float(row.ema20),'ema50':float(row.ema50),'neutral_band_pct':1.0}
            insert(db,kind='idx',source=source,symbol=feed,as_of=as_of,issued_at=issued_at,
                   horizon='next_session',target_at=None,base_price=float(row.close),band=float(row.close)*.01,
                   prediction=expected,model='technical_rules_v1',snapshot=snapshot)


def read_history(path, kind, limit=100, offset=0):
    limit = max(1,min(int(limit),1000))
    offset = max(0,int(offset))
    path = Path(path)
    if not path.is_file():
        return {'limit':limit,'offset':offset,'total':0,'resolved':0,'pending':0,'waiting_data':0,
                'expired':0,'scored':0,'accuracy':None,'by_horizon':{},'recent':[]}
    # Read-only connection also works on the web service's read-only bind mounts.
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=30)) as db:
        db.row_factory = sqlite3.Row
        counts = {row['status']:row['n'] for row in db.execute('SELECT status,count(*) n FROM forecasts WHERE kind=? GROUP BY status',(kind,))}
        groups = {}
        for row in db.execute('''SELECT source,symbol,horizon,count(correct) scored,avg(correct) accuracy,
            count(*) resolved FROM forecasts WHERE kind=? AND status='resolved' GROUP BY source,symbol,horizon''',(kind,)):
            groups[f"{row['source']} | {row['symbol']} | {row['horizon']}"] = dict(row)
        scored = sum(row['scored'] for row in groups.values())
        accuracy = sum(row['scored']*row['accuracy'] for row in groups.values() if row['scored'])/scored if scored else None
        recent = []
        for row in db.execute('SELECT * FROM forecasts WHERE kind=? ORDER BY issued_at DESC,id LIMIT ? OFFSET ?',(kind,limit,offset)):
            item = dict(row)
            item['snapshot'] = json.loads(item['snapshot'])
            item['correct'] = bool(item['correct']) if item['correct'] is not None else None
            recent.append(item)
    return {'limit':limit,'offset':offset,'total':sum(counts.values()),'resolved':counts.get('resolved',0),
            'pending':counts.get('pending',0),'waiting_data':counts.get('waiting_data',0),
            'expired':counts.get('expired',0),'scored':scored,'accuracy':accuracy,'by_horizon':groups,'recent':recent}
