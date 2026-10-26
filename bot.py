"""بوت تيليجرام لإشارات وتداول البيتكوين الاحترافي (Bitcoin Signals & Trading Bot).

نظام متكامل وشامل:
- استراتيجيتان مؤسسيتان (Jesse Ichimoku 4H, SMC Liquidity Sweep 4H) مع فلتر جودة شمعة.
- فحص دوري مستمر مع إشعارات فورية وشارت الشموع اليابانية.
- ربط مباشر وتداول آلي ويدوي على حساب Capital.com.
- إدارة المخاطر، الخروج الآلي، وتأمين الوقف التلقائي (Break-Even).
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
import whale_intel

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
            [KeyboardButton(text="🪙 البيتكوين BTC"), KeyboardButton(text="🥇 الذهب GOLD")],
            [KeyboardButton(text="🇺🇸 مؤشر US500"), KeyboardButton(text="🕯️ الشارت المباشر")],
            [KeyboardButton(text="💼 حساب كابيتال"), KeyboardButton(text="🎯 الصفقات المفتوحة")],
            [KeyboardButton(text="⚙️ إعدادات التداول"), KeyboardButton(text="📊 التقرير الشامل")],
            [KeyboardButton(text="❓ المساعدة")],
        ],
        resize_keyboard=True,
        input_field_placeholder="اختر أصلاً أو أمراً من القائمة 👇",
    )

# ── الأوامر الأساسية ──────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(m: Message):
    txt = (
        "👑 <b>بوت التداول والمضاربة المتعدد للأصول (Multi-Asset Institutional Trader)</b>\n\n"
        "نظام مؤسسي موحد يراقب ويقتنص الفرص في 3 أصول رئيسية معاً:\n\n"
        "1️⃣ <b>البيتكوين (BTCUSD) [4H]:</b> سحابة إيشيموكو + كنس سيولة SMC (ركوب موجات +8R إلى +10R).\n"
        "2️⃣ <b>الذهب (GOLD) [Daily/4H]:</b> ركوب ترندات الذهب المؤسسية (PF 4.80 ونمو تاريخي +88.8%).\n"
        "3️⃣ <b>الأسهم الأمريكية (US500) [15m]:</b> قنص كول وبوت مع إعادة الاختبار وتدفقات الأوبشن.\n\n"
        "⚡ <b>الميزات الذكية:</b>\n"
        "• حساب واحد موحّد في <b>Capital.com Live</b> مع إدارة مخاطر منضبطة للمحفظة.\n"
        "• فحص دوري مستمر لجميع الأصول على الشمعة المغلقة.\n"
        "• تأمين الوقف التلقائي (Break-Even) عند تحقيق الأهداف الأولية.\n\n"
        "اختر من الأزرار بالأسفل لاستعراض حالة الأسواق أو التحكم بالحساب 👇"
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

@router.message(F.text == "🪙 البيتكوين BTC")
async def cmd_status_btc(m: Message):
    await cmd_status(m)

@router.message(F.text == "🥇 الذهب GOLD")
async def cmd_status_gold(m: Message):
    if bot:
        await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    try:
        mkt = await asyncio.to_thread(client.get_market_info, "GOLD")
        sent = await asyncio.to_thread(client.get_sentiment, "GOLD")
    except Exception as e:
        await m.answer(f"❌ تعذّر جلب حالة الذهب: {html.escape(str(e))}")
        return

    bid = mkt.get("bid", 0.0) if mkt else 0.0
    offer = mkt.get("offer", 0.0) if mkt else 0.0
    spread = mkt.get("spread", 0.0) if mkt else 0.0
    long_sent = sent.get("long_pct", 50.0) if sent else 50.0
    short_sent = sent.get("short_pct", 50.0) if sent else 50.0

    txt = (
        "🥇 <b>حالة الذهب الفوري (GOLD / USD):</b>\n\n"
        f"• سعر الشراء (Ask): <b>${offer:,.2f}</b>\n"
        f"• سعر البيع (Bid): <b>${bid:,.2f}</b>\n"
        f"• السبريد: <b>${spread:.2f}</b>\n"
        f"• معنويات المتداولين: شراء <b>{long_sent:.1f}%</b> | بيع <b>{short_sent:.1f}%</b>\n\n"
        "🏛️ <b>الاستراتيجية النشطة:</b> ركوب ترند 20 يوماً فوق EMA200 المؤسسي + قنص سيولة 4H."
    )
    await m.answer(txt)

@router.message(F.text == "🇺🇸 مؤشر US500")
async def cmd_status_us500(m: Message):
    if bot:
        await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    try:
        mkt = await asyncio.to_thread(client.get_market_info, "US500")
        sent = await asyncio.to_thread(client.get_sentiment, "US500")
    except Exception as e:
        await m.answer(f"❌ تعذّر جلب حالة US500: {html.escape(str(e))}")
        return

    bid = mkt.get("bid", 0.0) if mkt else 0.0
    offer = mkt.get("offer", 0.0) if mkt else 0.0
    spread = mkt.get("spread", 0.0) if mkt else 0.0
    long_sent = sent.get("long_pct", 50.0) if sent else 50.0
    short_sent = sent.get("short_pct", 50.0) if sent else 50.0

    txt = (
        "🇺🇸 <b>حالة مؤشر S&P 500 (US500):</b>\n\n"
        f"• سعر الشراء (Ask): <b>{offer:,.1f}</b>\n"
        f"• سعر البيع (Bid): <b>{bid:,.1f}</b>\n"
        f"• السبريد: <b>{spread:.1f} نقطة</b>\n"
        f"• معنويات المتداولين: شراء <b>{long_sent:.1f}%</b> | بيع <b>{short_sent:.1f}%</b>\n\n"
        "🎯 <b>الاستراتيجية النشطة:</b> قنص كول/بوت مع إعادة الاختبار 15m وتدفقات السيولة."
    )
    await m.answer(txt)

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
        whale_data = await asyncio.to_thread(whale_intel.get_whale_metrics)
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
        f"🟢 مشترين: <b>{long_sent:.1f}%</b>  |  🔴 بائعين: <b>{short_sent:.1f}%</b>\n",
    ]

    if whale_data:
        txt.extend([
            "🐋 <b>رادار ومراكز سيولة الحيتان المباشرة:</b>",
            f"• تمركز كبار المتداولين والحيتان: <b>{whale_data['top_long_pct']}% شراء</b> مقابل <b>{whale_data['top_short_pct']}% بيع</b>",
            f"• تمركز صغار المتداولين والقطيع: <b>{whale_data['retail_long_pct']}% شراء</b>",
            f"• عقود الحيتان المفتوحة (OI): <code>{whale_data['open_interest_btc']:,.1f} BTC</code>",
            f"• معدل التمويل (Funding Rate): <code>{whale_data['funding_rate_pct']:+.4f}%</code>",
            f"• إشارة وسلوك الحيتان الآن: <b>{whale_data['bias']}</b>\n",
        ])

    txt.extend([
        "💼 <b>بيانات المحفظة:</b>",
        f"• الرصيد المتاح: <code>${acc.get('available', 0.0):,.2f}</code>",
        f"• الأرباح/الخسائر العائمة: <code>{acc.get('profit_loss', 0.0):+,.2f} USD</code>",
        f"• نمط التداول الآلي: <b>{'مفعّل 🟢' if state.is_auto_trade() else 'معطل ⏸'}</b>",
    ])
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
        f"• تأمين الوقف (Break-Even): <b>مفعّل تلقائياً عند +1.0R 🔒</b>\n"
        f"• الخروج الآلي: <b>شاندلير 4×ATR لـ[B]، و2×ATR لـ[C]</b>\n\n"
        "للتبديل:\n"
        "• <code>/autotrade on</code> أو <code>/autotrade off</code> لتفعيل/تعطيل الآلي.\n"
        "• <code>/risk 1.5</code> لتعديل نسبة المخاطرة (مثال 1.5%)."
    )
    await m.answer(txt, reply_markup=main_kb())

@router.message(Command("report"))
@router.message(F.text == "📊 التقرير والاستراتيجيات")
async def cmd_report(m: Message):
    txt = (
        "📊 <b>نتائج الاختبار الخلفي على كود المحرك (شمعة 4H مغلقة + تمويل):</b>\n"
        "• رأس المال: <b>$198.66</b> | مخاطرة <b>1%</b> لكل صفقة | سبريد <b>$50</b>\n\n"
        "🗓️ <b>آخر 12 شهراً (2025-10-24 → 2026-10-24):</b>\n"
        "• <b>7</b> صفقات | فوز <b>28.6%</b> | PF <b>4.96</b>\n"
        "• صافي <b>+$20.76 (+10.4%)</b> | أقصى تراجع <b>$2.64</b>\n\n"
        "🗓️ <b>آخر 6 أشهر (2026-04-24 → 2026-10-24):</b>\n"
        "• <b>5</b> صفقات | فوز <b>20.0%</b> | PF <b>4.19</b>\n"
        "• صافي <b>+$15.74 (+7.9%)</b> | أقصى تراجع <b>$2.60</b>\n\n"
        "📈 <b>الاختبار الكامل 2018-2026:</b> 101 صفقة | PF <b>5.89</b> | "
        "صافي <b>+$1,177.01 (+592.5%)</b> | أقصى تراجع <b>$26.03</b> | CAGR <b>24.5%</b>\n"
        "• 12 من 15 نافذة 6 أشهر رابحة.\n\n"
        "⚠️ <i>ربح آخر 6 أشهر جاء من صفقة واحدة ناجحة (هدف 8×ATR) مقابل 4 خسائر صغيرة. "
        "التحقق بدقة 15 دقيقة مع انزلاق 0.2×ATR يعطي PF 5.15 لنفس الإعداد (2022-2026).</i>\n\n"
        "🚪 <b>إدارة الخروج الآلية:</b>\n"
        "• [B]: إغلاق 4H تحت أعلى قمة للصفقة بمقدار 4×ATR (شاندلير).\n"
        "• [C]: إغلاق تحت الدخول بمقدار 2×ATR.\n"
        "• تأمين الوقف لنقطة الدخول عند +1.0R على الشمعة المغلقة.\n"
        "• [A] دونشيان معطّلة و[D] الحيتان مُخرجة: المحفظة الطويلة فقط أعلى عائداً/مخاطرة."
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
                    if act.get("event") == "close":
                        icon = "🟢" if act["direction"] == "BUY" else "🔴"
                        msg = (
                            f"🚪 <b>إغلاق تلقائي للصفقة</b>\n\n"
                            f"🎯 الاستراتيجية: <b>{act['strat_name']}</b>\n"
                            f"{icon} الاتجاه: <b>{act['direction']}</b>\n"
                            f"💰 سعر الدخول: <code>${act['entry']:,.2f}</code>\n"
                            f"🏁 سعر الإغلاق: <code>${act['exit_price']:,.2f}</code>\n"
                            f"📌 سبب الخروج: <b>{act['reason']}</b>\n"
                            f"💵 الربح/الخسارة: <b>{act['pnl']:+,.2f} USD</b>\n"
                        )
                        await bot.send_message(config.ADMIN_CHAT_ID, msg)
                        continue
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
