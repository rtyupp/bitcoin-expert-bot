import pandas as pd
import numpy as np

# اختبار استراتيجية Ichimoku Cloud + Bollinger على 4H (لتفادي إشارات الوهم في 1H)
df4h = pd.read_csv("research/btc_4h.csv", parse_dates=["ts"])
c, o, h, l, v = df4h.close.values, df4h.open.values, df4h.high.values, df4h.low.values, df4h.volume.values

# 1. Bollinger Bands 4H
sma20 = df4h.close.rolling(20).mean().values
std20 = df4h.close.rolling(20).std().values
bb_upper = sma20 + 2.0 * std20
bb_lower = sma20 - 2.0 * std20
bb_mid = sma20

# 2. Ichimoku Cloud 4H
tenkan = (df4h.high.rolling(9).max() + df4h.low.rolling(9).min()) / 2
kijun = (df4h.high.rolling(26).max() + df4h.low.rolling(26).min()) / 2
span_a = ((tenkan + kijun) / 2).shift(26).values
span_b = ((df4h.high.rolling(52).max() + df4h.low.rolling(52).min()) / 2).shift(26).values

tr = pd.concat([df4h.high - df4h.low, (df4h.high - df4h.close.shift()).abs(), (df4h.low - df4h.close.shift()).abs()], axis=1).max(axis=1)
atr = tr.ewm(alpha=1/14, adjust=False).mean().values

long_sig = (c > bb_upper) & (c > span_a) & (c > span_b)
short_sig = (c < bb_lower) & (c < span_a) & (c < span_b)
sig = np.where(long_sig, 1, np.where(short_sig, -1, 0))

trades = []
n = len(df4h)
i = 100
while i < n - 2:
    s = sig[i]
    if s == 0 or not np.isfinite(atr[i]): i += 1; continue
    entry = o[i+1]
    dist = 1.5 * atr[i]
    stop = entry - s * dist
    j = i + 1
    res = None
    while j < min(n, i + 1 + 60):
        if (s > 0 and l[j] <= stop) or (s < 0 and h[j] >= stop):
            res = (stop - entry) / dist if s > 0 else (entry - stop) / dist
            break
        if (s > 0 and c[j] < bb_mid[j]) or (s < 0 and c[j] > bb_mid[j]):
            res = s * (c[j] - entry) / dist
            break
        j += 1
    if res is None:
        res = s * (c[j-1] - entry) / dist
    trades.append((df4h.ts.iloc[i+1], s, res - 0.0008 * entry / dist, (j - i) * 4 / 24))
    i = j

tdf = pd.DataFrame(trades, columns=["ts", "side", "r", "days"])
pos_r = tdf[tdf.r > 0].r.sum(); neg_r = -tdf[tdf.r < 0].r.sum()
pf = pos_r / neg_r if neg_r > 0 else 99
w = (tdf.r > 0).mean() * 100
t_oos = tdf[tdf.ts >= pd.Timestamp("2024-01-01", tz="UTC")]
pos_oos = t_oos[t_oos.r > 0].r.sum(); neg_oos = -t_oos[t_oos.r < 0].r.sum()
pf_oos = pos_oos / neg_oos if neg_oos > 0 else 99
w_oos = (t_oos.r > 0).mean() * 100 if len(t_oos) else 0
t_7d = tdf[tdf.ts >= df4h.ts.iloc[-1] - pd.Timedelta(days=7)]
days = (tdf.ts.iloc[-1] - tdf.ts.iloc[0]).days

print(f"=== Jesse SimpleBollinger + Ichimoku on 4H ===")
print(f"Total Trades: {len(tdf)} ({len(tdf)/days*7:.1f}/week)")
print(f"Win Rate: {w:.1f}%")
print(f"Profit Factor: {pf:.2f}")
print(f"OOS 2024+: {len(t_oos)} trades | Win: {w_oos:.1f}% | PF: {pf_oos:.2f} | R: {t_oos.r.sum():+.1f}R")
print(f"Total Net R: {tdf.r.sum():+.1f}R")
print(f"Last 7 Days: {len(t_7d)} trades ({t_7d.r.sum():+.2f}R)")
