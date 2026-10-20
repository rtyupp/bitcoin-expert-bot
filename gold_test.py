"""مقارنة الذهب (PAXG) بالبيتكوين بنفس استراتيجيات الاختراق — بيانات حقيقية."""
import ccxt
import numpy as np
import pandas as pd
import ta


def fetch(symbol, timeframe="1d"):
    ex = ccxt.binance()
    since = ex.parse8601("2018-01-01T00:00:00Z")
    now = ex.milliseconds()
    frames = []
    while since < now and len(frames) < 20:
        try:
            raw = ex.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
        except Exception as e:  # noqa: BLE001
            print(f"  خطأ جلب {symbol}: {e}")
            break
        if not raw:
            break
        frames.append(raw)
        since = raw[-1][0] + 1
    data = [c for f in frames for c in f]
    df = pd.DataFrame(data, columns=["ts", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates("ts").reset_index(drop=True)
    df["ts"] = pd.to_datetime(df["ts"], unit="ms")
    return df


def to_events(sig):
    s = pd.Series(sig)
    return np.where(s.diff().fillna(0) != 0, s, 0).astype(float)


def backtest(df):
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    atr = ta.volatility.AverageTrueRange(h, l, c, 14).average_true_range()
    bb = ta.volatility.BollingerBands(c, 20, 2)
    up, lo = bb.bollinger_hband(), bb.bollinger_lband()
    vol20 = v.rolling(20).mean()

    def simulate(sig, rr=2.0, stop_mult=2.0, max_hold=30):
        closes, highs, lows, atrs = c.values, h.values, l.values, atr.values
        trades = []
        for i in range(250, len(df) - 1):
            if sig[i] == 0:
                continue
            d = int(sig[i])
            entry = closes[i]
            sd = stop_mult * atrs[i]
            stop = entry - d * sd
            target = entry + d * rr * sd
            won = None
            for j in range(i + 1, min(i + 1 + max_hold, len(df))):
                if d == 1:
                    if lows[j] <= stop:
                        won = False
                        break
                    if highs[j] >= target:
                        won = True
                        break
                else:
                    if highs[j] >= stop:
                        won = False
                        break
                    if lows[j] <= target:
                        won = True
                        break
            if won is None:
                ex = closes[min(i + max_hold, len(df) - 1)]
                trades.append(d * (ex - entry) / sd)
            else:
                trades.append(rr if won else -1.0)
        return trades

    def rep(name, trades):
        if not trades:
            return f"    {name}: 0"
        w = sum(1 for t in trades if t > 0)
        gp = sum(t for t in trades if t > 0)
        gl = sum(-t for t in trades if t < 0)
        pf = gp / gl if gl > 0 else float("inf")
        return (f"    {name}: {len(trades)} صفقة | فوز {w/len(trades)*100:.0f}% | "
                f"متوسط {np.mean(trades):+.2f}R | PF {pf:.2f}")

    bb_vol = to_events(np.where((c > up) & (v > 1.5 * vol20), 1, np.where((c < lo) & (v > 1.5 * vol20), -1, 0)))
    bb_plain = to_events(np.where(c > up, 1, np.where(c < lo, -1, 0)))
    print("  " + rep("كسر بولينجر + حجم", simulate(bb_vol)))
    print("  " + rep("كسر بولينجر (زخم)", simulate(bb_plain)))


for sym, label in [("PAXG/USDT", "الذهب PAXG"), ("BTC/USDT", "البيتكوين")]:
    print(f"═══ {label} ({sym}) ═══")
    df = fetch(sym)
    df = df[df["close"] > 0].reset_index(drop=True)
    if len(df) < 300:
        print("  بيانات غير كافية\n")
        continue
    print(f"  {len(df)} يوم ({df['ts'].iloc[0].date()} → {df['ts'].iloc[-1].date()})")
    # التقلب اليومي النسبي
    ret = df["close"].pct_change().dropna()
    print(f"  التقلب اليومي: متوسط {ret.abs().mean()*100:.2f}% | انحراف {ret.std()*100:.2f}%")
    # العائد الكلي
    tot = (df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100
    yrs = len(df) / 365
    print(f"  العائد الكلي: {tot:+.0f}% (≈ {tot/yrs:+.1f}%/سنة)")
    backtest(df)
    print()
