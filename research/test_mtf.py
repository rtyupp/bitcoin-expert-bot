import pandas as pd
import numpy as np

# اختبار استراتيجيات 1h و 15m مع فلاتر أطر زمنية أعلى (4H / Daily Regime) لضمان ربحية حقيقية
df1h = pd.read_csv("research/btc_1h.csv", parse_dates=["ts"])
df4h = pd.read_csv("research/btc_4h.csv", parse_dates=["ts"])

# حساب نظام 4H
df4h["ema50_4h"] = df4h.close.ewm(span=50, adjust=False).mean()
df4h["ema200_4h"] = df4h.close.ewm(span=200, adjust=False).mean()
df4h["bull_4h"] = (df4h.close > df4h.ema50_4h) & (df4h.ema50_4h > df4h.ema200_4h)
df4h["bear_4h"] = (df4h.close < df4h.ema50_4h) & (df4h.ema50_4h < df4h.ema200_4h)

# دمج نظام 4H مع 1H (مع إزاحة شمعة لتجنب التسريب)
df4h_shifted = df4h[["ts", "bull_4h", "bear_4h"]].copy()
df4h_shifted["ts"] = df4h_shifted["ts"] + pd.Timedelta(hours=4)

m = pd.merge_asof(df1h.sort_values("ts"), df4h_shifted.sort_values("ts"), on="ts", direction="backward")
bull_4h = m["bull_4h"].fillna(False).values
bear_4h = m["bear_4h"].fillna(False).values

c, o, h, l, v = df1h.close.values, df1h.open.values, df1h.high.values, df1h.low.values, df1h.volume.values

tr = pd.concat([df1h.high - df1h.low, (df1h.high - df1h.close.shift()).abs(), (df1h.low - df1h.close.shift()).abs()], axis=1).max(axis=1)
atr = tr.ewm(alpha=1/14, adjust=False).mean().values

ema20 = df1h.close.ewm(span=20, adjust=False).mean().values

# RSI(2) على 1h
diff = df1h.close.diff()
up2 = diff.clip(lower=0).ewm(alpha=1/2, adjust=False).mean()
dn2 = (-diff.clip(upper=0)).ewm(alpha=1/2, adjust=False).mean()
rsi2 = (100 - 100 / (1 + up2 / dn2.replace(0, np.nan))).values

# 1) 1H RSI(2) مع ترند 4H (صفقات سريعة ومرنة جداً)
# شراء: ترند 4H صاعد + RSI(2) تحت 10
# بيع: ترند 4H هابط + RSI(2) فوق 90
sig_rsi2_1h = np.zeros(len(df1h))
sig_rsi2_1h[bull_4h & (rsi2 < 10) & (c > ema20)] = 1
sig_rsi2_1h[bear_4h & (rsi2 > 90) & (c < ema20)] = -1

# 2) 1H Session Breakout: كسر قمة/قاع 8 ساعات مع ترند 4H
hi8 = df1h.high.rolling(8).max().shift().values
lo8 = df1h.low.rolling(8).min().shift().values
sig_brk = np.zeros(len(df1h))
sig_brk[bull_4h & (c > hi8)] = 1
sig_brk[bear_4h & (c < lo8)] = -1

# 3) 1H SMC Liquidity Sweep مع ترند 4H
hi16 = df1h.high.rolling(16).max().shift().values
lo16 = df1h.low.rolling(16).min().shift().values
sig_sw = np.zeros(len(df1h))
sig_sw[bull_4h & (l < lo16) & (c > lo16) & (c > o)] = 1
sig_sw[bear_4h & (h > hi16) & (c < hi16) & (c < o)] = -1

def test_strat(sig_arr, name, stop_atr=1.5, rr=2.0, trail_r=None, be_r=1.0, max_bars=36):
    trades = []
    n = len(df1h)
    i = 200
    while i < n - 2:
        s = sig_arr[i]
        if s == 0:
            i += 1
            continue
        entry = o[i+1]
        d = stop_atr * atr[i]
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
            if be_r and s * (best - entry) >= be_r * d:
                stop = max(stop, entry) if s > 0 else min(stop, entry)
            if trail_r:
                ns = best - s * trail_r * d
                stop = max(stop, ns) if s > 0 else min(stop, ns)
            j += 1
        if res is None:
            res = s * (c[j-1] - entry) / d
        trades.append((df1h.ts.iloc[i+1], s, res - 0.0008 * entry / d, j - i))
        i = j
    tdf = pd.DataFrame(trades, columns=["ts", "side", "r", "bars"])
    if len(tdf) == 0: return
    t_oos = tdf[tdf.ts >= pd.Timestamp("2024-01-01", tz="UTC")]
    t_7d = tdf[tdf.ts >= df1h.ts.iloc[-1] - pd.Timedelta(days=7)]
    days = (tdf.ts.iloc[-1] - tdf.ts.iloc[0]).days
    pos_r = tdf[tdf.r > 0].r.sum()
    neg_r = -tdf[tdf.r < 0].r.sum()
    pf = pos_r / neg_r if neg_r > 0 else 99
    
    pos_oos = t_oos[t_oos.r > 0].r.sum()
    neg_oos = -t_oos[t_oos.r < 0].r.sum()
    pf_oos = pos_oos / neg_oos if neg_oos > 0 else 99
    
    print(f"{name:35s} | N:{len(tdf):4d} ({len(tdf)/days*7:3.1f}/wk) | Win:{(tdf.r>0).mean()*100:4.1f}% | PF:{pf:.2f} | Exp:{tdf.r.mean():+.3f}R | OOS PF:{pf_oos:.2f} | 7D:{len(t_7d)} ({t_7d.r.sum():+.2f}R)")

test_strat(sig_rsi2_1h, "1H RSI2 + 4H Trend (rr=2.0, be=1.0)", 1.5, 2.0, be_r=1.0)
test_strat(sig_rsi2_1h, "1H RSI2 + 4H Trend (trail=1.5)", 1.5, None, trail_r=1.5)
test_strat(sig_brk, "1H Brk 8h + 4H Trend (rr=1.8)", 1.5, 1.8, be_r=1.0)
test_strat(sig_sw, "1H SMC Sweep 16h + 4H Trend (rr=2.0)", 1.5, 2.0, be_r=1.0)
test_strat(sig_sw, "1H SMC Sweep 16h + 4H Trend (trail=1.5)", 1.5, None, trail_r=1.5)
