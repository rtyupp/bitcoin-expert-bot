import pandas as pd
import numpy as np

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
ema100 = df1h.close.ewm(span=100, adjust=False).mean().values
v20 = df1h.volume.rolling(20).mean().values

long_s = squeeze_fired & (c > bb_up) & (v > 1.0 * v20) & (c > ema100)
short_s = squeeze_fired & (c < bb_lo) & (v > 1.0 * v20) & (c < ema100)
sig = np.where(long_s, 1, np.where(short_s, -1, 0))

for trail_mult in [None, 1.5, 2.0]:
    for rr in [2.0, 2.2, 2.5]:
        trades = []
        n = len(df1h)
        i = 50
        while i < n - 2:
            s = sig[i]
            if s == 0 or not np.isfinite(atr1h[i]): i += 1; continue
            entry = o[i+1]
            dist = 1.5 * atr1h[i]
            stop = entry - s * dist
            tp = entry + s * rr * dist if rr else None
            best = entry
            j = i + 1
            res = None
            while j < min(n, i + 1 + 36):
                if s > 0:
                    if l[j] <= stop: res = (stop - entry) / dist; break
                    if tp and h[j] >= tp: res = rr; break
                    best = max(best, h[j])
                else:
                    if h[j] >= stop: res = (entry - stop) / dist; break
                    if tp and l[j] <= tp: res = rr; break
                    best = min(best, l[j])
                # تأمين الوقف لنقطة الدخول عند +1R
                if s * (best - entry) >= 1.0 * dist:
                    stop = max(stop, entry) if s > 0 else min(stop, entry)
                if trail_mult:
                    ns = best - s * trail_mult * dist
                    stop = max(stop, ns) if s > 0 else min(stop, ns)
                j += 1
            if res is None: res = s * (c[j-1] - entry) / dist
            trades.append((df1h.ts.iloc[i+1], s, res - 0.0008 * entry / dist, j - i))
            i = j
        tdf = pd.DataFrame(trades, columns=["ts", "side", "r", "bars"])
        t_oos = tdf[tdf.ts >= pd.Timestamp("2024-01-01", tz="UTC")]
        pos_r = tdf[tdf.r > 0].r.sum(); neg_r = -tdf[tdf.r < 0].r.sum()
        pf = pos_r / neg_r if neg_r > 0 else 0
        pos_oos = t_oos[t_oos.r > 0].r.sum(); neg_oos = -t_oos[t_oos.r < 0].r.sum()
        pf_oos = pos_oos / neg_oos if neg_oos > 0 else 0
        w = (tdf.r > 0).mean() * 100
        print(f"rr={rr} | trail={trail_mult} | Win={w:.1f}% | PF={pf:.2f} | OOS PF={pf_oos:.2f} | Tot R={tdf.r.sum():+.1f}R")
