import pandas as pd
import numpy as np

# اختبار عمالقة التداول (Turtle 20 & SMC 4H Flow & Volatility Explosion)
df4h = pd.read_csv("research/btc_4h.csv", parse_dates=["ts"])
c, o, h, l, v = df4h.close.values, df4h.open.values, df4h.high.values, df4h.low.values, df4h.volume.values

tr = pd.concat([df4h.high - df4h.low, (df4h.high - df4h.close.shift()).abs(), (df4h.low - df4h.close.shift()).abs()], axis=1).max(axis=1)
atr = tr.ewm(alpha=1/14, adjust=False).mean().values

ema50 = df4h.close.ewm(span=50, adjust=False).mean().values
ema200 = df4h.close.ewm(span=200, adjust=False).mean().values

# Donchian 20 (Turtle Trading System) على 4H
hi20 = df4h.high.rolling(20).max().shift().values
lo20 = df4h.low.rolling(20).min().shift().values

long_t = (c > hi20) & (c > ema200)
short_t = (c < lo20) & (c < ema200)
sig_turtle = np.where(long_t, 1, np.where(short_t, -1, 0))

def sim_trend(sig, name, rr=3.0, stop_atr=2.0, trail_atr=2.0):
    trades = []
    n = len(df4h)
    i = 50
    while i < n - 2:
        s = sig[i]
        if s == 0: i += 1; continue
        entry = o[i+1]
        dist = stop_atr * atr[i]
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
            # وقف متحرك Chandelier Trailing
            ns = best - s * trail_atr * dist
            stop = max(stop, ns) if s > 0 else min(stop, ns)
            j += 1
        if res is None: res = s * (c[j-1] - entry) / dist
        trades.append((df4h.ts.iloc[i+1], s, res - 0.0008 * entry / dist, j - i))
        i = j
    tdf = pd.DataFrame(trades, columns=["ts", "side", "r", "bars"])
    t_oos = tdf[tdf.ts >= pd.Timestamp("2024-01-01", tz="UTC")]
    pos_r = tdf[tdf.r > 0].r.sum(); neg_r = -tdf[tdf.r < 0].r.sum()
    pf = pos_r / neg_r if neg_r > 0 else 99
    pos_oos = t_oos[t_oos.r > 0].r.sum(); neg_oos = -t_oos[t_oos.r < 0].r.sum()
    pf_oos = pos_oos / neg_oos if neg_oos > 0 else 99
    w = (tdf.r > 0).mean() * 100
    w_oos = (t_oos.r > 0).mean() * 100 if len(t_oos) else 0
    t_7d = tdf[tdf.ts >= df4h.ts.iloc[-1] - pd.Timedelta(days=7)]
    days = (tdf.ts.iloc[-1] - tdf.ts.iloc[0]).days
    print(f"{name:35s} | N:{len(tdf):4d} ({len(tdf)/days*7:3.1f}/wk) | Win:{w:4.1f}% | PF:{pf:.2f} | OOS Win:{w_oos:.1f}% | OOS PF:{pf_oos:.2f} | Tot R:{tdf.r.sum():+.1f}R | 7D: {len(t_7d)} ({t_7d.r.sum():+.2f}R)")

sim_trend(sig_turtle, "Turtle 20 4H (Trail 1.5)", trail_atr=1.5)
sim_trend(sig_turtle, "Turtle 20 4H (Trail 2.0)", trail_atr=2.0)
sim_trend(sig_turtle, "Turtle 20 4H (Trail 2.5)", trail_atr=2.5)
