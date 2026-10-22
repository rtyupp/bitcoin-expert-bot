import pandas as pd
import numpy as np

# اختبار سريع لاستراتيجيات intraday على فريم 1h وفريم 15m
# الهدف: 1 إلى 2 صفقة يومياً مع أداء رابح وتأكيد على آخر 7 أيام
COST = 0.0008  # سبريد + انزلاق 0.08%

df = pd.read_csv("research/btc_1h.csv", parse_dates=["ts"])
c, o, h, l = df.close.values, df.open.values, df.high.values, df.low.values

# ATR
tr = pd.concat([df.high - df.low, (df.high - df.close.shift()).abs(), (df.low - df.close.shift()).abs()], axis=1).max(axis=1)
atr = tr.ewm(alpha=1/14, adjust=False).mean().values

ema20 = df.close.ewm(span=20, adjust=False).mean().values
ema50 = df.close.ewm(span=50, adjust=False).mean().values
ema200 = df.close.ewm(span=200, adjust=False).mean().values

# RSI(14) و RSI(7)
diff = df.close.diff()
up = diff.clip(lower=0).ewm(alpha=1/7, adjust=False).mean()
dn = (-diff.clip(upper=0)).ewm(alpha=1/7, adjust=False).mean()
rsi7 = (100 - 100 / (1 + up / dn.replace(0, np.nan))).values

# كنس سيولة 12 شمعة (12 ساعة)
lo_12 = df.low.rolling(12).min().shift().values
hi_12 = df.high.rolling(12).max().shift().values

# اختراق Donchian 20 ساعة
lo_20 = df.low.rolling(20).min().shift().values
hi_20 = df.high.rolling(20).max().shift().values

# بولينجر باند
std20 = df.close.rolling(20).std().values
sma20 = df.close.rolling(20).mean().values
bb_up = sma20 + 2 * std20
bb_lo = sma20 - 2 * std20

print("Data loaded:", len(df))

# اختبار استراتيجية يومية مرنة:
# 1) كنس سيولة محلي (SMC Sweep 1H): كسر قاع/قمة 12 شمعة وارتداد مع اتجاه EMA50
sig_sweep = np.zeros(len(df))
long_c = (l < lo_12) & (c > lo_12) & (c > o) & (c > ema50)
short_c = (h > hi_12) & (c < hi_12) & (c < o) & (c < ema50)
sig_sweep[long_c] = 1
sig_sweep[short_c] = -1

# 2) ارتداد بولينجر + RSI في الاتجاه (Pullback Flow)
sig_flow = np.zeros(len(df))
long_f = (c > ema200) & (l <= bb_lo) & (c > o) & (rsi7 < 35)
short_f = (c < ema200) & (h >= bb_up) & (c < o) & (rsi7 > 65)
sig_flow[long_f] = 1
sig_flow[short_f] = -1

# دمج الإشارات
def run_bt(sig, stop_mult=1.5, rr=1.8, max_hold=36):
    trades = []
    n = len(df)
    i = 200
    while i < n - 2:
        s = sig[i]
        if s == 0:
            i += 1
            continue
        entry = o[i+1]
        d = stop_mult * atr[i]
        stop = entry - s * d
        tp = entry + s * rr * d
        j = i + 1
        res = None
        while j < min(n, i + 1 + max_hold):
            if s > 0:
                if l[j] <= stop:
                    res = (stop - entry) / d
                    break
                if h[j] >= tp:
                    res = rr
                    break
            else:
                if h[j] >= stop:
                    res = (entry - stop) / d
                    break
                if l[j] <= tp:
                    res = rr
                    break
            j += 1
        if res is None:
            # خروج بانتهاء المدة
            res = s * (c[j-1] - entry) / d
        trades.append((df.ts.iloc[i+1], s, res - COST * entry / d, j - i))
        i = j
    tdf = pd.DataFrame(trades, columns=["ts", "side", "r", "bars"])
    return tdf

t_sw = run_bt(sig_sweep, stop_mult=1.5, rr=1.8)
t_fl = run_bt(sig_flow, stop_mult=1.5, rr=1.8)

for name, t in [("1H SMC Sweep", t_sw), ("1H BB/RSI Flow", t_fl)]:
    t_oos = t[t.ts >= pd.Timestamp("2024-01-01", tz="UTC")]
    t_7d = t[t.ts >= df.ts.iloc[-1] - pd.Timedelta(days=7)]
    days_total = (t.ts.iloc[-1] - t.ts.iloc[0]).days
    print(f"\n=== {name} ===")
    print(f"Total Trades: {len(t)} ({len(t)/days_total:.2f}/day) | Win: {(t.r>0).mean()*100:.1f}% | PF: {t[t.r>0].r.sum()/(-t[t.r<0].r.sum()):.2f} | Exp: {t.r.mean():+.3f}R | Total: {t.r.sum():+.1f}R")
    print(f"OOS 2024+: Trades: {len(t_oos)} | Win: {(t_oos.r>0).mean()*100:.1f}% | PF: {t_oos[t_oos.r>0].r.sum()/(-t_oos[t_oos.r<0].r.sum()):.2f} | Total: {t_oos.r.sum():+.1f}R")
    print(f"Last 7 Days: {len(t_7d)} trades | R: {t_7d.r.sum():+.2f}R")
    if len(t_7d) > 0:
        for _, r in t_7d.iterrows():
            print(f"   {r.ts} | {'BUY' if r.side>0 else 'SELL'} | {r.r:+.2f}R | {r.bars}h")
