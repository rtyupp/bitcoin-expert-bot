"""تحليل الشارت وتحديد نقاط الصيد — الرسم عبر chartimg (Pillow، خفيف)."""
import pandas as pd
import numpy as np

import ta

import chartimg


_EXCHANGES = ("binance", "okx", "bybit", "kraken", "coinbase")


def fetch_4h(symbol: str, days: int = 30):
    """جلب بيانات 4h مع تبديل المنصات تلقائياً عند الحجب + مهلة زمنية."""
    import ccxt  # استيراد مؤجّل — ccxt ثقيل (~50MB) ولا نحتاجه إلا عند طلب شارت

    limit = min(days * 6, 300)
    errors = []
    for eid in _EXCHANGES:
        try:
            ex = getattr(ccxt, eid)({"enableRateLimit": True, "timeout": 15000})
            raw = ex.fetch_ohlcv(symbol, "4h", limit=limit)
            if not raw:
                raise ValueError("لا بيانات")
            df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
            df["ts"] = pd.to_datetime(df["ts"], unit="ms")
            return df
        except Exception as err:  # noqa: BLE001
            errors.append(f"{eid}:{type(err).__name__}")
    raise RuntimeError("تعذّر جلب البيانات: " + "; ".join(errors))


def analyze_chart(df: pd.DataFrame) -> dict:
    """تحليل الرسم البياني وإرجاع نقاط الصيد."""
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    atr = ta.volatility.AverageTrueRange(h, l, c, 14).average_true_range()
    bb = ta.volatility.BollingerBands(c, 20, 2)
    up, mid, lo = bb.bollinger_hband(), bb.bollinger_mavg(), bb.bollinger_lband()
    vol20 = v.rolling(20).mean()

    # الإشارة: كسر أعلى/أدنى بولينجر + حجم
    breakout_buy = (c > up) & (v > 1.5 * vol20)
    breakout_short = (c < lo) & (v > 1.5 * vol20)

    buy_idx = np.where(breakout_buy.values)[0]
    sell_idx = np.where(breakout_short.values)[0]
    buy_last = int(buy_idx[-1]) if len(buy_idx) else -1
    sell_last = int(sell_idx[-1]) if len(sell_idx) else -1
    direction = None
    idx = -1
    if buy_last > sell_last:
        direction, idx = "buy", buy_last
    elif sell_last > buy_last:
        direction, idx = "sell", sell_last

    events = {
        "current_price": float(c.iloc[-1]),
        "current_ts": df["ts"].iloc[-1],
        "first_entry": None,
        "second_entry": None,
        "stop_loss": None,
        "tp1": None,
        "tp2": None,
        "direction": direction,
        "signal_age_hours": None,
    }

    if idx < 0 or idx >= len(df) - 1:
        return events

    d = 1 if direction == "buy" else -1
    entry = float(c.iloc[idx])
    sd = float(atr.iloc[idx]) * 2
    events["first_entry"] = {
        "idx": int(idx),
        "price": entry,
        "ts": df["ts"].iloc[idx],
        "type": "breakout",
    }
    events["stop_loss"] = entry - d * sd
    events["tp1"] = entry + d * sd          # 1:1
    events["tp2"] = entry + d * 2 * sd      # 1:2
    events["signal_age_hours"] = int(
        (df["ts"].iloc[-1] - df["ts"].iloc[idx]).total_seconds() / 3600
    )

    # الصيد الثاني: رجعة للمتوسط (MA20) بعد الكسر
    for j in range(idx + 1, min(idx + 12, len(df))):
        if direction == "buy" and c.iloc[j] <= mid.iloc[j]:
            events["second_entry"] = {
                "idx": int(j),
                "price": float(c.iloc[j]),
                "ts": df["ts"].iloc[j],
                "type": "pullback",
            }
            break
        if direction == "sell" and c.iloc[j] >= mid.iloc[j]:
            events["second_entry"] = {
                "idx": int(j),
                "price": float(c.iloc[j]),
                "ts": df["ts"].iloc[j],
                "type": "pullback",
            }
            break

    return events


def plot_chart(df: pd.DataFrame, analysis: dict, symbol: str) -> bytes:
    """رسم الشارت عبر chartimg (Pillow) — ذاكرة منخفضة."""
    return chartimg.render(df, analysis, symbol)


def short_message(analysis: dict, symbol: str) -> str:
    """رسالة موجزة وواضحة بصيغة HTML (متوافقة مع ParseMode.HTML)."""
    if not analysis["first_entry"]:
        return (
            f"📊 <b>{symbol}</b>\n\n"
            "لا توجد إشارة صيد حالياً.\n"
            "انتظر كسر بولينجر مع حجم >= 1.5x."
        )

    d = analysis["direction"]
    fe = analysis["first_entry"]
    se = analysis["second_entry"]
    age = analysis["signal_age_hours"]

    head = f"{'🟢' if d == 'buy' else '🔴'} <b>{symbol} — إشارة {'شراء' if d == 'buy' else 'بيع'}</b>"
    lines = [head, ""]
    lines.append(f"📍 <b>أول صيد:</b> <code>{fe['price']:,.0f}</code> ({fe['type']})")
    if se:
        lines.append(f"📍 <b>ثاني صيد:</b> <code>{se['price']:,.0f}</code> ({se['type']})")
    lines.append(f"🛑 <b>وقف:</b> <code>{analysis['stop_loss']:,.0f}</code>")
    lines.append(f"🎯 <b>هدف 1:</b> <code>{analysis['tp1']:,.0f}</code>")
    if age is not None and age >= 6:
        lines.append(f"⏳ عمر الإشارة: {age} ساعة")
    lines.append("")
    lines.append(f"💰 الحالي: <code>{analysis['current_price']:,.0f}</code>")
    lines.append("⚠️ <i>تحليل تعليمي — مو نصيحة مالية.</i>")
    return "\n".join(lines)