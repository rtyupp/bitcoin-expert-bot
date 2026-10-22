import pandas as pd
import numpy as np

# اختبار المحفظة الذهبية الثلاثية:
# 1) Donchian 55 Daily (موجات الصعود الكبرى)
# 2) SMC Liquidity Sweep 4H (قنص السيولة - فوز 52.4%، PF 1.87)
# 3) Turtle 20 4H (نظام السلاحف الشهير على 4 ساعات - صفقة أسبوعياً، PF 1.56، +128R)

df4h = pd.read_csv("research/btc_4h.csv", parse_dates=["ts"])
df1d = pd.read_csv("research/btc_1d.csv", parse_dates=["ts"])

import sys
sys.path.insert(0, ".")
import strategy as S
import backtest

# محاكاة A و C
t_ac = backtest.simulate(df4h, df1d, enabled=("A", "C"))

# محاكاة Turtle 20 4H
c, o, h, l = df4h.close.values, df4h.open.values, df4h.high.values, df4h.low.values
tr = pd.concat([df4h.high - df4h.low, (df4h.high - df4h.close.shift()).abs(), (df4h.low - df4h.close.shift()).abs()], axis=1).max(axis=1)
atr = tr.ewm(alpha=1/14, adjust=False).mean().values
ema200 = df4h.close.ewm(span=200, adjust=False).mean().values
hi20 = df4h.high.rolling(20).max().shift().values
lo20 = df4h.low.rolling(20).min().shift().values

long_t = (c > hi20) & (c > ema200)
short_t = (c < lo20) & (c < ema200)
sig_turtle = np.where(long_t, 1, np.where(short_t, -1, 0))

trades_t = []
n = len(df4h)
i = 50
while i < n - 2:
    s = sig_turtle[i]
    if s == 0: i += 1; continue
    entry = o[i+1]
    dist = 2.0 * atr[i]
    stop = entry - s * dist
    best = entry
    j = i + 1
    res = None
    while j < min(n, i + 1 + 60):
        if s > 0:
            if l[j] <= stop: res = (stop - entry) / dist; break
            best = max(best, h[j])
        else:
            if h[j] >= stop: res = (entry - stop) / dist; break
            best = min(best, l[j])
        ns = best - s * 2.0 * dist
        stop = max(stop, ns) if s > 0 else min(stop, ns)
        j += 1
    if res is None: res = s * (c[j-1] - entry) / dist
    trades_t.append({"ts": df4h.ts.iloc[i+1], "exit_ts": df4h.ts.iloc[j-1], "strat": "Turtle", "side": s,
                     "entry": entry, "exit": entry + res * dist, "risk_pct": dist / entry * 100,
                     "r": res - 0.0008 * entry / dist, "days": (j - i) * 4 / 24})
    i = j

tt = pd.DataFrame(trades_t)
t_combo = pd.concat([t_ac, tt]).sort_values("ts").reset_index(drop=True)

s_all = backtest.stats(t_combo)
cut = pd.Timestamp("2024-01-01", tz="UTC")
s_in = backtest.stats(t_combo[t_combo.ts < cut])
s_out = backtest.stats(t_combo[t_combo.ts >= cut])

print("=== محفظة النخبة الذهبية (Donchian 55 + SMC Sweep + Turtle 20 4H) ===")
print(f"إجمالي الصفقات: {s_all['n']} صفقة ({s_all['per_year']:.1f}/سنة ≈ {s_all['per_year']/52:.1f} صفقة أسبوعياً)")
print(f"نسبة الفوز: {s_all['win']}%")
print(f"عامل الربح (Profit Factor): {s_all['pf']}")
print(f"إجمالي الأرباح الصافية: +{s_all['total_r']}R")
print(f"أقصى تراجع: {s_all['max_dd_r']}R")
print(f"العائد بمخاطرة 1%: +{s_all['ret_1pct']}%")

print("\n--- خارج العينة (2024 - 2026 Out-of-Sample) ---")
print(f"الصفقات: {s_out['n']} | الفوز: {s_out['win']}% | PF: {s_out['pf']} | الأرباح: +{s_out['total_r']}R")

yr = t_combo.groupby(t_combo.ts.dt.year)["r"].agg(["count", "sum"])
print("\nسنوياً:")
for y, (cnt, r_sum) in yr.iterrows():
    print(f"  {y}: {int(cnt)} صفقات | {r_sum:+.1f}R")
