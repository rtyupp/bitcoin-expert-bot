import pandas as pd
import numpy as np

# اختبار استراتيجية كنس سيولة جلسة آسيا المشهورة (Asian Range Sweep - ICT) على فريم 15 دقيقة
# وقت آسيا (UTC): 00:00 إلى 06:00
# وقت لندن/نيويورك: 07:00 إلى 16:00
# الشروط:
# تحديد أعلى وأدنى نقطة في جلسة آسيا.
# في جلسة لندن/نيويورك: إذا كسر السعر قاع آسيا ورجع أغلق فوقه داخل النطاق = شراء (قنص سيولة القيعان)
# إذا كسر السعر قمة آسيا ورجع أغلق تحتها = بيع (قنص سيولة القمم)

df = pd.read_csv("research/btc_15m.csv", parse_dates=["ts"])
df = df[df.ts >= "2023-01-01"].reset_index(drop=True)

df["hour"] = df.ts.dt.hour
df["date"] = df.ts.dt.date

# تجميع أعلى وأدنى آسيا (00:00 إلى 06:00)
asia = df[df.hour.between(0, 5)].groupby("date").agg(asia_high=("high", "max"), asia_low=("low", "min")).reset_index()

m = pd.merge(df, asia, on="date", how="left")

# ATR 15m
tr = pd.concat([m.high - m.low, (m.high - m.close.shift()).abs(), (m.low - m.close.shift()).abs()], axis=1).max(axis=1)
m["atr"] = tr.ewm(alpha=1/14, adjust=False).mean()
m["ema50"] = m.close.ewm(span=50, adjust=False).mean()

# إشارات في جلسة لندن/نيويورك (07:00 إلى 16:00)
active_hours = m.hour.between(7, 16)
long_cond = active_hours & (m.low < m.asia_low) & (m.close > m.asia_low) & (m.close > m.open) & (m.close > m.ema50)
short_cond = active_hours & (m.high > m.asia_high) & (m.close < m.asia_high) & (m.close < m.open) & (m.close < m.ema50)

sig = np.zeros(len(m))
sig[long_cond] = 1
sig[short_cond] = -1

o, h, l, c, a = m.open.values, m.high.values, m.low.values, m.close.values, m.atr.values
trades = []
i = 50
n = len(m)
while i < n - 2:
    s = sig[i]
    if s == 0:
        i += 1; continue
    entry = o[i+1]
    d = 1.5 * a[i]
    stop = entry - s * d
    tp = entry + s * 2.0 * d
    j = i + 1
    res = None
    while j < min(n, i + 1 + 32): # أقصى مدة 8 ساعات
        if s > 0:
            if l[j] <= stop: res = (stop - entry) / d; break
            if h[j] >= tp: res = 2.0; break
        else:
            if h[j] >= stop: res = (entry - stop) / d; break
            if l[j] <= tp: res = 2.0; break
        j += 1
    if res is None:
        res = s * (c[j-1] - entry) / d
    trades.append((m.ts.iloc[i+1], s, res - 0.0008 * entry / d, j - i))
    i = j

tdf = pd.DataFrame(trades, columns=["ts", "side", "r", "bars"])
days = (tdf.ts.iloc[-1] - tdf.ts.iloc[0]).days
t_7d = tdf[tdf.ts >= m.ts.iloc[-1] - pd.Timedelta(days=7)]

print(f"Asian Range Sweep 15m (2023-2026):")
print(f"Trades: {len(tdf)} ({len(tdf)/days*7:.1f}/week)")
print(f"Win Rate: {(tdf.r > 0).mean()*100:.1f}%")
pos_r = tdf[tdf.r > 0].r.sum(); neg_r = -tdf[tdf.r < 0].r.sum()
print(f"Profit Factor: {pos_r / neg_r:.2f}")
print(f"Expectancy: {tdf.r.mean():+.3f}R | Total R: {tdf.r.sum():+.1f}R")
print(f"Last 7 Days trades: {len(t_7d)} ({t_7d.r.sum():+.2f}R)")
