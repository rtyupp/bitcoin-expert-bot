import pandas as pd
import numpy as np

# فحص استراتيجيات 1H رابحة إحصائياً وتعمل بمعدل شبه يومي (4 إلى 7 صفقات بالأسبوع)
df = pd.read_csv("research/btc_1h.csv", parse_dates=["ts"])
c, o, h, l, v = df.close.values, df.open.values, df.high.values, df.low.values, df.volume.values

tr = pd.concat([df.high - df.low, (df.high - df.close.shift()).abs(), (df.low - df.close.shift()).abs()], axis=1).max(axis=1)
atr = tr.ewm(alpha=1/14, adjust=False).mean().values

ema20 = df.close.ewm(span=20, adjust=False).mean().values
ema50 = df.close.ewm(span=50, adjust=False).mean().values
ema100 = df.close.ewm(span=100, adjust=False).mean().values
ema200 = df.close.ewm(span=200, adjust=False).mean().values

v20 = df.volume.rolling(20).mean().values

# 1) Session Momentum Breakout: كسر قمة/قاع 12 شمعة مع تأكيد الحجم وترند EMA20>50
lo12 = df.low.rolling(12).min().shift().values
hi12 = df.high.rolling(12).max().shift().values

# 2) RSI Divergence / Extreme Reversal on 1H
diff = df.close.diff()
up = diff.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
dn = (-diff.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
rsi14 = (100 - 100 / (1 + up / dn.replace(0, np.nan))).values

# 3) Donchian 16h with Trend
lo16 = df.low.rolling(16).min().shift().values
hi16 = df.high.rolling(16).max().shift().values

# 4) EMA 20 Pullback in Trend:
# الترند صاعد قوي: EMA20 > EMA50 > EMA100
# الشمعة تلمس EMA20 من أعلى وتغلق فوقه (ارتداد)
bull_trend = (ema20 > ema50) & (c > ema100)
bear_trend = (ema20 < ema50) & (c < ema100)

pb_long = bull_trend & (l <= ema20) & (c > ema20) & (c > o)
pb_short = bear_trend & (h >= ema20) & (c < ema20) & (c < o)

def evaluate(sig_arr, name, stop_atr=1.5, rr=2.0, max_bars=24):
    trades = []
    n = len(df)
    i = 200
    while i < n - 2:
        s = sig_arr[i]
        if s == 0:
            i += 1
            continue
        entry = o[i+1]
        d = stop_atr * atr[i]
        stop = entry - s * d
        tp = entry + s * rr * d
        j = i + 1
        res = None
        while j < min(n, i + 1 + max_bars):
            if s > 0:
                if l[j] <= stop:
                    res = (stop - entry) / d; break
                if h[j] >= tp:
                    res = rr; break
            else:
                if h[j] >= stop:
                    res = (entry - stop) / d; break
                if l[j] <= tp:
                    res = rr; break
            j += 1
        if res is None:
            res = s * (c[j-1] - entry) / d
        # تكلفة 0.08%
        cost_r = 0.0008 * entry / d
        trades.append((df.ts.iloc[i+1], s, res - cost_r, j - i))
        i = j
    tdf = pd.DataFrame(trades, columns=["ts", "side", "r", "bars"])
    if len(tdf) == 0: return
    t_oos = tdf[tdf.ts >= pd.Timestamp("2024-01-01", tz="UTC")]
    t_7d = tdf[tdf.ts >= df.ts.iloc[-1] - pd.Timedelta(days=7)]
    days = (tdf.ts.iloc[-1] - tdf.ts.iloc[0]).days
    w = (tdf.r > 0).mean() * 100
    pos_r = tdf[tdf.r > 0].r.sum()
    neg_r = -tdf[tdf.r < 0].r.sum()
    pf = pos_r / neg_r if neg_r > 0 else 99
    
    w_oos = (t_oos.r > 0).mean() * 100
    pos_oos = t_oos[t_oos.r > 0].r.sum()
    neg_oos = -t_oos[t_oos.r < 0].r.sum()
    pf_oos = pos_oos / neg_oos if neg_oos > 0 else 99
    
    print(f"{name:32s} | N: {len(tdf):4d} ({len(tdf)/days*7:.1f}/wk) | Win: {w:4.1f}% | PF: {pf:.2f} | Exp: {tdf.r.mean():+.3f}R | OOS PF: {pf_oos:.2f} | 7D: {len(t_7d)} tr ({t_7d.r.sum():+.2f}R)")

sig1 = np.where(pb_long, 1, np.where(pb_short, -1, 0))
evaluate(sig1, "EMA20 Pullback (rr=2.0)", 1.5, 2.0)
evaluate(sig1, "EMA20 Pullback (rr=1.5)", 1.5, 1.5)
evaluate(sig1, "EMA20 Pullback (rr=2.5)", 2.0, 2.5)

# Donchian 16
dc_long = (c > hi16) & (c > ema100) & (v > 1.2 * v20)
dc_short = (c < lo16) & (c < ema100) & (v > 1.2 * v20)
sig2 = np.where(dc_long, 1, np.where(dc_short, -1, 0))
evaluate(sig2, "Donchian 16h + Vol (rr=2.0)", 1.5, 2.0)
evaluate(sig2, "Donchian 16h + Vol (rr=1.5)", 1.5, 1.5)

# Bollinger Bands Mean Reversion inside Range (ADX < 25)
tr_s = pd.Series(atr)
up_d = df.high.diff()
dn_d = -df.low.diff()
pdm = np.where((up_d > dn_d) & (up_d > 0), up_d, 0.0)
ndm = np.where((dn_d > up_d) & (dn_d > 0), dn_d, 0.0)
pdi = 100 * pd.Series(pdm).ewm(alpha=1/14, adjust=False).mean() / atr
ndi = 100 * pd.Series(ndm).ewm(alpha=1/14, adjust=False).mean() / atr
dx = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
adx = dx.ewm(alpha=1/14, adjust=False).mean().values

sma20 = df.close.rolling(20).mean().values
std20 = df.close.rolling(20).std().values
bb_u = sma20 + 2 * std20
bb_l = sma20 - 2 * std20

bb_long = (adx < 25) & (l <= bb_l) & (c > o) & (c > bb_l)
bb_short = (adx < 25) & (h >= bb_u) & (c < o) & (c < bb_u)
sig3 = np.where(bb_long, 1, np.where(bb_short, -1, 0))
evaluate(sig3, "BB Range Reversal (rr=1.5)", 1.5, 1.5)
evaluate(sig3, "BB Range Reversal (rr=1.2)", 1.2, 1.2)
