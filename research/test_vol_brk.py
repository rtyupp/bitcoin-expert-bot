import pandas as pd
import numpy as np

# اختبار استراتيجيات اختراق وتدفق الزخم على 1h (ساعة بساعة) مع أهداف سريعة
df = pd.read_csv("research/btc_1h.csv", parse_dates=["ts"])
c, o, h, l, v = df.close.values, df.open.values, df.high.values, df.low.values, df.volume.values

tr = pd.concat([df.high - df.low, (df.high - df.close.shift()).abs(), (df.low - df.close.shift()).abs()], axis=1).max(axis=1)
atr = tr.ewm(alpha=1/14, adjust=False).mean().values

ema20 = df.close.ewm(span=20, adjust=False).mean().values
ema50 = df.close.ewm(span=50, adjust=False).mean().values

# اختراق نطاق التذبذب (Volatility Expansion):
# شمعة 1H تكسر أعلى سعر لآخر 8 ساعات بحجم تداول > 1.5× المتوسط
v20 = df.volume.rolling(20).mean().values
hi8 = df.high.rolling(8).max().shift().values
lo8 = df.low.rolling(8).min().shift().values

for mult in (1.2, 1.5):
    for rr in (1.5, 2.0, 2.5):
        long_sig = (c > hi8) & (v > mult * v20) & (c > ema50)
        short_sig = (c < lo8) & (v > mult * v20) & (c < ema50)
        sig = np.where(long_sig, 1, np.where(short_sig, -1, 0))
        
        trades = []
        n = len(df)
        i = 100
        while i < n - 2:
            s = sig[i]
            if s == 0: i += 1; continue
            entry = o[i+1]
            d = 1.5 * atr[i]
            stop = entry - s * d
            tp = entry + s * rr * d
            j = i + 1
            res = None
            while j < min(n, i + 1 + 24):
                if s > 0:
                    if l[j] <= stop: res = (stop - entry) / d; break
                    if h[j] >= tp: res = rr; break
                else:
                    if h[j] >= stop: res = (entry - stop) / d; break
                    if l[j] <= tp: res = rr; break
                j += 1
            if res is None: res = s * (c[j-1] - entry) / d
            trades.append((df.ts.iloc[i+1], s, res - 0.0008 * entry / d))
            i = j
        tdf = pd.DataFrame(trades, columns=["ts", "side", "r"])
        pos_r = tdf[tdf.r > 0].r.sum(); neg_r = -tdf[tdf.r < 0].r.sum()
        pf = pos_r / neg_r if neg_r > 0 else 0
        w = (tdf.r > 0).mean() * 100
        days = (tdf.ts.iloc[-1] - tdf.ts.iloc[0]).days
        t_7d = tdf[tdf.ts >= df.ts.iloc[-1] - pd.Timedelta(days=7)]
        print(f"Vol Brk (v>{mult}, rr={rr}): N={len(tdf)} ({len(tdf)/days*7:.1f}/wk) | Win={w:.1f}% | PF={pf:.2f} | 7D: {len(t_7d)} tr ({t_7d.r.sum():+.2f}R)")
