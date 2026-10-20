"""اختبار استراتيجيات متداولين متقدمة + إدارة مخاطر ATR (وقف/هدف) — إشارات حدثية."""
import numpy as np
import pandas as pd
import ta

import backtest
import analysis


def add_indicators(df):
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    d = df.copy()
    d["ema20"] = ta.trend.EMAIndicator(c, 20).ema_indicator()
    d["ema50"] = ta.trend.EMAIndicator(c, 50).ema_indicator()
    d["ema200"] = ta.trend.EMAIndicator(c, 200).ema_indicator()
    d["rsi"] = ta.momentum.RSIIndicator(c, 14).rsi()
    d["atr"] = ta.volatility.AverageTrueRange(h, l, c, 14).average_true_range()
    d["adx"] = ta.trend.ADXIndicator(h, l, c, 14).adx()
    macd = ta.trend.MACD(c)
    d["macd"] = macd.macd()
    d["macd_signal"] = macd.macd_signal()
    bb = ta.volatility.BollingerBands(c, 20, 2)
    d["bb_up"] = bb.bollinger_hband()
    d["bb_lo"] = bb.bollinger_lband()
    d["vol_avg20"] = v.rolling(20).mean()
    d["st"] = supertrend(h, l, c, 10, 3.0)
    d["st2"] = supertrend(h, l, c, 10, 2.0)
    return d


def supertrend(high, low, close, period=10, mult=3.0):
    atr = ta.volatility.AverageTrueRange(high, low, close, period).average_true_range()
    hl2 = (high + low) / 2
    fu = hl2 + mult * atr
    fl = hl2 - mult * atr
    n = len(close)
    trend = np.ones(n)
    for i in range(1, n):
        if trend[i - 1] == 1:
            trend[i] = -1 if close.iloc[i] < fl.iloc[i - 1] else 1
        else:
            trend[i] = 1 if close.iloc[i] > fu.iloc[i - 1] else -1
    return trend


def to_events(sig):
    """يحوّل حالة مستمرة إلى إشارات دخول عند التغيّر فقط."""
    s = pd.Series(sig)
    change = s.diff().fillna(0) != 0
    return np.where(change, s, 0).astype(float)


def strat_score_state(d):
    sig = np.zeros(len(d))
    for i in range(250, len(d)):
        s = analysis.score_from_df(d.iloc[: i + 1], change_24h=None)
        sig[i] = 1 if s >= 4 else (-1 if s <= -4 else 0)
    return to_events(sig)


def strat_trend_adx(d):
    long = (d["close"] > d["ema200"]) & (d["ema20"] > d["ema50"]) & (d["adx"] > 20)
    short = (d["close"] < d["ema200"]) & (d["ema20"] < d["ema50"]) & (d["adx"] > 20)
    return to_events(np.where(long, 1, np.where(short, -1, 0)))


def strat_bb_break(d):
    return to_events(np.where(d["close"] > d["bb_up"], 1, np.where(d["close"] < d["bb_lo"], -1, 0)))


def strat_bb_trend(d):
    """كسر بولينجر في اتجاه الترند (EMA200)."""
    long = (d["close"] > d["bb_up"]) & (d["close"] > d["ema200"])
    short = (d["close"] < d["bb_lo"]) & (d["close"] < d["ema200"])
    return to_events(np.where(long, 1, np.where(short, -1, 0)))


def strat_bb_vol(d):
    """كسر بولينجر مع حجم مؤكد (×1.5)."""
    long = (d["close"] > d["bb_up"]) & (d["volume"] > 1.5 * d["vol_avg20"])
    short = (d["close"] < d["bb_lo"]) & (d["volume"] > 1.5 * d["vol_avg20"])
    return to_events(np.where(long, 1, np.where(short, -1, 0)))


def strat_ema_cross(d):
    c20 = (d["ema20"] > d["ema50"]).astype(float)
    return (c20.diff() == 1).astype(float) - (c20.diff() == -1).astype(float)


def strat_supertrend(d):
    return to_events(np.where(d["st"] == 1, 1, -1))


def strat_supertrend2(d):
    return to_events(np.where(d["st2"] == 1, 1, -1))


def strat_score_adx(d):
    base = np.zeros(len(d))
    for i in range(250, len(d)):
        s = analysis.score_from_df(d.iloc[: i + 1], change_24h=None)
        base[i] = 1 if s >= 4 else (-1 if s <= -4 else 0)
    long = (base == 1) & (d["close"] > d["ema200"]) & (d["adx"] > 20)
    short = (base == -1) & (d["close"] < d["ema200"]) & (d["adx"] > 20)
    return to_events(np.where(long, 1, np.where(short, -1, 0)))


STRATS = {
    "النقاط الحالية (≥4)": strat_score_state,
    "اتجاه + ADX": strat_trend_adx,
    "كسر بولينجر (زخم)": strat_bb_break,
    "كسر بولينجر + اتجاه": strat_bb_trend,
    "كسر بولينجر + حجم": strat_bb_vol,
    "تقاطع EMA20/50": strat_ema_cross,
    "Supertrend (×3)": strat_supertrend,
    "Supertrend (×2)": strat_supertrend2,
    "نقاط + ADX + اتجاه": strat_score_adx,
}


def simulate(df, sig, stop_mult=2.0, rr=2.0, max_hold=30):
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    atrs = df["atr"].values
    trades = []
    for i in range(250, len(df) - 1):
        if sig[i] == 0:
            continue
        direction = int(sig[i])
        entry = closes[i]
        stop_dist = stop_mult * atrs[i]
        stop = entry - direction * stop_dist
        target = entry + direction * rr * stop_dist
        won = None
        for j in range(i + 1, min(i + 1 + max_hold, len(df))):
            if direction == 1:
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
            exit_px = closes[min(i + max_hold, len(df) - 1)]
            r = direction * (exit_px - entry) / stop_dist
            trades.append(r)
        else:
            trades.append(rr if won else -1.0)
    return trades


def report(name, trades):
    if not trades:
        return f"  {name}: 0 صفقة"
    wins = sum(1 for t in trades if t > 0)
    wr = wins / len(trades) * 100
    avg = np.mean(trades)
    gross_p = sum(t for t in trades if t > 0)
    gross_l = sum(-t for t in trades if t < 0)
    pf = gross_p / gross_l if gross_l > 0 else float("inf")
    net = sum(trades)
    return (
        f"  {name}: {len(trades)} صفقة | فوز {wr:.0f}% | متوسط {avg:+.2f}R | "
        f"صافي {net:+.1f}R | ProfitFactor {pf:.2f}"
    )


def main():
    print("جاري جلب البيانات وحساب المؤشرات...")
    df = backtest.fetch_history()
    df = df[df["close"] > 0].reset_index(drop=True)
    d = add_indicators(df)
    print(f"{len(df)} يوم ({df['ts'].iloc[0].date()} → {df['ts'].iloc[-1].date()})")
    print()

    for rr in (2.0,):
        print(f"═══ وقف 2×ATR | هدف {rr:.0f}:1 | أقصى احتفاظ 30 يوم ═══")
        for name, fn in STRATS.items():
            trades = simulate(d, fn(d), stop_mult=2.0, rr=rr, max_hold=30)
            print(report(name, trades))
        print()

    print("═══ تفصيل الأفضل عند أهداف مختلفة ═══")
    for name in ["كسر بولينجر + اتجاه", "كسر بولينجر (زخم)", "اتجاه + ADX", "النقاط الحالية (≥4)"]:
        sig = STRATS[name](d)
        for rr in (1.5, 2.0, 3.0):
            trades = simulate(d, sig, stop_mult=2.0, rr=rr, max_hold=30)
            print(report(f"{name} | هدف {rr:.1f}:1", trades))


if __name__ == "__main__":
    main()
