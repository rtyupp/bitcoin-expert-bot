"""بوت خبير توصيات البيتكوين — aiogram 3 (webhook على Render / polling محلياً)."""
import asyncio
import logging
import secrets

from aiohttp import web

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

import ai_insights
import alerts
import analysis
import config
import data_feeds

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# يُبنى الـ Bot فقط إذا وُجد التوكن — بدون توكن يعمل خادم الويب للفحص الصحي وينتظر
if config.BOT_TOKEN:
    bot: Bot | None = Bot(
        token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
else:
    bot = None
dp = Dispatcher()
router = Router()
dp.include_router(router)

# الأزرار الثابتة تحت الكيبورد
KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 التحليل"), KeyboardButton(text="🧭 التوصية")],
        [KeyboardButton(text="💰 السعر"), KeyboardButton(text="😱 الخوف والطمع")],
        [KeyboardButton(text="⛓️ أون-تشين"), KeyboardButton(text="🌍 السوق")],
        [KeyboardButton(text="🤖 الذكاء الاصطناعي"), KeyboardButton(text="⏰ تنبيه سعر")],
    ],
    resize_keyboard=True,
    input_field_placeholder="اضغط زر أو اكتب أمراً مثل /alert",
)


@router.message(CommandStart())
async def cmd_start(m: Message):
    await m.answer(
        "🪙 <b>أهلاً بك في خبير توصيات البيتكوين</b>\n\n"
        "أقوى محلل بيتكوين في جيبك — يدمج:\n"
        "• تحليل فني متعدد الأطر (1س/4س/يوم)\n"
        "• مؤشر الخوف والطمع + بيانات أون-تشين\n"
        "• مستويات فيبوناتشي + توصية بثقة\n"
        "• تنبيهات صيدة تلقائية + أهداف سعر\n\n"
        "استخدم الأزرار بالأسفل 👇 أو اكتب /help",
        reply_markup=KB,
    )


@router.message(Command("help"))
async def cmd_help(m: Message):
    await m.answer(
        "📖 <b>الأوامر:</b>\n"
        "/start — القائمة الرئيسية\n"
        "/analysis — لوحة التحليل الشاملة (كل الأطر + فيبوناتشي)\n"
        "/recommend — توصية مباشرة مع الثقة\n"
        "/price — السعر الحالي\n"
        "/feargreed — الخوف والطمع\n"
        "/onchain — رسوم الشبكة + الهاش ريت\n"
        "/market — نظرة السوق (CoinGecko)\n"
        "/ai — تحليل ذكاء اصطناعي\n"
        "/signal — فحص صيدة فوري\n"
        "/alert — تنبيه سعر (مثال: /alert 85000)\n"
        "/alerts — تنبيهاتك الحالية\n"
        "/delalerts — حذف كل التنبيهات\n"
        "/myid — معرف المحادثة",
        reply_markup=KB,
    )


@router.message(Command("myid"))
async def cmd_myid(m: Message):
    await m.answer(f"🆔 Chat ID الخاص بك: <code>{m.chat.id}</code>", reply_markup=KB)


@router.message(Command("signal"))
async def cmd_signal(m: Message):
    """فحص صيدة فوري — يعرض النقاط الموزونة وتوافق الأطر."""
    await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    try:
        mm = await asyncio.to_thread(analysis.analyze_multi)
        combined = mm["combined"]
        agreement = mm["agreement"]
        strong = abs(combined) >= config.SIGNAL_THRESHOLD
        agree_ok = agreement >= config.SIGNAL_MIN_AGREEMENT
        if strong and agree_ok:
            state = "🚨 <b>صيدة!</b> (توافق أطر ✅)"
        elif strong:
            state = f"⚠️ نقاط قوية ({combined:+.1f}) لكن توافق الأطر ضعيف ({agreement}/{mm['total']})"
        else:
            state = f"ℹ️ لا توجد صيدة حالياً (نقاط {combined:+.1f})"
        await m.answer(
            f"{state}\n\n"
            f"🤝 توافق الأطر: {agreement}/{mm['total']}\n"
            f"🎯 النقاط الموزونة: <code>{combined:+.1f}</code> (العتبة ±{config.SIGNAL_THRESHOLD:.1f})\n\n"
            f"للتفاصيل: /analysis",
            reply_markup=KB,
        )
    except Exception as e:  # noqa: BLE001
        await m.answer(f"❌ تعذّر الفحص: {e}", reply_markup=KB)


@router.message(Command("price"))
@router.message(F.text == "💰 السعر")
async def cmd_price(m: Message):
    await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    try:
        price, change, exchange = await asyncio.to_thread(analysis.ticker)
        txt = f"💰 <b>سعر البيتكوين</b>\n\n$<b>{price:,.0f}</b>\n"
        if change is not None:
            icon = "🟢" if change >= 0 else "🔴"
            txt += f"التغير 24س: {icon} {change:+.2f}%\n"
        txt += f"\n🏦 المنصة: <code>{exchange}</code>"
        await m.answer(txt, reply_markup=KB)
    except Exception as e:  # noqa: BLE001
        await m.answer(f"❌ تعذّر جلب السعر: {e}", reply_markup=KB)


@router.message(Command("analysis"))
@router.message(F.text == "📊 التحليل")
async def cmd_analysis(m: Message):
    await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    await m.answer(await asyncio.to_thread(_analyze_msg), reply_markup=KB)


@router.message(Command("recommend"))
@router.message(F.text == "🧭 التوصية")
async def cmd_recommend(m: Message):
    await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    report = await asyncio.to_thread(analysis.analyze)
    await m.answer(
        f"🧭 <b>توصية البيتكوين</b>\n\n"
        f"💰 السعر: <b>${report.price:,.0f}</b>\n"
        f"📈 التوصية: <b>{report.recommendation}</b>\n"
        f"🎯 الثقة: <b>{report.confidence}%</b>\n"
        f"🛡 وقف الخسارة المقترح: <code>${report.price - 2 * report.atr:,.0f}</code>\n\n"
        f"للتفاصيل الكاملة: /analysis\n\n"
        f"⚠️ <i>ليست نصيحة مالية.</i>",
        reply_markup=KB,
    )


@router.message(Command("feargreed"))
@router.message(F.text == "😱 الخوف والطمع")
async def cmd_fng(m: Message):
    await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    try:
        fng = await data_feeds.fear_greed()
        bar = "🟥" * (fng["value"] // 20) + "⬜" * (5 - fng["value"] // 20)
        await m.answer(
            f"😱 <b>مؤشر الخوف والطمع</b>\n\n"
            f"القيمة: <b>{fng['value']}/100</b>\n"
            f"الحالة: <b>{fng['ar']}</b>\n"
            f"{bar}\n\n"
            f"💡 <i>قيم منخفضة = فرص شراء غالباً، قيم مرتفعة = حذر من التصحيحات.</i>",
            reply_markup=KB,
        )
    except Exception as e:  # noqa: BLE001
        await m.answer(f"❌ تعذّر جلب المؤشر: {e}", reply_markup=KB)


@router.message(Command("onchain"))
@router.message(F.text == "⛓️ أون-تشين")
async def cmd_onchain(m: Message):
    await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    try:
        oc = await data_feeds.onchain()
        await m.answer(
            f"⛓️ <b>بيانات شبكة البيتكوين</b>\n\n"
            f"⚡ رسوم التحويل (سات/بايت):\n"
            f"• سريع: <code>{oc['fast']}</code>\n"
            f"• متوسط: <code>{oc['half']}</code>\n"
            f"• اقتصادي: <code>{oc['eco']}</code>\n\n"
            f"🖥 الهاش ريت: <code>{oc['hashrate_eh']} EH/s</code>\n"
            f"⛏ الصعوبة: <code>{oc['difficulty_t']} T</code>\n\n"
            f"💡 <i>الهاش ريت المرتفع = شبكة أقوى وأكثر أماناً.</i>",
            reply_markup=KB,
        )
    except Exception as e:  # noqa: BLE001
        await m.answer(f"❌ تعذّر جلب بيانات الشبكة: {e}", reply_markup=KB)


@router.message(Command("market"))
@router.message(F.text == "🌍 السوق")
async def cmd_market(m: Message):
    await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    try:
        mk = await data_feeds.market_overview()
        await m.answer(
            f"🌍 <b>نظرة سوق البيتكوين</b> (CoinGecko)\n\n"
            f"💰 السعر: <b>${mk['price']:,.0f}</b>\n"
            f"📅 24س: {mk['change_24h']:+.1f}% | 7 أيام: {mk['change_7d']:+.1f}%\n"
            f"🏔 القمة التاريخية: <b>${mk['ath']:,.0f}</b> ({mk['ath_change']:+.1f}% عنها)\n"
            f"📈 أعلى/أدنى 24س: <code>{mk['high_24h']:,.0f} / {mk['low_24h']:,.0f}</code>\n"
            f"💎 القيمة السوقية: <code>{data_feeds.fmt_big(mk['market_cap'])}</code>\n"
            f"🔄 حجم التداول 24س: <code>{data_feeds.fmt_big(mk['volume_24h'])}</code>\n"
            + (f"👑 هيمنة البيتكوين: <code>{mk['dominance']:.1f}%</code>\n" if mk["dominance"] else "")
            + f"\n⚠️ <i>ليست نصيحة مالية.</i>",
            reply_markup=KB,
        )
    except Exception as e:  # noqa: BLE001
        await m.answer(f"❌ تعذّر جلب بيانات السوق: {e}", reply_markup=KB)


@router.message(Command("ai"))
@router.message(F.text == "🤖 الذكاء الاصطناعي")
async def cmd_ai(m: Message):
    if not config.DEEPSEEK_API_KEY:
        await m.answer(
            "🤖 <b>تحليل الذكاء الاصطناعي غير مفعّل</b>\n\n"
            "أضف متغير البيئة <code>DEEPSEEK_API_KEY</code> "
            "في لوحة Render ثم أعد النشر، أو اطلب مني تفعيله.",
            reply_markup=KB,
        )
        return
    wait_msg = await m.answer("🤖 جاري التحليل بالذكاء الاصطناعي... (قد يأخذ ~30 ثانية)", reply_markup=KB)
    try:
        report = await asyncio.to_thread(analysis.analyze)
        fng, market = None, None
        try:
            fng = await data_feeds.fear_greed()
            market = await data_feeds.market_overview()
        except Exception:  # noqa: BLE001
            pass
        ctx = ai_insights.build_context(report.summary, fng, market)
        text = await ai_insights.ai_analysis(ctx)
        if text:
            await wait_msg.edit_text(f"🤖 <b>تحليل الخبير (DeepSeek)</b>\n\n{text}")
        else:
            await wait_msg.edit_text("❌ لم يصل رد من خدمة الذكاء الاصطناعي.")
    except Exception as e:  # noqa: BLE001
        await wait_msg.edit_text(f"❌ فشل التحليل: {e}")


# ── تنبيهات السعر ──────────────────────────────────────────────

@router.message(Command("alert"))
async def cmd_alert(m: Message):
    await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    parts = m.text.split()
    if len(parts) < 2:
        await _alert_help(m)
        return
    raw = parts[1].replace(",", "").replace("$", "").replace("k", "000").replace("K", "000")
    try:
        target = float(raw)
    except ValueError:
        await m.answer("❌ سعر غير صحيح. مثال: <code>/alert 85000</code>", reply_markup=KB)
        return
    try:
        cur, _, _ = await asyncio.to_thread(analysis.ticker)
    except Exception as e:  # noqa: BLE001
        await m.answer(f"❌ تعذّر جلب السعر الحالي: {e}", reply_markup=KB)
        return
    direction = "up" if target > cur else "down"
    alerts.set_alert(m.chat.id, target, direction)
    arrow = "📈 فوق" if direction == "up" else "📉 تحت"
    await m.answer(
        f"⏰ <b>تم ضبط التنبيه</b>\n\n"
        f"🎯 الهدف: <code>${target:,.0f}</code> ({arrow} السعر الحالي ${cur:,.0f})\n"
        f"🔔 سأرسل لك فور الوصول.\n\n"
        f"تنبيهاتك الحالية: /alerts",
        reply_markup=KB,
    )


@router.message(F.text == "⏰ تنبيه سعر")
async def txt_alert(m: Message):
    await _alert_help(m)


async def _alert_help(m: Message):
    await m.answer(
        "⏰ <b>تنبيه السعر</b>\n\n"
        "حدد سعراً والبوت يرسلك تنبيه لحظة وصول البيتكوين له.\n\n"
        "الاستخدام:\n"
        "<code>/alert 85000</code> — تنبيه عند وصول 85 ألف\n"
        "<code>/alerts</code> — تنبيهاتك الحالية\n"
        "<code>/delalerts</code> — حذف كل التنبيهات\n\n"
        "مثال: /alert 95000",
        reply_markup=KB,
    )


@router.message(Command("alerts"))
async def cmd_alerts(m: Message):
    items = alerts.list_alerts(m.chat.id)
    if not items:
        await m.answer("📭 لا توجد تنبيهات سعر حالية.\n\nلإضافة: <code>/alert 85000</code>", reply_markup=KB)
        return
    lines = ["⏰ <b>تنبيهات السعر الحالية:</b>\n"]
    for i, a in enumerate(items, 1):
        arrow = "📈 فوق" if a["direction"] == "up" else "📉 تحت"
        lines.append(f"{i}. <code>${a['price']:,.0f}</code> — تنبيه {arrow} السعر الحالي")
    lines.append("\nللحذف: /delalerts")
    await m.answer("\n".join(lines), reply_markup=KB)


@router.message(Command("delalerts"))
async def cmd_delalerts(m: Message):
    n = alerts.clear_alerts(m.chat.id)
    await m.answer(f"🗑 حذفت {n} تنبيه سعر.", reply_markup=KB)


# ── مساعدات ────────────────────────────────────────────────────

def _analyze_msg() -> str:
    try:
        return analysis.multi_summary()
    except Exception as e:  # noqa: BLE001
        return f"❌ تعذّر التحليل: {e}"


def build_digest() -> str:
    """الملخص اليومي للتنبيه المجدول."""
    lines = ["🌅 <b>الملخص اليومي للبيتكوين</b>\n"]
    try:
        price, change, exchange = analysis.ticker()
        lines.append(f"💰 السعر: <b>${price:,.0f}</b> ({change:+.2f}% 24س) — {exchange}")
    except Exception as e:  # noqa: BLE001
        lines.append(f"💰 السعر: غير متوفر ({e})")
    try:
        report = analysis.analyze()
        lines.append(f"🧭 التوصية: <b>{report.recommendation}</b> (ثقة {report.confidence}%)")
    except Exception:  # noqa: BLE001
        lines.append("🧭 التوصية: غير متوفرة")
    try:
        fng = asyncio.run(data_feeds.fear_greed())
        lines.append(f"😱 الخوف والطمع: <b>{fng['value']}/100</b> — {fng['ar']}")
    except Exception:  # noqa: BLE001
        pass
    lines.append("\n⚠️ <i>ليست نصيحة مالية.</i>")
    return "\n".join(lines)


# ── خادم الويب (webhook + cron + health) ───────────────────────

async def health(request: web.Request) -> web.Response:
    if bot is None:
        return web.Response(status=503, text="BOT_TOKEN missing — add it in Render dashboard")
    return web.Response(text="OK")


async def cron(request: web.Request) -> web.Response:
    """يستدعيه Render Cron Job لإرسال الملخص اليومي."""
    if bot is None:
        return web.Response(status=503, text="BOT_TOKEN missing")
    secret = request.headers.get("X-Cron-Secret", "")
    if config.CRON_SECRET and not secrets.compare_digest(secret, config.CRON_SECRET):
        return web.Response(status=403, text="forbidden")
    if not config.ADMIN_CHAT_ID:
        return web.Response(text="DAILY_CHAT_ID غير مضبوط")
    try:
        text = await asyncio.to_thread(build_digest)
        await bot.send_message(config.ADMIN_CHAT_ID, text, parse_mode=ParseMode.HTML)
    except Exception as e:  # noqa: BLE001
        logging.exception("digest failed")
        return web.Response(status=500, text=str(e))
    return web.Response(text="ok")


async def signal_check(request: web.Request) -> web.Response:
    """يستدعيه Render Cron Job لفحص الصيدة وإرسال تنبيه إن وُجدت."""
    if bot is None:
        return web.Response(status=503, text="BOT_TOKEN missing")
    secret = request.headers.get("X-Cron-Secret", "")
    if config.CRON_SECRET and not secrets.compare_digest(secret, config.CRON_SECRET):
        return web.Response(status=403, text="forbidden")
    res = await alerts.check_and_alert(bot)
    return web.json_response(res)


async def main():
    if bot is None:
        if config.WEBHOOK_MODE:
            # بدون توكن: نخدم /health فقط حتى يضيف المستخدم BOT_TOKEN في لوحة Render
            app = web.Application()
            app.router.add_get("/health", health)
            app.router.add_post("/cron", cron)
            app.router.add_post("/signal-check", signal_check)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, host="0.0.0.0", port=config.PORT)
            await site.start()
            logging.critical("BOT_TOKEN مفقود — أضفه في لوحة Render وسيشتغل البوت تلقائياً")
            await asyncio.Event().wait()
        raise RuntimeError("BOT_TOKEN غير مضبوط — ضعه في متغيرات البيئة")

    # مراقبة الصيدة + أهداف السعر تعمل في الوضعين — ما دامت الخدمة مستيقظة
    asyncio.create_task(alerts.watcher_loop(bot))

    if config.WEBHOOK_MODE:
        app = web.Application()
        handler = SimpleRequestHandler(
            dispatcher=dp, bot=bot, secret_token=config.WEBHOOK_SECRET
        )
        handler.register(app, path=config.WEBHOOK_PATH)
        app.router.add_get("/health", health)
        app.router.add_post("/cron", cron)
        app.router.add_post("/signal-check", signal_check)
        setup_application(app, dp, bot=bot)

        await bot.set_webhook(
            config.WEBHOOK_URL,
            secret_token=config.WEBHOOK_SECRET,
            drop_pending_updates=False,
        )
        logging.info("Webhook مفعّل على %s", config.WEBHOOK_URL)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=config.PORT)
        await site.start()
        await asyncio.Event().wait()
    else:
        logging.info("وضع polling محلي — لإيقافه Ctrl+C")
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
