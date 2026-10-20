"""محرك التوصيات: بيانات ccxt + مؤشرات ta + نظام نقاط مستوحى من استراتيجيات freqtrade."""
from __future__ import annotations

from dataclasses import dataclass, field

EXCHANGES = ("binance", "okx", "bybit", "kraken", "coinbase")
SYMBOL = "BTC/USDT"
MAX_SCORE = 9.5  # مجموع أعلى الأوزان الإيجابية — لتطبيع الثقة


def verdict(score: float) -> str:
    if score >= 5:
        return "شراء قوي 🟢"
    if score >= 2:
        return "شراء 🟩"
    if score > -2:
        return "محايد / انتظار 🟨"
    if score > -5:
        return "بيع 🟧"
    return "بيع قوي 🔴"


def confidence_pct(score: float) -> int:
    return round(min(abs(score) / MAX_SCORE, 1.0) * 100)


def fetch_ohlcv(timeframe: str = "1h", limit: int = 250) -> tuple[pd.DataFrame, str]:
    """جلب الشموع من أول منصة تستجيب (تحويل تلقائي بين المنصات عند الحظر)."""
    import ccxt
    import pandas as pd

    errors = []
    for eid in EXCHANGES:
        try:
            ex = getattr(ccxt, eid)()
            raw = ex.fetch_ohlcv(SYMBOL, timeframe, limit=limit)
            df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
            df["ts"] = pd.to_datetime(df["ts"], unit="ms")
            return df, eid
        except Exception as err:  # noqa: BLE001
            errors.append(f"{eid}: {type(err).__name__}")
    raise RuntimeError("تعذّر جلب البيانات من كل المنصات: " + "; ".join(errors))


def ticker() -> tuple[float, float | None, str]:
    """سعر البيتكوين الحالي + نسبة التغير 24س من أول منصة تستجيب."""
    import ccxt

    for eid in EXCHANGES:
        try:
            ex = getattr(ccxt, eid)()
            t = ex.fetch_ticker(SYMBOL)
            price = float(t["last"] or t["close"])
            change = t.get("percentage")
            return price, change, eid
        except Exception:  # noqa: BLE001
            continue
    raise RuntimeError("تعذّر جلب السعر من كل المنصات")


@dataclass
class Report:
    exchange: str
    price: float
    timeframe: str
    rsi: float
    ema20: float
    ema50: float
    ema200: float | None
    macd: float
    macd_signal: float
    bb_upper: float
    bb_lower: float
    support: float
    resistance: float
    atr: float
    vol_ratio: float
    change_24h: float | None
    score: float
    reasons: list[str] = field(default_factory=list)

    @property
    def confidence(self) -> int:
        return confidence_pct(self.score)

    @property
    def recommendation(self) -> str:
        return verdict(self.score)

    @property
    def summary(self) -> str:
        lines = [
            f"📊 <b>تحليل {SYMBOL}</b> — فريم {self.timeframe}",
            f"🏦 المنصة: <code>{self.exchange}</code>",
            "",
            f"💰 السعر: <b>${self.price:,.0f}</b>"
            + (f"  (24س: {self.change_24h:+.2f}%)" if self.change_24h is not None else ""),
            "",
            "📈 <b>المؤشرات:</b>",
            f"• RSI(14): <code>{self.rsi:.1f}</code>",
            f"• EMA20/50: <code>{self.ema20:,.0f} / {self.ema50:,.0f}</code>",
        ]
        if self.ema200 is not None:
            lines.append(f"• EMA200: <code>{self.ema200:,.0f}</code>")
        lines += [
            f"• MACD: <code>{self.macd:,.0f}</code> (إشارة: {self.macd_signal:,.0f})",
            f"• بولينجر: <code>{self.bb_lower:,.0f} — {self.bb_upper:,.0f}</code>",
            f"• دعم: <code>${self.support:,.0f}</code> | مقاومة: <code>${self.resistance:,.0f}</code>",
            f"• حجم التداول: <code>{self.vol_ratio:.1f}×</code> المتوسط",
            "",
            f"🧭 <b>التوصية: {self.recommendation}</b> (ثقة {self.confidence}%)",
            "",
            "الأسباب:",
        ]
        lines += [f"  {i+1}. {r}" for i, r in enumerate(self.reasons)]
        lines += [
            "",
            f"🛡 وقف خسارة مقترح: <code>${self.price - 2 * self.atr:,.0f}</code> (2×ATR)",
            "⚠️ <i>ليست نصيحة مالية — لأغراض تعليمية وتحليلية فقط.</i>",
        ]
        return "\n".join(lines)


def analyze(timeframe: str = "1h") -> Report:
    import ta

    df, exchange = fetch_ohlcv(timeframe)
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]

    ema20 = ta.trend.EMAIndicator(close, 20).ema_indicator()
    ema50 = ta.trend.EMAIndicator(close, 50).ema_indicator()
    ema200 = ta.trend.EMAIndicator(close, 200).ema_indicator() if len(df) >= 200 else None
    rsi = ta.momentum.RSIIndicator(close, 14).rsi()
    macd = ta.trend.MACD(close)
    bb = ta.volatility.BollingerBands(close, 20, 2)
    atr = ta.volatility.AverageTrueRange(high, low, close, 14).average_true_range()

    price = float(close.iloc[-1])
    score = 0.0
    reasons: list[str] = []

    # 1) الاتجاه العام مقابل EMA200
    if ema200 is not None:
        e200 = float(ema200.iloc[-1])
        if price > e200:
            score += 2.0 if float(ema20.iloc[-1]) > float(ema50.iloc[-1]) else 1.0
            reasons.append("السعر فوق EMA200 — الاتجاه العام صاعد 📈")
        else:
            score -= 2.0 if float(ema20.iloc[-1]) < float(ema50.iloc[-1]) else 1.0
            reasons.append("السعر تحت EMA200 — الاتجاه العام هابط 📉")

    # 2) تقاطع EMA20/50
    e20, e50 = float(ema20.iloc[-1]), float(ema50.iloc[-1])
    e20p, e50p = float(ema20.iloc[-2]), float(ema50.iloc[-2])
    if e20 > e50 and e20p <= e50p:
        score += 2.0
        reasons.append("تقاطع ذهبي حديث EMA20×EMA50 ✨")
    elif e20 > e50:
        score += 1.0
        reasons.append("EMA20 فوق EMA50 — زخم قصير المدى إيجابي")
    elif e20 < e50 and e20p >= e50p:
        score -= 2.0
        reasons.append("تقاطع موت حديث EMA20×EMA50 ⚠️")
    else:
        score -= 1.0
        reasons.append("EMA20 تحت EMA50 — زخم قصير المدى سلبي")

    # 3) RSI
    r = float(rsi.iloc[-1])
    if r < 30:
        score += 1.5
        reasons.append(f"RSI = {r:.0f} — تشبّع بيعي (فرصة ارتداد محتملة)")
    elif r < 45:
        score += 0.5
        reasons.append(f"RSI = {r:.0f} — في منطقة الدعم")
    elif r > 70:
        score -= 1.5
        reasons.append(f"RSI = {r:.0f} — تشبّع شرائي (خطر تصحيح)")
    elif r > 55:
        score += 0.5
        reasons.append(f"RSI = {r:.0f} — زخم إيجابي")

    # 4) MACD
    m_line = macd.macd()
    s_line = macd.macd_signal()
    m, s = float(m_line.iloc[-1]), float(s_line.iloc[-1])
    mp, sp = float(m_line.iloc[-2]), float(s_line.iloc[-2])
    if m > s and mp <= sp:
        score += 2.0
        reasons.append("MACD تقاطع صاعد حديث 🔺")
    elif m > s:
        score += 1.0
        reasons.append("MACD إيجابي")
    elif m < s and mp >= sp:
        score -= 2.0
        reasons.append("MACD تقاطع هابط حديث 🔻")
    else:
        score -= 1.0
        reasons.append("MACD سلبي")

    # 5) بولينجر باند
    bu = float(bb.bollinger_hband().iloc[-1])
    bl = float(bb.bollinger_lband().iloc[-1])
    if price <= bl * 1.005:
        score += 1.0
        reasons.append("السعر عند الحد السفلي لبولينجر (ضغط بيعي مفرط)")
    elif price >= bu * 0.995:
        score -= 1.0
        reasons.append("السعر عند الحد العلوي لبولينجر (تمدد زائد)")

    # 6) الحجم
    avg_vol = float(vol.iloc[-21:-1].mean()) if len(vol) > 21 else float(vol.mean())
    vol_ratio = float(vol.iloc[-1]) / avg_vol if avg_vol else 1.0
    if vol_ratio > 1.5:
        score += 0.5
        reasons.append(f"حجم تداول مرتفع ({vol_ratio:.1f}× المتوسط) — اهتمام متزايد")
    elif vol_ratio < 0.6:
        score -= 0.5
        reasons.append(f"حجم تداول ضعيف ({vol_ratio:.1f}× المتوسط)")

    # 7) تغير 24س (من التيكر)
    change = None
    try:
        _, change, _ = ticker()
    except Exception:  # noqa: BLE001
        pass
    if change is not None:
        if -8 <= change < -3:
            score += 0.5
            reasons.append(f"انخفاض 24س {change:+.1f}% — قد تكون منطقة تجميع")
        elif change < -8:
            reasons.append(f"انهيار 24س {change:+.1f}% — كن حذراً من سكين هابطة 🔪")
        elif change > 8:
            score -= 0.5
            reasons.append(f"ارتفاع حاد 24س {change:+.1f}% — خطر مطاردة السعر")

    recent = df.iloc[-20:]
    return Report(
        exchange=exchange,
        price=price,
        timeframe=timeframe,
        rsi=r,
        ema20=e20,
        ema50=e50,
        ema200=float(ema200.iloc[-1]) if ema200 is not None else None,
        macd=m,
        macd_signal=s,
        bb_upper=bu,
        bb_lower=bl,
        support=float(recent["low"].min()),
        resistance=float(recent["high"].max()),
        atr=float(atr.iloc[-1]),
        vol_ratio=vol_ratio,
        change_24h=change,
        score=round(score, 1),
        reasons=reasons,
    )


# ── تحليل متعدد الأطر الزمنية + فيبوناتشي ──────────────────────

TIMEFRAME_WEIGHTS = {"1h": 0.4, "4h": 0.35, "1d": 0.25}


def fib_levels(df) -> dict:
    """مستويات فيبوناتشي من آخر 100 شمعة (أعلى قمة → أدنى قاع)."""
    recent = df.iloc[-100:]
    hi = float(recent["high"].max())
    lo = float(recent["low"].min())
    diff = hi - lo
    return {f"{r:.3f}": round(lo + diff * r, 0) for r in (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0)}


def analyze_multi() -> dict:
    """تحليل عدة أطر زمنية بنقاط موزونة — الإطار الأعلى وزن أكبر."""
    reports = {}
    for tf in TIMEFRAME_WEIGHTS:
        try:
            reports[tf] = analyze(tf)
        except Exception:  # noqa: BLE001
            reports[tf] = None
    valid = {tf: r for tf, r in reports.items() if r is not None}
    if not valid:
        raise RuntimeError("تعذّر التحليل على كل الأطر الزمنية")
    denom = sum(TIMEFRAME_WEIGHTS[tf] for tf in valid)
    combined = sum(r.score * TIMEFRAME_WEIGHTS[tf] for tf, r in valid.items()) / denom
    bullish = sum(1 for r in valid.values() if r.score >= 2)
    bearish = sum(1 for r in valid.values() if r.score <= -2)
    agreement = max(bullish, bearish)
    return {
        "reports": valid,
        "combined": round(combined, 1),
        "agreement": agreement,
        "total": len(valid),
    }


def multi_summary() -> str:
    """لوحة تحليل شاملة — كل الأطر + الحكم النهائي + فيبوناتشي."""
    m = analyze_multi()
    reports = m["reports"]
    r1h = reports.get("1h")
    lines = ["📊 <b>لوحة التحليل الشاملة</b> — BTC/USDT", ""]
    if r1h:
        chg = f" ({r1h.change_24h:+.2f}% 24س)" if r1h.change_24h is not None else ""
        lines.append(f"💰 السعر: <b>${r1h.price:,.0f}</b>{chg}")
        lines.append("")
    lines.append("<b>🎯 الأطر الزمنية:</b>")
    for tf, r in reports.items():
        icon = "🟢" if r.score >= 2 else ("🔴" if r.score <= -2 else "🟡")
        lines.append(
            f"  {icon} <b>{tf}</b>: {r.recommendation} — نقاط <code>{r.score:+.1f}</code> | RSI {r.rsi:.0f}"
        )
    lines.append("")
    lines.append(f"🧭 <b>الحكم النهائي: {verdict(m['combined'])}</b> (ثقة {confidence_pct(m['combined'])}%)")
    lines.append(f"🤝 توافق الأطر الزمنية: {m['agreement']}/{m['total']} في نفس الاتجاه")
    try:
        df, _ = fetch_ohlcv("1h")
        fib = fib_levels(df)
        lines.append("")
        lines.append("📐 <b>مستويات فيبوناتشي (1h):</b>")
        for k in ("0.382", "0.500", "0.618"):
            lines.append(f"  • {k}: <code>${fib[k]:,.0f}</code>")
    except Exception:  # noqa: BLE001
        pass
    lines.append("")
    lines.append("⚠️ <i>ليست نصيحة مالية — لأغراض تعليمية.</i>")
    return "\n".join(lines)
