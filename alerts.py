"""تنبيه الصيدة (حسب استراتيجية كل أصل) + تنبيهات السعر — متعدد الأصول."""
import asyncio
import json
import logging
import os
import time

import analysis
import assets
import config

_HERE = os.path.dirname(__file__)


def _state_path(asset: str) -> str:
    return os.path.join(_HERE, f"last_alert_{asset}.txt")


def _read_last(asset: str) -> float:
    try:
        with open(_state_path(asset), "r", encoding="utf-8") as f:
            return float(f.read().strip())
    except Exception:  # noqa: BLE001
        return 0.0


def _write_last(asset: str, ts: float) -> None:
    try:
        with open(_state_path(asset), "w", encoding="utf-8") as f:
            f.write(str(ts))
    except Exception:  # noqa: BLE001
        logging.exception("تعذّر حفظ توقيت آخر تنبيه")


def _alert_text_signal(sig: dict) -> str:
    """رسالة إشارة استراتيجية الأصل."""
    icon = "🚀" if sig["direction"] == "long" else "🔻"
    word = "شراء" if sig["direction"] == "long" else "بيع"
    return (
        f"{icon} <b>صيدة {sig['name']} — {word}</b>\n\n"
        f"🎯 الاستراتيجية: <b>{sig['strategy']}</b>\n"
        f"📌 {sig['label']}\n"
        f"💰 السعر: <b>${sig['price']:,.2f}</b>\n"
        f"📈 الفريم: {sig['timeframe']} | قوة الإشارة: <code>{sig['strength']:+.1f}</code>\n"
        f"🏦 المنصة: <code>{sig['exchange']}</code>\n\n"
        f"للتفاصيل: اضغط 🕯️ الشارت أو 🛡 خطة الصفقة\n"
        f"⚠️ <i>ليست نصيحة مالية.</i>"
    )


async def check_and_alert(bot, target: int | None = None) -> dict:
    """يفحص إشارة الاستراتيجية لكل أصل ويرسل تنبيهاً عند تحققها."""
    target = target or config.ADMIN_CHAT_ID
    if target is None:
        return {"sent": False, "reason": "no_chat_id"}

    out: dict[str, dict] = {}
    for key in assets.keys():
        try:
            sig = await asyncio.to_thread(analysis.breakout_signal, "4h", key)
        except Exception as e:  # noqa: BLE001
            out[key] = {"sent": False, "reason": f"fetch_failed: {type(e).__name__}"}
            continue
        if not sig:
            out[key] = {"sent": False, "reason": "no_signal"}
            continue
        now = time.time()
        if now - _read_last(key) < config.SIGNAL_COOLDOWN_MIN * 60:
            out[key] = {"sent": False, "reason": "cooldown"}
            continue
        _write_last(key, now)
        try:
            await bot.send_message(target, _alert_text_signal(sig), parse_mode="HTML")
            out[key] = {"sent": True, "label": sig["label"]}
        except Exception as e:  # noqa: BLE001
            out[key] = {"sent": False, "reason": f"send_failed: {e}"}
    return {"assets": out}


async def watcher_loop(bot) -> None:
    """مراقبة مستمرة (وضع polling على خادم دائم)."""
    logging.info(
        "مراقبة الصيد بدأت — كل %ds، الأصول: %s",
        config.SIGNAL_INTERVAL_SEC,
        ", ".join(assets.keys()),
    )
    while True:
        try:
            res = await check_and_alert(bot)
            sent = [k for k, v in res.get("assets", {}).items() if v.get("sent")]
            if sent:
                logging.info("أُرسل تنبيه لـ: %s", ", ".join(sent))
        except Exception:  # noqa: BLE001
            logging.exception("خطأ في مراقبة الصيد")
        try:
            await check_price_alerts(bot)
        except Exception:  # noqa: BLE001
            logging.exception("خطأ في فحص أهداف السعر")
        await asyncio.sleep(config.SIGNAL_INTERVAL_SEC)


# ── تنبيهات السعر المستهدفة ────────────────────────────────────

PRICE_ALERTS_FILE = os.path.join(_HERE, "price_alerts.json")
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


def set_alert(chat_id: int, price: float, direction: str, asset: str = "btc") -> None:
    key = str(chat_id)
    _price_alerts.setdefault(key, []).append(
        {"price": price, "direction": direction, "asset": asset}
    )
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
    """يفحص أهداف السعر لكل أصل ويرسل تنبيهاً عند الوصول."""
    if not _price_alerts:
        return
    prices: dict[str, float] = {}
    for key in list(_price_alerts.keys()):
        remaining = []
        for a in _price_alerts[key]:
            asset = a.get("asset", "btc")
            if asset not in prices:
                try:
                    p, _, _ = await asyncio.to_thread(analysis.ticker, assets.get(asset)["symbol"])
                    prices[asset] = p
                except Exception:  # noqa: BLE001
                    prices[asset] = -1.0
            price = prices[asset]
            if price <= 0:
                remaining.append(a)
                continue
            fired = (a["direction"] == "up" and price >= a["price"]) or (
                a["direction"] == "down" and price <= a["price"]
            )
            if fired:
                name = assets.get(asset)["name"]
                try:
                    await bot.send_message(
                        int(key),
                        f"⏰ <b>وصل {name} لهدفك!</b>\n\n"
                        f"💰 السعر الآن: <b>${price:,.2f}</b>\n"
                        f"🎯 الهدف: <code>${a['price']:,.2f}</code>\n\n"
                        f"⚠️ <i>ليست نصيحة مالية.</i>",
                        parse_mode="HTML",
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
