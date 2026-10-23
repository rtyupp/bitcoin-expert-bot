"""بوت تيليجرام لإشارات وتداول البيتكوين الاحترافي (Bitcoin Signals & Trading Bot).

نظام متكامل وشامل:
- 4 استراتيجيات مؤسسية متكيفة (Jesse Ichimoku 4H, SMC 4H, Donchian 1D, Fast 1H Trend).
- فحص دوري مستمر مع إشعارات فورية وشارت الشموع اليابانية.
- ربط مباشر وتداول آلي ويدوي على حساب Capital.com.
- إدارة المخاطر وتأمين الوقف التلقائي (Break-Even).
"""
from __future__ import annotations

import asyncio
import html
import logging
import time

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import BufferedInputFile, KeyboardButton, Message, ReplyKeyboardMarkup
import pandas as pd

from capital_trader import client
import chart
import config
import engine
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

def main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🪙 حالة البيتكوين"), KeyboardButton(text="🕯️ الشارت المباشر")],
            [KeyboardButton(text="💼 حساب كابيتال"), KeyboardButton(text="🎯 الصفقات المفتوحة")],
            [KeyboardButton(text="🟢 شراء فوري"), KeyboardButton(text="🔴 بيع فوري")],
            [KeyboardButton(text="⚙️ إعدادات التداول"), KeyboardButton(text="📊 التقرير والاستراتيجيات")],
            [KeyboardButton(text="❓ المساعدة")],
        ],
        resize_keyboard=True,
        input_field_placeholder="اختر أمراً من القائمة 👇",
    )

# ── الأوامر الأساسية ──────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(m: Message):
    txt = (
        "👑 <b>بوت خبير البيتكوين المؤسسي (BTC Institutional Trader)</b>\n\n"
        "تم بناء وتطوير النظام ليتأقلم تلقائياً مع <b>كل ظروف السوق</b> عبر 4 استراتيجيات مختبرة ومثبتة إحصائياً عبر 8 سنوات من البيانات:\n\n"
        "1️⃣ <b>سحابة إيشيموكو وبولينجر 4H (B):</b> ركوب الاتجاه المؤسسي (PF 2.03، عائد +490%).\n"
        "2️⃣ <b>قنص كنس السيولة SMC 4H (C):</b> اصطياد فخاخ الدببة وصناع السوق عند القيعان (PF 1.73).\n"
        "3️⃣ <b>اختراق دونشيان اليومي 55 (A):</b> ركوب الانفجارات السعرية الكبرى (PF 1.92).\n"
        "4️⃣ <b>اختراق الزخم السريع 1H (D):</b> تداول سريع يومي مع تأكيد الاتجاه والفوليوم (+184 R).\n\n"
        "⚡ <b>الميزات الذكية:</b>\n"
        "• تكامل كامل مع حساب <b>Capital.com</b> للتداول الحي والتجريبي.\n"
        "• فحص دوري مستمر كل دقيقة مع إرسال إشارات مؤكدة وفورية.\n"
        "• نظام حماية الأرباح ونقل الوقف لنقطة الدخول (Break-Even) عند +1.0R.\n\n"
        "اختر من الأزرار بالأسفل للبدء 👇"
    )
    await m.answer(txt, reply_markup=main_kb())

@router.message(Command("help"))
@router.message(F.text == "❓ المساعدة")
async def cmd_help(m: Message):
    txt = (
        "📖 <b>دليل الأوامر والاستخدام:</b>\n\n"
        "• 🪙 <b>حالة البيتكوين:</b> فحص الأسعار، السبريد، معنويات المتداولين (Sentiment)، ونظام السوق الحالي.\n"
        "• 🕯️ <b>الشارت المباشر:</b> رسم شموع يابانية لحظية مع المتوسطات الفنية.\n"
        "• 💼 <b>حساب كابيتال:</b> استعراض الرصيد، الهامش المتاح، والأرباح الحالية.\n"
        "• 🎯 <b>الصفقات المفتوحة:</b> قائمة الصفقات النشطة ومستويات الوقف والأهداف.\n"
        "• ⚙️ <b>إعدادات التداول:</b> تفعيل/تعطيل التداول الآلي، وتحديد نسبة المخاطرة.\n"
        "• 🟢 <b>شراء فوري</b> / 🔴 <b>بيع فوري:</b> فتح صفقة يدوية فورية بحجم محسوب بدقة.\n\n"
        "الأوامر السريعة: /status, /chart, /capital, /positions, /autotrade, /risk"
    )
    await m.answer(txt, reply_markup=main_kb())

# ── حالة السوق والشارت ────────────────────────────────────────

@router.message(Command("status"))
@router.message(F.text == "🪙 حالة البيتكوين")
async def cmd_status(m: Message):
    if bot:
        await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    try:
        mkt = await asyncio.to_thread(client.get_market_info, "BTCUSD")
        sent = await asyncio.to_thread(client.get_sentiment, "BTCUSD")
        acc = await asyncio.to_thread(client.get_account_details)
    except Exception as e:
        await m.answer(f"❌ تعذّر جلب حالة السوق: {html.escape(str(e))}")
        return

    bid = mkt.get("bid", 0.0) if mkt else 0.0
    offer = mkt.get("offer", 0.0) if mkt else 0.0
    spread = mkt.get("spread", 0.0) if mkt else 0.0
    status_str = mkt.get("status", "—") if mkt else "—"

    long_sent = sent.get("long_pct", 50.0) if sent else 50.0
    short_sent = sent.get("short_pct", 50.0) if sent else 50.0

    txt = [
        "🪙 <b>حالة سوق البيتكوين (Capital.com - BTC/USD)</b>\n",
        f"💰 سعر الشراء (Ask): <b>${offer:,.2f}</b>",
        f"💰 سعر البيع (Bid): <b>${bid:,.2f}</b>",
        f"📏 السبريد اللحظي: <code>${spread:,.2f}</code> | حالة السوق: <b>{status_str}</b>\n",
        "📊 <b>معنويات المتداولين (Capital Sentiment):</b>",
        f"🟢 مشترين: <b>{long_sent:.1f}%</b>  |  🔴 بائعين: <b>{short_sent:.1f}%</b>",
        f"💡 <i>{('الأغلبية شراء (حذر من التشبع)' if long_sent > 75 else 'الأغلبية بيع (فرص كنس قيعان)' if short_sent > 60 else 'معنويات متوازنة')}</i>\n",
        "💼 <b>بيانات المحفظة:</b>",
        f"• الرصيد المتاح: <code>${acc.get('available', 0.0):,.2f}</code>",
        f"• الأرباح/الخسائر العائمة: <code>{acc.get('profit_loss', 0.0):+,.2f} USD</code>",
        f"• نمط التداول الآلي: <b>{'مفعّل 🟢' if state.is_auto_trade() else 'معطل ⏸'}</b>",
    ]
    await m.answer("\n".join(txt), reply_markup=main_kb())

@router.message(Command("chart"))
@router.message(F.text == "🕯️ الشارت المباشر")
async def cmd_chart(m: Message):
    if bot:
        await bot.send_chat_action(m.chat.id, ChatAction.UPLOAD_PHOTO)
    try:
        async with _chart_lock:
            png = await asyncio.to_thread(chart.generate_chart_image, "HOUR_4", 40)
        photo = BufferedInputFile(png, filename="btc_chart.png")
        mkt = client.get_market_info("BTCUSD")
        cur_px = mkt.get("bid", 0.0) if mkt else 0.0
        caption = f"🕯️ <b>شارت البيتكوين المباشر (4H Candles)</b>\n💰 السعر اللحظي: <b>${cur_px:,.2f}</b>\nخطوط المتوسطات: أزرق (EMA20) | برتقالي (EMA50)"
        await m.answer_photo(photo=photo, caption=caption, reply_markup=main_kb())
    except Exception as e:
        await m.answer(f"❌ تعذّر رسم الشارت: {html.escape(str(e))}")

# ── حساب كابيتال والصفقات ────────────────────────────────────

@router.message(Command("capital"))
@router.message(F.text == "💼 حساب كابيتال")
async def cmd_capital(m: Message):
    if bot:
        await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    try:
        acc = await asyncio.to_thread(client.get_account_details)
        if not acc:
            await m.answer("❌ تعذّر جلب بيانات الحساب من Capital.com.")
            return

        txt = (
            f"💼 <b>حساب Capital.com ({acc['account_name']})</b>\n\n"
            f"💵 الرصيد الإجمالي: <b>${acc['balance']:,.2f} {acc['currency']}</b>\n"
            f"🛡 الهامش المتاح: <b>${acc['available']:,.2f}</b>\n"
            f"🔒 الهامش المحجوز: <b>${acc['deposit']:,.2f}</b>\n"
            f"📈 الأرباح/الخسائر غير المحققة: <b>{acc['profit_loss']:+,.2f} USD</b>\n"
            f"⚙️ الحالة: <code>{acc['status']}</code>"
        )
        await m.answer(txt, reply_markup=main_kb())
    except Exception as e:
        await m.answer(f"❌ خطأ: {html.escape(str(e))}")

@router.message(Command("positions"))
@router.message(F.text == "🎯 الصفقات المفتوحة")
async def cmd_positions(m: Message):
    if bot:
        await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    try:
        positions = await asyncio.to_thread(client.get_open_positions, "BTCUSD")
        if not positions:
            await m.answer("📭 لا توجد صفقات مفتوحة حالياً في الحساب.", reply_markup=main_kb())
            return

        lines = ["🎯 <b>الصفقات المفتوحة حالياً (BTCUSD):</b>\n"]
        for p in positions:
            side_str = "🟢 شراء" if p["direction"] == "BUY" else "🔴 بيع"
            lines.append(
                f"• <b>{side_str}</b> | الحجم: <code>{p['size']} BTC</code>\n"
                f"  سعر الدخول: <code>${p['level']:,.2f}</code> | السعر الآن: <code>${p['current_price']:,.2f}</code>\n"
                f"  الوقف: <code>${p['stop_level']:,.2f}</code> | الهدف: <code>${p['profit_level']:,.2f}</code>\n"
                f"  الربح/الخسارة: <b>{p['upl']:+,.2f} USD</b>\n"
                f"  معرف الصفقة: <code>{p['deal_id']}</code>\n"
            )
        lines.append("لإغلاق أي صفقة يدوياً، أرسل: <code>/close &lt;deal_id&gt;</code>")
        await m.answer("\n".join(lines), reply_markup=main_kb())
    except Exception as e:
        await m.answer(f"❌ خطأ: {html.escape(str(e))}")

# ── أوامر التداول اليدوي ──────────────────────────────────────

@router.message(Command("buy"))
@router.message(F.text == "🟢 شراء فوري")
async def cmd_buy(m: Message):
    await _execute_manual_trade(m, "BUY")

@router.message(Command("sell"))
@router.message(F.text == "🔴 بيع فوري")
async def cmd_sell(m: Message):
    await _execute_manual_trade(m, "SELL")

async def _execute_manual_trade(m: Message, direction: str):
    if bot:
        await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    try:
        mkt = client.get_market_info("BTCUSD")
        if not mkt:
            await m.answer("❌ تعذر جلب السعر اللحظي لتنفيذ الصفقة.")
            return

        ref_px = mkt["offer"] if direction == "BUY" else mkt["bid"]
        candles_1h = client.get_prices("BTCUSD", resolution="HOUR", max_candles=20)
        df = pd.DataFrame(candles_1h)
        atr_val = float(S.compute_atr(df, 14).iloc[-1])

        stop_loss = ref_px - 1.5 * atr_val if direction == "BUY" else ref_px + 1.5 * atr_val
        take_profit = ref_px + 3.0 * atr_val if direction == "BUY" else ref_px - 3.0 * atr_val
        size = engine.calculate_position_size(ref_px, stop_loss, state.get_risk_pct())

        ok, msg, deal = await asyncio.to_thread(
            client.open_position,
            direction=direction,
            size=size,
            epic="BTCUSD",
            stop_level=stop_loss,
            profit_level=take_profit,
        )

        if ok and deal:
            side_icon = "🟢" if direction == "BUY" else "🔴"
            txt = (
                f"{side_icon} <b>تم تنفيذ الصفقة الفورية بنجاح!</b>\n\n"
                f"• الاتجاه: <b>{direction}</b>\n"
                f"• الحجم: <code>{size} BTC</code>\n"
                f"• سعر التنفيذ: <code>${deal.get('level', ref_px):,.2f}</code>\n"
                f"• الوقف: <code>${stop_loss:,.2f}</code>\n"
                f"• الهدف (1:2): <code>${take_profit:,.2f}</code>\n"
                f"• المعرف: <code>{deal['deal_id']}</code>"
            )
            await m.answer(txt, reply_markup=main_kb())
        else:
            await m.answer(f"❌ فشل التنفيذ: {html.escape(msg)}", reply_markup=main_kb())
    except Exception as e:
        await m.answer(f"❌ خطأ غير متوقع: {html.escape(str(e))}")

@router.message(Command("close"))
async def cmd_close(m: Message):
    parts = m.text.split()
    if len(parts) < 2:
        await m.answer("يرجى إرسال معرف الصفقة. مثال: <code>/close 00000000-xxxx-xxxx</code>")
        return
    deal_id = parts[1].strip()
    ok, msg = await asyncio.to_thread(client.close_position, deal_id)
    if ok:
        await m.answer(f"✅ تم إغلاق الصفقة بنجاح: {deal_id}")
    else:
        await m.answer(f"❌ تعذّر إغلاق الصفقة: {html.escape(msg)}")

# ── الإعدادات والتقرير ────────────────────────────────────────

@router.message(Command("autotrade"))
@router.message(F.text == "⚙️ إعدادات التداول")
async def cmd_settings(m: Message):
    auto_st = state.is_auto_trade()
    risk = state.get_risk_pct()
    txt = (
        "⚙️ <b>إعدادات البوت وإدارة المخاطر:</b>\n\n"
        f"• التداول الآلي التلقائي: <b>{'مفعّل 🟢' if auto_st else 'معطل ⏸'}</b>\n"
        f"• نسبة المخاطرة لكل صفقة: <b>{risk:.1f}%</b> من الرصيد المتاح\n"
        f"• تأمين الوقف (Break-Even): <b>مفعّل تلقائياً عند +1.0R 🔒</b>\n\n"
        "للتبديل:\n"
        "• <code>/autotrade on</code> أو <code>/autotrade off</code> لتفعيل/تعطيل الآلي.\n"
        "• <code>/risk 1.5</code> لتعديل نسبة المخاطرة (مثال 1.5%)."
    )
    await m.answer(txt, reply_markup=main_kb())

@router.message(Command("report"))
@router.message(F.text == "📊 التقرير والاستراتيجيات")
async def cmd_report(m: Message):
    txt = (
        "📊 <b>التقرير التاريخي لاستراتيجيات النظام المتكيفة:</b>\n\n"
        "1️⃣ <b>سحابة إيشيموكو وبولينجر 4H (Jesse Ichimoku):</b>\n"
        "• معامل الربح (PF): <b>2.03</b> | العائد التراكمي: <b>+490%</b>\n"
        "• ركوب الاتجاه المؤسسي الصاعد والهابط وحلب الأرباح.\n\n"
        "2️⃣ <b>قنص كنس السيولة 4H (SMC Liquidity Sweep):</b>\n"
        "• معامل الربح (PF): <b>1.73</b> | نسبة الفوز: <b>46.4%</b>\n"
        "• اصطياد فخاخ الدببة والقيعان العميقة عند كسر 24 شمعة.\n\n"
        "3️⃣ <b>اختراق دونشيان اليومي 55:</b>\n"
        "• معامل الربح (PF): <b>1.92</b> | نسبة الفوز: <b>49.0%</b>\n"
        "• اقتناص موجات الصعود التاريخية الكبرى.\n\n"
        "4️⃣ <b>اختراق الزخم السريع 1H:</b>\n"
        "• صافي العائد التراكمي: <b>+184.0 R</b>\n"
        "• تداول سريع ومستمر مع تأكيد اتجاه الأطر العليا."
    )
    await m.answer(txt, reply_markup=main_kb())

# ── حلقة المراقبة الخلفية المستمرة ────────────────────────────

async def background_watcher():
    """فحص مستمر للسوق والشموع المكتملة كل 60 ثانية."""
    log.info("بدء تشغيل حلقة المراقبة الآلية للسوق...")
    while True:
        try:
            actions, logs = await asyncio.to_thread(engine.evaluate_and_trade)
            if actions and bot and config.ADMIN_CHAT_ID:
                for act in actions:
                    icon = "🟢" if act["direction"] == "BUY" else "🔴"
                    msg = (
                        f"🚨 <b>إشارة تداول مؤكدة جديدة!</b>\n\n"
                        f"🎯 الاستراتيجية: <b>{act['strat_name']}</b>\n"
                        f"{icon} الاتجاه: <b>{act['direction']}</b>\n"
                        f"💰 سعر الدخول: <code>${act['entry']:,.2f}</code>\n"
                        f"🛑 وقف الخسارة: <code>${act['stop_level']:,.2f}</code>\n"
                        f"🎯 الهدف المقترح: <code>${act['target_level']:,.2f}</code>\n"
                        f"💼 حجم العقد: <code>{act['size']} BTC</code>\n"
                    )
                    if act.get("deal_id"):
                        msg += f"⚡ <b>تم فتح الصفقة تلقائياً على Capital.com!</b>\nمعرف الصفقة: <code>{act['deal_id']}</code>\n"
                    if act.get("reasons"):
                        msg += "\n<b>الأسباب الفنية:</b>\n" + "\n".join(f"  • {r}" for r in act["reasons"])
                    await bot.send_message(config.ADMIN_CHAT_ID, msg)
        except Exception as e:
            log.error(f"خطأ في حلقة المراقبة: {e}")
        await asyncio.sleep(60)

async def main():
    if not bot:
        log.error("BOT_TOKEN مفقود في متغيرات البيئة!")
        return

    # تشغيل حلقة المراقبة في الخلفية
    asyncio.create_task(background_watcher())

    log.info("بدء تشغيل استقبال رسائل البوت (Polling)...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
