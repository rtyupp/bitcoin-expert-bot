import pandas as pd
import numpy as np

# اختبار استراتيجية Jesse الشهيرة (SimpleBollinger + Ichimoku Cloud on 1h)
# Repo: https://github.com/gabrielweich/jesse-strategies & jesse-ai/example-strategies
df1h = pd.read_csv("research/btc_1h.csv", parse_dates=["ts"])
c, o, h, l, v = df1h.close.values, df1h.open.values, df1h.high.values, df1h.low.values, df1h.volume.values

# 1. Bollinger Bands
sma20 = df1h.close.rolling(20).mean().values
std20 = df1h.close.rolling(20).std().values
bb_upper = sma20 + 2.0 * std20
bb_lower = sma20 - 2.0 * std20
bb_mid = sma20

# 2. Ichimoku Cloud (Tenkan 9, Kijun 26, Senkou Span B 52)
tenkan = (df1h.high.rolling(9).max() + df1h.low.rolling(9).min()) / 2
kijun = (df1h.high.rolling(26).max() + df1h.low.rolling(26).min()) / 2
span_a = ((tenkan + kijun) / 2).shift(26).values
span_b = ((df1h.high.rolling(52).max() + df1h.low.rolling(52).min()) / 2).shift(26).values

# ATR
tr = pd.concat([df1h.high - df1h.low, (df1h.high - df1h.close.shift()).abs(), (df1h.low - df1h.close.shift()).abs()], axis=1).max(axis=1)
atr = tr.ewm(alpha=1/14, adjust=False).mean().values

# شروط Jesse:
# Long: Close > BB Upper AND Close > Span A AND Close > Span B
# Short (symmetric): Close < BB Lower AND Close < Span A AND Close < Span B
long_sig = (c > bb_upper) & (c > span_a) & (c > span_b)
short_sig = (c < bb_lower) & (c < span_a) & (c < span_b)
sig = np.where(long_sig, 1, np.where(short_sig, -1, 0))

trades = []
n = len(df1h)
i = 100
while i < n - 2:
    s = sig[i]
    if s == 0 or not np.isfinite(atr[i]): i += 1; continue
    entry = o[i+1]
    dist = 1.5 * atr[i]
    stop = entry - s * dist
    j = i + 1
    res = None
    while j < min(n, i + 1 + 48):
        # وقف خسارة
        if (s > 0 and l[j] <= stop) or (s < 0 and h[j] >= stop):
            res = (stop - entry) / dist if s > 0 else (entry - stop) / dist
            break
        # خروج Jesse: إغلاق تحت/فوق خط الوسط BB Middle
        if (s > 0 and c[j] < bb_mid[j]) or (s < 0 and c[j] > bb_mid[j]):
            res = s * (c[j] - entry) / dist
            break
        j += 1
    if res is None:
        res = s * (c[j-1] - entry) / dist
    trades.append((df1h.ts.iloc[i+1], s, res - 0.0008 * entry / dist, j - i))
    i = j

tdf = pd.DataFrame(trades, columns=["ts", "side", "r", "bars"])
pos_r = tdf[tdf.r > 0].r.sum(); neg_r = -tdf[tdf.r < 0].r.sum()
pf = pos_r / neg_r if neg_r > 0 else 99
w = (tdf.r > 0).mean() * 100
t_oos = tdf[tdf.ts >= pd.Timestamp("2024-01-01", tz="UTC")]
pos_oos = t_oos[t_oos.r > 0].r.sum(); neg_oos = -t_oos[t_oos.r < 0].r.sum()
pf_oos = pos_oos / neg_oos if neg_oos > 0 else 99
w_oos = (t_oos.r > 0).mean() * 100 if len(t_oos) else 0
t_7d = tdf[tdf.ts >= df1h.ts.iloc[-1] - pd.Timedelta(days=7)]
days = (tdf.ts.iloc[-1] - tdf.ts.iloc[0]).days

print(f"=== Jesse SimpleBollinger + Ichimoku on 1H ===")
print(f"Total Trades: {len(tdf)} ({len(tdf)/days*7:.1f}/week)")
print(f"Win Rate: {w:.1f}%")
print(f"Profit Factor: {pf:.2f}")
print(f"OOS 2024+: {len(t_oos)} trades | Win: {w_oos:.1f}% | PF: {pf_oos:.2f} | R: {t_oos.r.sum():+.1f}R")
print(f"Total Net R: {tdf.r.sum():+.1f}R")
print(f"Last 7 Days: {len(t_7d)} trades ({t_7d.r.sum():+.2f}R)")
