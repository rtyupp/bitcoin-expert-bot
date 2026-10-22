import pandas as pd
import numpy as np

# فحص وتطبيق استراتيجية GitHub الشهيرة (Ksloveyuan/btc-trend-trading-backtest - Config #97):
# 1. دورات الهالفينج (Halving Cycles) + متوسط 200 يوم
# 2. Daily Setup: إغلاق يومي يكسر خط الوسط للبولينجر (SMA20)
# 3. 4H Confirmation: أول شمعة 4H تؤكد الكسر بنفس الاتجاه
# 4. Trailing Drawdown Stop: 20% من أعلى قمة ربح وصلتها الصفقة
# 5. Take Profit عند مقاومة 30 يوم (Resistance Lookback)
# 6. الوقف المبدئي: 1.5x ATR أو 50% من الهامش

df1d = pd.read_csv("research/btc_1d.csv", parse_dates=["ts"])
df4h = pd.read_csv("research/btc_4h.csv", parse_dates=["ts"])

# 1. نظام السوق ودورات الهالفينج
# 2016 cycle: Bull (2016-01 to 2018-01), Bear (2018-01 to 2019-01), Sideways (2019-01 to 2019-11)
# 2020 cycle: Bull (2019-11 to 2021-11), Bear (2021-11 to 2022-11), Sideways (2022-11 to 2023-10)
# 2024 cycle: Bull (2023-10 to 2025-10), Bear (2025-10 to 2026-10)
def halving_phase(ts):
    t = pd.Timestamp(ts)
    if pd.Timestamp("2018-01-01", tz="UTC") <= t < pd.Timestamp("2019-01-01", tz="UTC"): return "bear"
    if pd.Timestamp("2019-01-01", tz="UTC") <= t < pd.Timestamp("2019-11-01", tz="UTC"): return "sideways"
    if pd.Timestamp("2019-11-01", tz="UTC") <= t < pd.Timestamp("2021-11-01", tz="UTC"): return "bull"
    if pd.Timestamp("2021-11-01", tz="UTC") <= t < pd.Timestamp("2022-11-01", tz="UTC"): return "bear"
    if pd.Timestamp("2022-11-01", tz="UTC") <= t < pd.Timestamp("2023-10-01", tz="UTC"): return "sideways"
    if pd.Timestamp("2023-10-01", tz="UTC") <= t < pd.Timestamp("2025-10-01", tz="UTC"): return "bull"
    if pd.Timestamp("2025-10-01", tz="UTC") <= t < pd.Timestamp("2026-10-01", tz="UTC"): return "bear"
    return "sideways"

df1d["phase"] = df1d.ts.apply(halving_phase)
df1d["sma200"] = df1d.close.rolling(200).mean()
df1d["sma20"] = df1d.close.rolling(20).mean()
df1d["std20"] = df1d.close.rolling(20).std()
df1d["bb_mid"] = df1d.sma20

# ATR 1D
tr1d = pd.concat([df1d.high - df1d.low, (df1d.high - df1d.close.shift()).abs(), (df1d.low - df1d.close.shift()).abs()], axis=1).max(axis=1)
df1d["atr"] = tr1d.ewm(alpha=1/14, adjust=False).mean()

# مقاومة ودعم 30 يوم
df1d["res30"] = df1d.high.rolling(30).max().shift(1)
df1d["sup30"] = df1d.low.rolling(30).min().shift(1)

# إشارات اليوم
bull_regime = (df1d.phase.isin(["bull", "sideways"])) & (df1d.close > df1d.sma200)
bear_regime = (df1d.phase == "bear") & (df1d.close < df1d.sma200)

long_setup = bull_regime & (df1d.close > df1d.bb_mid) & (df1d.close.shift(1) <= df1d.bb_mid.shift(1))
short_setup = bear_regime & (df1d.close < df1d.bb_mid) & (df1d.close.shift(1) >= df1d.bb_mid.shift(1))

df1d["long_setup"] = long_setup
df1d["short_setup"] = short_setup

# تأكيد على فريم 4H: أول شمعة 4H في اليوم التالي D+1 00:00 تكسر في نفس الاتجاه
df1d_shifted = df1d[["ts", "long_setup", "short_setup", "atr", "res30", "sup30"]].copy()
df1d_shifted["ts"] = df1d_shifted["ts"] + pd.Timedelta(days=1)

m = pd.merge_asof(df4h.sort_values("ts"), df1d_shifted.sort_values("ts"), on="ts", direction="backward")

trades = []
n = len(m)
i = 200
while i < n - 2:
    is_long = m.long_setup.iat[i] and (m.close.iat[i] > m.open.iat[i])
    is_short = m.short_setup.iat[i] and (m.close.iat[i] < m.open.iat[i])
    if not (is_long or is_short):
        i += 1; continue
    s = 1 if is_long else -1
    entry = m.open.iat[i+1]
    dist = 1.5 * m.atr.iat[i] # 1.5x Daily ATR
    stop = entry - s * dist
    res_lvl = m.res30.iat[i] if s > 0 else m.sup30.iat[i]
    
    peak_profit = 0.0
    j = i + 1
    res = None
    while j < min(n, i + 1 + 14 * 6): # أقصى مدة 14 يوماً (84 شمعة 4H)
        cur_high = m.high.iat[j]
        cur_low = m.low.iat[j]
        cur_close = m.close.iat[j]
        
        # ربح حالي
        cur_profit = s * (cur_high - entry if s > 0 else entry - cur_low)
        peak_profit = max(peak_profit, cur_profit)
        
        # 1. وقف الخسارة المبدئي
        if (s > 0 and cur_low <= stop) or (s < 0 and cur_high >= stop):
            res = (stop - entry) / dist if s > 0 else (entry - stop) / dist
            break
            
        # 2. هدف المقاومة/الدعم (30 يوم)
        if res_lvl and np.isfinite(res_lvl):
            if (s > 0 and cur_high >= res_lvl) or (s < 0 and cur_low <= res_lvl):
                res = s * (res_lvl - entry) / dist
                break
                
        # 3. Trailing Drawdown Stop: إذا كان في ربح وتراجع الربح بنسبة 20% من أقصى قمة
        if peak_profit > 1.0 * dist:
            drawdown = (peak_profit - s * (cur_close - entry)) / peak_profit
            if drawdown >= 0.20:
                res = s * (cur_close - entry) / dist
                break
        j += 1
        
    if res is None:
        res = s * (m.close.iat[j-1] - entry) / dist
        
    cost_r = 0.0009 * entry / dist
    trades.append((m.ts.iat[i+1], s, res - cost_r, (j - i) * 4 / 24))
    i = j

tdf = pd.DataFrame(trades, columns=["ts", "side", "r", "days"])
pos_r = tdf[tdf.r > 0].r.sum(); neg_r = -tdf[tdf.r < 0].r.sum()
pf = pos_r / neg_r if neg_r > 0 else 99
w = (tdf.r > 0).mean() * 100
t_oos = tdf[tdf.ts >= pd.Timestamp("2024-01-01", tz="UTC")]
pos_oos = t_oos[t_oos.r > 0].r.sum(); neg_oos = -t_oos[t_oos.r < 0].r.sum()
pf_oos = pos_oos / neg_oos if neg_oos > 0 else 99
w_oos = (t_oos.r > 0).mean() * 100 if len(t_oos) else 0
days = (tdf.ts.iloc[-1] - tdf.ts.iloc[0]).days

print("=== اختبار استراتيجية GitHub (Bollinger Trend + Halving Regime #97) ===")
print(f"الصفقات: {len(tdf)} ({len(tdf)/days*365:.1f}/سنة)")
print(f"نسبة الفوز: {w:.1f}%")
print(f"عامل الربح (Profit Factor): {pf:.2f}")
print(f"إجمالي الأرباح الصافية: +{tdf.r.sum():+.1f}R")
print(f"خارج العينة (2024+): {len(t_oos)} صفقة | فوز {w_oos:.1f}% | PF: {pf_oos:.2f} | أرباح: +{t_oos.r.sum():+.1f}R")

yr = tdf.groupby(tdf.ts.dt.year)["r"].agg(["count", "sum"]).round(1)
print("\nالنتائج السنوية:")
for y, (cnt, r_sum) in yr.iterrows():
    print(f"  {y}: {int(cnt)} صفقات | {r_sum:+.1f}R")
