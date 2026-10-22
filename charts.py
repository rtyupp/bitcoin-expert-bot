"""تحليل الشارت ونقاط الصيد لكل أصل (استراتيجية الأصل نفسها) + رسم الشموع."""
import numpy as np
import pandas as pd

import assets
import chartimg

def fetch_4h(symbol: str, days: int = 20):
    """جلب شموع 4h — REST مباشر مع تبديل المصادر تلقائياً."""
    import markets

    limit = min(days * 6, 300)
    df, _ = markets.fetch_ohlcv(symbol, "4h", limit)
    return df


def _ind(df):
    import analysis

    return analysis.indicators(df)


def signal_series(df, ind, cfg) -> np.ndarray:
    """سلسلة إشارات استراتيجية الأصل لكل شمعة (نفس منطق التنبيه)."""
    c = df["close"].values
    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    vol = df["volume"].values
    n = len(df)
    out = np.zeros(n)

    up = ind["bb_up"].values
    lo = ind["bb_lo"].values
    v20 = pd.Series(ind["vol20"]).fillna(0).values
    e20 = ind["ema20"].values
    e50 = ind["ema50"].values
    e200 = ind["ema200"].values if ind["ema200"] is not None else e50
    rsi = pd.Series(ind["rsi"]).fillna(50).values
    adx = pd.Series(ind["adx"]).fillna(20).values if ind.get("adx") is not None else np.full(n, 20.0)
    sw20_hi = pd.Series(ind["don20_hi"]).fillna(pd.Series(up)).values
    sw20_lo = pd.Series(ind["don20_lo"]).fillna(pd.Series(lo)).values
    mult = cfg.get("volume_mult", 1.5)

    kind = cfg["strategy"]
    if kind in ("smc_liquidity", "bb_vol"):
        for i in range(20, n - 1):
            vol_ok = v20[i] > 0 and vol[i] > mult * v20[i]
            swept_lo = (l[i] < sw20_lo[i] and c[i] > sw20_lo[i]) or (
                l[i - 1] < sw20_lo[i - 1] and c[i] > sw20_lo[i] and c[i] > h[i - 1]
            )
            bb_fake_lo = c[i - 1] < lo[i - 1] and c[i] > lo[i] and c[i] > h[i - 1]
            swept_hi = (h[i] > sw20_hi[i] and c[i] < sw20_hi[i]) or (
                h[i - 1] > sw20_hi[i - 1] and c[i] < sw20_hi[i] and c[i] < l[i - 1]
            )
            bb_fake_hi = c[i - 1] > up[i - 1] and c[i] < up[i] and c[i] < l[i - 1]
            if (swept_lo or bb_fake_lo) and c[i] > o[i] and rsi[i] < 55:
                out[i] = 1.0
            elif c[i] > up[i] and c[i] > sw20_hi[i] and vol_ok and e20[i] > e50[i] and c[i] > e200[i] and rsi[i] < 78:
                out[i] = 1.0
            elif (swept_hi or bb_fake_hi) and c[i] < o[i] and rsi[i] > 50 and (c[i] < e200[i] or rsi[i - 1] > 68):
                out[i] = -1.0
    else:  # smc_ema20_reclaim / bb_trap_donchian / macd_ema200
        for i in range(20, n - 1):
            recent_swept_lo = (l[i - 1] <= lo[i - 1]) or (l[i - 2] <= lo[i - 2]) or (l[i - 1] < sw20_lo[i - 1])
            recent_swept_hi = (h[i - 1] >= up[i - 1]) or (h[i - 2] >= up[i - 2]) or (h[i - 1] > sw20_hi[i - 1])
            cross_up_e20 = c[i] > e20[i] and c[i - 1] <= e20[i - 1] and c[i] > o[i]
            cross_dn_e20 = c[i] < e20[i] and c[i - 1] >= e20[i - 1] and c[i] < o[i]
            bb_trap_up = c[i - 1] < lo[i - 1] and c[i] > lo[i] and c[i] > h[i - 1] and c[i] > o[i] and c[i] > e200[i]
            bb_trap_dn = c[i - 1] > up[i - 1] and c[i] < up[i] and c[i] < l[i - 1] and c[i] < o[i] and c[i] < e200[i]
            if c[i] > e200[i] and ((recent_swept_lo and cross_up_e20 and rsi[i] < 62) or bb_trap_up):
                out[i] = 1.0
            elif c[i] < e200[i] and ((recent_swept_hi and cross_dn_e20 and rsi[i] > 38) or bb_trap_dn):
                out[i] = -1.0

    out[:20] = 0
    out[-1] = 0  # الشمعة الحية لم تُغلق — لا تُعتبر إشارة
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
    stale = age is not None and age > 48
    icon = "🟢" if d == "buy" else "🔴"
    word = "شراء" if d == "buy" else "بيع"

    lines = list(head)
    lines.append(f"🎯 {a.get('strategy', '')}")
    lines.append("")
    if stale:
        lines.append(f"⚠️ <b>آخر إشارة تاريخية — قبل {age} ساعة (تجاوزت 48 ساعة — منتهية)</b>")
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
