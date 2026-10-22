import pandas as pd
import numpy as np

# اختبار نماذج النخبة والمحترفين ذات نسبة الفوز العالية جداً (>60-70% Win Rate):
# 1. Previous Day High / Low (PDH / PDL) Turtle Soup Sweep (كنس قمة/قاع اليوم السابق المؤسسي)
# 2. 4H Range High/Low Liquidity Sweep with 1H Confirmation
# 3. EMA Pullback in Strong Bull Market (SMA50 > SMA200 + Daily Trend)
# 4. Multi-Timeframe High-Win-Rate Reversion (RSI 4-bar extreme + BB pinch)

df1h = pd.read_csv("research/btc_1h.csv", parse_dates=["ts"])
df1d = pd.read_csv("research/btc_1d.csv", parse_dates=["ts"])

# حساب قمة وقاع اليوم السابق بدقة (تتاح للشمعة الحالية بعد إغلاق اليوم فقط)
df1d["date"] = df1d.ts.dt.date
df1d["pdh"] = df1d.high.shift(1)
df1d["pdl"] = df1d.low.shift(1)
df1d["pdc"] = df1d.close.shift(1)

df1h["date"] = df1h.ts.dt.date
m = pd.merge(df1h, df1d[["date", "pdh", "pdl", "pdc"]], on="date", how="left")

# ترند يومي
df1d["ema50"] = df1d.close.ewm(span=50, adjust=False).mean()
df1d["ema200"] = df1d.close.ewm(span=200, adjust=False).mean()
df1d["daily_bull"] = (df1d.close > df1d.ema50) & (df1d.ema50 > df1d.ema200)
df1d["daily_bear"] = (df1d.close < df1d.ema50) & (df1d.ema50 < df1d.ema200)

df1d_shift = df1d[["date", "daily_bull", "daily_bear"]].copy()
m = pd.merge(m, df1d_shift, on="date", how="left")

c, o, h, l, v = m.close.values, m.open.values, m.high.values, m.low.values, m.volume.values
pdh, pdl = m.pdh.values, m.pdl.values
bull = m.daily_bull.fillna(False).values
bear = m.daily_bear.fillna(False).values

tr1h = pd.concat([m.high - m.low, (m.high - m.close.shift()).abs(), (m.low - m.close.shift()).abs()], axis=1).max(axis=1)
atr1h = tr1h.ewm(alpha=1/14, adjust=False).mean().values
ema50_1h = m.close.ewm(span=50, adjust=False).mean().values

# استراتيجية 1: PDL / PDH Turtle Soup Sweep
# في ترند صاعد: يكسر قاع اليوم السابق PDL ثم يعود يغلق فوقه داخل شمعة 1H = فخ مؤسسي Bear Trap (شراء)
# في ترند هابط: يكسر قمة اليوم السابق PDH ثم يعود يغلق تحتها = فخ مؤسسي Bull Trap (بيع)
long_soup = bull & (l < pdl) & (c > pdl) & (c > o)
short_soup = bear & (h > pdh) & (c < pdh) & (c < o)
sig_soup = np.where(long_soup, 1, np.where(short_soup, -1, 0))

def test_strat(sig_arr, name, stop_atr=1.5, rr=2.0, be_r=1.0, max_bars=36):
    trades = []
    n = len(m)
    i = 50
    while i < n - 2:
        s = sig_arr[i]
        if s == 0 or not np.isfinite(atr1h[i]): i += 1; continue
        entry = o[i+1]
        dist = stop_atr * atr1h[i]
        stop = entry - s * dist
        tp = entry + s * rr * dist
        best = entry
        j = i + 1
        res = None
        while j < min(n, i + 1 + max_bars):
            if s > 0:
                if l[j] <= stop: res = (stop - entry) / dist; break
                if h[j] >= tp: res = rr; break
                best = max(best, h[j])
            else:
                if h[j] >= stop: res = (entry - stop) / dist; break
                if l[j] <= tp: res = rr; break
                best = min(best, l[j])
            if be_r and s * (best - entry) >= be_r * dist:
                stop = max(stop, entry) if s > 0 else min(stop, entry)
            j += 1
        if res is None: res = s * (c[j-1] - entry) / dist
        trades.append((m.ts.iloc[i+1], s, res - 0.0008 * entry / dist, j - i))
        i = j
    tdf = pd.DataFrame(trades, columns=["ts", "side", "r", "bars"])
    if len(tdf) == 0: return
    t_oos = tdf[tdf.ts >= pd.Timestamp("2024-01-01", tz="UTC")]
    t_7d = tdf[tdf.ts >= m.ts.iloc[-1] - pd.Timedelta(days=7)]
    days = (tdf.ts.iloc[-1] - tdf.ts.iloc[0]).days
    pos_r = tdf[tdf.r > 0].r.sum(); neg_r = -tdf[tdf.r < 0].r.sum()
    pf = pos_r / neg_r if neg_r > 0 else 99
    pos_oos = t_oos[t_oos.r > 0].r.sum(); neg_oos = -t_oos[t_oos.r < 0].r.sum()
    pf_oos = pos_oos / neg_oos if neg_oos > 0 else 99
    w = (tdf.r > 0).mean() * 100
    w_oos = (t_oos.r > 0).mean() * 100 if len(t_oos) else 0
    print(f"{name:32s} | N:{len(tdf):4d} ({len(tdf)/days*7:3.1f}/wk) | Win:{w:4.1f}% | PF:{pf:.2f} | OOS Win:{w_oos:.1f}% | OOS PF:{pf_oos:.2f} | Tot R:{tdf.r.sum():+.1f}R | 7D: {len(t_7d)} ({t_7d.r.sum():+.2f}R)")

for rr in (1.5, 2.0):
    for stop_atr in (1.0, 1.5):
        test_strat(sig_soup, f"PDH/PDL Sweep (stop={stop_atr}, rr={rr})", stop_atr=stop_atr, rr=rr, be_r=1.0)
