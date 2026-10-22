import pandas as pd
import numpy as np

# اختبار المحفظة الكاملة بعد دمج استراتيجية Keltner Squeeze 1H السريعة (D)
# لمعرفة إجمالي عدد الصفقات والعائد التراكمي
df1h = pd.read_csv("research/btc_1h.csv", parse_dates=["ts"])
df4h = pd.read_csv("research/btc_4h.csv", parse_dates=["ts"])
df1d = pd.read_csv("research/btc_1d.csv", parse_dates=["ts"])

# استراتيجية D: Keltner Squeeze 1H
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
ema50 = df1h.close.ewm(span=50, adjust=False).mean().values
v20 = df1h.volume.rolling(20).mean().values

long_sq = squeeze_fired & (c > bb_up) & (v > 1.0 * v20) & (c > ema50)
short_sq = squeeze_fired & (c < bb_lo) & (v > 1.0 * v20) & (c < ema50)
sig_d = np.where(long_sq, 1, np.where(short_sq, -1, 0))

# استيراد محاكاة A, B, C من backtest.py
import sys
sys.path.insert(0, ".")
import strategy as S
import backtest

t_abc = backtest.simulate(df4h, df1d)

# محاكاة D
trades_d = []
n = len(df1h)
i = 50
while i < n - 2:
    s = sig_d[i]
    if s == 0 or not np.isfinite(atr1h[i]): i += 1; continue
    entry = o[i+1]
    dist = 1.5 * atr1h[i]
    stop = entry - s * dist
    tp = entry + s * 2.2 * dist
    best = entry
    j = i + 1
    res = None
    while j < min(n, i + 1 + 36):
        if s > 0:
            if l[j] <= stop: res = (stop - entry) / dist; break
            if h[j] >= tp: res = 2.2; break
            best = max(best, h[j])
        else:
            if h[j] >= stop: res = (entry - stop) / dist; break
            if l[j] <= tp: res = 2.2; break
            best = min(best, l[j])
        if s * (best - entry) >= 1.0 * dist:
            stop = max(stop, entry) if s > 0 else min(stop, entry)
        j += 1
    if res is None: res = s * (c[j-1] - entry) / dist
    trades_d.append({"ts": df1h.ts.iloc[i+1], "exit_ts": df1h.ts.iloc[j-1], "strat": "D", "side": s,
                     "entry": entry, "exit": res * dist + entry, "risk_pct": dist / entry * 100,
                     "r": res - 0.0008 * entry / dist, "days": (j - i) / 24})
    i = j

td = pd.DataFrame(trades_d)

# دمج الصفقات
t_total = pd.concat([t_abc, td]).sort_values("ts").reset_index(drop=True)
s_tot = backtest.stats(t_total)
cut = pd.Timestamp("2024-01-01", tz="UTC")
s_in = backtest.stats(t_total[t_total.ts < cut])
s_out = backtest.stats(t_total[t_total.ts >= cut])

print("\n=== محفظة البيتكوين الكبرى (A + B + C + D السريعة) ===")
print(f"إجمالي الصفقات: {s_tot['n']} صفقة ({s_tot['per_year']:.1f} صفقة/سنة ≈ {s_tot['per_year']/52:.1f} صفقات/أسبوع)")
print(f"نسبة الفوز: {s_tot['win']}%")
print(f"عامل الربح (Profit Factor): {s_tot['pf']}")
print(f"إجمالي الأرباح الصافية: +{s_tot['total_r']}R")
print(f"أقصى تراجع: {s_tot['max_dd_r']}R")
print(f"العائد بمخاطرة 1%: +{s_tot['ret_1pct']}%")

print("\n--- خارج العينة (2024 - 2026 Out-of-Sample) ---")
print(f"الصفقات: {s_out['n']} | الفوز: {s_out['win']}% | PF: {s_out['pf']} | الأرباح: +{s_out['total_r']}R")

t_7d = t_total[t_total.ts >= df1h.ts.iloc[-1] - pd.Timedelta(days=7)]
print(f"\nآخر 7 أيام: {len(t_7d)} صفقات")
for _, r in t_7d.iterrows():
    side_str = "BUY 🟢" if r.side > 0 else "SELL 🔴"
    strat_tag = "D (1H Squeeze)" if r.strat == "D" else r.strat
    print(f"   {r.ts} | {strat_tag} | {side_str} | {r.r:+.2f}R")
