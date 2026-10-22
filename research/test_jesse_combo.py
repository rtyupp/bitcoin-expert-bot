import pandas as pd
import numpy as np

# اختبار دمج استراتيجية Jesse Ichimoku + Bollinger 4H كاستراتيجية B الأساسية
df4h = pd.read_csv("research/btc_4h.csv", parse_dates=["ts"])
df1d = pd.read_csv("research/btc_1d.csv", parse_dates=["ts"])

import sys
sys.path.insert(0, ".")
import strategy as S
import backtest

# محاكاة A و C
t_ac = backtest.simulate(df4h, df1d, enabled=("A", "C"))

# محاكاة Jesse Ichimoku 4H
c, o, h, l = df4h.close.values, df4h.open.values, df4h.high.values, df4h.low.values
sma20 = df4h.close.rolling(20).mean().values
std20 = df4h.close.rolling(20).std().values
bb_upper = sma20 + 2.0 * std20
bb_lower = sma20 - 2.0 * std20
bb_mid = sma20

tenkan = (df4h.high.rolling(9).max() + df4h.low.rolling(9).min()) / 2
kijun = (df4h.high.rolling(26).max() + df4h.low.rolling(26).min()) / 2
span_a = ((tenkan + kijun) / 2).shift(26).values
span_b = ((df4h.high.rolling(52).max() + df4h.low.rolling(52).min()) / 2).shift(26).values

tr = pd.concat([df4h.high - df4h.low, (df4h.high - df4h.close.shift()).abs(), (df4h.low - df4h.close.shift()).abs()], axis=1).max(axis=1)
atr = tr.ewm(alpha=1/14, adjust=False).mean().values

long_sig = (c > bb_upper) & (c > span_a) & (c > span_b)
short_sig = (c < bb_lower) & (c < span_a) & (c < span_b)
sig = np.where(long_sig, 1, np.where(short_sig, -1, 0))

trades_j = []
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
    trades_j.append({"ts": df4h.ts.iloc[i+1], "exit_ts": df4h.ts.iloc[j-1], "strat": "Jesse_Ichimoku",
                     "side": s, "entry": entry, "exit": entry + res * dist, "risk_pct": dist / entry * 100,
                     "r": res - 0.0008 * entry / dist, "days": (j - i) * 4 / 24})
    i = j

tj = pd.DataFrame(trades_j)
t_combo = pd.concat([t_ac, tj]).sort_values("ts").reset_index(drop=True)

s_all = backtest.stats(t_combo)
cut = pd.Timestamp("2024-01-01", tz="UTC")
s_in = backtest.stats(t_combo[t_combo.ts < cut])
s_out = backtest.stats(t_combo[t_combo.ts >= cut])

print("\n=== محفظة النخبة العالمية (Donchian 55 + SMC Sweep + Jesse Ichimoku 4H) ===")
print(f"إجمالي الصفقات: {s_all['n']} صفقة ({s_all['per_year']:.1f}/سنة ≈ {s_all['per_year']/52:.1f} صفقة أسبوعياً)")
print(f"نسبة الفوز: {s_all['win']}%")
print(f"عامل الربح (Profit Factor): {s_all['pf']}")
print(f"العائد المتوقع لكل صفقة: +{s_all['exp_r']}R")
print(f"إجمالي الأرباح الصافية: +{s_all['total_r']}R")
print(f"أقصى تراجع: {s_all['max_dd_r']}R")
print(f"العائد بمخاطرة 1%: +{s_all['ret_1pct']}%")

print("\n--- خارج العينة (2024 - 2026 Out-of-Sample) ---")
print(f"الصفقات: {s_out['n']} | الفوز: {s_out['win']}% | PF: {s_out['pf']} | الأرباح: +{s_out['total_r']}R")

yr = t_combo.groupby(t_combo.ts.dt.year)["r"].agg(["count", "sum"]).round(1)
print("\nالنتائج السنوية:")
for y, (cnt, r_sum) in yr.iterrows():
    print(f"  {y}: {int(cnt)} صفقات | {r_sum:+.1f}R")
