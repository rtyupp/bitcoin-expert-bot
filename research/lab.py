"""مختبر الاستراتيجيات: شبكة معاملات على 2019-2023 (تدريب) ثم تحقق خارج العينة 2024-2026."""
import itertools, json, sys
import numpy as np, pandas as pd
sys.path.insert(0, "research")
from engine import *

def feats(df):
    f = pd.DataFrame(index=df.index)
    f["atr"] = atr(df)
    for n in (20, 50, 100, 200):
        f[f"e{n}"] = ema(df.close, n)
    f["rsi"] = rsi(df.close); f["rsi2"] = rsi(df.close, 2)
    f["adx"] = adx(df)
    f["v20"] = df.volume.rolling(20).mean()
    m = df.close.rolling(20).mean(); sd = df.close.rolling(20).std()
    f["bbu"], f["bbl"], f["bbw"] = m + 2 * sd, m - 2 * sd, 4 * sd / m
    return f

def S_donchian(df, f, n=55, filt=200, vol=0.0):
    hi = df.high.rolling(n).max().shift(); lo = df.low.rolling(n).min().shift()
    tr = f[f"e{filt}"]
    vok = df.volume > vol * f.v20
    long = (df.close > hi) & (df.close > tr) & vok
    short = (df.close < lo) & (df.close < tr) & vok
    return np.where(long, 1, np.where(short, -1, 0))

def S_pullback(df, f, filt=200, adxmin=20):
    up = (f.e20 > f.e50) & (f.e50 > f[f"e{filt}"]) & (f.adx > adxmin)
    dn = (f.e20 < f.e50) & (f.e50 < f[f"e{filt}"]) & (f.adx > adxmin)
    # لمس EMA20 ثم إغلاق باتجاه الترند
    long = up & (df.low.shift() <= f.e20.shift()) & (df.close > df.high.shift()) & (df.close > f.e20)
    short = dn & (df.high.shift() >= f.e20.shift()) & (df.close < df.low.shift()) & (df.close < f.e20)
    return np.where(long, 1, np.where(short, -1, 0))

def S_sweep(df, f, n=24, filt=200):
    lo = df.low.rolling(n).min().shift(); hi = df.high.rolling(n).max().shift()
    long = (df.low < lo) & (df.close > lo) & (df.close > df.open) & (df.close > f[f"e{filt}"])
    short = (df.high > hi) & (df.close < hi) & (df.close < df.open) & (df.close < f[f"e{filt}"])
    return np.where(long, 1, np.where(short, -1, 0))

def S_squeeze(df, f, q=0.2, filt=200):
    w = f.bbw; thr = w.rolling(250).quantile(q)
    sq = (w.shift() < thr.shift())
    long = sq & (df.close > f.bbu) & (df.close > f[f"e{filt}"])
    short = sq & (df.close < f.bbl) & (df.close < f[f"e{filt}"])
    return np.where(long, 1, np.where(short, -1, 0))

def S_rsi2(df, f, lvl=10, filt=200):
    long = (f.rsi2 < lvl) & (df.close > f[f"e{filt}"])
    short = (f.rsi2 > 100 - lvl) & (df.close < f[f"e{filt}"])
    return np.where(long, 1, np.where(short, -1, 0))

STRATS = {
    "donchian": (S_donchian, {"n": [20, 55, 100], "filt": [100, 200], "vol": [0, 1.3]}),
    "pullback": (S_pullback, {"filt": [100, 200], "adxmin": [15, 25]}),
    "sweep": (S_sweep, {"n": [12, 24, 48], "filt": [100, 200]}),
    "squeeze": (S_squeeze, {"q": [0.1, 0.2], "filt": [100, 200]}),
    "rsi2": (S_rsi2, {"lvl": [5, 10], "filt": [100, 200]}),
}
EXITS = [
    {"sm": 2.0, "rr": 2.0}, {"sm": 2.0, "rr": 3.0}, {"sm": 1.5, "rr": 2.0},
    {"sm": 2.0, "rr": None, "trail": 2.0}, {"sm": 3.0, "rr": None, "trail": 1.0},
    {"sm": 2.0, "rr": 3.0, "be": 1.0},
]

out = []
for tf in sys.argv[1:]:
    df = load(tf); f = feats(df)
    for name, (fn, grid) in STRATS.items():
        keys = list(grid)
        for vals in itertools.product(*[grid[k] for k in keys]):
            p = dict(zip(keys, vals))
            sig = fn(df, f, **p)
            for ex in EXITS:
                for side in ("both", "long"):
                    s = sig.copy() if side == "both" else np.where(sig > 0, 1, 0)
                    t = run(df, s, f.atr.values * ex["sm"], rr=ex.get("rr"), trail=ex.get("trail"), be_at=ex.get("be"))
                    tin, tout = split(t)
                    a, b = stats(tin), stats(tout)
                    out.append({"tf": tf, "strat": name, **p, **{f"x_{k}": v for k, v in ex.items()}, "side": side,
                                "in_n": a.get("n"), "in_pf": a.get("pf"), "in_exp": a.get("exp"), "in_dd": a.get("maxDD_R"), "in_years": a.get("pos_years"),
                                "out_n": b.get("n"), "out_pf": b.get("pf"), "out_exp": b.get("exp"), "out_dd": b.get("maxDD_R"), "out_win": b.get("win")})
    print(tf, "done", flush=True)
pd.DataFrame(out).to_csv(f"research/lab_{'_'.join(sys.argv[1:])}.csv", index=False)
