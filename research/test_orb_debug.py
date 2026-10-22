import pandas as pd
import numpy as np

# اختبار وتحسين ORB مع فحص وجود صفقات
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

d["ema50"] = d.close.ewm(span=50, adjust=False).mean()

# كسر لندن بين 07:15 و 10:00:
# شمعة تغلق فوق أعلى سعر لشمعة 07:00
lon_long = (d.hour >= 7) & (d.hour <= 10) & (d.close > d.lon_h) & (d.close.shift(1) <= d.lon_h) & (d.close > d.ema50)
lon_short = (d.hour >= 7) & (d.hour <= 10) & (d.close < d.lon_l) & (d.close.shift(1) >= d.lon_l) & (d.close < d.ema50)

print(f"Long signals: {lon_long.sum()} | Short signals: {lon_short.sum()}")
