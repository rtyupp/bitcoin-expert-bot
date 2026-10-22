import pandas as pd
import numpy as np

# اختبار استراتيجية يومية للبيتكوين (Intraday Daily Scalper/Hunter)
# تجمع بين كنس السيولة المحلي (Session Sweep 4h/8h) مع مؤشر الزخم RSI
# والهدف: إعطاء صيدة كل 1 إلى 2 يوم (4-6 صفقات في الأسبوع) بربحية حقيقية

df = pd.read_csv("research/btc_1h.csv", parse_dates=["ts"])
c, o, h, l, v = df.close.values, df.open.values, df.high.values, df.low.values, df.volume.values

tr = pd.concat([df.high - df.low, (df.high - df.close.shift()).abs(), (df.low - df.close.shift()).abs()], axis=1).max(axis=1)
atr = tr.ewm(alpha=1/14, adjust=False).mean().values

ema20 = df.close.ewm(span=20, adjust=False).mean().values
ema50 = df.close.ewm(span=50, adjust=False).mean().values

# RSI(14)
diff = df.close.diff()
up = diff.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
dn = (-diff.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
rsi = (100 - 100 / (1 + up / dn.replace(0, np.nan))).values

# كنس نطاق 8 ساعات (أعلى/أدنى جلسة تداول)
lo8 = df.low.rolling(8).min().shift().values
hi8 = df.high.rolling(8).max().shift().values

# فحص المعايير المرنة:
# شراء: ضرب قاع 8 ساعات ثم ارتداد إغلاق أخضر و RSI > 35 و c > ema20
# بيع: ضرب قمة 8 ساعات ثم ارتداد إغلاق أحمر و RSI < 65 و c < ema20
for rr in (1.5, 2.0):
    for stop_atr in (1.2, 1.5):
        long_sig = (l < lo8) & (c > lo8) & (c > o) & (c > ema20) & (rsi > 35)
        short_sig = (h > hi8) & (c < hi8) & (c < o) & (c < ema20) & (rsi < 65)
        sig = np.where(long_sig, 1, np.where(short_sig, -1, 0))
        
        trades = []
        n = len(df)
        i = 50
        while i < n - 2:
            s = sig[i]
            if s == 0: i += 1; continue
            entry = o[i+1]
            d = stop_atr * atr[i]
            stop = entry - s * d
            tp = entry + s * rr * d
            j = i + 1
            res = None
            while j < min(n, i + 1 + 24):
                if s > 0:
                    if l[j] <= stop: res = (stop - entry) / d; break
                    if h[j] >= tp: res = rr; break
                else:
                    if h[j] >= stop: res = (entry - stop) / d; break
                    if l[j] <= tp: res = rr; break
                j += 1
            if res is None: res = s * (c[j-1] - entry) / d
            trades.append((df.ts.iloc[i+1], s, res - 0.0008 * entry / d, j - i))
            i = j
        tdf = pd.DataFrame(trades, columns=["ts", "side", "r", "bars"])
        days = (tdf.ts.iloc[-1] - tdf.ts.iloc[0]).days
        pos_r = tdf[tdf.r > 0].r.sum(); neg_r = -tdf[tdf.r < 0].r.sum()
        pf = pos_r / neg_r if neg_r > 0 else 0
        w = (tdf.r > 0).mean() * 100
        t_7d = tdf[tdf.ts >= df.ts.iloc[-1] - pd.Timedelta(days=7)]
        t_oos = tdf[tdf.ts >= pd.Timestamp("2024-01-01", tz="UTC")]
        pf_oos = t_oos[t_oos.r > 0].r.sum() / -t_oos[t_oos.r < 0].r.sum() if len(t_oos) else 0
        print(f"Sweep8+RSI (stop={stop_atr}, rr={rr}): N={len(tdf)} ({len(tdf)/days*7:.1f}/wk) | Win={w:.1f}% | PF={pf:.2f} | OOS PF={pf_oos:.2f} | 7D: {len(t_7d)} tr ({t_7d.r.sum():+.2f}R)")
