"""تحليل الشارت ونقاط الصيد لكل أصل (استراتيجية الأصل نفسها) + رسم الشموع."""
import numpy as np
import pandas as pd

import assets
import chartimg

_EXCHANGES = ("binance", "okx", "bybit", "kraken", "coinbase")


def fetch_4h(symbol: str, days: int = 20):
    """جلب شموع 4h مع تبديل المنصات تلقائياً عند الحجب."""
    import ccxt

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


def _ind(df):
    import analysis

    return analysis.indicators(df)


def signal_series(df, ind, cfg) -> np.ndarray:
    """سلسلة إشارات استراتيجية الأصل لكل شمعة (نفس منطق التنبيه)."""
    c = df["close"].values
    n = len(df)
    out = np.zeros(n)

    if cfg["strategy"] == "bb_vol":
        up = ind["bb_up"].values
        lo = ind["bb_lo"].values
        v20 = pd.Series(ind["vol20"]).fillna(0).values
        vol = df["volume"].values
        mult = cfg["volume_mult"]
        with np.errstate(invalid="ignore"):
            out = np.where((c > up) & (vol > mult * v20), 1.0, out)
            out = np.where((c < lo) & (vol > mult * v20), -1.0, out)
    else:  # macd_ema200
        m = ind["macd"].macd().values
        s = ind["macd"].macd_signal().values
        e = ind["ema200"].values if ind["ema200"] is not None else np.full(n, np.nan)
        above = c > e
        mu, su = np.roll(m, 1), np.roll(s, 1)
        out = np.where((m > s) & (mu <= su) & above, 1.0, out)
        out = np.where((m < s) & (mu >= su) & (~above), -1.0, out)
        out = np.where((out == 0) & (m > s) & above, 0.5, out)
        out = np.where((out == 0) & (m < s) & (~above), -0.5, out)

    out[:20] = 0
    return out


def analyze_chart(df: pd.DataFrame, asset: str = "btc") -> dict:
    """أحدث إشارة قوية لاستراتيجية الأصل + صيد ثانٍ (رجعة للمتوسط) + وقف/هدف."""
    cfg = assets.get(asset)
    ind = _ind(df)
    ser = signal_series(df, ind, cfg)
    c = df["close"]
    atr = ind["atr"]
    mid = ind["bb_mid"]

    strong = np.where(np.abs(ser) >= 1.0)[0]
    idx = int(strong[-1]) if len(strong) else -1
    direction = None
    if idx >= 0:
        direction = "buy" if ser[idx] > 0 else "sell"
    else:
        weak = np.where(np.abs(ser) >= 0.5)[0]
        if len(weak):
            idx = int(weak[-1])
            direction = "buy" if ser[idx] > 0 else "sell"

    out = {
        "asset": cfg["key"],
        "asset_name": cfg["name"],
        "strategy": cfg["strategy_name"],
        "strategy_en": cfg["strategy_en"],
        "rr": cfg["rr"],
        "current_price": float(c.iloc[-1]),
        "current_ts": df["ts"].iloc[-1],
        "first_entry": None,
        "second_entry": None,
        "stop_loss": None,
        "tp1": None,
        "direction": direction,
        "signal_age_hours": None,
        "strength": 0.0,
    }
    if idx < 0 or idx >= len(df) - 1:
        return out

    d = 1 if direction == "buy" else -1
    entry = float(c.iloc[idx])
    sd = float(atr.iloc[idx]) * cfg["stop_mult"]
    out["first_entry"] = {"idx": idx, "price": entry, "ts": df["ts"].iloc[idx]}
    out["stop_loss"] = entry - d * sd
    out["tp1"] = entry + d * cfg["rr"] * sd
    out["strength"] = float(ser[idx])
    out["signal_age_hours"] = int((df["ts"].iloc[-1] - df["ts"].iloc[idx]).total_seconds() / 3600)

    # الصيد الثاني: رجعة السعر للمتوسط بعد الإشارة
    for j in range(idx + 1, min(idx + 12, len(df))):
        if direction == "buy" and c.iloc[j] <= mid.iloc[j]:
            out["second_entry"] = {"idx": j, "price": float(c.iloc[j]), "ts": df["ts"].iloc[j]}
            break
        if direction == "sell" and c.iloc[j] >= mid.iloc[j]:
            out["second_entry"] = {"idx": j, "price": float(c.iloc[j]), "ts": df["ts"].iloc[j]}
            break
    return out


def plot_chart(df: pd.DataFrame, a: dict, symbol: str, live_price: float | None = None) -> bytes:
    """شارت الشموع اليابانية (نص إنجليزي داخل الصورة — Pillow لا يشكّل العربية)."""
    return chartimg.render(df, a, symbol, strategy=a.get("strategy_en", ""), live_price=live_price)


def short_message(a: dict, symbol: str, dec: dict | None = None, live: dict | None = None) -> str:
    """رسالة موجزة: الحالة الآن + السعر اللحظي + آخر إشارة (مع تحذير لو قديمة)."""
    name = a.get("asset_name", symbol)

    head = []
    if dec:
        head.append(
            f"<b>{name}</b> — الحالة الآن: <b>{dec['stance_ar']}</b> · ثقة {dec['confidence']}%"
        )
        if dec.get("prob_up") is not None:
            head.append(f"🤖 احتمال صعود: <b>{dec['prob_up']:.1%}</b>")
        reg = dec.get("regime") or {}
        if reg:
            head.append(f"🌊 {reg.get('name')} — {reg.get('note')}")
        head.append("")
    else:
        head.append(f"<b>{name}</b> — {symbol}")
        head.append("")

    if live:
        head.append(f"💰 <b>السعر اللحظي: ${live['price']:,.2f}</b>")
        if live.get("change") is not None:
            head.append(f"   24س: {'🟢' if live['change'] >= 0 else '🔴'} {live['change']:+.2f}%")
        head.append("")

    if not a["first_entry"]:
        return "\n".join(
            head
            + [
                f"🎯 الاستراتيجية: <b>{a.get('strategy', '—')}</b>",
                "لا توجد إشارة صيد على الشارت الحالي.",
                "انتظر تحقق شروط الاستراتيجية.",
            ]
        )

    d = a["direction"]
    fe, se = a["first_entry"], a["second_entry"]
    age = a["signal_age_hours"]
    stale = age is not None and age >= 24
    icon = "🟢" if d == "buy" else "🔴"
    word = "شراء" if d == "buy" else "بيع"

    lines = list(head)
    lines.append(f"🎯 {a.get('strategy', '')}")
    lines.append("")
    if stale:
        lines.append(f"⚠️ <b>آخر إشارة تاريخية — قبل {age} ساعة (منتهية)</b>")
    label = "آخر إشارة" if stale else "أول صيد"
    lines.append(f"{icon} <b>{label} ({word}):</b> <code>{fe['price']:,.2f}</code>")
    if se:
        lines.append(f"📍 <b>ثاني صيد:</b> <code>{se['price']:,.2f}</code>")
    lines.append(f"🛑 <b>وقف:</b> <code>{a['stop_loss']:,.2f}</code>")
    lines.append(f"🎯 <b>هدف:</b> <code>{a['tp1']:,.2f}</code> (1:{a['rr']:.0f})")
    if not stale and age is not None and age >= 6:
        lines.append(f"⏳ عمر الإشارة: {age} ساعة")
    lines += [
        "",
        "⚠️ <i>تحليل تعليمي — مو نصيحة مالية.</i>",
    ]
    return "\n".join(lines)
