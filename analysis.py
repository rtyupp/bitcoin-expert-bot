"""محرك التوصيات متعدد الأصول: لكل أصل استراتيجيته وأوزانه (مبنية على الاختبار التاريخي)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import assets
import datetime
import halving_utils

EXCHANGES = ("binance", "bybit", "okx")
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


def fetch_ohlcv(symbol: str, timeframe: str = "1h", limit: int = 250):
    """جلب الشموع — REST مباشر بدون ccxt (طلب واحد لكل استدعاء، سريع)."""
    import markets

    return markets.fetch_ohlcv(symbol, timeframe, limit)


def ticker(symbol: str) -> tuple[float, float | None, str]:
    """السعر الحالي + تغير 24س."""
    import markets

    return markets.ticker(symbol)


def live_ticker(symbol: str) -> dict:
    """سعر لحظي كامل (آخر صفقة) + أعلى/أدنى 24س + طابع زمني."""
    import markets

    return markets.live_ticker(symbol)


def indicators(df):
    """كل المؤشرات المطلوبة (تُحسب مرة واحدة لكل تحليل)."""
    import ta

    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    bb = ta.volatility.BollingerBands(c, 20, 2)
    return {
        "atr": ta.volatility.AverageTrueRange(h, l, c, 14).average_true_range() if len(df) >= 15 else (h - l),
        "rsi": ta.momentum.RSIIndicator(c, 14).rsi(),
        "ema20": ta.trend.EMAIndicator(c, 20).ema_indicator(),
        "ema50": ta.trend.EMAIndicator(c, 50).ema_indicator(),
        "ema200": ta.trend.EMAIndicator(c, 200).ema_indicator() if len(df) >= 200 else None,
        "macd": ta.trend.MACD(c),
        "bb_up": bb.bollinger_hband(),
        "bb_mid": bb.bollinger_mavg(),
        "bb_lo": bb.bollinger_lband(),
        "vol20": v.rolling(20).mean(),
        "adx": ta.trend.ADXIndicator(h, l, c, 14).adx() if len(df) >= 15 else None,
        "don55_hi": h.rolling(55).max().shift(1),
        "don55_lo": l.rolling(55).min().shift(1),
        "don20_hi": h.rolling(20).max().shift(1),
        "don20_lo": l.rolling(20).min().shift(1),
    }


def strategy_signal(df, ind: dict, cfg: dict) -> tuple[float, str, list[str]]:
    """إشارة الاستراتيجية الاحترافية المخصصة للأصل → (نقاط، وصف، أسباب).

    البيتكوين (smc_liquidity): قنص السيولة (SMC Stop-Hunt / Bear Trap Reclaim) + اختراق مؤسسي صاعد
    الذهب (bb_trap_donchian): مصيدة الكسر الكاذب لبولينجر + اختراق قناة Donchian 20 مع الاتجاه
    """
    c, o, h, l, v = df["close"], df["open"], df["high"], df["low"], df["volume"]
    kind = cfg["strategy"]
    if len(c) < 25:
        return 0.0, "بيانات غير كافية", []
    i = -2 if len(c) >= 2 else -1  # آخر شمعة مغلقة — الحية ما زالت تتشكل
    ip = i - 1

    up, lo = float(ind["bb_up"].iloc[i]), float(ind["bb_lo"].iloc[i])
    up_p, lo_p = float(ind["bb_up"].iloc[ip]), float(ind["bb_lo"].iloc[ip])
    sw20_hi = float(ind["don20_hi"].iloc[i]) if ind["don20_hi"].iloc[i] == ind["don20_hi"].iloc[i] else up
    sw20_lo = float(ind["don20_lo"].iloc[i]) if ind["don20_lo"].iloc[i] == ind["don20_lo"].iloc[i] else lo
    sw20_hi_p = float(ind["don20_hi"].iloc[ip]) if ind["don20_hi"].iloc[ip] == ind["don20_hi"].iloc[ip] else up_p
    sw20_lo_p = float(ind["don20_lo"].iloc[ip]) if ind["don20_lo"].iloc[ip] == ind["don20_lo"].iloc[ip] else lo_p
    v20 = float(ind["vol20"].iloc[i]) if ind["vol20"].iloc[i] == ind["vol20"].iloc[i] else 0.0
    vol_ratio = float(v.iloc[i]) / v20 if v20 else 1.0
    e20 = float(ind["ema20"].iloc[i])
    e50 = float(ind["ema50"].iloc[i])
    e200 = float(ind["ema200"].iloc[i]) if ind["ema200"] is not None else e50
    rsi_now = float(ind["rsi"].iloc[i])
    rsi_prev = float(ind["rsi"].iloc[ip])
    adx_now = float(ind["adx"].iloc[i]) if ind["adx"] is not None and ind["adx"].iloc[i] == ind["adx"].iloc[i] else 20.0

    if kind in ("smc_liquidity", "bb_vol"):
        ts = df["ts"].iloc[i] if "ts" in df.columns else datetime.datetime.now(datetime.timezone.utc)
        phase = halving_utils.halving_phase(ts)
        vol_ok = vol_ratio > cfg.get("volume_mult", 1.5)

        # 1) صيدة سيولة شرائية (SMC Bear Trap / Stop-Hunt Reclaim)
        swept_20_lo = (l.iloc[i] < sw20_lo and c.iloc[i] > sw20_lo) or (
            l.iloc[ip] < sw20_lo_p and c.iloc[i] > sw20_lo and c.iloc[i] > h.iloc[ip]
        )
        bb_fake_lo = c.iloc[ip] < lo_p and c.iloc[i] > lo and c.iloc[i] > h.iloc[ip]
        if (swept_20_lo or bb_fake_lo) and c.iloc[i] > o.iloc[i] and rsi_now < 55 and phase != "bear":
            return (
                3.5,
                "صيدة سيولة شرائية — كنس قاع وارتداد (Bear Trap)",
                [f"كنس سيولة القاع ({sw20_lo:,.0f}) وإغلاق شرائي مؤكد داخل النطاق"],
            )

        # 2) اختراق مؤسسي صاعد (فقط مع توافق الاتجاه الكامل EMA20>EMA50 وفوق EMA200 وحجم عالٍ)
        if c.iloc[i] > up and c.iloc[i] > sw20_hi and vol_ok and e20 > e50 and c.iloc[i] > e200 and rsi_now < 78 and phase != "bear":
            return (
                3.5,
                f"اختراق مؤسسي صاعد بحجم {vol_ratio:.1f}×",
                [f"اختراق قمة 20 شمعة ({sw20_hi:,.0f}) وبولينجر مع اتجاه صاعد وحجم {vol_ratio:.1f}×"],
            )

        # 3) صيدة سيولة بيعية (Bull Trap Sweep) عند التشبع أو تحت EMA200
        swept_20_hi = (h.iloc[i] > sw20_hi and c.iloc[i] < sw20_hi) or (
            h.iloc[ip] > sw20_hi_p and c.iloc[i] < sw20_hi and c.iloc[i] < l.iloc[ip]
        )
        bb_fake_hi = c.iloc[ip] > up_p and c.iloc[i] < up and c.iloc[i] < l.iloc[ip]
        if (swept_20_hi or bb_fake_hi) and c.iloc[i] < o.iloc[i] and rsi_now > 50 and (c.iloc[i] < e200 or rsi_prev > 68):
            return (
                -3.5,
                "صيدة سيولة بيعية — كنس قمة ورفض (Bull Trap)",
                [f"كنس سيولة القمة ({sw20_hi:,.0f}) وإغلاق بيعي رافض داخل النطاق"],
            )

        # إشارات تحذيرية (قرب المناطق الحساسة)
        if l.iloc[i] <= sw20_lo * 1.003:
            return 1.0, "مراقبة سيولة القاع — انتظار شمعة الاسترداد", [f"السعر يختبر قاع السيولة ({sw20_lo:,.0f}) — انتظر الإغلاق الإيجابي"]
        if c.iloc[i] > up * 0.996 and e20 > e50:
            return 1.0, "قرب اختراق صاعد — ينقصه تأكيد الحجم", ["السعر يختبر الحد العلوي لبولينجر"]
        return 0.0, "داخل النطاق — انتظار صيدة سيولة", ["لا يوجد كنس سيولة أو اختراق مؤسسي حالياً"]

    if kind in ("bb_trap_donchian", "macd_ema200"):
        vol_ok = vol_ratio > cfg.get("volume_mult", 1.2)
        bb_fake_lo = c.iloc[ip] < lo_p and c.iloc[i] > lo and c.iloc[i] > o.iloc[i]
        bb_fake_hi = c.iloc[ip] > up_p and c.iloc[i] < up and c.iloc[i] < o.iloc[i]
        don_up = c.iloc[i] > sw20_hi and e20 > e50 and c.iloc[i] > e200 and adx_now > 22 and vol_ok
        don_dn = c.iloc[i] < sw20_lo and e20 < e50 and c.iloc[i] < e200 and adx_now > 22 and vol_ok

        if bb_fake_lo and (c.iloc[i] > e200 or rsi_prev < 35):
            return 3.5, "ارتداد مصيدة بولينجر السفلية (Bear Trap)", [f"كسر كاذب تحت بولينجر ({lo_p:,.0f}) واسترداد شرائي مباشر"]
        if don_up:
            return 3.5, "اختراق قناة Donchian 20 صاعد مع الاتجاه", [f"اختراق قمة 20 شمعة ({sw20_hi:,.0f}) بدعم ADX={adx_now:.0f} وفوق EMA200"]
        if bb_fake_hi and (c.iloc[i] < e200 or rsi_prev > 65):
            return -3.5, "ارتداد مصيدة بولينجر العلوية (Bull Trap)", [f"كسر كاذب فوق بولينجر ({up_p:,.0f}) ورفض بيعي مباشر"]
        if don_dn:
            return -3.5, "كسر قناة Donchian 20 هابط مع الاتجاه", [f"كسر قاع 20 شمعة ({sw20_lo:,.0f}) بدعم ADX={adx_now:.0f} وتحت EMA200"]

        if c.iloc[i] > e200 and e20 > e50:
            return 1.0, "ميل صاعد فوق EMA200 — انتظار نقطة قنص", ["الاتجاه العام صاعد — بانتظار مصيدة سيولة أو اختراق"]
        if c.iloc[i] < e200 and e20 < e50:
            return -1.0, "ميل هابط تحت EMA200 — انتظار نقطة قنص", ["الاتجاه العام هابط — بانتظار مصيدة سيولة أو كسر"]
        return 0.0, "تذبذب محايد — انتظار", ["لا توجد مصيدة بولينجر أو اختراق قناة مكتمل"]

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


def breakout_signal(timeframe: str = "1h", asset: str = "btc") -> dict | None:
    """إشارة الاستراتيجية القوية للأصل — للتنبيه التلقائي (عند تحقق شروط الصيدة القوية فقط)."""
    cfg = assets.get(asset)
    df, exchange = fetch_ohlcv(cfg["symbol"], timeframe, limit=250)
    ind = indicators(df)
    strat_score, strat_label, _ = strategy_signal(df, ind, cfg)
    if abs(strat_score) < 2.0:
        return None
    i = -2 if len(df) >= 2 else -1
    direction = "long" if strat_score > 0 else "short"
    phase = halving_utils.halving_phase()
    if direction == "long" and phase == "bear":
        return None
    if direction == "short" and phase == "bull":
        return None
    return {
        "asset": cfg["key"],
        "symbol": cfg["symbol"],
        "name": cfg["name"],
        "direction": direction,
        "strategy": cfg["strategy_name"],
        "label": strat_label,
        "strength": strat_score,
        "price": float(df["close"].iloc[i]),
        "timeframe": timeframe,
        "exchange": exchange,
    }


def _rr_label(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".")


def risk_plan(
    entry: float,
    direction: str,
    atr: float,
    account_size: float = 0.0,
    risk_pct: float = 1.0,
    rr: float = 2.0,
    stop_mult: float = 1.8,
) -> dict:
    """خطة إدارة مخاطر احترافية: وقف stop_mult×ATR + تأمين عند TP1 (1R) + هدف كامل TP2 + TP3."""
    sign = 1 if direction == "long" else -1
    stop_dist = stop_mult * atr
    stop = entry - sign * stop_dist
    targets = {
        "TP1 (1:1 — تأمين الوقف للدخول 🔒)": entry + sign * 1.0 * stop_dist,
        f"TP2 (1:{_rr_label(rr)} — الهدف الكامل 🎯)": entry + sign * rr * stop_dist,
        f"TP3 (1:{_rr_label(rr * 1.5)} — هدف ممتد 🚀)": entry + sign * rr * 1.5 * stop_dist,
    }
    plan = {
        "entry": entry,
        "direction": direction,
        "atr": atr,
        "stop": stop,
        "stop_dist": stop_dist,
        "stop_mult": stop_mult,
        "tp1_be": entry + sign * 1.0 * stop_dist,
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


# ── طبقة القرار: استراتيجية + نظام سوق + نموذج تعلّم ──────────────

_ml_cache: dict[str, tuple[float, dict]] = {}
_ML_TTL = 900  # 15 دقيقة

_STANCE_AR = {"long": "شراء 🟢", "short": "بيع 🔴", "flat": "لا صفقة ⏸"}


def ml_view(asset: str = "btc", bars: int = 1000) -> dict:
    """نموذج التعلّم + نظام السوق، مع تخزين مؤقت 15 دقيقة."""
    import time

    import ml_engine

    now = time.time()
    hit = _ml_cache.get(asset)
    if hit and now - hit[0] < _ML_TTL:
        return hit[1]
    cfg = assets.get(asset)
    df, _ = fetch_ohlcv(cfg["symbol"], "4h", bars)
    out = {"ml": ml_engine.walk_forward(df), "regime": ml_engine.regime(df)}
    _ml_cache[asset] = (now, out)
    return out


def decision(asset: str = "btc") -> dict:
    """القرار النهائي: الاستراتيجية + نظام السوق + احتمال النموذج (بالدالتين بالتوازي)."""
    from concurrent.futures import ThreadPoolExecutor

    cfg = assets.get(asset)
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="dec") as ex:
        f_r = ex.submit(analyze, "1h", asset)
        f_m = ex.submit(ml_view, asset)
        r = f_r.result()
        mv = f_m.result()
    ml = mv.get("ml", {})
    reg = mv.get("regime", {})
    prob = float(ml["prob_up"]) if ml.get("ok") else None

    strat = r.strategy_score
    if strat > 0 and (prob is None or prob >= 0.5):
        stance = "long"
    elif strat < 0 and (prob is None or prob < 0.5):
        stance = "short"
    else:
        stance = "flat"

    strength = min(abs(strat) / 3.5, 1.0)
    conf_ml = abs((prob if prob is not None else 0.5) - 0.5) * 2
    confidence = round(min(1.0, strength * 0.65 + conf_ml * 0.35) * 100)

    reasons = list(r.reasons)
    if prob is not None:
        reasons.insert(0, f"نموذج {ml['model']}: احتمال صعود {prob:.1%} (AUC {ml['metrics']['auc']})")
    reasons.insert(0, f"نظام السوق: {reg.get('name', '—')} — {reg.get('note', '')}")

    # الإشارة تُعتبر نشطة فقط إذا تحققت شروط الاستراتيجية القوية (|strat| >= 2.0) وتوافقت مع دورة السوق
    phase = halving_utils.halving_phase()
    phase_ok = (phase != "bear") if strat >= 0 else (phase != "bull")
    active_signal = phase_ok and abs(strat) >= 2.0

    return {
        "asset": asset,
        "name": cfg["name"],
        "symbol": cfg["symbol"],
        "strategy": cfg["strategy_name"],
        "rr": cfg["rr"],
        "price": r.price,
        "atr": r.atr,
        "strategy_label": r.strategy_label,
        "strategy_score": strat,
        "stance": stance,
        "stance_ar": _STANCE_AR[stance],
        "confidence": confidence,
        "active": active_signal,
        "regime": reg,
        "prob_up": prob,
        "ml_model": ml.get("model"),
        "ml_metrics": ml.get("metrics"),
        "reasons": reasons[:6],
    }
