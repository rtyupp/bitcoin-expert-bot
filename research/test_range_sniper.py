import pandas as pd
import numpy as np

# اختبار استراتيجية صيد التذبذب والمناطق العرضية (High-Win-Rate Range Sniper):
# عندما يكون السوق في مسار عرضي (ADX < 22):
# - شراء عند ملامسة بولينجر السفلي + RSI(2) < 5 + إغلاق أخضر (هدف: خط الوسط SMA20)
# - بيع عند ملامسة بولينجر العلوي + RSI(2) > 95 + إغلاق أحمر (هدف: خط الوسط SMA20)
# - وقف خسارة ضيق ومحكم 1.0x ATR

df1h = pd.read_csv("research/btc_1h.csv", parse_dates=["ts"])
c, o, h, l = df1h.close.values, df1h.open.values, df1h.high.values, df1h.low.values

tr = pd.concat([df1h.high - df1h.low, (df1h.high - df1h.close.shift()).abs(), (df1h.low - df1h.close.shift()).abs()], axis=1).max(axis=1)
atr = tr.ewm(alpha=1/14, adjust=False).mean().values

# ADX
up_d = df1h.high.diff()
dn_d = -df1h.low.diff()
pdm = np.where((up_d > dn_d) & (up_d > 0), up_d, 0.0)
ndm = np.where((dn_d > up_d) & (dn_d > 0), dn_d, 0.0)
pdi = 100 * pd.Series(pdm).ewm(alpha=1/14, adjust=False).mean() / atr
ndi = 100 * pd.Series(ndm).ewm(alpha=1/14, adjust=False).mean() / atr
dx = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
adx = dx.ewm(alpha=1/14, adjust=False).mean().values

sma20 = df1h.close.rolling(20).mean().values
std20 = df1h.close.rolling(20).std().values
bb_up = sma20 + 2.0 * std20
bb_lo = sma20 - 2.0 * std20

diff = df1h.close.diff()
up = diff.clip(lower=0).ewm(alpha=1/2, adjust=False).mean()
dn = (-diff.clip(upper=0)).ewm(alpha=1/2, adjust=False).mean()
rsi2 = (100 - 100 / (1 + up / dn.replace(0, np.nan))).values

long_sig = (adx < 22) & (l <= bb_lo) & (rsi2 < 5) & (c > o)
short_sig = (adx < 22) & (h >= bb_up) & (rsi2 > 95) & (c < o)
sig = np.where(long_sig, 1, np.where(short_sig, -1, 0))

trades = []
n = len(df1h)
i = 50
while i < n - 2:
    s = sig[i]
    if s == 0 or not np.isfinite(atr[i]): i += 1; continue
    entry = o[i+1]
    dist = 1.0 * atr[i]
    stop = entry - s * dist
    # الهدف: خط الوسط SMA20
    j = i + 1
    res = None
    while j < min(n, i + 1 + 16):
        # وقف
        if (s > 0 and l[j] <= stop) or (s < 0 and h[j] >= stop):
            res = -1.0; break
        # وصول خط الوسط SMA20
        if (s > 0 and h[j] >= sma20[j]) or (s < 0 and l[j] <= sma20[j]):
            exit_px = sma20[j]
            res = s * (exit_px - entry) / dist
            break
        j += 1
    if res is None: res = s * (c[j-1] - entry) / dist
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

print(f"Range Sniper (ADX<22 + BB + RSI2<5):")
print(f"Total Trades: {len(tdf)} ({len(tdf)/days*7:.1f}/week) | Win: {w:.1f}% | PF: {pf:.2f} | Tot R: {tdf.r.sum():+.1f}R")
print(f"OOS 2024+: Trades: {len(t_oos)} | Win: {w_oos:.1f}% | PF: {pf_oos:.2f} | Tot R: {t_oos.r.sum():+.1f}R")
print(f"Last 7 Days: {len(t_7d)} trades | R: {t_7d.r.sum():+.2f}R")
for _, r in t_7d.iterrows():
    side_str = "BUY" if r.side > 0 else "SELL"
    print(f"   {r.ts} | {side_str} | {r.r:+.2f}R | {r.bars}h")
