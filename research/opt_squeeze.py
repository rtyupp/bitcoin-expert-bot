import pandas as pd
import numpy as np

# تحسين وتصفية استراتيجية Keltner Squeeze 1H لرفع عامل الربح وتقليل الصفقات الخاسرة
df1h = pd.read_csv("research/btc_1h.csv", parse_dates=["ts"])
c, o, h, l, v = df1h.close.values, df1h.open.values, df1h.high.values, df1h.low.values, df1h.volume.values

tr1h = pd.concat([df1h.high - df1h.low, (df1h.high - df1h.close.shift()).abs(), (df1h.low - df1h.close.shift()).abs()], axis=1).max(axis=1)
atr1h = tr1h.ewm(alpha=1/14, adjust=False).mean().values

sma20 = df1h.close.rolling(20).mean().values
std20 = df1h.close.rolling(20).std().values
bb_up = sma20 + 2.0 * std20
bb_lo = sma20 - 2.0 * std20

kelt_up = sma20 + 1.5 * atr1h
kelt_lo = sma20 - 1.5 * atr1h

squeeze_on = (bb_up < kelt_up) & (bb_lo > kelt_lo)
squeeze_fired = pd.Series(squeeze_on).shift(1).fillna(False).values & (~squeeze_on)

ema50 = df1h.close.ewm(span=50, adjust=False).mean().values
ema100 = df1h.close.ewm(span=100, adjust=False).mean().values
ema200 = df1h.close.ewm(span=200, adjust=False).mean().values
v20 = df1h.volume.rolling(20).mean().values

up_d = df1h.high.diff()
dn_d = -df1h.low.diff()
pdm = np.where((up_d > dn_d) & (up_d > 0), up_d, 0.0)
ndm = np.where((dn_d > up_d) & (dn_d > 0), dn_d, 0.0)
pdi = 100 * pd.Series(pdm).ewm(alpha=1/14, adjust=False).mean() / atr1h
ndi = 100 * pd.Series(ndm).ewm(alpha=1/14, adjust=False).mean() / atr1h
dx = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
adx = dx.ewm(alpha=1/14, adjust=False).mean().values

filters = [
    ("Base (v>1.0, EMA50)", (c > bb_up) & (v > 1.0 * v20) & (c > ema50), (c < bb_lo) & (v > 1.0 * v20) & (c < ema50)),
    ("EMA100 Trend Align", (c > bb_up) & (v > 1.0 * v20) & (c > ema100), (c < bb_lo) & (v > 1.0 * v20) & (c < ema100)),
    ("EMA200 Trend Align", (c > bb_up) & (v > 1.0 * v20) & (c > ema200), (c < bb_lo) & (v > 1.0 * v20) & (c < ema200)),
    ("Vol > 1.3x", (c > bb_up) & (v > 1.3 * v20) & (c > ema50), (c < bb_lo) & (v > 1.3 * v20) & (c < ema50)),
    ("ADX > 20 (Strong Move)", (c > bb_up) & (adx > 20) & (c > ema50), (c < bb_lo) & (adx > 20) & (c < ema50)),
    ("EMA50 + ADX>20 + Vol>1.2", (c > bb_up) & (adx > 20) & (v > 1.2 * v20) & (c > ema50), (c < bb_lo) & (adx > 20) & (v > 1.2 * v20) & (c < ema50)),
]

for name, long_c, short_c in filters:
    long_s = squeeze_fired & long_c
    short_s = squeeze_fired & short_c
    sig = np.where(long_s, 1, np.where(short_s, -1, 0))
    
    trades = []
    n = len(df1h)
    i = 50
    while i < n - 2:
        s = sig[i]
        if s == 0 or not np.isfinite(atr1h[i]): i += 1; continue
        entry = o[i+1]
        dist = 1.5 * atr1h[i]
        stop = entry - s * dist
        tp = entry + s * 2.2 * dist
        best = entry
        j = i + 1
        res = None
        while j < min(n, i + 1 + 36):
            if s > 0:
                if l[j] <= stop: res = (stop - entry) / dist; break
                if h[j] >= tp: res = 2.2; break
                best = max(best, h[j])
            else:
                if h[j] >= stop: res = (entry - stop) / dist; break
                if l[j] <= tp: res = 2.2; break
                best = min(best, l[j])
            if s * (best - entry) >= 1.0 * dist:
                stop = max(stop, entry) if s > 0 else min(stop, entry)
            j += 1
        if res is None: res = s * (c[j-1] - entry) / dist
        trades.append((df1h.ts.iloc[i+1], s, res - 0.0008 * entry / dist, j - i))
        i = j
    tdf = pd.DataFrame(trades, columns=["ts", "side", "r", "bars"])
    if len(tdf) == 0: continue
    t_oos = tdf[tdf.ts >= pd.Timestamp("2024-01-01", tz="UTC")]
    days = (tdf.ts.iloc[-1] - tdf.ts.iloc[0]).days
    pos_r = tdf[tdf.r > 0].r.sum(); neg_r = -tdf[tdf.r < 0].r.sum()
    pf = pos_r / neg_r if neg_r > 0 else 0
    pos_oos = t_oos[t_oos.r > 0].r.sum(); neg_oos = -t_oos[t_oos.r < 0].r.sum()
    pf_oos = pos_oos / neg_oos if neg_oos > 0 else 0
    w = (tdf.r > 0).mean() * 100
    print(f"{name:26s} | N: {len(tdf):4d} ({len(tdf)/days*7:.1f}/wk) | Win: {w:.1f}% | PF: {pf:.2f} | OOS PF: {pf_oos:.2f} | Tot R: {tdf.r.sum():+.1f}R")
