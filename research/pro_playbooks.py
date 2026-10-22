"""مختبر استراتيجيات المحترفين للتداول السريع على البيتكوين (15m و 1h).
يختبر 10 من أقوى مخططات التداول اليومي المعروفة عالمياً:
1. ORB (London/NY Opening Range Breakout - كسر نطاق افتتاح الجلسات)
2. Daily VWAP Deviation Bands (ارتداد انحراف الفوليوم المؤسسي VWAP)
3. FVG Displacement & Retest (فجوات القيمة العادلة المؤسسية مع الارتداد)
4. Asia Sweep + MSS (Market Structure Shift - كنس آسيا مع تحول الهيكل)
5. Camarilla Equation Pivots (معادلات كاماريلا للمحترفين L3/H3 Reversal, L4/H4 Breakout)
6. Keltner/Bollinger Squeeze Intraday (انفجار التذبذب المضغوط)
7. SuperTrend + MFI/Chaikin (متابعة الزخم وتدفق السيولة)
8. EMA Ribbon Trend Flow (شريط المتوسطات 9/21/55 للتداول مع الاتجاه)
9. Connors RSI Momentum Scalper (قناص الارتدادات السريعة)
10. Session High/Low Retest Flow (اختبار مناطق العرض والطلب للجلسات السابقة)
"""
import pandas as pd
import numpy as np

# تحميل بيانات 15m (168,000 شمعة من 2022 إلى 2026) وبيانات 1h (68,000 شمعة من 2019 إلى 2026)
df15 = pd.read_csv("research/btc_15m.csv", parse_dates=["ts"])
df1h = pd.read_csv("research/btc_1h.csv", parse_dates=["ts"])

print(f"Data 15m: {len(df15)} bars | 1h: {len(df1h)} bars")

COST = 0.0008  # 0.08% سبريد وانزلاق

def sim_fast(df, sig, stop_mult=1.5, rr=1.8, max_bars=32, be_at=1.0, trail_r=None):
    o, h, l, c = df.open.values, df.high.values, df.low.values, df.close.values
    atr = df.atr.values
    n = len(df)
    trades = []
    i = 100
    while i < n - 2:
        s = sig[i]
        if s == 0 or not np.isfinite(atr[i]):
            i += 1; continue
        entry = o[i+1]
        d = stop_mult * atr[i]
        stop = entry - s * d
        tp = entry + s * rr * d if rr else None
        best = entry
        j = i + 1
        res = None
        while j < min(n, i + 1 + max_bars):
            if s > 0:
                if l[j] <= stop:
                    res = (stop - entry) / d; break
                if tp and h[j] >= tp:
                    res = rr; break
                best = max(best, h[j])
            else:
                if h[j] >= stop:
                    res = (entry - stop) / d; break
                if tp and l[j] <= tp:
                    res = rr; break
                best = min(best, l[j])
            if be_at and s * (best - entry) >= be_at * d:
                stop = max(stop, entry) if s > 0 else min(stop, entry)
            if trail_r:
                ns = best - s * trail_r * d
                stop = max(stop, ns) if s > 0 else min(stop, ns)
            j += 1
        if res is None:
            res = s * (c[j-1] - entry) / d
        trades.append((df.ts.iloc[i+1], s, res - COST * entry / d, j - i))
        i = j
    tdf = pd.DataFrame(trades, columns=["ts", "side", "r", "bars"])
    return tdf

def calc_stats(tdf, df_ref, name=""):
    if len(tdf) == 0:
        return f"{name:40s} | NO TRADES"
    t_oos = tdf[tdf.ts >= pd.Timestamp("2024-01-01", tz="UTC")]
    t_7d = tdf[tdf.ts >= df_ref.ts.iloc[-1] - pd.Timedelta(days=7)]
    days = max(1, (tdf.ts.iloc[-1] - tdf.ts.iloc[0]).days)
    pos_r = tdf[tdf.r > 0].r.sum(); neg_r = -tdf[tdf.r < 0].r.sum()
    pf = pos_r / neg_r if neg_r > 0 else 99
    
    pos_oos = t_oos[t_oos.r > 0].r.sum(); neg_oos = -t_oos[t_oos.r < 0].r.sum()
    pf_oos = pos_oos / neg_oos if neg_oos > 0 else 99
    
    w = (tdf.r > 0).mean() * 100
    w_oos = (t_oos.r > 0).mean() * 100 if len(t_oos) else 0
    freq_wk = len(tdf) / days * 7
    return {
        "name": name, "n": len(tdf), "freq_wk": round(freq_wk, 1),
        "win": round(w, 1), "pf": round(pf, 2), "total_r": round(tdf.r.sum(), 1),
        "exp": round(tdf.r.mean(), 3), "oos_n": len(t_oos), "oos_pf": round(pf_oos, 2),
        "oos_r": round(t_oos.r.sum(), 1), "7d_n": len(t_7d), "7d_r": round(t_7d.r.sum(), 2)
    }

# ==============================================================================
# 1. Opening Range Breakout (ORB) - فريم 15m
# افتتاح لندن 07:00 UTC (شمعة 07:00-07:15 هي نطاق الافتتاح)
# ==============================================================================
print("\n--- 1. Testing ORB (Opening Range Breakout 15m) ---")
d15 = df15.copy()
tr = pd.concat([d15.high - d15.low, (d15.high - d15.close.shift()).abs(), (d15.low - d15.close.shift()).abs()], axis=1).max(axis=1)
d15["atr"] = tr.ewm(alpha=1/14, adjust=False).mean()
d15["hour"] = d15.ts.dt.hour
d15["min"] = d15.ts.dt.minute
d15["date"] = d15.ts.dt.date
d15["ema50"] = d15.close.ewm(span=50, adjust=False).mean()

# لندن: نطاق شمعة 07:00
orb_bars = d15[(d15.hour == 7) & (d15.min == 0)][["date", "high", "low"]].rename(columns={"high": "orb_h", "low": "orb_l"})
d15 = pd.merge(d15, orb_bars, on="date", how="left")

# دخول عند كسر الـ ORB بين 07:15 و 11:00 مع EMA50
sig_orb = np.zeros(len(d15))
london_hours = (d15.hour >= 7) & (d15.hour <= 11)
orb_long = london_hours & (d15.close > d15.orb_h) & (d15.close.shift() <= d15.orb_h) & (d15.close > d15.ema50)
orb_short = london_hours & (d15.close < d15.orb_l) & (d15.close.shift() >= d15.orb_l) & (d15.close < d15.ema50)
sig_orb[orb_long] = 1; sig_orb[orb_short] = -1

t_orb = sim_fast(d15, sig_orb, stop_mult=1.5, rr=2.0, max_bars=16, be_at=1.0)
print(calc_stats(t_orb, d15, "London ORB 15m (rr=2.0)"))

# ==============================================================================
# 2. Daily VWAP Deviation Bands (ارتداد الفوليوم المؤسسي VWAP على 15m)
# ==============================================================================
print("\n--- 2. Testing Daily Anchored VWAP Deviation (15m) ---")
# حساب VWAP يومي يبدأ كل يوم عند 00:00 UTC
d15["pv"] = d15.close * d15.volume
d15["cum_pv"] = d15.groupby("date")["pv"].cumsum()
d15["cum_vol"] = d15.groupby("date")["volume"].cumsum()
d15["vwap"] = d15["cum_pv"] / d15["cum_vol"].replace(0, np.nan)
d15["vwap_diff2"] = ((d15.close - d15.vwap) ** 2) * d15.volume
d15["vwap_sd"] = np.sqrt(d15.groupby("date")["vwap_diff2"].cumsum() / d15["cum_vol"].replace(0, np.nan))

d15["vwap_up2"] = d15.vwap + 2.0 * d15.vwap_sd
d15["vwap_lo2"] = d15.vwap - 2.0 * d15.vwap_sd

# استراتيجية VWAP: ارتداد عند ملامسة ±2 انحراف معياري نحو خط الـ VWAP المركزي
sig_vwap = np.zeros(len(d15))
vwap_long = (d15.low <= d15.vwap_lo2) & (d15.close > d15.open) & (d15.close < d15.vwap)
vwap_short = (d15.high >= d15.vwap_up2) & (d15.close < d15.open) & (d15.close > d15.vwap)
sig_vwap[vwap_long] = 1; sig_vwap[vwap_short] = -1

t_vwap = sim_fast(d15, sig_vwap, stop_mult=1.2, rr=1.8, max_bars=20, be_at=1.0)
print(calc_stats(t_vwap, d15, "Daily VWAP 2-Sigma Mean Reversion 15m"))

# ==============================================================================
# 3. Fair Value Gap (FVG) Displacement & Retest (فريم 1h)
# شمعة اندفاع مؤسسي تخلق فجوة FVG ثم إعادة اختبار الفجوة في الاتجاه
# ==============================================================================
print("\n--- 3. Testing FVG Displacement & Retest (1h) ---")
d1h = df1h.copy()
tr1h = pd.concat([d1h.high - d1h.low, (d1h.high - d1h.close.shift()).abs(), (d1h.low - d1h.close.shift()).abs()], axis=1).max(axis=1)
d1h["atr"] = tr1h.ewm(alpha=1/14, adjust=False).mean()
d1h["ema100"] = d1h.close.ewm(span=100, adjust=False).mean()

# Bullish FVG: Low[i] > High[i-2]
# Bearish FVG: High[i] < Low[i-2]
fvg_bull = d1h.low.shift(1) > d1h.high.shift(3)
fvg_top = d1h.low.shift(1)
fvg_bot = d1h.high.shift(3)

fvg_bear = d1h.high.shift(1) < d1h.low.shift(3)
fvg_b_top = d1h.low.shift(3)
fvg_b_bot = d1h.high.shift(1)

# إعادة اختبار الفجوة
long_fvg = fvg_bull & (d1h.low <= fvg_top) & (d1h.close >= fvg_bot) & (d1h.close > d1h.open) & (d1h.close > d1h.ema100)
short_fvg = fvg_bear & (d1h.high >= fvg_b_bot) & (d1h.close <= fvg_b_top) & (d1h.close < d1h.open) & (d1h.close < d1h.ema100)

sig_fvg = np.zeros(len(d1h))
sig_fvg[long_fvg] = 1; sig_fvg[short_fvg] = -1

t_fvg = sim_fast(d1h, sig_fvg, stop_mult=1.5, rr=2.0, max_bars=24, be_at=1.0)
print(calc_stats(t_fvg, d1h, "SMC FVG Displacement & Retest 1H"))

# ==============================================================================
# 4. Camarilla Equation Pivots (H3/L3 Reversal, H4/L4 Breakout - 15m)
# معادلات كاماريلا الشهيرة لمستويات التداول اليومي
# ==============================================================================
print("\n--- 4. Testing Camarilla Pivots (15m) ---")
# حساب H, L, C لليوم السابق
daily = d15.groupby("date").agg(d_high=("high", "max"), d_low=("low", "min"), d_close=("close", "last")).reset_index()
daily["range"] = daily.d_high - daily.d_low
daily["h4"] = daily.d_close + daily["range"] * 1.1 / 2.0
daily["h3"] = daily.d_close + daily["range"] * 1.1 / 4.0
daily["l3"] = daily.d_close - daily["range"] * 1.1 / 4.0
daily["l4"] = daily.d_close - daily["range"] * 1.1 / 2.0
daily_prev = daily.shift(1).copy()
daily_prev["date"] = daily["date"]

d15_cam = pd.merge(d15, daily_prev[["date", "h4", "h3", "l3", "l4"]], on="date", how="left")

# كسر H4/L4 اختراق اتجاهي (Camarilla Breakout)
cam_long = (d15_cam.close > d15_cam.h4) & (d15_cam.close.shift() <= d15_cam.h4)
cam_short = (d15_cam.close < d15_cam.l4) & (d15_cam.close.shift() >= d15_cam.l4)
sig_cam = np.zeros(len(d15_cam))
sig_cam[cam_long] = 1; sig_cam[cam_short] = -1

t_cam = sim_fast(d15_cam, sig_cam, stop_mult=1.5, rr=2.0, max_bars=20, be_at=1.0)
print(calc_stats(t_cam, d15_cam, "Camarilla H4/L4 Breakout 15m"))

# ==============================================================================
# 5. Keltner + Bollinger Squeeze (فريم 1h)
# ضغط البولينجر داخل قنوات كيلتنر ثم انفجار الزخم
# ==============================================================================
print("\n--- 5. Testing Keltner Squeeze Momentum (1h) ---")
sma20_1h = d1h.close.rolling(20).mean()
std20_1h = d1h.close.rolling(20).std()
bb_up_1h = sma20_1h + 2.0 * std20_1h
bb_lo_1h = sma20_1h - 2.0 * std20_1h

kelt_up = sma20_1h + 1.5 * d1h.atr
kelt_lo = sma20_1h - 1.5 * d1h.atr

# Squeeze On: بولينجر داخل كيلتنر
squeeze_on = (bb_up_1h < kelt_up) & (bb_lo_1h > kelt_lo)
squeeze_fired = squeeze_on.shift(1) & ~squeeze_on

# اتجاه الانفجار مع فوليوم
v20_1h = d1h.volume.rolling(20).mean()
sq_long = squeeze_fired & (d1h.close > bb_up_1h) & (d1h.volume > 1.3 * v20_1h)
sq_short = squeeze_fired & (d1h.close < bb_lo_1h) & (d1h.volume > 1.3 * v20_1h)
sig_sq = np.zeros(len(d1h))
sig_sq[sq_long] = 1; sig_sq[sq_short] = -1

t_sq = sim_fast(d1h, sig_sq, stop_mult=1.5, rr=2.5, max_bars=24, be_at=1.0)
print(calc_stats(t_sq, d1h, "Keltner/BB Squeeze Breakout 1H"))

# ==============================================================================
# 6. EMA Ribbon Trend Flow (9 / 21 / 55 EMA) مع فلتر فوليوم (15m)
# ==============================================================================
print("\n--- 6. Testing EMA Ribbon Flow 15m ---")
e9 = d15.close.ewm(span=9, adjust=False).mean()
e21 = d15.close.ewm(span=21, adjust=False).mean()
e55 = d15.close.ewm(span=55, adjust=False).mean()

ribbon_long = (e9 > e21) & (e21 > e55) & (d15.low <= e21) & (d15.close > e9) & (d15.close > d15.open)
ribbon_short = (e9 < e21) & (e21 < e55) & (d15.high >= e21) & (d15.close < e9) & (d15.close < d15.open)
sig_ribbon = np.zeros(len(d15))
sig_ribbon[ribbon_long] = 1; sig_ribbon[ribbon_short] = -1

t_rib = sim_fast(d15, sig_ribbon, stop_mult=1.5, rr=2.0, max_bars=24, be_at=1.0)
print(calc_stats(t_rib, d15, "EMA Ribbon 9/21/55 Flow 15m"))

# ==============================================================================
# 7. Connors RSI Multi-Timeframe Momentum (15m)
# ==============================================================================
print("\n--- 7. Testing Connors RSI MTF Momentum (15m) ---")
diff15 = d15.close.diff()
up15 = diff15.clip(lower=0).ewm(alpha=1/3, adjust=False).mean()
dn15 = (-diff15.clip(upper=0)).ewm(alpha=1/3, adjust=False).mean()
crsi = (100 - 100 / (1 + up15 / dn15.replace(0, np.nan)))

# ترند عام بواسطة EMA200
e200_15 = d15.close.ewm(span=200, adjust=False).mean()
crsi_long = (d15.close > e200_15) & (crsi < 15) & (d15.close > d15.open)
crsi_short = (d15.close < e200_15) & (crsi > 85) & (d15.close < d15.open)
sig_crsi = np.zeros(len(d15))
sig_crsi[crsi_long] = 1; sig_crsi[crsi_short] = -1

t_crsi = sim_fast(d15, sig_crsi, stop_mult=1.5, rr=1.8, max_bars=16, be_at=1.0)
print(calc_stats(t_crsi, d15, "Connors RSI Trend Dip 15m"))
