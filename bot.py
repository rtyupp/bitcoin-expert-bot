"""بوت تيليجرام لإشارات وتداول البيتكوين المؤسسي (Bitcoin Signals & Trading Bot).

نظام مستقل تماماً للبيتكوين مبني على استراتيجيات النخبة من GitHub:
- Donchian 55 Breakout 1D
- SMC Liquidity Sweep 4H
- Jesse Ichimoku Cloud + Bollinger Bands 4H
- ربط كامل مع حساب Capital.com التجريبي لفتح الصفقات وإدارتها.
"""
from __future__ import annotations

import asyncio
import html
import logging
import time

import pandas as pd

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import BufferedInputFile, KeyboardButton, Message, ReplyKeyboardMarkup

import capital_trader
import chart
import config
import engine
import markets
import state
import strategy as S

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("btc-bot")

bot: Bot | None = None
if config.BOT_TOKEN:
    bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

dp = Dispatcher()
router = Router()
dp.include_router(router)

_chart_lock = asyncio.Lock()


def is_owner(chat_id: int) -> bool:
    return not config.ADMIN_CHAT_ID or chat_id == config.ADMIN_CHAT_ID


def main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🪙 حالة البيتكوين"), KeyboardButton(text="🕯️ الشارت")],
            [KeyboardButton(text="🎯 الصفقات النشطة"), KeyboardButton(text="📊 التقرير التاريخي")],
            [KeyboardButton(text="💼 حساب كابيتال"), KeyboardButton(text="⚙️ إعدادات التداول")],
            [KeyboardButton(text="🟢 شراء فوري"), KeyboardButton(text="🔴 بيع فوري")],
            [KeyboardButton(text="❓ المساعدة")],
        ],
        resize_keyboard=True,
        input_field_placeholder="اختر أمراً من القائمة 👇",
    )


# ── الأوامر الأساسية ──────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(m: Message):
    txt = (
        "👑 <b>بوت خبير البيتكوين المؤسسي (Bitcoin Institutional Elite)</b>\n\n"
        "نظام توصيات وتداول آلي معتمد ومختبر إحصائياً على 8 سنوات (2018 - 2026):\n\n"
        "1️⃣ <b>اختراق دونشيان اليومي (A):</b> ركوب الاتجاه الكاسح بعد كسر قمة 55 يوماً (فوز 61%، PF 2.41).\n"
        "2️⃣ <b>قنص السيولة 4 ساعات (C):</b> اصطياد فخاخ الدببة SMC بعد كنس السيولة (فوز 52%، PF 1.87).\n"
        "3️⃣ <b>إيشيموكو وبولينجر 4H (B):</b> أقوى استراتيجية من GitHub (Jesse Cloud Breakout) تحقق أرباحاً هائلة (PF 1.64، صافي +200R، بمعدل 1.2 صفقة أسبوعياً).\n\n"
        "⚡ <b>الميزات:</b>\n"
        "• فحص دوري مستمر للشموع المكتملة وتنبيهات فورية.\n"
        "• تكامل كامل مع حساب Capital.com للتداول الآلي واليدوي.\n"
        "• نظام متوازن لا يستنزف المحفظة في التذبذب العرضي.\n\n"
        "اختر من الأزرار بالأسفل للبدء 👇"
    )
    await m.answer(txt, reply_markup=main_kb())


@router.message(Command("help"))
@router.message(F.text == "❓ المساعدة")
async def cmd_help(m: Message):
    txt = (
        "📖 <b>دليل الأوامر والاستخدام:</b>\n\n"
        "• 🪙 <b>حالة البيتكوين:</b> فحص نظام السوق، سحابة إيشيموكو، والفرص الحالية.\n"
        "• 🕯️ <b>الشارت:</b> رسم شارت 4H يوضح المتوسطات ومستويات الدخول.\n"
        "• 🎯 <b>الصفقات النشطة:</b> متابعة الصفقات المفتوحة ومستويات الوقف والأرباح.\n"
        "• 📊 <b>التقرير التاريخي:</b> إحصائيات الأداء لجميع الاستراتيجيات مجتمعة ومنفصلة.\n"
        "• 💼 <b>حساب كابيتال:</b> الرصيد، الهامش المتاح، والأرباح العائمة.\n"
        "• ⚙️ <b>إعدادات التداول:</b> تفعيل/تعطيل التداول الآلي، ونسبة المخاطرة.\n"
        "• 🟢 <b>شراء فوري</b> / 🔴 <b>بيع فوري:</b> تنفيذ صفقة يدوية فورية على Capital.com.\n\n"
        "الأوامر السريعة: /status, /chart, /positions, /capital, /report, /autotrade"
    )
    await m.answer(txt, reply_markup=main_kb())


# ── حالة السوق والشارت ────────────────────────────────────────

@router.message(Command("status"))
@router.message(F.text == "🪙 حالة البيتكوين")
async def cmd_status(m: Message):
    if bot:
        await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    try:
        h4, d1, src = await asyncio.to_thread(engine.load_data)
        st = await asyncio.to_thread(S.market_state, h4, d1)
        sigs = await asyncio.to_thread(S.latest_signals, h4, d1)
        quote = await asyncio.to_thread(engine.live_quote)
    except Exception as e:
        await m.answer(f"❌ تعذّر جلب حالة السوق: {html.escape(str(e))}")
        return

    txt = [
        "🪙 <b>حالة سوق البيتكوين (BTC/USD)</b>",
        f"💰 السعر الحالي: <b>${quote['bid']:,.2f}</b> ({quote['src'].upper()})",
        f"🌊 نظام السوق: <b>{st['regime']}</b>",
        "",
        "📊 <b>المؤشرات الفنية (4H / Daily):</b>",
        f"• سحابة الإيشيموكو 4H (Span A): <code>${st['ichimoku_span_a']:,.0f}</code>",
        f"• سحابة الإيشيموكو 4H (Span B): <code>${st['ichimoku_span_b']:,.0f}</code>",
        f"• خط وسط البولينجر 4H (SMA20): <code>${st['bb_mid_4h']:,.0f}</code>",
        f"• متوسط EMA50 اليومي: <code>${st['ema50_d']:,.0f}</code>",
        f"• متوسط EMA200 اليومي: <code>${st['ema200_d']:,.0f}</code>",
        f"• قمة 55 يوماً (Donchian): <code>${st['hi55_d']:,.0f}</code> (تبعد <code>{st['dist_hi55_pct']:+.1f}%</code>)",
        f"• تذبذب ATR (4H): <code>${st['atr_4h']:,.0f}</code>",
        "",
    ]

    if sigs:
        txt.append("🚨 <b>إشارات مكتشفة على الشموع الأخيرة:</b>")
        for s in sigs:
            side_str = "🟢 شراء (LONG)" if s.side > 0 else "🔴 بيع (SHORT)"
            txt.append(f"• <b>{s.spec.name}</b>: {side_str}")
            for r in s.reasons:
                txt.append(f"   ▫️ {r}")
    else:
        txt.append("⏸ <i>لا توجد إشارة صيد جديدة مكتملة في هذه الشمعة — النظام يراقب السوق بدقة.</i>")

    await m.answer("\n".join(txt), reply_markup=main_kb())


@router.message(Command("chart"))
@router.message(F.text == "🕯️ الشارت")
async def cmd_chart(m: Message):
    if bot:
        await bot.send_chat_action(m.chat.id, ChatAction.UPLOAD_PHOTO)
    try:
        async with _chart_lock:
            h4, _, _ = await asyncio.to_thread(engine.load_data)
            quote = await asyncio.to_thread(engine.live_quote)
            st_data = state.load()
            active = st_data.get("active", {})
            levels = {}
            title = "BTC/USD 4H Analysis"
            if active:
                k, tr = list(active.items())[0]
                levels = {"entry": tr.get("entry"), "stop": tr.get("stop"), "tp": tr.get("tp")}
                title = f"BTC/USD 4H — {S.SPECS[k].name}"
            png = await asyncio.to_thread(chart.render, h4, title, levels, 90, quote["bid"])

        photo = BufferedInputFile(png, filename="btc_chart.png")
        await m.answer_photo(photo, caption=f"🕯️ <b>شارت البيتكوين 4H</b>\nالسعر: <b>${quote['bid']:,.2f}</b>", reply_markup=main_kb())
    except Exception as e:
        log.exception("فشل توليد الشارت")
        await m.answer(f"❌ تعذّر رسم الشارت: {html.escape(str(e))}")


# ── إدارة الصفقات والمحفظة ──────────────────────────────────────

@router.message(Command("positions"))
@router.message(F.text == "🎯 الصفقات النشطة")
async def cmd_positions(m: Message):
    st_data = state.load()
    active = st_data.get("active", {})
    if not active:
        await m.answer("📭 لا توجد صفقات نشطة حالياً في النظام.\nالنظام بانتظار إشارة صيد مؤكدة.", reply_markup=main_kb())
        return

    quote = engine.live_quote()
    lines = ["🎯 <b>الصفقات النشطة للنظام:</b>\n"]
    for k, tr in active.items():
        spec = S.SPECS[k]
        side_icon = "🟢 شراء" if tr["side"] > 0 else "🔴 بيع"
        cur_px = quote["bid"] if tr["side"] > 0 else quote["offer"]
        diff_r = tr["side"] * (cur_px - tr["entry"]) / tr["stop_dist"]
        tp_txt = f"<code>${tr['tp']:,.1f}</code>" if tr.get("tp") else "خروج إيشيموكو / خط الوسط"
        mode_txt = "كابيتال Demo ✅" if tr.get("mode") == "capital" else "ورقي (Paper)"

        lines.extend([
            f"📌 <b>استراتيجية: {spec.name} ({k})</b>",
            f"• النوع: <b>{side_icon}</b> | الوضع: {mode_txt}",
            f"• نقطة الدخول: <code>${tr['entry']:,.1f}</code>",
            f"• السعر الحالي: <code>${cur_px:,.1f}</code> (<b>{diff_r:+.2f}R</b>)",
            f"• وقف الخسارة: <code>${tr['stop']:,.1f}</code>",
            f"• هدف الربح: {tp_txt}",
            f"• تاريخ الفتح: <code>{tr['opened'][:16]} UTC</code>",
            "",
        ])
    await m.answer("\n".join(lines), reply_markup=main_kb())


@router.message(Command("capital"))
@router.message(F.text == "💼 حساب كابيتال")
async def cmd_capital(m: Message):
    if not is_owner(m.chat.id):
        await m.answer("⛔ هذا الأمر خاص بمالك البوت.")
        return
    if not capital_trader.is_configured():
        await m.answer("⚠️ بيانات Capital.com غير مضبوطة في البيئة.", reply_markup=main_kb())
        return

    if bot:
        await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    try:
        acc = await asyncio.to_thread(capital_trader.account_summary)
    except Exception as e:
        await m.answer(f"❌ تعذّر الاتصال بـ Capital.com: {html.escape(str(e))}")
        return

    pl_icon = "🟢" if acc["profitLoss"] >= 0 else "🔴"
    lines = [
        "💼 <b>حساب Capital.com التجريبي (Demo):</b>",
        f"🆔 رقم الحساب: <code>{acc['accountId']}</code>",
        f"💰 الرصيد الإجمالي: <b>${acc['balance']:,.2f}</b>",
        f"💵 المتاح للتداول: <b>${acc['available']:,.2f}</b>",
        f"{pl_icon} الربح/الخسارة العائمة: <b>${acc['profitLoss']:+,.2f}</b>",
        f"🤖 التداول الآلي: <b>{'مفعّل ✅' if state.auto_trade() else 'معطل ⏸'}</b>",
        "",
    ]
    pos = acc.get("positions", [])
    if pos:
        lines.append(f"📊 <b>الصفقات المفتوحة في الحساب ({len(pos)}):</b>")
        for i, p in enumerate(pos, 1):
            d_icon = "🟢 شراء" if p["direction"] == "BUY" else "🔴 بيع"
            st_txt = f" | وقف <code>{p['stopLevel']}</code>" if p.get("stopLevel") else ""
            tp_txt = f" | هدف <code>{p['profitLevel']}</code>" if p.get("profitLevel") else ""
            lines.append(f"{i}. <b>{p['epic']}</b> {d_icon} ({p['size']}) @ <code>${p['level']:,.2f}</code>{st_txt}{tp_txt} → <b>${p['upl']:+,.2f}</b>")
        lines.append("\nلإغلاق كل الصفقات: /closeall")
    else:
        lines.append("📭 <i>لا توجد صفقات مفتوحة على المنصة.</i>")

    await m.answer("\n".join(lines), reply_markup=main_kb())


@router.message(Command("report"))
@router.message(F.text == "📊 التقرير التاريخي")
async def cmd_report(m: Message):
    if bot:
        await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    try:
        import backtest
        h4, d1 = await asyncio.to_thread(backtest.load, "research")
        t = await asyncio.to_thread(backtest.simulate, h4, d1)
        st_all = backtest.stats(t)
        st_out = backtest.stats(t[t.ts >= pd.Timestamp("2024-01-01", tz="UTC")])
        lines = [
            "📊 <b>التقرير التاريخي لمحفظة البيتكوين العالمية (2018 - 2026):</b>\n",
            "🏆 <b>الأداء الكلي (بعد خصم السبريد ورسوم التبييت):</b>",
            f"• عدد الصفقات: <b>{st_all['n']}</b> صفقة (معدل <b>{st_all['per_year']:.0f}</b> صفقة/سنة)",
            f"• نسبة الفوز: <b>{st_all['win']}%</b>",
            f"• عامل الربح (Profit Factor): <b>{st_all['pf']}</b>",
            f"• العائد المتوقع لكل صفقة: <b>+{st_all['exp_r']}R</b>",
            f"• إجمالي الأرباح الصافية: <b>+{st_all['total_r']}R</b>",
            f"• أقصى تراجع: <b>{st_all['max_dd_r']}R</b>",
            f"• نمو المحفظة بمخاطرة 1%: <b>+{st_all['ret_1pct']}%</b>",
            "",
            "🧪 <b>اختبار خارج العينة (2024 - 2026 Out-of-Sample):</b>",
            f"• الصفقات: {st_out['n']} | الفوز: {st_out['win']}% | PF: <b>{st_out['pf']}</b> | الربح: <b>+{st_out['total_r']}R</b>",
            "",
            "📌 <b>تفاصيل أداء كل استراتيجية:</b>",
        ]
        for k in ("A", "C", "B"):
            sub = t[t.strat == k]
            if not sub.empty:
                s_k = backtest.stats(sub)
                lines.append(f"• <b>{S.SPECS[k].name}:</b> {s_k['n']} صفقة | فوز {s_k['win']}% | PF {s_k['pf']} | +{s_k['total_r']}R")

        await m.answer("\n".join(lines), reply_markup=main_kb())
    except Exception as e:
        log.exception("فشل حساب التقرير")
        await m.answer(f"❌ تعذّر توليد التقرير: {html.escape(str(e))}")


# ── إعدادات التداول الآلي ──────────────────────────────────────

@router.message(Command("autotrade"))
@router.message(F.text == "⚙️ إعدادات التداول")
async def cmd_settings(m: Message):
    if not is_owner(m.chat.id):
        await m.answer("⛔ هذا الأمر خاص بمالك البوت.")
        return

    cur_auto = state.auto_trade()
    cur_risk = state.risk_pct()
    txt = (
        "⚙️ <b>إعدادات التداول الآلي والمخاطرة:</b>\n\n"
        f"• حالة التداول الآلي على Capital.com: <b>{'مفعّل ✅' if cur_auto else 'معطل ⏸'}</b>\n"
        f"• نسبة المخاطرة لكل صفقة: <b>{cur_risk:.1f}%</b> من رصيد المحفظة\n\n"
        "للتبديل أو التعديل، أرسل:\n"
        "• <code>/toggle</code> — تفعيل أو إيقاف التداول الآلي\n"
        "• <code>/risk 1.5</code> — ضبط نسبة المخاطرة (مثلاً 1.5%)"
    )
    await m.answer(txt, reply_markup=main_kb())


@router.message(Command("toggle"))
async def cmd_toggle(m: Message):
    if not is_owner(m.chat.id):
        return
    cur = state.auto_trade()
    state.set_setting("auto_trade", not cur)
    status_str = "مفعّل الآن ✅" if not cur else "معطل الآن ⏸"
    await m.answer(f"🤖 تم تعديل التداول الآلي: <b>{status_str}</b>", reply_markup=main_kb())


@router.message(Command("risk"))
async def cmd_set_risk(m: Message):
    if not is_owner(m.chat.id):
        return
    parts = (m.text or "").split()
    if len(parts) < 2:
        await m.answer("❌ يرجى كتابة النسبة. مثال: <code>/risk 2.0</code>")
        return
    try:
        val = float(parts[1].replace("%", "").strip())
        if not (0.1 <= val <= 20.0):
            raise ValueError
        state.set_setting("risk_pct", val)
        await m.answer(f"✅ تم ضبط نسبة المخاطرة على <b>{val:.1f}%</b> لكل صفقة.", reply_markup=main_kb())
    except ValueError:
        await m.answer("❌ نسبة غير صالحة. اختر رقماً بين 0.1 و 20.")


# ── التداول الفوري اليدوي ──────────────────────────────────────

async def _manual_order(m: Message, direction: str):
    if not is_owner(m.chat.id):
        await m.answer("⛔ هذا الأمر مخصص لمالك البوت.")
        return
    if not capital_trader.is_configured():
        await m.answer("⚠️ بيانات Capital.com غير مهيأة.", reply_markup=main_kb())
        return

    if bot:
        await bot.send_chat_action(m.chat.id, ChatAction.TYPING)

    try:
        h4, _, _ = await asyncio.to_thread(engine.load_data)
        a = float(S.atr(h4).iloc[-2])
        stop_dist = 2.0 * a
        q = await asyncio.to_thread(engine.live_quote)
        side = "BUY" if direction == "long" else "SELL"
        entry_ref = q["offer"] if side == "BUY" else q["bid"]
        d = 1 if side == "BUY" else -1
        stop_lvl = entry_ref - d * stop_dist
        tp_lvl = entry_ref + d * 2.0 * stop_dist

        bal = capital_trader.account_summary()["available"]
        size = engine._size(bal, state.risk_pct(), stop_dist)

        res = await asyncio.to_thread(capital_trader.open_trade, "btc", side, size, stop_lvl, tp_lvl, True)
        side_ar = "شراء 🟢" if side == "BUY" else "بيع 🔴"
        txt = (
            f"✅ <b>تم تنفيذ صفقة {side_ar} يدوية على البيتكوين (Demo)</b>\n\n"
            f"📦 الكمية: <code>{res['size']} BTC</code>\n"
            f"📍 سعر التنفيذ: <b>${res['level']:,.2f}</b>\n"
            f"🛑 وقف الخسارة: <code>${res.get('stopLevel') or stop_lvl:,.2f}</code>\n"
            f"🎯 هدف الربح: <code>${res.get('profitLevel') or tp_lvl:,.2f}</code>\n"
            f"🆔 رقم العقد: <code>{res.get('dealId') or res.get('dealReference')}</code>"
        )
        await m.answer(txt, reply_markup=main_kb())
    except Exception as e:
        log.exception("فشل تنفيذ الصفقة اليدوية")
        await m.answer(f"❌ فشل فتح الصفقة: {html.escape(str(e))}")


@router.message(Command("buy"))
@router.message(F.text == "🟢 شراء فوري")
async def cmd_buy(m: Message):
    await _manual_order(m, "long")


@router.message(Command("sell"))
@router.message(F.text == "🔴 بيع فوري")
async def cmd_sell(m: Message):
    await _manual_order(m, "short")


@router.message(Command("closeall"))
async def cmd_closeall(m: Message):
    if not is_owner(m.chat.id):
        return
    if bot:
        await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    try:
        n = await asyncio.to_thread(capital_trader.close_all, "btc")
        with state._LOCK:
            st = state.load()
            st["active"].clear()
            state.save(st)
        await m.answer(f"✅ تم إغلاق <b>{n}</b> صفقة مفتوحة على البيتكوين في Capital.com.", reply_markup=main_kb())
    except Exception as e:
        await m.answer(f"❌ تعذّر الإغلاق: {html.escape(str(e))}")


# ── حلقة المراقبة الآلية وإرسال التنبيهات ────────────────────────

async def notify_event(ev: engine.Event):
    if not bot or not config.ADMIN_CHAT_ID:
        return
    tr = ev.trade
    spec = S.SPECS.get(tr.get("strategy", ""))
    strat_name = spec.name if spec else tr.get("strategy", "")

    if ev.kind == "open":
        side_str = "🟢 شراء (LONG)" if tr["side"] > 0 else "🔴 بيع (SHORT)"
        tp_txt = f"<code>${tr['tp']:,.1f}</code>" if tr.get("tp") else "خروج إيشيموكو / خط الوسط"
        mode_txt = "تم الفتح تلقائياً في Capital.com ✅" if tr.get("mode") == "capital" else "تنبيه تحليلي (ورقي)"
        txt = [
            f"🚨 <b>إشارة تداول جديدة — {strat_name}</b>",
            f"• التوجه: <b>{side_str}</b>",
            f"• سعر الدخول: <b>${tr['entry']:,.2f}</b>",
            f"• وقف الخسارة: <code>${tr['stop']:,.2f}</code>",
            f"• هدف الربح: {tp_txt}",
            f"• التنفيذ: <i>{mode_txt}</i>",
            "",
            "<b>الأسباب والشروط:</b>",
        ]
        for r in tr.get("reasons", []):
            txt.append(f"▫️ {r}")

        caption = "\n".join(txt)
        try:
            h4, _, _ = await asyncio.to_thread(engine.load_data)
            lv = {"entry": tr["entry"], "stop": tr["stop"], "tp": tr.get("tp")}
            png = await asyncio.to_thread(chart.render, h4, f"BTC Signal — {strat_name}", lv, 90, tr["entry"])
            photo = BufferedInputFile(png, filename="signal_chart.png")
            await bot.send_photo(config.ADMIN_CHAT_ID, photo, caption=caption)
        except Exception:
            await bot.send_message(config.ADMIN_CHAT_ID, caption)

    elif ev.kind == "close":
        r_val = tr.get("r", 0.0)
        pnl_icon = "🎉 رابحة 🟢" if r_val > 0 else "🛑 خسارة 🔴"
        txt = (
            f"🔔 <b>إغلاق صفقة — {strat_name}</b>\n\n"
            f"• النتيجة: <b>{pnl_icon}</b> (<b>{r_val:+.2f}R</b>)\n"
            f"• سبب الإغلاق: {tr.get('reason', '—')}\n"
            f"• سعر الخروج: <code>${tr.get('exit', 0):,.2f}</code>\n"
            f"• نقطة الدخول: <code>${tr.get('entry', 0):,.2f}</code>"
        )
        if tr.get("pnl_usd"):
            txt += f"\n• الربح/الخسارة بالدولار: <b>${tr['pnl_usd']:+,.2f}</b>"
        await bot.send_message(config.ADMIN_CHAT_ID, txt)

    elif ev.kind == "trail":
        txt = (
            f"🛡 <b>تحديث الوقف وتأمين الصفقة (Break-even / Trailing)</b>\n"
            f"استراتيجية: <b>{strat_name}</b>\n"
            f"• تم تعديل الوقف إلى: <code>${tr['stop']:,.2f}</code> لحماية الأرباح وتأمين العقد 🔒"
        )
        await bot.send_message(config.ADMIN_CHAT_ID, txt)


async def engine_loop():
    log.info("بدء حلقة مراقبة محرك الإشارات...")
    while True:
        try:
            events = await asyncio.to_thread(engine.tick)
            for ev in events:
                await notify_event(ev)
        except Exception as e:
            log.exception("خطأ في دورة المحرك: %s", e)
        await asyncio.sleep(config.LOOP_SEC)


async def main():
    if not bot:
        raise RuntimeError("BOT_TOKEN مفقود في البيئة.")
    log.info("بدء تشغيل البوت...")
    await bot.delete_webhook(drop_pending_updates=True)
    asyncio.create_task(engine_loop())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
