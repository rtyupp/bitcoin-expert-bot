"""تنبيه الصيدة: فحص التوصية وإرسال تنبيه فوري عند إشارة قوية."""
import asyncio
import json
import logging
import os
import time

import analysis
import config

STATE_FILE = os.path.join(os.path.dirname(__file__), "last_alert.txt")


def _read_last() -> float:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return float(f.read().strip())
    except Exception:  # noqa: BLE001
        return 0.0


def _write_last(ts: float) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            f.write(str(ts))
    except Exception:  # noqa: BLE001
        logging.exception("تعذّر حفظ توقيت آخر تنبيه")


def _alert_text_multi(m: dict) -> str:
    combined = m["combined"]
    r1h = m["reports"].get("1h")
    icon = "🟢 صيدة شراء!" if combined > 0 else "🔴 صيدة بيع!"
    lines = [f"🚨 <b>{icon}</b>", ""]
    if r1h:
        lines.append(f"💰 السعر: <b>${r1h.price:,.0f}</b>")
    lines.append(f"📈 الحكم (موزون): <b>{analysis.verdict(combined)}</b> (ثقة {analysis.confidence_pct(combined)}%)")
    lines.append(f"🎯 النقاط: <code>{combined:+.1f}</code> (العتبة ±{config.SIGNAL_THRESHOLD:.1f})")
    lines.append(f"🤝 توافق الأطر: {m['agreement']}/{m['total']}")
    lines.append("")
    lines.append("الأطر الزمنية:")
    for tf, r in m["reports"].items():
        icon_tf = "🟢" if r.score >= 2 else ("🔴" if r.score <= -2 else "🟡")
        lines.append(f"  {icon_tf} {tf}: {r.recommendation} ({r.score:+.1f})")
    if r1h:
        lines.append(f"\n🛡 وقف خسارة مقترح: <code>${r1h.price - 2 * r1h.atr:,.0f}</code>")
    lines.append("\n⚠️ <i>ليست نصيحة مالية.</i>")
    return "\n".join(lines)


async def check_and_alert(bot, target: int | None = None) -> dict:
    """يفحص التوصية (متعدد الأطر + توافق) ويرسل تنبيهاً عند صيدة قوية (مع تهدئة)."""
    target = target or config.ADMIN_CHAT_ID
    if target is None:
        return {"sent": False, "reason": "no_chat_id"}
    try:
        m = await asyncio.to_thread(analysis.analyze_multi)
    except Exception as e:  # noqa: BLE001
        return {"sent": False, "reason": f"analysis_failed: {e}"}

    combined = m["combined"]
    if abs(combined) < config.SIGNAL_THRESHOLD:
        return {"sent": False, "reason": "weak_signal", "score": combined}
    if m["agreement"] < config.SIGNAL_MIN_AGREEMENT:
        return {"sent": False, "reason": "no_confluence", "score": combined, "agreement": m["agreement"]}

    now = time.time()
    if now - _read_last() < config.SIGNAL_COOLDOWN_MIN * 60:
        return {"sent": False, "reason": "cooldown", "score": combined}

    _write_last(now)
    try:
        await bot.send_message(target, _alert_text_multi(m))
        return {"sent": True, "score": combined, "agreement": m["agreement"]}
    except Exception as e:  # noqa: BLE001
        return {"sent": False, "reason": f"send_failed: {e}", "score": combined}


async def watcher_loop(bot) -> None:
    """مراقبة مستمرة (لوضع polling على خادم دائم مثل Oracle)."""
    logging.info(
        "مراقبة الصيدة بدأت — كل %ds، العتبة ±%.1f",
        config.SIGNAL_INTERVAL_SEC,
        config.SIGNAL_THRESHOLD,
    )
    while True:
        try:
            res = await check_and_alert(bot)
            if res.get("sent"):
                logging.info("أُرسل تنبيه صيدة (score=%s)", res.get("score"))
        except Exception:  # noqa: BLE001
            logging.exception("خطأ في مراقبة الصيدة")
        try:
            await check_price_alerts(bot)
        except Exception:  # noqa: BLE001
            logging.exception("خطأ في فحص أهداف السعر")
        await asyncio.sleep(config.SIGNAL_INTERVAL_SEC)


# ── تنبيهات السعر المستهدفة ────────────────────────────────────

PRICE_ALERTS_FILE = os.path.join(os.path.dirname(__file__), "price_alerts.json")
_price_alerts: dict[str, list[dict]] = {}


def _load_alerts() -> None:
    global _price_alerts
    try:
        with open(PRICE_ALERTS_FILE, "r", encoding="utf-8") as f:
            _price_alerts = json.load(f)
    except Exception:  # noqa: BLE001
        _price_alerts = {}


def _save_alerts() -> None:
    try:
        with open(PRICE_ALERTS_FILE, "w", encoding="utf-8") as f:
            json.dump(_price_alerts, f, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        logging.exception("تعذّر حفظ تنبيهات السعر")


def set_alert(chat_id: int, price: float, direction: str) -> None:
    key = str(chat_id)
    _price_alerts.setdefault(key, []).append({"price": price, "direction": direction})
    _save_alerts()


def list_alerts(chat_id: int) -> list[dict]:
    return _price_alerts.get(str(chat_id), [])


def clear_alerts(chat_id: int) -> int:
    key = str(chat_id)
    n = len(_price_alerts.get(key, []))
    _price_alerts.pop(key, None)
    _save_alerts()
    return n


async def check_price_alerts(bot) -> None:
    """يفحص أهداف السعر ويرسل تنبيهاً عند الوصول (ويحذف المنفّذ)."""
    if not _price_alerts:
        return
    try:
        price, _, _ = await asyncio.to_thread(analysis.ticker)
    except Exception:  # noqa: BLE001
        return
    for key in list(_price_alerts.keys()):
        remaining = []
        for a in _price_alerts[key]:
            fired = (a["direction"] == "up" and price >= a["price"]) or (
                a["direction"] == "down" and price <= a["price"]
            )
            if fired:
                try:
                    await bot.send_message(
                        int(key),
                        f"⏰ <b>وصل البيتكوين لهدفك!</b>\n\n"
                        f"💰 السعر الآن: <b>${price:,.0f}</b>\n"
                        f"🎯 الهدف: <code>${a['price']:,.0f}</code>\n\n"
                        f"⚠️ <i>ليست نصيحة مالية.</i>",
                    )
                except Exception:  # noqa: BLE001
                    logging.exception("فشل إرسال تنبيه السعر")
            else:
                remaining.append(a)
        if remaining:
            _price_alerts[key] = remaining
        else:
            del _price_alerts[key]
    _save_alerts()


_load_alerts()
