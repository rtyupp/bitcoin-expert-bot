import pandas as pd
import numpy as np

# اختبار استراتيجية الذهب (XAUUSD / GOLD) على بيانات Capital.com فريم الساعة 1H
df = pd.read_csv("research/btc_1h.csv", nrows=10) # dummy
# نختبر بيانات الذهب الحية من Capital.com
import sys, types, os
cfg = types.ModuleType("config")
cfg.CAPITAL_EMAIL = os.environ.get("CAPITAL_EMAIL", "")
cfg.CAPITAL_API_KEY = os.environ.get("CAPITAL_API_KEY", "")
cfg.CAPITAL_API_PASSWORD = os.environ.get("CAPITAL_API_PASSWORD", "")
sys.modules["config"] = cfg

import capital_trader as ct

df, src = ct.fetch_ohlcv("GOLD", "1h", 1000)
c, o, h, l, v = df.close.values, df.open.values, df.high.values, df.low.values, df.volume.values

tr = pd.concat([df.high - df.low, (df.high - df.close.shift()).abs(), (df.low - df.close.shift()).abs()], axis=1).max(axis=1)
atr = tr.ewm(alpha=1/14, adjust=False).mean().values

ema20 = df.close.ewm(span=20, adjust=False).mean().values
ema50 = df.close.ewm(span=50, adjust=False).mean().values
ema200 = df.close.ewm(span=200, adjust=False).mean().values

# استراتيجية التدفق المؤسسي للذهب:
# كنس سيولة قمم/قيعان 10 شموع + ارتداد باتجاه EMA50/EMA200
lo10 = df.low.rolling(10).min().shift().values
hi10 = df.high.rolling(10).max().shift().values

long_gold = (l < lo10) & (c > lo10) & (c > o) & (c > ema50) & (ema50 > ema200)
short_gold = (h > hi10) & (c < hi10) & (c < o) & (c < ema50) & (ema50 < ema200)
sig = np.where(long_gold, 1, np.where(short_gold, -1, 0))

trades = []
n = len(df)
i = 50
while i < n - 2:
    s = sig[i]
    if s == 0: i += 1; continue
    entry = o[i+1]
    d = 1.5 * atr[i]
    stop = entry - s * d
    tp = entry + s * 2.0 * d
    j = i + 1
    res = None
    while j < min(n, i + 1 + 24):
        if s > 0:
            if l[j] <= stop: res = (stop - entry) / d; break
            if h[j] >= tp: res = 2.0; break
        else:
            if h[j] >= stop: res = (entry - stop) / d; break
            if l[j] <= tp: res = 2.0; break
        j += 1
    if res is None: res = s * (c[j-1] - entry) / d
    trades.append((df.ts.iloc[i+1], s, res - 0.0004 * entry / d, j - i))
    i = j

tdf = pd.DataFrame(trades, columns=["ts", "side", "r", "bars"])
days = (tdf.ts.iloc[-1] - tdf.ts.iloc[0]).days
t_7d = tdf[tdf.ts >= df.ts.iloc[-1] - pd.Timedelta(days=7)]
pos_r = tdf[tdf.r > 0].r.sum(); neg_r = -tdf[tdf.r < 0].r.sum()
pf = pos_r / neg_r if neg_r > 0 else 0
w = (tdf.r > 0).mean() * 100

print(f"Gold 1H Institutional Flow (Capital.com 1000 hours ~ 42 days):")
print(f"Trades: {len(tdf)} ({len(tdf)/days*7:.1f}/week) | Win: {w:.1f}% | PF: {pf:.2f} | Total: {tdf.r.sum():+.2f}R")
print(f"Last 7 Days trades: {len(t_7d)} ({t_7d.r.sum():+.2f}R)")
for _, tr in t_7d.iterrows():
    side_str = "BUY" if tr.side > 0 else "SELL"
    print(f"   {tr.ts} | {side_str} | {tr.r:+.2f}R | {tr.bars}h")
