import pandas as pd
import numpy as np

# اختبار: ترند 4H + دخول 1H عند تشبع بولينجر/RSI في اتجاه الترند (Trend Continuation Hunter)
df1h = pd.read_csv("research/btc_1h.csv", parse_dates=["ts"])
df4h = pd.read_csv("research/btc_4h.csv", parse_dates=["ts"])

# اتجاه 4H: EMA20 و EMA50
df4h["ema20"] = df4h.close.ewm(span=20, adjust=False).mean()
df4h["ema50"] = df4h.close.ewm(span=50, adjust=False).mean()
df4h["trend_up"] = df4h.close > df4h.ema50
df4h["trend_down"] = df4h.close < df4h.ema50

df4h_s = df4h[["ts", "trend_up", "trend_down"]].copy()
df4h_s["ts"] = df4h_s["ts"] + pd.Timedelta(hours=4)

m = pd.merge_asof(df1h.sort_values("ts"), df4h_s.sort_values("ts"), on="ts", direction="backward")
trend_up = m["trend_up"].fillna(False).values
trend_down = m["trend_down"].fillna(False).values

c, o, h, l, v = df1h.close.values, df1h.open.values, df1h.high.values, df1h.low.values, df1h.volume.values

tr = pd.concat([df1h.high - df1h.low, (df1h.high - df1h.close.shift()).abs(), (df1h.low - df1h.close.shift()).abs()], axis=1).max(axis=1)
atr = tr.ewm(alpha=1/14, adjust=False).mean().values

# RSI(14) على 1h
diff = df1h.close.diff()
up = diff.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
dn = (-diff.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
rsi = (100 - 100 / (1 + up / dn.replace(0, np.nan))).values

# بولينجر 1H
sma20 = df1h.close.rolling(20).mean().values
std20 = df1h.close.rolling(20).std().values
bb_l = sma20 - 2 * std20
bb_u = sma20 + 2 * std20

for rsi_thresh in (35, 40):
    for rr in (1.5, 2.0):
        # شراء: ترند 4H صاعد + شمعة 1H تلمس بولينجر السفلي أو RSI منخفض + إغلاق صاعد
        long_s = trend_up & ((l <= bb_l) | (rsi < rsi_thresh)) & (c > o)
        short_s = trend_down & ((h >= bb_u) | (rsi > 100 - rsi_thresh)) & (c < o)
        sig = np.where(long_s, 1, np.where(short_s, -1, 0))
        
        trades = []
        n = len(df1h)
        i = 100
        while i < n - 2:
            s = sig[i]
            if s == 0: i += 1; continue
            entry = o[i+1]
            d = 1.5 * atr[i]
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
            trades.append((df1h.ts.iloc[i+1], s, res - 0.0008 * entry / d, j - i))
            i = j
        tdf = pd.DataFrame(trades, columns=["ts", "side", "r", "bars"])
        days = (tdf.ts.iloc[-1] - tdf.ts.iloc[0]).days
        pos_r = tdf[tdf.r > 0].r.sum(); neg_r = -tdf[tdf.r < 0].r.sum()
        pf = pos_r / neg_r if neg_r > 0 else 0
        w = (tdf.r > 0).mean() * 100
        t_7d = tdf[tdf.ts >= df1h.ts.iloc[-1] - pd.Timedelta(days=7)]
        t_oos = tdf[tdf.ts >= pd.Timestamp("2024-01-01", tz="UTC")]
        pf_oos = t_oos[t_oos.r > 0].r.sum() / -t_oos[t_oos.r < 0].r.sum() if len(t_oos) else 0
        print(f"MTF Hunter (rsi<{rsi_thresh}, rr={rr}): N={len(tdf)} ({len(tdf)/days*7:.1f}/wk) | Win={w:.1f}% | PF={pf:.2f} | OOS PF={pf_oos:.2f} | 7D: {len(t_7d)} tr ({t_7d.r.sum():+.2f}R)")
