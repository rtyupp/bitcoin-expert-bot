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


def _alert_text_signal(sig: dict, plan: dict | None = None) -> str:
    """رسالة إشارة استراتيجية الأصل (مع الأهداف إن توفرت الخطة)."""
    icon = "🚀" if sig["direction"] == "long" else "🔻"
    word = "شراء" if sig["direction"] == "long" else "بيع"
    lines = [
        f"{icon} <b>صيدة {sig['name']} — {word}</b>",
        "",
        f"🎯 الاستراتيجية: <b>{sig['strategy']}</b>",
        f"📌 {sig['label']}",
        f"💰 السعر: <b>${sig['price']:,.2f}</b>",
    ]
    fe = (plan or {}).get("first_entry")
    if plan and fe and plan.get("stop_loss") and plan.get("tp1"):
        lines += [
            f"📍 الدخول: <code>${fe['price']:,.2f}</code>",
            f"🛑 الوقف: <code>${plan['stop_loss']:,.2f}</code>",
        ]
        if plan.get("tp_be"):
            lines.append(f"🔒 تأمين الوقف (1:1): <code>${plan['tp_be']:,.2f}</code>")
        lines.append(f"🎯 الهدف الكامل: <code>${plan['tp1']:,.2f}</code> (1:{plan.get('rr', 0):.0f})")
    lines += [
        f"📈 الفريم: {sig['timeframe']} | قوة الإشارة: <code>{sig['strength']:+.1f}</code>",
        f"🏦 المنصة: <code>{sig['exchange']}</code>",
        "",
        ("📊 الأهداف مرسومة على الشارت 👆 — ويصلك تنبيه فور وصول الهدف"
         if plan and plan.get("tp1") else "📊 الشارت مبني على البيانات الحية"),
        "للتفاصيل: اضغط 🕯️ الشارت أو 🛡 خطة الصفقة",
        "⚠️ <i>ليست نصيحة مالية.</i>",
    ]
    return "\n".join(lines)


def _build_chart_package(asset_key: str, sig: dict) -> tuple[dict, bytes]:
    """خطة الصفقة + شارت — الخطة تُحسب من شمعة وفريم الإشارة نفسها (1h)
    حتى يتطابق الشارت والرسالة والأهداف دائماً مع الإشارة اللي أطلقت التنبيه."""
    import charts
    import markets as _markets

    cfg = assets.get(asset_key)
    tf = sig.get("timeframe", "1h")
    df, _ = _markets.fetch_ohlcv(cfg["symbol"], tf, 120)
    plan = charts.analyze_chart(df, asset_key)

    import analysis as _analysis

    n = len(df)
    si = n - 2 if n >= 2 else 0  # شمعة الإشارة = آخر شمعة مغلقة
    atr = float(sig.get("atr") or _analysis.indicators(df)["atr"].iloc[si])
    entry = float(sig.get("price") or df["close"].iloc[si])
    d = 1 if sig.get("direction", "long") == "long" else -1
    sd = atr * cfg["stop_mult"]
    plan = {
        **plan,
        "direction": "buy" if d == 1 else "sell",
        "first_entry": {"idx": si, "price": entry, "ts": df["ts"].iloc[si]},
        "second_entry": None,
        "stop_loss": entry - d * sd,
        "tp_be": entry + d * 1.0 * sd,
        "tp1": entry + d * cfg["rr"] * sd,
        "strength": sig["strength"],
    }
    try:
        live = _markets.ticker(cfg["symbol"])[0]
    except Exception:  # noqa: BLE001
        live = entry
    png = charts.plot_chart(df, plan, cfg["symbol"], live_price=live)
    return plan, png


async def check_and_alert(bot, target: int | None = None) -> dict:
    """يفحص إشارة الاستراتيجية لكل أصل ويرسل تنبيهاً عند تحققها (فقط إذا لا توجد صيدة مفتوحة لنفس الأصل)."""
    target = target or config.ADMIN_CHAT_ID
    if target is None:
        return {"sent": False, "reason": "no_chat_id"}

    out: dict[str, dict] = {}
    for key in assets.keys():
        # 1) منع إرسال صيدة جديدة إذا كان هناك صيدة مفتوحة في _watch
        if key in _watch:
            out[key] = {"sent": False, "reason": "active_watch_in_progress"}
            continue
        # 2) فحص Capital.com مباشرة: إذا كانت هناك صفقة مفتوحة على نفس الأصل، نسجلها في _watch ولا نرسل صيدة جديدة
        try:
            import capital_trader

            if capital_trader.is_configured():
                open_pos = await asyncio.to_thread(capital_trader.has_open_position, key)
                if open_pos:
                    out[key] = {"sent": False, "reason": "capital_position_already_open"}
                    continue
        except Exception:  # noqa: BLE001
            pass
        try:
            sig = await asyncio.to_thread(analysis.breakout_signal, "1h", key)
        except Exception as e:  # noqa: BLE001
            out[key] = {"sent": False, "reason": f"fetch_failed: {type(e).__name__}"}
            continue
        if not sig:
            out[key] = {"sent": False, "reason": "no_signal"}
            continue
        now = time.time()
        # 3) منع إعادة إرسال نفس شمعة الإشارة أو خلال فترة التهدئة (4 ساعات = 240 دقيقة كحد أدنى بين صيدتين لنفس الأصل)
        cooldown_sec = max(config.SIGNAL_COOLDOWN_MIN, 240) * 60
        if now - _read_last(key) < cooldown_sec:
            out[key] = {"sent": False, "reason": "cooldown"}
            continue
        # الشارت + الخطة (الدخول/الوقف/الهدف مرسومة على الشارت)
        plan: dict | None = None
        png: bytes | None = None
        try:
            plan, png = await asyncio.to_thread(_build_chart_package, key, sig)
        except Exception:  # noqa: BLE001
            logging.exception("تعذّر بناء شارت الإشارة لـ %s", key)
        text = _alert_text_signal(sig, plan)
        # تنفيذ تلقائي على حساب Capital.com التجريبي إذا كان مفعلاً
        cap_deal = None
        if config.CAPITAL_AUTO_TRADE:
            try:
                import capital_trader

                if capital_trader.is_configured():
                    cap_deal = await asyncio.to_thread(
                        capital_trader.open_trade,
                        key,
                        sig["direction"],
                        None,
                        (plan or {}).get("stop_loss"),
                        (plan or {}).get("tp1"),
                    )
                    if cap_deal and cap_deal.get("ok"):
                        text += (
                            f"\n\n💼 <b>تم فتح الصفقة تلقائياً في Capital.com (Demo):</b>\n"
                            f"• الرمز: <code>{cap_deal['epic']}</code> ({cap_deal['direction']}) | الحجم: <code>{cap_deal['size']}</code>\n"
                            f"• تنفيذ الدخول: <code>${cap_deal['level']:,.2f}</code>"
                        )
            except Exception as cap_err:  # noqa: BLE001
                logging.exception("تعذّر فتح الصفقة تلقائياً على Capital.com لـ %s: %s", key, cap_err)
        try:
            if png:
                from aiogram.types import BufferedInputFile

                await bot.send_photo(
                    target,
                    photo=BufferedInputFile(png, filename=f"signal_{key}.png"),
                    caption=text,
                    parse_mode="HTML",
                )
            else:
                await bot.send_message(target, text, parse_mode="HTML")
            _write_last(key, now)  # بعد نجاح الإرسال فقط — الفشل لا يحرق التهدئة
            # سجّل الأهداف للمتابعة حتى تتحقق
            _register_watch(key, sig, plan, target, cap_deal=cap_deal)
            out[key] = {"sent": True, "label": sig["label"], "chart": bool(png), "capital": bool(cap_deal)}
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
        try:
            await check_signal_targets(bot)
        except Exception:  # noqa: BLE001
            logging.exception("خطأ في فحص أهداف الصيدات")
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


def _atomic_write(path: str, data: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(data)
    os.replace(tmp, path)


def _save_alerts() -> None:
    try:
        _atomic_write(PRICE_ALERTS_FILE, json.dumps(_price_alerts, ensure_ascii=False))
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


# ── متابعة أهداف الصيدات (تنبيه عند وصول الهدف أو الوقف) ────────

WATCH_FILE = os.path.join(_HERE, "signal_watch.json")
_watch: dict[str, dict] = {}


def _load_watch() -> None:
    global _watch
    try:
        with open(WATCH_FILE, "r", encoding="utf-8") as f:
            _watch = json.load(f)
    except Exception:  # noqa: BLE001
        _watch = {}


def _save_watch() -> None:
    try:
        _atomic_write(WATCH_FILE, json.dumps(_watch, ensure_ascii=False))
    except Exception:  # noqa: BLE001
        logging.exception("تعذّر حفظ متابعة الأهداف")


def _register_watch(
    asset_key: str, sig: dict, plan: dict | None, chat_id: int, cap_deal: dict | None = None
) -> None:
    """يسجّل أهداف الصيدة الحالية لمتابعتها حتى تتحقق (مع هدف التأمين 1R والهدف الكامل ورقم صفقة Capital)."""
    fe = (plan or {}).get("first_entry") or {}
    entry = float(fe.get("price") or sig["price"])
    tp1 = (plan or {}).get("tp1")
    if not tp1:
        return
    direction = sig.get("direction", "long")
    if direction == "long" and sig["price"] >= float(tp1):
        return
    if direction != "long" and sig["price"] <= float(tp1):
        return
    stop = (plan or {}).get("stop_loss")
    tp_be = (plan or {}).get("tp_be")
    _watch[asset_key] = {
        "direction": direction,
        "entry": entry,
        "tp_be": float(tp_be) if tp_be else None,
        "be_locked": False,
        "tp1": float(tp1),
        "stop": float(stop) if stop else None,
        "capital_deal_id": (cap_deal or {}).get("dealId"),
        "opened_ts": time.time(),
        "chat_ids": [int(chat_id)],
    }
    _save_watch()


def _hit_chart_sync(asset_key: str, price: float, watch: dict) -> bytes | None:
    """شارت لحظة تحقق الهدف — بمستويات الصيدة المراقَبة نفسها (لا إشارة معاد حسابها)."""
    try:
        import charts

        cfg = assets.get(asset_key)
        df = charts.fetch_4h(cfg["symbol"], days=20)
        n = len(df)
        d = 1 if watch.get("direction", "long") == "long" else -1
        plan = {
            "asset": asset_key,
            "asset_name": cfg["name"],
            "strategy": cfg["strategy_name"],
            "strategy_en": cfg["strategy_en"],
            "rr": cfg["rr"],
            "current_price": float(df["close"].iloc[-1]),
            "current_ts": df["ts"].iloc[-1],
            "first_entry": {"idx": n - 1, "price": watch["entry"], "ts": df["ts"].iloc[-1]},
            "second_entry": None,
            "stop_loss": watch.get("stop"),
            "tp1": watch["tp1"],
            "direction": "buy" if d == 1 else "sell",
            "signal_age_hours": 0,
            "strength": 0.0,
        }
        return charts.plot_chart(df, plan, cfg["symbol"], live_price=price)
    except Exception:  # noqa: BLE001
        logging.exception("تعذّر بناء شارت تحقق الهدف لـ %s", asset_key)
        return None


async def check_signal_targets(bot) -> int:
    """يفحص الصيدات المفتوحة: تأمين الوقف عند 1R (Break-Even)، أو وصول الهدف الكامل، أو ضرب الوقف."""
    if not _watch:
        return 0
    fired = 0
    for key, w in list(_watch.items()):
        try:
            price, _, _ = await asyncio.to_thread(analysis.ticker, assets.get(key)["symbol"])
        except Exception:  # noqa: BLE001
            continue
        direction = w.get("direction", "long")
        tp_be = w.get("tp_be")
        be_locked = bool(w.get("be_locked"))
        name = assets.get(key)["name"]

        # 1) فحص وصول الهدف الأول (1R) لتأمين الوقف على الدخول (Break-Even)
        if tp_be and not be_locked:
            reached_be = (direction == "long" and price >= tp_be) or (direction != "long" and price <= tp_be)
            if reached_be and ((direction == "long" and price < w["tp1"]) or (direction != "long" and price > w["tp1"])):
                w["be_locked"] = True
                w["stop"] = w["entry"]
                _save_watch()
                cap_moved = 0
                try:
                    import capital_trader

                    if capital_trader.is_configured():
                        cap_moved = await asyncio.to_thread(
                            capital_trader.move_stop_to_breakeven, key, w["entry"]
                        )
                except Exception:  # noqa: BLE001
                    logging.exception("تعذّر نقل الوقف في Capital.com لـ %s", key)
                cap_note = "\n💼 <b>Capital.com:</b> تم تعديل الوقف إلى نقطة الدخول في حسابك التجريبي ✅" if cap_moved else ""
                be_text = (
                    f"🔒 <b>تأمين الصيدة (1:1) — {name}!</b>\n\n"
                    f"📍 الدخول: <code>${w['entry']:,.2f}</code>\n"
                    f"✅ وصل الهدف الأول: <code>${tp_be:,.2f}</code>\n"
                    f"💰 السعر الآن: <b>${price:,.2f}</b>\n\n"
                    f"🛡 <b>تم نقل الوقف لنقطة الدخول (${w['entry']:,.2f}) تلقائياً — الصفقة الآن بدون مخاطرة والهدف القادم ${w['tp1']:,.2f} 🎯</b>"
                    f"{cap_note}"
                )
                for chat_id in w.get("chat_ids", []):
                    try:
                        await bot.send_message(int(chat_id), be_text, parse_mode="HTML")
                    except Exception:  # noqa: BLE001
                        logging.exception("فشل إرسال تنبيه التأمين %s", key)
                continue

        # 2) فحص الهدف الكامل أو الوقف
        if direction == "long":
            hit = "tp" if price >= w["tp1"] else ("sl" if w.get("stop") and price <= w["stop"] else None)
        else:
            hit = "tp" if price <= w["tp1"] else ("sl" if w.get("stop") and price >= w["stop"] else None)
        if not hit:
            continue
        if hit == "tp":
            head = f"🎯 <b>الهدف الكامل تحقق — {name}!</b>"
            body = (
                f"📍 الدخول: <code>${w['entry']:,.2f}</code>\n"
                f"🎯 الهدف: <code>${w['tp1']:,.2f}</code>\n"
                f"💰 السعر الآن: <b>${price:,.2f}</b>\n\n"
                f"✅ الصيدة وصلت هدفها الكامل — شوف الشارت 👆"
            )
        elif w.get("be_locked"):
            head = f"🛡 <b>خروج على الدخول بعد ربح الهدف الأول — {name}</b>"
            body = (
                f"📍 الدخول (الوقف المؤمّن): <code>${w['entry']:,.2f}</code>\n"
                f"✅ الهدف الأول المحقق سابقاً: <code>${tp_be:,.2f}</code>\n"
                f"💰 السعر الآن: <b>${price:,.2f}</b>\n\n"
                f"🔒 انتهت الصيدة بأمان بدون أي خسارة بعد تأمين الهدف الأول."
            )
        else:
            head = f"🛑 <b>ضرب الوقف — {name}</b>"
            body = (
                f"📍 الدخول: <code>${w['entry']:,.2f}</code>\n"
                f"🛑 الوقف: <code>${w['stop']:,.2f}</code>\n"
                f"💰 السعر الآن: <b>${price:,.2f}</b>\n\n"
                f"⚠️ اخرج من الصيدة واحترم إدارة المخاطر."
            )
        text = f"{head}\n\n{body}\n\n⚠️ <i>ليست نصيحة مالية.</i>"
        png = await asyncio.to_thread(_hit_chart_sync, key, price, w)
        delivered = False
        for chat_id in w.get("chat_ids", []):
            try:
                if png:
                    from aiogram.types import BufferedInputFile

                    await bot.send_photo(
                        int(chat_id),
                        photo=BufferedInputFile(png, filename=f"{key}_hit.png"),
                        caption=text,
                        parse_mode="HTML",
                    )
                else:
                    await bot.send_message(int(chat_id), text, parse_mode="HTML")
                delivered = True
            except Exception:  # noqa: BLE001
                logging.exception("فشل إرسال تنبيه هدف %s", key)
        # نحذف المراقبة فقط إذا وصل التنبيه فعلاً — وإلا يعاد المحاولة بالدورة القادمة
        if delivered:
            fired += 1
            _watch.pop(key, None)
            _save_watch()
            logging.info("هدف صيدة %s تحقق (%s) — أُرسل التنبيه", key, hit)
    return fired


_load_alerts()
_load_watch()
