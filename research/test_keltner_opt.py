import pandas as pd
import numpy as np

# اختبار وتطوير استراتيجية Keltner Squeeze 1H لتكون استراتيجية سريعة نشطة ومربحة
df1h = pd.read_csv("research/btc_1h.csv", parse_dates=["ts"])
c, o, h, l, v = df1h.close.values, df1h.open.values, df1h.high.values, df1h.low.values, df1h.volume.values

tr1h = pd.concat([df1h.high - df1h.low, (df1h.high - df1h.close.shift()).abs(), (df1h.low - df1h.close.shift()).abs()], axis=1).max(axis=1)
atr = tr1h.ewm(alpha=1/14, adjust=False).mean().values

sma20 = df1h.close.rolling(20).mean().values
std20 = df1h.close.rolling(20).std().values
bb_up = sma20 + 2.0 * std20
bb_lo = sma20 - 2.0 * std20

kelt_up = sma20 + 1.5 * atr
kelt_lo = sma20 - 1.5 * atr

# Squeeze: بولينجر داخل كيلتنر
squeeze_on = (bb_up < kelt_up) & (bb_lo > kelt_lo)
squeeze_fired = pd.Series(squeeze_on).shift(1).fillna(False).values & (~squeeze_on)

v20 = df1h.volume.rolling(20).mean().values
ema50 = df1h.close.ewm(span=50, adjust=False).mean().values

for vol_mult in (1.0, 1.2):
    for rr in (1.8, 2.2, 2.5):
        long_sq = squeeze_fired & (c > bb_up) & (v > vol_mult * v20) & (c > ema50)
        short_sq = squeeze_fired & (c < bb_lo) & (v > vol_mult * v20) & (c < ema50)
        sig = np.where(long_sq, 1, np.where(short_sq, -1, 0))
        
        trades = []
        n = len(df1h)
        i = 50
        while i < n - 2:
            s = sig[i]
            if s == 0: i += 1; continue
            entry = o[i+1]
            dist = 1.5 * atr[i]
            stop = entry - s * dist
            tp = entry + s * rr * dist
            best = entry
            j = i + 1
            res = None
            while j < min(n, i + 1 + 36):
                if s > 0:
                    if l[j] <= stop: res = (stop - entry) / dist; break
                    if h[j] >= tp: res = rr; break
                    best = max(best, h[j])
                else:
                    if h[j] >= stop: res = (entry - stop) / dist; break
                    if l[j] <= tp: res = rr; break
                    best = min(best, l[j])
                # تأمين الوقف لنقطة الدخول عند +1R
                if s * (best - entry) >= 1.0 * dist:
                    stop = max(stop, entry) if s > 0 else min(stop, entry)
                j += 1
            if res is None: res = s * (c[j-1] - entry) / dist
            trades.append((df1h.ts.iloc[i+1], s, res - 0.0008 * entry / dist, j - i))
            i = j
        tdf = pd.DataFrame(trades, columns=["ts", "side", "r", "bars"])
        if len(tdf) == 0: continue
        t_oos = tdf[tdf.ts >= pd.Timestamp("2024-01-01", tz="UTC")]
        t_7d = tdf[tdf.ts >= df1h.ts.iloc[-1] - pd.Timedelta(days=7)]
        days = (tdf.ts.iloc[-1] - tdf.ts.iloc[0]).days
        pos_r = tdf[tdf.r > 0].r.sum(); neg_r = -tdf[tdf.r < 0].r.sum()
        pf = pos_r / neg_r if neg_r > 0 else 0
        pos_oos = t_oos[t_oos.r > 0].r.sum(); neg_oos = -t_oos[t_oos.r < 0].r.sum()
        pf_oos = pos_oos / neg_oos if neg_oos > 0 else 0
        w = (tdf.r > 0).mean() * 100
        print(f"Keltner (v>{vol_mult}, rr={rr}): N={len(tdf)} ({len(tdf)/days*7:.1f}/wk) | Win={w:.1f}% | PF={pf:.2f} | OOS PF={pf_oos:.2f} | Tot R={tdf.r.sum():+.1f}R | 7D: {len(t_7d)} ({t_7d.r.sum():+.2f}R)")
