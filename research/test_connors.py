import pandas as pd
import numpy as np

# اختبار Larry Connors RSI(2) الأصلية + Trend Filter (وهي أشهر استراتيجية High Win Rate في وول ستريت بنسبة فوز 65-75%)
df1h = pd.read_csv("research/btc_1h.csv", parse_dates=["ts"])
df4h = pd.read_csv("research/btc_4h.csv", parse_dates=["ts"])
df1d = pd.read_csv("research/btc_1d.csv", parse_dates=["ts"])

# مؤشر Connors على 4H و 1D
for tf, df in [("4H", df4h), ("1D", df1d)]:
    c, o, h, l = df.close.values, df.open.values, df.high.values, df.low.values
    tr = pd.concat([df.high - df.low, (df.high - df.close.shift()).abs(), (df.low - df.close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/14, adjust=False).mean().values
    
    # RSI(2)
    diff = df.close.diff()
    up = diff.clip(lower=0).ewm(alpha=1/2, adjust=False).mean()
    dn = (-diff.clip(upper=0)).ewm(alpha=1/2, adjust=False).mean()
    rsi2 = (100 - 100 / (1 + up / dn.replace(0, np.nan))).values
    
    ema200 = df.close.ewm(span=200, adjust=False).mean().values
    ema50 = df.close.ewm(span=50, adjust=False).mean().values
    
    # خروج عند إغلاق الشمعة فوق EMA5 (طريقة كونورز الكلاسيكية التي تعطي نسبة فوز 70%+)
    ema5 = df.close.ewm(span=5, adjust=False).mean().values
    
    # شراء: السعر فوق EMA200 + RSI(2) < 5
    sig_buy = (c > ema200) & (rsi2 < 5)
    
    trades = []
    n = len(df)
    i = 200
    while i < n - 2:
        if not sig_buy[i]: i += 1; continue
        entry = o[i+1]
        dist = 1.5 * atr[i]
        stop = entry - dist
        j = i + 1
        res = None
        while j < min(n, i + 1 + 20):
            # وقف الخسارة
            if l[j] <= stop:
                res = (stop - entry) / dist
                break
            # خروج كونورز: أول شمعة تغلق فوق EMA5
            if c[j] > ema5[j]:
                res = (c[j] - entry) / dist
                break
            j += 1
        if res is None:
            res = (c[j-1] - entry) / dist
        trades.append((df.ts.iloc[i+1], 1, res - 0.0008 * entry / dist, j - i))
        i = j
    tdf = pd.DataFrame(trades, columns=["ts", "side", "r", "bars"])
    pos_r = tdf[tdf.r > 0].r.sum(); neg_r = -tdf[tdf.r < 0].r.sum()
    pf = pos_r / neg_r if neg_r > 0 else 99
    w = (tdf.r > 0).mean() * 100
    t_oos = tdf[tdf.ts >= pd.Timestamp("2024-01-01", tz="UTC")]
    pos_oos = t_oos[t_oos.r > 0].r.sum(); neg_oos = -t_oos[t_oos.r < 0].r.sum()
    pf_oos = pos_oos / neg_oos if neg_oos > 0 else 99
    w_oos = (t_oos.r > 0).mean() * 100 if len(t_oos) else 0
    t_7d = tdf[tdf.ts >= df.ts.iloc[-1] - pd.Timedelta(days=7)]
    days = (tdf.ts.iloc[-1] - tdf.ts.iloc[0]).days
    print(f"Connors Classic {tf}: N={len(tdf)} ({len(tdf)/days*7:.1f}/wk) | Win={w:.1f}% | PF={pf:.2f} | OOS Win={w_oos:.1f}% | OOS PF={pf_oos:.2f} | Tot R={tdf.r.sum():+.1f}R | 7D={len(t_7d)} ({t_7d.r.sum():+.2f}R)")
