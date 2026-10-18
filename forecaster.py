"""XAUUSD multi-horizon directional research. UTC hourly candle-close CSV input."""
import argparse
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score, balanced_accuracy_score, confusion_matrix, log_loss

HORIZONS = (1, 4, 8, 24)
NAMES = np.array(["BEARISH", "NEUTRAL", "BULLISH"])
CLASSES = np.array([0, 1, 2])

def load_csv(path):
    d = pd.read_csv(path)
    d.columns = d.columns.str.strip().str.lower()
    if "datetime" in d and "time" not in d:
        d = d.rename(columns={"datetime": "time"})
    if not {"time", "open", "high", "low", "close"}.issubset(d):
        raise ValueError("CSV requires time,open,high,low,close")
    d["time"] = pd.to_datetime(d["time"], utc=True)
    d = d.set_index("time").sort_index()
    if d.index.has_duplicates:
        raise ValueError("Duplicate timestamps")
    for col in ("open", "high", "low", "close"):
        d[col] = pd.to_numeric(d[col], errors="raise")
    if ((d.low > d.high) | (d.close < d.low) | (d.close > d.high)).any():
        raise ValueError("Invalid OHLC values")
    return d

def indicators(d, dxy=None):
    d = d.copy()
    pc = d.close.shift()
    tr = pd.concat([(d.high-d.low), (d.high-pc).abs(), (d.low-pc).abs()], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    d["ema50"] = d.close.ewm(span=50, adjust=False).mean()
    d["ema200"] = d.close.ewm(span=200, adjust=False).mean()
    delta = d.close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    d["rsi"] = 100-100/(1+gain/loss.replace(0,np.nan))
    up, down = d.high.diff(), -d.low.diff()
    plus = up.where((up>down)&(up>0),0).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    minus = down.where((down>up)&(down>0),0).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    d["pdi"] = 100*plus/d.atr.replace(0,np.nan)
    d["mdi"] = 100*minus/d.atr.replace(0,np.nan)
    dx = 100*(d.pdi-d.mdi).abs()/(d.pdi+d.mdi).replace(0,np.nan)
    d["adx"] = dx.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    for n in (1,4,24):
        d[f"ret{n}"] = d.close.pct_change(n)
    d["ema_spread"] = (d.ema50-d.ema200)/d.atr.replace(0,np.nan)
    d["ema_distance"] = (d.close-d.ema50)/d.atr.replace(0,np.nan)
    d["range_atr"] = (d.high-d.low)/d.atr.replace(0,np.nan)
    # Seven-bar pivot becomes known only three bars after its center.
    highpivot = d.high.where(d.high.eq(d.high.rolling(7,center=True).max())).shift(3).ffill()
    lowpivot = d.low.where(d.low.eq(d.low.rolling(7,center=True).min())).shift(3).ffill()
    d["bos_up"] = ((d.close>highpivot)&(pc<=highpivot.shift())).astype(int).rolling(6).max()
    d["bos_down"] = ((d.close<lowpivot)&(pc>=lowpivot.shift())).astype(int).rolling(6).max()
    h4 = d[["open","high","low","close"]].resample("4h",label="right",closed="right").agg(
        {"open":"first","high":"max","low":"min","close":"last"}).dropna()
    # Only complete 4-hour buckets can be consumed.
    counts = d.close.resample("4h",label="right",closed="right").count()
    h4 = h4.loc[counts.eq(4)]
    h4["ema200"] = h4.close.ewm(span=200,adjust=False).mean()
    d["h4_up"] = (h4.close>h4.ema200).astype(float).reindex(d.index,method="ffill")
    d["h4_down"] = (h4.close<h4.ema200).astype(float).reindex(d.index,method="ffill")
    d["hour_sin"] = np.sin(2*np.pi*d.index.hour/24)
    d["hour_cos"] = np.cos(2*np.pi*d.index.hour/24)
    if dxy is not None:
        aligned = dxy.close.reindex(d.index,method="ffill",tolerance=pd.Timedelta("6h"))
        d["dxy_ret4"] = aligned.pct_change(4,fill_method=None)
    return d

def rule_signal(d, has_dxy):
    bull = ((d.h4_up==1).astype(int)+(d.ema50>d.ema200).astype(int)
            +(d.rsi>55).astype(int)+((d.adx>20)&(d.pdi>d.mdi)).astype(int)
            +d.bos_up.fillna(0).astype(int))
    bear = ((d.h4_down==1).astype(int)+(d.ema50<d.ema200).astype(int)
            +(d.rsi<45).astype(int)+((d.adx>20)&(d.mdi>d.pdi)).astype(int)
            +d.bos_down.fillna(0).astype(int))
    if has_dxy:
        bull += (d.dxy_ret4<0).astype(int)
        bear += (d.dxy_ret4>0).astype(int)
    return np.where((bull>=4)&(bull-bear>=2),2,
                    np.where((bear>=4)&(bear-bull>=2),0,1))

def aligned_probs(model, x):
    p = np.full((len(x),3),1e-9)
    raw = model.predict_proba(x)
    for j,c in enumerate(model.classes_):
        p[:,int(c)] = raw[:,j]
    return p/p.sum(axis=1,keepdims=True)

def temperature(p, y):
    def apply(t):
        z = np.log(np.clip(p,1e-9,1))/t
        z -= z.max(axis=1,keepdims=True)
        ex = np.exp(z)
        return ex/ex.sum(axis=1,keepdims=True)
    opt = minimize_scalar(lambda t:log_loss(y,apply(t),labels=CLASSES),
                          bounds=(.3,5),method="bounded")
    return opt.x,apply

def score(y, pred, prob=None):
    out = {"samples":len(y),"accuracy":float(accuracy_score(y,pred)),
           "balanced_accuracy":float(balanced_accuracy_score(y,pred)),
           "coverage":float(np.mean(pred!=1)),
           "confusion_matrix":confusion_matrix(y,pred,labels=CLASSES).tolist()}
    if prob is not None:
        out["log_loss"] = float(log_loss(y,prob,labels=CLASSES))
        out["brier"] = float(np.mean(np.sum((prob-np.eye(3)[y])**2,axis=1)))
    return out

def run(args):
    d = indicators(load_csv(args.xau),load_csv(args.dxy) if args.dxy else None)
    cols = ["atr","rsi","adx","pdi","mdi","ret1","ret4","ret24","ema_spread",
            "ema_distance","range_atr","bos_up","bos_down","h4_up","h4_down",
            "hour_sin","hour_cos"]
    if args.dxy: cols.append("dxy_ret4")
    out = Path(args.out)
    out.mkdir(parents=True,exist_ok=True)
    report = {}
    for horizon in HORIZONS:
        future_time = d.index.to_series().shift(-horizon)
        exact = (future_time-d.index.to_series()).eq(pd.Timedelta(hours=horizon))
        delta = d.close.shift(-horizon)-d.close
        band = args.threshold_atr*d.atr
        target = pd.Series(np.where(delta>band,2,np.where(delta< -band,0,1)),index=d.index)
        valid = exact & delta.notna() & d[cols].notna().all(axis=1) & (d.atr>0)
        frame = d.loc[valid]
        y = target.loc[valid].to_numpy(dtype=int)
        n = len(frame)
        if n<1200:
            print(f"{horizon}h skipped: only {n} valid observations")
            continue
        a,b = int(.6*n),int(.8*n)
        train = np.arange(0,a-horizon)
        val = np.arange(a,b-horizon)
        test = np.arange(b,n)
        if len(np.unique(y[train]))<2:
            print(f"{horizon}h skipped: insufficient training classes")
            continue
        x = frame[cols]
        candidates = [
            ("logistic",make_pipeline(SimpleImputer(strategy="median"),StandardScaler(),
                 LogisticRegression(max_iter=1500,class_weight="balanced"))),
            ("boosting",make_pipeline(SimpleImputer(strategy="median"),
                 HistGradientBoostingClassifier(max_iter=180,max_leaf_nodes=15,
                                                learning_rate=.05,l2_regularization=5,random_state=42)))
        ]
        fitted = []
        for name,model in candidates:
            model.fit(x.iloc[train],y[train])
            t,apply = temperature(aligned_probs(model,x.iloc[val]),y[val])
            loss = log_loss(y[val],apply(t),labels=CLASSES)
            fitted.append((loss,name,model,t))
        _,name,model,t = min(fitted,key=lambda item:item[0])
        def calibrated(z):
            raw = aligned_probs(model,z)
            logits = np.log(np.clip(raw,1e-9,1))/t
            logits -= logits.max(axis=1,keepdims=True)
            e = np.exp(logits)
            return e/e.sum(axis=1,keepdims=True)
        prob = calibrated(x.iloc[test])
        pred = np.where(prob.max(axis=1)>=args.min_prob,prob.argmax(axis=1),1)
        baseline = np.full(len(test),np.bincount(y[train],minlength=3).argmax())
        rules = rule_signal(frame.iloc[test],bool(args.dxy))
        report[f"{horizon}h"] = {
            "model":name,"test_start":str(frame.index[test[0]]),
            "test_end":str(frame.index[test[-1]]),
            "test":score(y[test],pred,prob),
            "rule_based":score(y[test],rules),
            "majority_baseline":score(y[test],baseline)}
        pd.DataFrame({"time":frame.index[test],"actual":NAMES[y[test]],
            "predicted":NAMES[pred],"p_bearish":prob[:,0],
            "p_neutral":prob[:,1],"p_bullish":prob[:,2]}).to_csv(
                out/f"predictions_{horizon}h.csv",index=False)
        latest = d.dropna(subset=cols).iloc[[-1]]
        p = calibrated(latest[cols])[0]
        choice = int(p.argmax()) if p.max()>=args.min_prob else 1
        report[f"{horizon}h"]["latest_forecast"] = {
            "as_of_utc":str(latest.index[-1]),"direction":str(NAMES[choice]),
            "p_bearish":float(p[0]),"p_neutral":float(p[1]),"p_bullish":float(p[2])}
        joblib.dump({"model":model,"temperature":t,"features":cols,
                     "min_prob":args.min_prob},out/f"model_{horizon}h.joblib")
        print(f"{horizon}h {name}: accuracy={report[f'{horizon}h']['test']['accuracy']:.3f}")
    (out/"report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")

if __name__=="__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--xau",required=True,help="H1 XAUUSD UTC close-time CSV")
    parser.add_argument("--dxy",help="Optional DXY H1 CSV")
    parser.add_argument("--out",default="results")
    parser.add_argument("--threshold-atr",type=float,default=.25)
    parser.add_argument("--min-prob",type=float,default=.50)
    run(parser.parse_args())
