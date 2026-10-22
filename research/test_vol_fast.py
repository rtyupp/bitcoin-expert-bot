import pandas as pd
import numpy as np

df = pd.read_csv("research/btc_1h.csv", parse_dates=["ts"])
c, o, h, l, v = df.close.values, df.open.values, df.high.values, df.low.values, df.volume.values

tr = pd.concat([df.high - df.low, (df.high - df.close.shift()).abs(), (df.low - df.close.shift()).abs()], axis=1).max(axis=1)
atr = tr.ewm(alpha=1/14, adjust=False).mean().values

ema50 = df.close.ewm(span=50, adjust=False).mean().values
v20 = df.volume.rolling(20).mean().values
hi8 = df.high.rolling(8).max().shift().values
lo8 = df.low.rolling(8).min().shift().values

long_sig = (c > hi8) & (v > 1.8 * v20) & (c > ema50) & (o > ema50)
short_sig = (c < lo8) & (v > 1.8 * v20) & (c < ema50) & (o < ema50)
sig = np.where(long_sig, 1, np.where(short_sig, -1, 0))

trades = []
n = len(df)
i = 100
while i < n - 2:
    s = sig[i]
    if s == 0: i += 1; continue
    entry = o[i+1]
    d = 1.2 * atr[i]
    stop = entry - s * d
    tp = entry + s * 1.8 * d
    j = i + 1
    res = None
    while j < min(n, i + 1 + 18):
        if s > 0:
            if l[j] <= stop: res = (stop - entry) / d; break
            if h[j] >= tp: res = 1.8; break
        else:
            if h[j] >= stop: res = (entry - stop) / d; break
            if l[j] <= tp: res = 1.8; break
        j += 1
    if res is None: res = s * (c[j-1] - entry) / d
    trades.append((df.ts.iloc[i+1], s, res - 0.0008 * entry / d, j - i))
    i = j

tdf = pd.DataFrame(trades, columns=["ts", "side", "r", "bars"])
t_7d = tdf[tdf.ts >= df.ts.iloc[-1] - pd.Timedelta(days=7)]
pos_r = tdf[tdf.r > 0].r.sum(); neg_r = -tdf[tdf.r < 0].r.sum()
pf = pos_r / neg_r if neg_r > 0 else 0
w = (tdf.r > 0).mean() * 100
days = (tdf.ts.iloc[-1] - tdf.ts.iloc[0]).days
t_oos = tdf[tdf.ts >= pd.Timestamp("2024-01-01", tz="UTC")]
pf_oos = t_oos[t_oos.r > 0].r.sum() / -t_oos[t_oos.r < 0].r.sum() if len(t_oos) else 0

print(f"High-Volume 1H Breakout:")
print(f"Total: {len(tdf)} trades ({len(tdf)/days*7:.1f}/week) | Win: {w:.1f}% | PF: {pf:.2f} | OOS PF: {pf_oos:.2f} | Total R: {tdf.r.sum():+.1f}R")
print(f"Last 7 Days: {len(t_7d)} trades | R: {t_7d.r.sum():+.2f}R")
for _, r in t_7d.iterrows():
    side_str = "BUY" if r.side > 0 else "SELL"
    print(f"   {r.ts} | {side_str} | {r.r:+.2f}R | {r.bars}h")
