"""اختبار تاريخي (backtest) لنظام توصيات البوت.

يجلب تاريخ بيتكوين اليومي، يحسب نقاط score_from_df على نافذة متحركة،
ويقيس أداء إشارات الشراء/البيع عند عتبات مختلفة مقابل الشراء والاحتفاظ.
"""
import sys

import ccxt
import pandas as pd

import analysis

SYMBOL = "BTC/USDT"


def fetch_history(timeframe="1d", start="2017-01-01"):
    ex = ccxt.binance()
    since = ex.parse8601(f"{start}T00:00:00Z")
    now = ex.milliseconds()
    frames = []
    while since < now:
        try:
            raw = ex.fetch_ohlcv(SYMBOL, timeframe, since=since, limit=1000)
        except Exception as e:  # noqa: BLE001
            print(f"تعذّر الجلب: {e}")
            break
        if not raw:
            break
        frames.append(raw)
        since = raw[-1][0] + 1
        if len(frames) > 20:
            break
    data = [c for f in frames for c in f]
    df = pd.DataFrame(data, columns=["ts", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates(subset="ts").reset_index(drop=True)
    df["ts"] = pd.to_datetime(df["ts"], unit="ms")
    return df


def score_series(df, min_window=250):
    """يحسب النقاط لكل يوم (نافذة متحركة). يرجع قائمة (ts, score, price)."""
    closes = df["close"].values
    rows = []
    for i in range(min_window, len(df)):
        win = df.iloc[: i + 1]
        chg = (closes[i] - closes[i - 1]) / closes[i - 1] * 100
        s = analysis.score_from_df(win, change_24h=chg)
        rows.append((df["ts"].iloc[i], s, closes[i]))
    return rows


def forward_returns(rows, horizons=(7, 14, 30)):
    """لكل إشارة (نقاط فوق/تحت العتبة) يحسب العائد المستقبلي."""
    n = len(rows)
    prices = [r[2] for r in rows]
    out = {}
    for h in horizons:
        out[h] = []
        for i in range(n - h):
            ret = (prices[i + h] - prices[i]) / prices[i] * 100
            out[h].append((rows[i][0], rows[i][1], ret))
    return out


def summarize(signals, horizon, label):
    if not signals:
        return f"  {label}: 0 إشارة"
    rets = [s[2] for s in signals]
    wins = sum(1 for r in rets if r > 0)
    avg = sum(rets) / len(rets)
    med = sorted(rets)[len(rets) // 2]
    return (
        f"  {label}: {len(signals)} إشارة | فوز {wins}/{len(signals)} "
        f"({wins/len(signals)*100:.0f}%) | متوسط {avg:+.2f}% | وسيط {med:+.2f}% | "
        f"أفضل {max(rets):+.2f}% | أسوأ {min(rets):+.2f}%"
    )


def main():
    print("جاري جلب تاريخ البيتكوين اليومي...")
    df = fetch_history()
    print(f"تم الجلب: {len(df)} يوم ({df['ts'].iloc[0].date()} → {df['ts'].iloc[-1].date()})\n")

    rows = score_series(df)
    horizon_rows = forward_returns(rows)
    horizons = (7, 14, 30)

    # توزيع النقاط
    scores = [r[1] for r in rows]
    print("📊 توزيع النقاط اليومية:")
    for lo, hi, name in [(-9.5, -5, "بيع قوي"), (-5, -2, "بيع"), (-2, 2, "محايد"),
                          (2, 5, "شراء"), (5, 9.5, "شراء قوي")]:
        cnt = sum(1 for s in scores if lo <= s < hi or (hi == 9.5 and s >= 5))
        print(f"  {name}: {cnt} يوم ({cnt/len(scores)*100:.0f}%)")
    print()

    # أداء الإشارات عند عتبات مختلفة
    for threshold in (4.0, 5.0, 6.0):
        print(f"🎯 العتبة ±{threshold:.0f}:")
        for h in horizons:
            buys = [s for s in horizon_rows[h] if s[1] >= threshold]
            sells = [s for s in horizon_rows[h] if s[1] <= -threshold]
            print(f" أفق {h} يوم:")
            print(summarize(buys, h, "شراء (طويل)"))
            print(summarize(sells, h, "بيع (شورت)"))
        print()

    # المقارنة: شراء واحتفاظ
    closes = df["close"].values
    total_ret = (closes[-1] - closes[0]) / closes[0] * 100
    years = len(df) / 365.0
    print(f"📈 الشراء والاحتفاظ (Buy & Hold):")
    print(f"  من {df['ts'].iloc[0].date()} إلى {df['ts'].iloc[-1].date()}: {total_ret:+.1f}% "
          f"(≈ {total_ret/years:+.1f}%/سنة)")


if __name__ == "__main__":
    main()
