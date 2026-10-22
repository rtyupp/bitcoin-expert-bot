import pandas as pd
import numpy as np

# اختبار وتحسين ORB (London & New York Breakout) بدقة
df15 = pd.read_csv("research/btc_15m.csv", parse_dates=["ts"])
tr = pd.concat([df15.high - df15.low, (df15.high - df15.close.shift()).abs(), (df15.low - df15.close.shift()).abs()], axis=1).max(axis=1)
df15["atr"] = tr.ewm(alpha=1/14, adjust=False).mean()
df15["hour"] = df15.ts.dt.hour
df15["min"] = df15.ts.dt.minute
df15["date"] = df15.ts.dt.date

# شمعة 07:00 UTC (افتتاح لندن)
london_open = df15[(df15.hour == 7) & (df15.min == 0)].copy()
london_open = london_open[["date", "high", "low"]].rename(columns={"high": "lon_h", "low": "lon_l"})
d = pd.merge(df15, london_open, on="date", how="left")

# نيويورك 13:30 UTC
ny_open = d[(d.hour == 13) & (d.min == 30)].copy()
ny_open = ny_open[["date", "high", "low"]].rename(columns={"high": "ny_h", "low": "ny_l"})
d = pd.merge(d, ny_open, on="date", how="left")

d["ema50"] = d.close.ewm(span=50, adjust=False).mean()
d["ema200"] = d.close.ewm(span=200, adjust=False).mean()

# كسر لندن بين 07:15 و 10:00
lon_long = (d.hour >= 7) & (d.hour <= 10) & (d.close > d.lon_h) & (d.close.shift(1) <= d.lon_h) & (d.close > d.ema50)
lon_short = (d.hour >= 7) & (d.hour <= 10) & (d.close < d.lon_l) & (d.close.shift(1) >= d.lon_l) & (d.close < d.ema50)

# كسر نيويورك بين 13:45 و 16:00
ny_long = (d.hour >= 13) & (d.hour <= 16) & (d.close > d.ny_h) & (d.close.shift(1) <= d.ny_h) & (d.close > d.ema50)
ny_short = (d.hour >= 13) & (d.hour <= 16) & (d.close < d.ny_l) & (d.close.shift(1) >= d.ny_l) & (d.close < d.ema50)

sig_lon = np.where(lon_long, 1, np.where(lon_short, -1, 0))
sig_ny = np.where(ny_long, 1, np.where(ny_short, -1, 0))

def run_orb(sig, name, rr=1.8, stop_mult=1.5):
    o, h, l, c, atr = d.open.values, d.high.values, d.low.values, d.close.values, d.atr.values
    trades = []
    n = len(d)
    i = 100
    while i < n - 2:
        s = sig[i]
        if s == 0 or not np.isfinite(atr[i]): i += 1; continue
        entry = o[i+1]
        dist = stop_mult * atr[i]
        stop = entry - s * dist
        tp = entry + s * rr * dist
        best = entry
        j = i + 1
        res = None
        while j < min(n, i + 1 + 24):
            if s > 0:
                if l[j] <= stop: res = (stop - entry) / dist; break
                if h[j] >= tp: res = rr; break
                best = max(best, h[j])
            else:
                if h[j] >= stop: res = (entry - stop) / dist; break
                if l[j] <= tp: res = rr; break
                best = min(best, l[j])
            # تأمين عند 1R
            if s * (best - entry) >= 1.0 * dist:
                stop = max(stop, entry) if s > 0 else min(stop, entry)
            j += 1
        if res is None: res = s * (c[j-1] - entry) / dist
        trades.append((d.ts.iloc[i+1], s, res - 0.0008 * entry / dist, j - i))
        i = j
    tdf = pd.DataFrame(trades, columns=["ts", "side", "r", "bars"])
    t_oos = tdf[tdf.ts >= pd.Timestamp("2024-01-01", tz="UTC")]
    t_7d = tdf[tdf.ts >= d.ts.iloc[-1] - pd.Timedelta(days=7)]
    pos_r = tdf[tdf.r > 0].r.sum(); neg_r = -tdf[tdf.r < 0].r.sum()
    pf = pos_r / neg_r if neg_r > 0 else 0
    pos_oos = t_oos[t_oos.r > 0].r.sum(); neg_oos = -t_oos[t_oos.r < 0].r.sum()
    pf_oos = pos_oos / neg_oos if neg_oos > 0 else 0
    days = (tdf.ts.iloc[-1] - tdf.ts.iloc[0]).days
    print(f"{name:25s} | N: {len(tdf):4d} ({len(tdf)/days*7:.1f}/wk) | Win: {(tdf.r>0).mean()*100:.1f}% | PF: {pf:.2f} | Exp: {tdf.r.mean():+.3f}R | OOS PF: {pf_oos:.2f} | 7D: {len(t_7d)} ({t_7d.r.sum():+.2f}R)")

run_orb(sig_lon, "London ORB (15m, rr=1.8)", rr=1.8)
run_orb(sig_lon, "London ORB (15m, rr=2.5)", rr=2.5)
run_orb(sig_ny, "NY ORB (15m, rr=1.8)", rr=1.8)
run_orb(sig_ny, "NY ORB (15m, rr=2.5)", rr=2.5)
