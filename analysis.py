"""محرك التوصيات متعدد الأصول: لكل أصل استراتيجيته وأوزانه (مبنية على الاختبار التاريخي)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import assets

EXCHANGES = ("binance", "okx", "bybit", "kraken", "coinbase")
MAX_SCORE = 9.5

# مجمع خيوط لإطارات التحليل — يعمل بالتوازي بدل التسلسل
_POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix="tf")


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


_GOOD_EXCHANGE: str | None = None


def _order() -> tuple[str, ...]:
    if _GOOD_EXCHANGE:
        return (_GOOD_EXCHANGE,) + tuple(e for e in EXCHANGES if e != _GOOD_EXCHANGE)
    return EXCHANGES


def fetch_ohlcv(symbol: str, timeframe: str = "1h", limit: int = 250):
    """جلب الشموع — يبدأ من المنصة الناجحة سابقاً (يوفّر محاولات فاشلة بطيئة)."""
    import ccxt
    import pandas as pd

    global _GOOD_EXCHANGE
    errors = []
    for eid in _order():
        try:
            ex = getattr(ccxt, eid)({"enableRateLimit": True, "timeout": 12000})
            raw = ex.fetch_ohlcv(symbol, timeframe, limit=limit)
            if not raw:
                raise ValueError("لا بيانات")
            df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
            df["ts"] = pd.to_datetime(df["ts"], unit="ms")
            _GOOD_EXCHANGE = eid
            return df, eid
        except Exception as err:  # noqa: BLE001
            errors.append(f"{eid}: {type(err).__name__}")
    raise RuntimeError("تعذّر جلب البيانات من كل المنصات: " + "; ".join(errors))


def ticker(symbol: str) -> tuple[float, float | None, str]:
    """السعر الحالي + تغير 24س."""
    import ccxt

    global _GOOD_EXCHANGE
    for eid in _order():
        try:
            ex = getattr(ccxt, eid)({"enableRateLimit": True, "timeout": 12000})
            t = ex.fetch_ticker(symbol)
            price = float(t["last"] or t["close"])
            change = t.get("percentage")
            _GOOD_EXCHANGE = eid
            return price, change, eid
        except Exception:  # noqa: BLE001
            continue
    raise RuntimeError("تعذّر جلب السعر من كل المنصات")


def indicators(df):
    """كل المؤشرات المطلوبة (تُحسب مرة واحدة لكل تحليل)."""
    import ta

    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    bb = ta.volatility.BollingerBands(c, 20, 2)
    return {
        "atr": ta.volatility.AverageTrueRange(h, l, c, 14).average_true_range(),
        "rsi": ta.momentum.RSIIndicator(c, 14).rsi(),
        "ema20": ta.trend.EMAIndicator(c, 20).ema_indicator(),
        "ema50": ta.trend.EMAIndicator(c, 50).ema_indicator(),
        "ema200": ta.trend.EMAIndicator(c, 200).ema_indicator() if len(df) >= 200 else None,
        "macd": ta.trend.MACD(c),
        "bb_up": bb.bollinger_hband(),
        "bb_mid": bb.bollinger_mavg(),
        "bb_lo": bb.bollinger_lband(),
        "vol20": v.rolling(20).mean(),
        "adx": ta.trend.ADXIndicator(h, l, c, 14).adx(),
        "don55_hi": h.rolling(55).max().shift(1),
        "don55_lo": l.rolling(55).min().shift(1),
        "don20_hi": h.rolling(20).max().shift(1),
        "don20_lo": l.rolling(20).min().shift(1),
    }


def strategy_signal(df, ind: dict, cfg: dict) -> tuple[float, str, list[str]]:
    """إشارة الاستراتيجية المخصصة للأصل → (نقاط، وصف، أسباب).

    البيتكوين: كسر بولينجر + حجم (PF 2.98 في الاختبار التاريخي)
    الذهب:     تقاطع MACD مع فلتر EMA200 (PF 2.69)
    """
    c, v = df["close"], df["volume"]
    kind = cfg["strategy"]
    i = -1

    if kind == "bb_vol":
        up, lo = float(ind["bb_up"].iloc[i]), float(ind["bb_lo"].iloc[i])
        v20 = float(ind["vol20"].iloc[i]) if ind["vol20"].iloc[i] == ind["vol20"].iloc[i] else 0.0
        vol_ok = bool(v20 and v.iloc[i] > cfg["volume_mult"] * v20)
        vol_txt = f"حجم {v.iloc[i] / v20:.1f}×" if v20 else "حجم —"
        if c.iloc[i] > up and vol_ok:
            return 3.5, "كسر صاعد مؤكد بالحجم", [f"اختراق الحد العلوي لبولينجر ({up:,.0f}) مع {vol_txt}"]
        if c.iloc[i] < lo and vol_ok:
            return -3.5, "كسر هابط مؤكد بالحجم", [f"اختراق الحد السفلي لبولينجر ({lo:,.0f}) مع {vol_txt}"]
        if c.iloc[i] > up * 0.995:
            return 1.0, "على وشك اختراق صاعد", ["السعر ملاصق للحد العلوي — ينقصه تأكيد الحجم"]
        if c.iloc[i] < lo * 1.005:
            return -1.0, "على وشك اختراق هابط", ["السعر ملاصق للحد السفلي — ينقصه تأكيد الحجم"]
        return 0.0, "لا اختراق — انتظار", ["السعر داخل نطاق بولينجر"]

    if kind == "macd_ema200":
        m, s = ind["macd"].macd(), ind["macd"].macd_signal()
        e200 = ind["ema200"]
        if e200 is None:
            return 0.0, "بيانات غير كافية", ["تحتاج 200 شمعة لحساب EMA200"]
        above = bool(c.iloc[i] > e200.iloc[i])
        cross_up = bool(m.iloc[i] > s.iloc[i] and m.iloc[i - 1] <= s.iloc[i - 1])
        cross_dn = bool(m.iloc[i] < s.iloc[i] and m.iloc[i - 1] >= s.iloc[i - 1])
        don_hi = float(ind["don55_hi"].iloc[i]) if ind["don55_hi"].iloc[i] == ind["don55_hi"].iloc[i] else 0.0
        don_lo = float(ind["don55_lo"].iloc[i]) if ind["don55_lo"].iloc[i] == ind["don55_lo"].iloc[i] else 0.0
        if cross_up and above:
            return 3.5, "تقاطع MACD صاعد فوق EMA200", ["تقاطع صاعد حديث مع اتجاه عام صاعد"]
        if cross_dn and not above:
            return -3.5, "تقاطع MACD هابط تحت EMA200", ["تقاطع هابط حديث مع اتجاه عام هابط"]
        if m.iloc[i] > s.iloc[i] and above:
            score = 1.5
            reasons = ["MACD إيجابي والسعر فوق EMA200"]
            if don_hi and c.iloc[i] > don_hi:
                score += 1.5
                reasons.append(f"كسر أعلى قمة 55 شمعة ({don_hi:,.0f})")
            return score, "اتجاه صاعد", reasons
        if m.iloc[i] < s.iloc[i] and not above:
            score = -1.5
            reasons = ["MACD سلبي والسعر تحت EMA200"]
            if don_lo and c.iloc[i] < don_lo:
                score -= 1.5
                reasons.append(f"كسر أدنى قاع 55 شمعة ({don_lo:,.0f})")
            return score, "اتجاه هابط", reasons
        return 0.0, "لا توافق — انتظار", ["MACD والاتجاه العام غير متوافقين"]

    return 0.0, "—", []


@dataclass
class Report:
    asset: str
    asset_name: str
    strategy_name: str
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
    strategy_score: float
    strategy_label: str
    final_score: float
    reasons: list[str] = field(default_factory=list)

    @property
    def confidence(self) -> int:
        return confidence_pct(self.final_score)

    @property
    def recommendation(self) -> str:
        return verdict(self.final_score)

    @property
    def summary(self) -> str:
        lines = [
            f"📊 <b>تحليل {self.asset_name}</b> — فريم {self.timeframe}",
            f"🏦 المنصة: <code>{self.exchange}</code>",
            "",
            f"💰 السعر: <b>${self.price:,.0f}</b>"
            + (f"  (24س: {self.change_24h:+.2f}%)" if self.change_24h is not None else ""),
            "",
            f"🎯 <b>الاستراتيجية:</b> {self.strategy_name}",
            f"   الإشارة: <b>{self.strategy_label}</b> ({self.strategy_score:+.1f})",
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
            f"📊 النقاط: <code>{self.final_score:+.1f}</code> "
            f"(مؤشرات {self.score:+.1f} + استراتيجية {self.strategy_score:+.1f})",
            "",
            "الأسباب:",
        ]
        lines += [f"  {n}. {r}" for n, r in enumerate(self.reasons)]
        lines += [
            "",
            f"🛡 وقف خسارة مقترح: <code>${self.price - 2 * self.atr:,.0f}</code> (2×ATR)",
            "⚠️ <i>ليست نصيحة مالية — لأغراض تعليمية وتحليلية فقط.</i>",
        ]
        return "\n".join(lines)


def score_from_df(df, change_24h: float | None = None) -> float:
    """نقاط المؤشرات (للاستخدام في الاختبار التاريخي)."""
    import ta

    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]
    ema20 = ta.trend.EMAIndicator(close, 20).ema_indicator()
    ema50 = ta.trend.EMAIndicator(close, 50).ema_indicator()
    ema200 = ta.trend.EMAIndicator(close, 200).ema_indicator() if len(df) >= 200 else None
    rsi = ta.momentum.RSIIndicator(close, 14).rsi()
    macd = ta.trend.MACD(close)
    bb = ta.volatility.BollingerBands(close, 20, 2)

    price = float(close.iloc[-1])
    score = 0.0

    if ema200 is not None:
        e200 = float(ema200.iloc[-1])
        if price > e200:
            score += 2.0 if float(ema20.iloc[-1]) > float(ema50.iloc[-1]) else 1.0
        else:
            score -= 2.0 if float(ema20.iloc[-1]) < float(ema50.iloc[-1]) else 1.0

    e20, e50 = float(ema20.iloc[-1]), float(ema50.iloc[-1])
    e20p, e50p = float(ema20.iloc[-2]), float(ema50.iloc[-2])
    if e20 > e50 and e20p <= e50p:
        score += 2.0
    elif e20 > e50:
        score += 1.0
    elif e20 < e50 and e20p >= e50p:
        score -= 2.0
    else:
        score -= 1.0

    r = float(rsi.iloc[-1])
    if r < 30:
        score += 1.5
    elif r < 45:
        score += 0.5
    elif r > 70:
        score -= 1.5
    elif r > 55:
        score += 0.5

    m = float(macd.macd().iloc[-1])
    s = float(macd.macd_signal().iloc[-1])
    mp = float(macd.macd().iloc[-2])
    sp = float(macd.macd_signal().iloc[-2])
    if m > s and mp <= sp:
        score += 2.0
    elif m > s:
        score += 1.0
    elif m < s and mp >= sp:
        score -= 2.0
    else:
        score -= 1.0

    bu = float(bb.bollinger_hband().iloc[-1])
    bl = float(bb.bollinger_lband().iloc[-1])
    if price <= bl * 1.005:
        score += 1.0
    elif price >= bu * 0.995:
        score -= 1.0

    avg_vol = float(vol.iloc[-21:-1].mean()) if len(vol) > 21 else float(vol.mean())
    vol_ratio = float(vol.iloc[-1]) / avg_vol if avg_vol else 1.0
    if vol_ratio > 1.5:
        score += 0.5
    elif vol_ratio < 0.6:
        score -= 0.5

    if change_24h is not None:
        if -8 <= change_24h < -3:
            score += 0.5
        elif change_24h > 8:
            score -= 0.5

    return round(score, 1)


def analyze(timeframe: str = "1h", asset: str = "btc") -> Report:
    cfg = assets.get(asset)
    df, exchange = fetch_ohlcv(cfg["symbol"], timeframe)
    ind = indicators(df)
    close, vol = df["close"], df["volume"]

    w = cfg["weights"]
    price = float(close.iloc[-1])
    score = 0.0
    reasons: list[str] = []

    # 1) الاتجاه مقابل EMA200
    if ind["ema200"] is not None:
        e200 = float(ind["ema200"].iloc[-1])
        aligned = float(ind["ema20"].iloc[-1]) > float(ind["ema50"].iloc[-1])
        if price > e200:
            score += w["trend"] if aligned else w["trend"] * 0.5
            reasons.append("السعر فوق EMA200 — الاتجاه العام صاعد 📈")
        else:
            score -= w["trend"] if not aligned else w["trend"] * 0.5
            reasons.append("السعر تحت EMA200 — الاتجاه العام هابط 📉")

    # 2) تقاطع EMA20/50
    e20, e50 = float(ind["ema20"].iloc[-1]), float(ind["ema50"].iloc[-1])
    e20p, e50p = float(ind["ema20"].iloc[-2]), float(ind["ema50"].iloc[-2])
    if e20 > e50 and e20p <= e50p:
        score += w["cross"]
        reasons.append("تقاطع ذهبي حديث EMA20×EMA50 ✨")
    elif e20 > e50:
        score += w["cross"] * 0.5
    elif e20 < e50 and e20p >= e50p:
        score -= w["cross"]
        reasons.append("تقاطع موت حديث EMA20×EMA50 ⚠️")
    else:
        score -= w["cross"] * 0.5

    # 3) RSI
    r = float(ind["rsi"].iloc[-1])
    if r < 30:
        score += w["rsi"] * 1.5
        reasons.append(f"RSI = {r:.0f} — تشبّع بيعي")
    elif r < 45:
        score += w["rsi"] * 0.5
    elif r > 70:
        score -= w["rsi"] * 1.5
        reasons.append(f"RSI = {r:.0f} — تشبّع شرائي (خطر تصحيح)")
    elif r > 55:
        score += w["rsi"] * 0.5

    # 4) MACD
    m_line, s_line = ind["macd"].macd(), ind["macd"].macd_signal()
    m, s = float(m_line.iloc[-1]), float(s_line.iloc[-1])
    mp, sp = float(m_line.iloc[-2]), float(s_line.iloc[-2])
    if m > s and mp <= sp:
        score += w["macd"]
        reasons.append("MACD تقاطع صاعد حديث 🔺")
    elif m > s:
        score += w["macd"] * 0.5
    elif m < s and mp >= sp:
        score -= w["macd"]
        reasons.append("MACD تقاطع هابط حديث 🔻")
    else:
        score -= w["macd"] * 0.5

    # 5) بولينجر
    bu = float(ind["bb_up"].iloc[-1])
    bl = float(ind["bb_lo"].iloc[-1])
    if price <= bl * 1.005:
        score += w["bb"]
        reasons.append("السعر عند الحد السفلي لبولينجر")
    elif price >= bu * 0.995:
        score -= w["bb"]
        reasons.append("السعر عند الحد العلوي لبولينجر (تمدد)")

    # 6) الحجم
    avg_vol = float(vol.iloc[-21:-1].mean()) if len(vol) > 21 else float(vol.mean())
    vol_ratio = float(vol.iloc[-1]) / avg_vol if avg_vol else 1.0
    if vol_ratio > 1.5:
        score += w["vol"]
        reasons.append(f"حجم تداول مرتفع ({vol_ratio:.1f}× المتوسط)")
    elif vol_ratio < 0.6:
        score -= w["vol"] * 0.5

    # 7) تغير 24س
    change = None
    try:
        _, change, _ = ticker(cfg["symbol"])
    except Exception:  # noqa: BLE001
        pass
    if change is not None:
        if -8 <= change < -3:
            score += w["chg"]
            reasons.append(f"انخفاض 24س {change:+.1f}% — منطقة تجميع محتملة")
        elif change < -8:
            reasons.append(f"انهيار 24س {change:+.1f}% — حذر من سكين هابطة 🔪")
        elif change > 8:
            score -= w["chg"]
            reasons.append(f"ارتفاع حاد 24س {change:+.1f}% — خطر مطاردة")

    # 8) الاستراتيجية المخصصة للأصل
    strat_score, strat_label, strat_reasons = strategy_signal(df, ind, cfg)
    reasons = strat_reasons + reasons
    base = round(score, 1)
    final = round(base * 0.55 + strat_score, 1) if strat_score != 0 else round(base * 0.3, 1)

    recent = df.iloc[-20:]
    return Report(
        asset=cfg["key"],
        asset_name=cfg["name"],
        strategy_name=cfg["strategy_name"],
        exchange=exchange,
        price=price,
        timeframe=timeframe,
        rsi=r,
        ema20=e20,
        ema50=e50,
        ema200=float(ind["ema200"].iloc[-1]) if ind["ema200"] is not None else None,
        macd=m,
        macd_signal=s,
        bb_upper=bu,
        bb_lower=bl,
        support=float(recent["low"].min()),
        resistance=float(recent["high"].max()),
        atr=float(ind["atr"].iloc[-1]),
        vol_ratio=vol_ratio,
        change_24h=change,
        score=base,
        strategy_score=strat_score,
        strategy_label=strat_label,
        final_score=final,
        reasons=reasons,
    )


# ── تحليل متعدد الأطر + فيبوناتشي ──────────────────────────────

TIMEFRAME_WEIGHTS = {"1h": 0.4, "4h": 0.35, "1d": 0.25}


def fib_levels(df) -> dict:
    """مستويات فيبوناتشي من آخر 100 شمعة."""
    recent = df.iloc[-100:]
    hi = float(recent["high"].max())
    lo = float(recent["low"].min())
    diff = hi - lo
    return {f"{r:.3f}": round(lo + diff * r, 0) for r in (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0)}


def analyze_multi(asset: str = "btc") -> dict:
    """تحليل عدة أطر زمنية بالتوازي — الإطار الأعلى وزن أكبر."""
    cfg = assets.get(asset)
    reports = {}
    futures = {tf: _POOL.submit(analyze, tf, asset) for tf in TIMEFRAME_WEIGHTS}
    for tf, fut in futures.items():
        try:
            reports[tf] = fut.result(timeout=45)
        except Exception:  # noqa: BLE001
            reports[tf] = None
    valid = {tf: r for tf, r in reports.items() if r is not None}
    if not valid:
        raise RuntimeError("تعذّر التحليل على كل الأطر الزمنية")
    denom = sum(TIMEFRAME_WEIGHTS[tf] for tf in valid)
    combined = sum(r.final_score * TIMEFRAME_WEIGHTS[tf] for tf, r in valid.items()) / denom
    bullish = sum(1 for r in valid.values() if r.final_score >= 2)
    bearish = sum(1 for r in valid.values() if r.final_score <= -2)
    return {
        "reports": valid,
        "combined": round(combined, 1),
        "agreement": max(bullish, bearish),
        "total": len(valid),
        "asset": cfg["key"],
        "symbol": cfg["symbol"],
        "threshold": cfg["threshold"],
    }


def multi_summary(asset: str = "btc") -> str:
    """لوحة تحليل شاملة للأصل المحدد."""
    cfg = assets.get(asset)
    m = analyze_multi(asset)
    reports = m["reports"]
    r1h = reports.get("1h")
    lines = [f"📊 <b>لوحة تحليل {cfg['name']}</b> — {cfg['symbol']}", ""]
    if r1h:
        chg = f" ({r1h.change_24h:+.2f}% 24س)" if r1h.change_24h is not None else ""
        lines.append(f"💰 السعر: <b>${r1h.price:,.0f}</b>{chg}")
        lines.append("")
    lines.append(f"🎯 <b>الاستراتيجية:</b> {cfg['strategy_name']}")
    lines.append(f"   <i>{cfg['strategy_note']}</i>")
    lines.append("")
    lines.append("<b>⏱ الأطر الزمنية:</b>")
    for tf, r in reports.items():
        icon = "🟢" if r.final_score >= 2 else ("🔴" if r.final_score <= -2 else "🟡")
        lines.append(
            f"  {icon} <b>{tf}</b>: {r.recommendation} — <code>{r.final_score:+.1f}</code> | {r.strategy_label}"
        )
    lines.append("")
    lines.append(f"🧭 <b>الحكم النهائي: {verdict(m['combined'])}</b> (ثقة {confidence_pct(m['combined'])}%)")
    lines.append(f"🤝 توافق الأطر: {m['agreement']}/{m['total']}")
    try:
        df, _ = fetch_ohlcv(cfg["symbol"], "1h")
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


def breakout_signal(timeframe: str = "4h", asset: str = "btc") -> dict | None:
    """إشارة الاستراتيجية المخصصة للأصل — للتنبيه التلقائي (صعود فقط)."""
    cfg = assets.get(asset)
    df, exchange = fetch_ohlcv(cfg["symbol"], timeframe, limit=250)
    ind = indicators(df)
    strat_score, strat_label, _ = strategy_signal(df, ind, cfg)
    if strat_score <= 0:
        return None
    return {
        "asset": cfg["key"],
        "symbol": cfg["symbol"],
        "name": cfg["name"],
        "direction": "long",
        "strategy": cfg["strategy_name"],
        "label": strat_label,
        "strength": strat_score,
        "price": float(df["close"].iloc[-1]),
        "timeframe": timeframe,
        "exchange": exchange,
    }


def risk_plan(
    entry: float,
    direction: str,
    atr: float,
    account_size: float = 0.0,
    risk_pct: float = 1.0,
    rr: float = 2.0,
) -> dict:
    """خطة إدارة مخاطر: وقف 2×ATR + 3 أهداف حسب نسبة الأصل + حجم الصفقة."""
    sign = 1 if direction == "long" else -1
    stop_dist = 2.0 * atr
    stop = entry - sign * stop_dist
    targets = {
        f"TP1 (1:{rr / 2:.0f})": entry + sign * (rr / 2) * stop_dist,
        f"TP2 (1:{rr:.0f})": entry + sign * rr * stop_dist,
        f"TP3 (1:{rr * 1.5:.0f})": entry + sign * rr * 1.5 * stop_dist,
    }
    plan = {
        "entry": entry,
        "direction": direction,
        "atr": atr,
        "stop": stop,
        "stop_dist": stop_dist,
        "targets": targets,
        "rr": rr,
    }
    if account_size > 0:
        risk_amount = account_size * (risk_pct / 100.0)
        qty = risk_amount / stop_dist if stop_dist else 0.0
        max_qty = account_size / entry if entry else 0.0
        capped = qty > max_qty
        if capped:
            qty = max_qty
        plan.update({
            "account_size": account_size,
            "risk_pct": risk_pct,
            "risk_amount": risk_amount,
            "qty": qty,
            "qty_usd": qty * entry,
            "capped": capped,
        })
    return plan
