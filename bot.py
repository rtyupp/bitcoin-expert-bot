"""Multi-Asset Telegram Bot (GBP/USD, Gold, Silver) with Capital.com Integration."""
from __future__ import annotations

import json
import logging
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

import requests

import capital
import charts
import config
import engine
import state
import strategy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("multiasset-bot")

TG_API = f"https://api.telegram.org/bot{config.BOT_TOKEN}"
_RUNNING = True


def send_message(chat_id: int | str, text: str, reply_markup: dict | None = None) -> bool:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post(f"{TG_API}/sendMessage", json=payload, timeout=12)
        return bool(r.json().get("ok", False))
    except Exception as e:
        log.warning("send_message failed: %s", e)
        return False


def send_photo(chat_id: int | str, photo_bytes: bytes, caption: str, reply_markup: dict | None = None) -> bool:
    data = {"chat_id": str(chat_id), "caption": caption, "parse_mode": "HTML"}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    files = {"photo": ("chart.png", photo_bytes, "image/png")}
    try:
        r = requests.post(f"{TG_API}/sendPhoto", data=data, files=files, timeout=25)
        return bool(r.json().get("ok", False))
    except Exception as e:
        log.warning("send_photo failed: %s", e)
        return False


def main_keyboard(is_admin: bool = False) -> dict:
    rows = [
        [
            {"text": "📊 GBP/USD", "callback_data": "cmd_analysis_GBPUSD"},
            {"text": "🥇 Gold", "callback_data": "cmd_analysis_GOLD"},
            {"text": "🥈 Silver", "callback_data": "cmd_analysis_SILVER"},
        ],
        [
            {"text": "₿ Bitcoin", "callback_data": "cmd_analysis_BTCUSD"},
            {"text": "Ξ Ethereum", "callback_data": "cmd_analysis_ETHUSD"},
            {"text": "🇺🇸 US500", "callback_data": "cmd_analysis_US500"},
        ],
        [
            {"text": "🎯 الصفقات النشطة", "callback_data": "cmd_signals"},
            {"text": "💼 حساب Capital", "callback_data": "cmd_capital"},
        ],
        [
            {"text": "📈 شارت GBPUSD", "callback_data": "cmd_chart_GBPUSD"},
            {"text": "📈 شارت Gold", "callback_data": "cmd_chart_GOLD"},
            {"text": "📈 شارت Silver", "callback_data": "cmd_chart_SILVER"},
        ],
        [
            {"text": "📈 شارت BTC", "callback_data": "cmd_chart_BTCUSD"},
            {"text": "📈 شارت ETH", "callback_data": "cmd_chart_ETHUSD"},
            {"text": "📈 شارت US500", "callback_data": "cmd_chart_US500"},
        ],
    ]
    if is_admin:
        rows.append([
            {"text": "⚙️ التداول الآلي", "callback_data": "cmd_autotrade"},
            {"text": "🧪 فحص ذاتي", "callback_data": "cmd_selftest"},
        ])
    else:
        rows.append([{"text": "📖 المساعدة", "callback_data": "cmd_help"}])
    return {"inline_keyboard": rows}


def format_asset_summary(summary: dict) -> str:
    if "error" in summary:
        return f"❌ {summary['error']}"

    asset = summary["asset"]
    epic = summary["epic"]
    price = summary["price"]
    regime = summary["regime"]
    atr = summary["atr"]
    adx = summary.get("adx", 0)
    er = summary.get("er", 0)
    strat = summary["strategy"]

    regime_map = {
        "TRENDING_UP": "📈 ترند صاعد قوي",
        "TRENDING_DOWN": "📉 ترند هابط قوي",
        "RANGING": "📊 نطاقي تذبذبي",
        "CHOPPY": "⚡ تذبذب عشوائي (Chop)",
        "UNKNOWN": "❓ غير محدد",
    }
    regime_ar = regime_map.get(regime, regime)
    decimals = config.ASSETS[epic]["decimals"]
    tf = config.ASSETS[epic].get("timeframe", "4h").upper()

    lines = [
        f"🏛 <b>{asset} ({epic}) — إطار {tf}</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"💵 <b>السعر اللحظي:</b> <code>{price:,.{decimals}f}</code>",
        f"🧭 <b>حالة السوق:</b> {regime_ar}",
        f"📊 <b>ADX:</b> {adx:.1f} | <b>ER:</b> {er:.3f} | <b>ATR:</b> {atr:,.{decimals}f}",
        f"🎯 <b>الاستراتيجية:</b> {strat}",
        "",
    ]

    if strat == "donchian20_vol15":
        lines.extend([
            f"📈 <b>قناة دونشيان 20:</b>",
            f"  • سقف القناة: <code>{summary.get('dc_upper', 0):,.5f}</code>",
            f"  • قاع القناة: <code>{summary.get('dc_lower', 0):,.5f}</code>",
            f"  • نسبة الحجم: <code>{summary.get('vol_ratio', 0):.2f}x</code> (المطلوب > 1.50x)",
        ])
    elif strat == "macd_ema200":
        lines.extend([
            f"📈 <b>مؤشر MACD:</b>",
            f"  • خط MACD: <code>{summary.get('macd', 0):.5f}</code>",
            f"  • خط الإشارة: <code>{summary.get('signal', 0):.5f}</code>",
            f"  • الهيستوغرام: <code>{summary.get('histogram', 0):.5f}</code>",
            f"  • متوسط EMA200: <code>{summary.get('ema200', 0):,.{decimals}f}</code>",
        ])
    elif strat == "bb_rsi_reversion":
        lines.extend([
            f"📈 <b>مؤشر البولينجر والارتداد (BB 2.5 + RSI):</b>",
            f"  • الحد العلوي: <code>{summary.get('bb_upper', 0):,.{decimals}f}</code>",
            f"  • الحد السفلي: <code>{summary.get('bb_lower', 0):,.{decimals}f}</code>",
            f"  • مؤشر RSI(14): <code>{summary.get('rsi', 0):.1f}</code>",
        ])
    elif strat == "smc_liquidity_sweep":
        lines.extend([
            f"📈 <b>سحب السيولة المؤسسي (SMC 20-Bar Sweep):</b>",
            f"  • قمة السيولة (20 شمعة): <code>{summary.get('hi20', 0):,.{decimals}f}</code>",
            f"  • قاع السيولة (20 شمعة): <code>{summary.get('lo20', 0):,.{decimals}f}</code>",
            f"  • متوسط EMA200: <code>{summary.get('ema200', 0):,.{decimals}f}</code>",
        ])

    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("<i>إشارات مؤكدة فقط على الشمعة المغلقة.</i>")
    return "\n".join(lines)


def format_signal_message(sig: strategy.AssetSignal, asset_cfg: dict) -> str:
    direction_ar = "شراء (LONG) 🟢" if sig.side == 1 else "بيع (SHORT) 🔴"
    side_icon = "🟢" if sig.side == 1 else "🔴"
    decimals = asset_cfg["decimals"]

    lines = [
        f"🚨 <b>إشارة مؤسسية جديدة — {asset_cfg['name']}</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"{side_icon} <b>الاتجاه:</b> {direction_ar}",
        f"🎯 <b>الاستراتيجية:</b> {sig.spec_id}",
        f"💵 <b>سعر الدخول:</b> <code>{sig.price:,.{decimals}f}</code>",
        f"🛑 <b>وقف الخسارة:</b> <code>{sig.stop_level:,.{decimals}f}</code>",
        f"🎯 <b>الهدف (1:{asset_cfg['rr']:.0f}):</b> <code>{sig.target_level:,.{decimals}f}</code>",
        f"⏰ <b>وقت الشمعة:</b> {sig.time}",
        "",
        "<b>الأسباب الفنية:</b>",
    ]
    for r in sig.reasons:
        lines.append(f"  • {r}")

    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("<i>تأمين الوقف التلقائي إلى نقطة الدخول عند تحقيق +1.0R.</i>")
    return "\n".join(lines)


def format_capital_message(acc: dict) -> str:
    lines = [
        f"💼 <b>حساب Capital.com ({config.CAPITAL_ENV.upper()})</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"🆔 <b>رقم الحساب:</b> <code>{acc.get('accountId', '—')}</code>",
        f"💵 <b>الرصيد الإجمالي:</b> <code>${acc.get('balance', 0):,.2f}</code>",
        f"📊 <b>الربح/الخسارة اللحظية:</b> <code>${acc.get('profitLoss', 0):+,.2f}</code>",
        f"🟢 <b>الرصيد المتاح:</b> <code>${acc.get('available', 0):,.2f}</code>",
        f"🔒 <b>الهامش المحجوز:</b> <code>${acc.get('deposit', 0):,.2f}</code>",
        "",
    ]
    positions = acc.get("positions") or []
    if positions:
        lines.append(f"<b>الصفقات المفتوحة ({len(positions)}):</b>")
        for p in positions:
            side_icon = "🟢 BUY" if p.get("direction") == "BUY" else "🔴 SELL"
            upl = p.get("upl", 0.0)
            lines.append(
                f"• {side_icon} <b>{p.get('name', p.get('epic'))}</b> | الحجم: {p.get('size')}\n"
                f"   دخول: <code>{p.get('level')}</code> | PnL: <code>${upl:+,.2f}</code>\n"
                f"   الوقف: <code>{p.get('stopLevel')}</code> | الهدف: <code>{p.get('profitLevel')}</code>"
            )
    else:
        lines.append("<i>لا توجد صفقات مفتوحة حالياً.</i>")
    return "\n".join(lines)


def handle_message(msg: dict, st: dict) -> None:
    chat_id = msg.get("chat", {}).get("id")
    user_id = msg.get("from", {}).get("id") or chat_id
    text = (msg.get("text") or "").strip()
    if not chat_id or not text:
        return

    is_admin = bool(user_id and user_id == config.ADMIN_CHAT_ID)
    raw_cmd = text.split()[0].lower()
    cmd = raw_cmd.split("@")[0]

    if cmd in ("/start", "ابدأ"):
        intro = (
            "🏛 <b>بوت التداول والمضاربة المؤسسي متعدد الأصول</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "نظام متكامل مبني على نتائج الباكتست الحقيقي على حساب Capital.com:\n\n"
            "1️⃣ <b>GBP/USD [4H]:</b> كسر دونشيان 20 + الحجم (PF 4.20 | Win 73%)\n"
            "2️⃣ <b>Gold الذهب [4H]:</b> تقاطع MACD + EMA200 (PF 2.49 | Win 65%)\n"
            "3️⃣ <b>Silver الفضة [4H]:</b> تقاطع MACD + EMA200 (PF 2.76 | Win 60%)\n"
            "4️⃣ <b>US500 إس آند بي [1H]:</b> سحب السيولة SMC Sweep (PF 5.00 | Win 67%)\n"
            "5️⃣ <b>Bitcoin بيتكوين [4H]:</b> ارتداد بولينجر 2.5 + RSI (PF 4.00 | Win 55%)\n"
            "6️⃣ <b>Ethereum إيثيريوم [4H]:</b> ارتداد بولينجر 2.5 + RSI (PF 2.25 | Win 43%)\n\n"
            "⚡ <b>ميزات الأمان:</b> تأمين الوقف التلقائي عند +1.0R، وتحجيم مركب ذكي.\n"
            "اختر من الأزرار التفاعلية بالأسفل 👇"
        )
        send_message(chat_id, intro, reply_markup=main_keyboard(is_admin))

    elif cmd in ("/analysis", "/التحليل"):
        parts = text.split()
        asset = parts[1].upper() if len(parts) > 1 else "GBPUSD"
        if asset not in config.ASSETS:
            send_message(chat_id, f"الأصول المتاحة: {', '.join(config.ASSETS.keys())}")
            return
        try:
            cfg = config.ASSETS[asset]
            tf = cfg.get("timeframe", "4h")
            df = capital.client.fetch_ohlcv(cfg["epic"], tf, 300)
            summary = strategy.get_asset_summary(df, cfg)
            send_message(chat_id, format_asset_summary(summary))
        except Exception as e:
            send_message(chat_id, f"❌ خطأ في التحليل: {e}")

    elif cmd in ("/signals", "/الصفقات"):
        active = state.get_active_trades(st)
        if not active:
            send_message(chat_id, "📭 لا توجد صفقات أو إشارات نشطة حالياً.")
            return
        lines = ["🎯 <b>الصفقات والإشارات المسجلة:</b>\n"]
        for spec_id, tr in active.items():
            if tr.get("closed"):
                continue
            icon = "🟢" if tr.get("direction") == "BUY" else "🔴"
            lines.append(
                f"{icon} <b>{tr.get('strat_name', spec_id)}</b> ({tr.get('asset')})\n"
                f"• الدخول: <code>{tr.get('entry', tr.get('level'))}</code>\n"
                f"• الوقف: <code>{tr.get('stop_level', tr.get('stopLevel'))}</code>\n"
                f"• الهدف: <code>{tr.get('target_level', tr.get('profitLevel'))}</code>\n"
                f"• الحجم: {tr.get('size')} | تأمين الدخول: {'مفعّل ✅' if tr.get('moved_be') else 'قيد الانتظار ⏳'}\n"
            )
        send_message(chat_id, "\n".join(lines))

    elif cmd in ("/chart", "/الشارت"):
        parts = text.split()
        asset = parts[1].upper() if len(parts) > 1 else "GBPUSD"
        if asset not in config.ASSETS:
            send_message(chat_id, f"الأصول المتاحة للشارت: {', '.join(config.ASSETS.keys())}")
            return
        try:
            cfg = config.ASSETS[asset]
            tf = cfg.get("timeframe", "4h")
            df = capital.client.fetch_ohlcv(cfg["epic"], tf, 80)
            summary = strategy.get_asset_summary(df, cfg)
            chart_bytes = charts.render_asset_chart(asset, df, summary)
            caption = f"📈 <b>شارت {cfg['name']} ({tf.upper()})</b>\nالسعر: <code>{summary.get('price')}</code> | النظام: {summary.get('regime')}"
            send_photo(chat_id, chart_bytes, caption)
        except Exception as e:
            send_message(chat_id, f"❌ خطأ أثناء توليد الشارت: {e}")

    elif cmd in ("/capital", "/الحساب"):
        if not is_admin:
            send_message(chat_id, "🔒 هذا الأمر مخصص للمسؤول فقط.")
            return
        try:
            acc = capital.client.account_summary()
            send_message(chat_id, format_capital_message(acc))
        except Exception as e:
            send_message(chat_id, f"❌ تعذر جلب بيانات الحساب: {e}")

    elif cmd in ("/autotrade", "/التداول_التلقائي"):
        if not is_admin:
            send_message(chat_id, "🔒 هذا الأمر مخصص للمسؤول فقط.")
            return
        parts = text.split()
        if len(parts) > 1:
            val = parts[1].lower() in ("on", "1", "true", "تفعيل", "نعم")
            state.set_auto_trade(st, val)
            send_message(chat_id, f"⚙️ وضع التداول الآلي أصبح: <b>{'مفعّل 🟢' if val else 'معطل 🔴'}</b>")
        else:
            cur = "مفعّل 🟢" if state.is_auto_trade(st) else "معطل 🔴"
            send_message(chat_id, f"وضع التداول الآلي الحالي: <b>{cur}</b>\nللتبديل: <code>/autotrade on</code> أو <code>/autotrade off</code>")

    elif cmd in ("/risk", "/المخاطرة"):
        if not is_admin:
            send_message(chat_id, "🔒 هذا الأمر مخصص للمسؤول فقط.")
            return
        parts = text.split()
        if len(parts) > 1:
            try:
                pct = float(parts[1])
                if 0.1 <= pct <= 10.0:
                    state.set_risk_pct(st, pct)
                    send_message(chat_id, f"✅ تم تعيين نسبة المخاطرة لكل صفقة إلى: <b>{pct:.1f}%</b>")
                else:
                    send_message(chat_id, "❌ النطاق المسموح به بين 0.1% و 10.0%")
            except ValueError:
                send_message(chat_id, "❌ صيغة غير صحيحة. مثال: <code>/risk 1.5</code>")
        else:
            send_message(chat_id, f"المخاطرة الحالية لكل صفقة: <b>{state.get_risk_pct(st):.1f}%</b>")

    elif cmd in ("/closeall", "/إغلاق"):
        if not is_admin:
            send_message(chat_id, "🔒 هذا الأمر مخصص للمسؤول فقط.")
            return
        try:
            closed = capital.client.close_all()
            send_message(chat_id, f"✅ تم إغلاق <b>{closed}</b> صفقات مفتوحة على الحساب.")
        except Exception as e:
            send_message(chat_id, f"❌ فشل إغلاق الصفقات: {e}")

    elif cmd in ("/selftest", "/فحص"):
        send_message(chat_id, "⏳ جاري فحص كافة الاتصالات ومصادر البيانات...")
        lines = ["🧪 <b>نتائج الفحص الذاتي الشامل:</b>"]
        try:
            for ak, cfg in config.ASSETS.items():
                mkt = capital.client.live_price(cfg["epic"])
                lines.append(f"✅ {ak}: <code>{mkt['price']:,.{cfg['decimals']}f}</code> (سبريد: {mkt['spread']})")
        except Exception as e:
            lines.append(f"❌ الأسعار المباشرة: {e}")

        try:
            for ak, cfg in config.ASSETS.items():
                tf = cfg.get("timeframe", "4h")
                df = capital.client.fetch_ohlcv(cfg["epic"], tf, 50)
                lines.append(f"✅ شموع {ak} ({tf.upper()}): {len(df)} شمعة")
        except Exception as e:
            lines.append(f"❌ الشموع التاريخية: {e}")

        try:
            acc = capital.client.account_summary()
            lines.append(f"✅ حساب Capital: رصيد <code>${acc['balance']:,.2f}</code> | متاح <code>${acc['available']:,.2f}</code>")
        except Exception as e:
            lines.append(f"❌ حساب Capital: {e}")

        send_message(chat_id, "\n".join(lines))

    elif cmd in ("/help", "/مساعدة"):
        h = (
            "📖 <b>دليل أوامر البوت متعدد الأصول:</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "/start — القائمة التفاعلية الرئيسية\n"
            "/analysis [GBPUSD|GOLD|SILVER] — فحص التحليل الفني لأصل معين\n"
            "/signals — كشف الصفقات والإشارات الحالية\n"
            "/chart [GBPUSD|GOLD|SILVER] — رسم شارت 4H مع المؤشرات\n"
            "/capital — كشف رصيد وصفقات حساب Capital (أدمن)\n"
            "/autotrade [on/off] — تفعيل أو إيقاف التداول الآلي (أدمن)\n"
            "/risk [نسبة] — تغيير نسبة المخاطرة لكل صفقة (أدمن)\n"
            "/closeall — إغلاق جميع الصفقات المفتوحة فوراً (أدمن)\n"
            "/selftest — فحص صحة الاتصال بالمنصة وتدفق الأسعار\n"
        )
        send_message(chat_id, h)


def handle_callback(cb: dict, st: dict) -> None:
    cb_id = cb.get("id")
    data = cb.get("data", "")
    msg = cb.get("message", {})
    chat_id = msg.get("chat", {}).get("id")

    try:
        requests.post(f"{TG_API}/answerCallbackQuery", json={"callback_query_id": cb_id}, timeout=6)
    except Exception:
        pass

    cmd_map = {
        "cmd_analysis_GBPUSD": "/analysis GBPUSD",
        "cmd_analysis_GOLD": "/analysis GOLD",
        "cmd_analysis_SILVER": "/analysis SILVER",
        "cmd_analysis_BTCUSD": "/analysis BTCUSD",
        "cmd_analysis_ETHUSD": "/analysis ETHUSD",
        "cmd_analysis_US500": "/analysis US500",
        "cmd_signals": "/signals",
        "cmd_capital": "/capital",
        "cmd_chart_GBPUSD": "/chart GBPUSD",
        "cmd_chart_GOLD": "/chart GOLD",
        "cmd_chart_SILVER": "/chart SILVER",
        "cmd_chart_BTCUSD": "/chart BTCUSD",
        "cmd_chart_ETHUSD": "/chart ETHUSD",
        "cmd_chart_US500": "/chart US500",
        "cmd_autotrade": "/autotrade",
        "cmd_selftest": "/selftest",
        "cmd_help": "/help",
    }
    target = cmd_map.get(data)
    if target and chat_id:
        handle_message({"chat": {"id": chat_id}, "text": target}, st)


def signal_watcher_loop(st: dict) -> None:
    log.info("Signal watcher loop started (interval: %ds, cooldown: %dm)", config.SIGNAL_INTERVAL_SEC, config.SIGNAL_COOLDOWN_MIN)
    target_chat = config.CHANNEL_ID or config.ADMIN_CHAT_ID

    while _RUNNING:
        try:
            actions, logs = engine.evaluate_and_trade(st)
            for log_msg in logs:
                log.info(log_msg)

            if actions and config.BOT_TOKEN and target_chat:
                for act in actions:
                    if act.get("event") == "close":
                        icon = "🟢" if act.get("direction") == "BUY" else "🔴"
                        msg = (
                            f"🚪 <b>إغلاق تلقائي للصفقة</b>\n"
                            f"━━━━━━━━━━━━━━━━━━\n"
                            f"🎯 <b>الاستراتيجية:</b> {act.get('strat_name', act.get('spec_id'))}\n"
                            f"{icon} <b>الاتجاه:</b> {act.get('direction')}\n"
                            f"💰 <b>سعر الدخول:</b> <code>{act.get('entry')}</code>\n"
                            f"🏁 <b>سعر الخروج:</b> <code>{act.get('exit_price')}</code>\n"
                            f"📌 <b>السبب:</b> {act.get('reason')}\n"
                            f"💵 <b>الربح/الخسارة:</b> <b>${act.get('pnl', 0.0):+,.2f}</b>"
                        )
                        send_message(target_chat, msg)
                    else:
                        asset_key = act.get("asset", "")
                        asset_cfg = config.ASSETS.get(asset_key, {})
                        sig_obj = strategy.AssetSignal(
                            asset=asset_key,
                            spec_id=act["spec_id"],
                            side=1 if act["direction"] == "BUY" else -1,
                            price=act["entry"],
                            stop_level=act["stop_level"],
                            target_level=act["target_level"],
                            time=act["time"],
                            reasons=act.get("reasons", []),
                            meta=act.get("meta", {}),
                        )
                        msg = format_signal_message(sig_obj, asset_cfg)
                        if act.get("deal_id"):
                            msg += f"\n\n⚡ <b>تم فتح الصفقة تلقائياً على Capital.com!</b>\nمعرف الصفقة: <code>{act['deal_id']}</code>"
                        send_message(target_chat, msg)

                        try:
                            tf = asset_cfg.get("timeframe", "4h")
                            df = capital.client.fetch_ohlcv(asset_cfg["epic"], tf, 80)
                            summary = strategy.get_asset_summary(df, asset_cfg)
                            chart_bytes = charts.render_asset_chart(asset_key, df, summary)
                            send_photo(target_chat, chart_bytes, f"📊 <b>شارت دخول {asset_cfg['name']} ({tf.upper()})</b>")
                        except Exception as ce:
                            log.warning("Chart send on signal failed: %s", ce)

        except Exception as e:
            log.exception("Signal watcher loop exception: %s", e)

        for _ in range(config.SIGNAL_INTERVAL_SEC):
            if not _RUNNING:
                break
            time.sleep(1)


def main() -> None:
    global _RUNNING
    if not config.BOT_TOKEN:
        log.error("BOT_TOKEN is not configured!")
        sys.exit(1)

    errors = config.validate_config()
    if errors:
        for e in errors:
            log.error("Config validation error: %s", e)
        sys.exit(1)

    st = state.load_state()

    def handle_sig(sig, frame):
        global _RUNNING
        log.info("Signal %s received, shutting down gracefully...", sig)
        _RUNNING = False

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    watcher_th = threading.Thread(target=signal_watcher_loop, args=(st,), daemon=True)
    watcher_th.start()

    log.info("Bot polling loop started...")
    offset = 0

    while _RUNNING:
        try:
            url = f"{TG_API}/getUpdates"
            params = {"offset": offset, "timeout": 15, "allowed_updates": ["message", "callback_query"]}
            resp = requests.get(url, params=params, timeout=20)
            if resp.status_code == 409:
                log.warning("409 Conflict: Another bot instance is polling. Waiting 10s...")
                time.sleep(10)
                continue
            if resp.status_code != 200:
                time.sleep(3)
                continue

            data = resp.json()
            if not data.get("ok"):
                time.sleep(3)
                continue

            for upd in data.get("result", []):
                offset = max(offset, upd["update_id"] + 1)
                if "message" in upd:
                    handle_message(upd["message"], st)
                elif "callback_query" in upd:
                    handle_callback(upd["callback_query"], st)

        except requests.exceptions.RequestException:
            time.sleep(4)
        except Exception as e:
            log.exception("Polling loop error: %s", e)
            time.sleep(3)

    log.info("Bot terminated cleanly.")


if __name__ == "__main__":
    main()
