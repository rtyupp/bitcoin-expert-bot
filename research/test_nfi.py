import pandas as pd
import numpy as np

# اختبار استراتيجية NostalgiaForInfinity (NFI) الشهيرة على البيتكوين (15m و 1h)
# وهي أشهر استراتيجية مفتوحة المصدر في مجتمع Freqtrade
df15 = pd.read_csv("research/btc_15m.csv", parse_dates=["ts"])
df1h = pd.read_csv("research/btc_1h.csv", parse_dates=["ts"])

# 1. 1H informative RSI & EWO
df1h["rsi_1h"] = df1h.close.diff().pipe(lambda d: 100 - 100 / (1 + d.clip(lower=0).ewm(alpha=1/14, adjust=False).mean() / (-d.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean().replace(0, np.nan)))
df1h["ema50"] = df1h.close.ewm(span=50, adjust=False).mean()
df1h["ema200"] = df1h.close.ewm(span=200, adjust=False).mean()
df1h["ewo_1h"] = (df1h.ema50 - df1h.ema200) / df1h.close * 100

df1h_s = df1h[["ts", "rsi_1h", "ewo_1h", "ema200"]].copy()
df1h_s["ts"] = df1h_s["ts"] + pd.Timedelta(hours=1)

m = pd.merge_asof(df15.sort_values("ts"), df1h_s.sort_values("ts"), on="ts", direction="backward")

c, o, h, l, v = m.close.values, m.open.values, m.high.values, m.low.values, m.volume.values

# بولينجر 15m
sma20 = m.close.rolling(20).mean().values
std20 = m.close.rolling(20).std().values
bb_lower = sma20 - 2.0 * std20
bb_upper = sma20 + 2.0 * std20

# ATR 15m
tr = pd.concat([m.high - m.low, (m.high - m.close.shift()).abs(), (m.low - m.close.shift()).abs()], axis=1).max(axis=1)
atr = tr.ewm(alpha=1/14, adjust=False).mean().values

# شروط دخول NFI Dip:
# 1) إغلاق تحت بولينجر باند السفلي (Dip) بنسبة 0.5% (Close < bb_lower * 0.995)
# 2) RSI على فريم الساعة أكبر من 32 (لتجنب الانهيارات المفتوحة)
# 3) EWO موجب أو فوق -5 (اتجاه عام مدعوم)
# 4) شمعة ارتداد (Close > Open)
dip_buy = (c < bb_lower * 0.995) & (m.rsi_1h.values > 32) & (m.ewo_1h.values > -5) & (c > o)

# خروج NFI:
# - ربح عند ملامسة SMA20 أو BB Upper (متوسط 1.5R إلى 2.0R)
# - أو وقف خسارة 1.5x ATR
trades = []
n = len(m)
i = 100
while i < n - 2:
    if not dip_buy[i] or not np.isfinite(atr[i]): i += 1; continue
    entry = o[i+1]
    dist = 1.5 * atr[i]
    stop = entry - dist
    tp = entry + 1.8 * dist
    j = i + 1
    res = None
    while j < min(n, i + 1 + 24):
        # وقف
        if l[j] <= stop:
            res = (stop - entry) / dist
            break
        # وصول الهدف أو خط الوسط
        if h[j] >= tp or h[j] >= sma20[j]:
            exit_px = max(sma20[j], tp) if h[j] >= tp else sma20[j]
            res = (exit_px - entry) / dist
            break
        j += 1
    if res is None:
        res = (c[j-1] - entry) / dist
    trades.append((m.ts.iloc[i+1], 1, res - 0.0008 * entry / dist, j - i))
    i = j

tdf = pd.DataFrame(trades, columns=["ts", "side", "r", "bars"])
pos_r = tdf[tdf.r > 0].r.sum(); neg_r = -tdf[tdf.r < 0].r.sum()
pf = pos_r / neg_r if neg_r > 0 else 99
w = (tdf.r > 0).mean() * 100
t_oos = tdf[tdf.ts >= pd.Timestamp("2024-01-01", tz="UTC")]
pos_oos = t_oos[t_oos.r > 0].r.sum(); neg_oos = -t_oos[t_oos.r < 0].r.sum()
pf_oos = pos_oos / neg_oos if neg_oos > 0 else 99
w_oos = (t_oos.r > 0).mean() * 100 if len(t_oos) else 0
t_7d = tdf[tdf.ts >= m.ts.iloc[-1] - pd.Timedelta(days=7)]
days = (tdf.ts.iloc[-1] - tdf.ts.iloc[0]).days

print(f"=== NostalgiaForInfinity (NFI Dip Buy on 15m) ===")
print(f"Total Trades: {len(tdf)} ({len(tdf)/days*7:.1f}/week)")
print(f"Win Rate: {w:.1f}%")
print(f"Profit Factor: {pf:.2f}")
print(f"OOS 2024+: {len(t_oos)} trades | Win: {w_oos:.1f}% | PF: {pf_oos:.2f} | R: {t_oos.r.sum():+.1f}R")
print(f"Total Net R: {tdf.r.sum():+.1f}R")
print(f"Last 7 Days: {len(t_7d)} trades ({t_7d.r.sum():+.2f}R)")
