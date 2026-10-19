"""بوت خبير توصيات البيتكوين — aiogram 3 (webhook على Render / polling محلياً)."""
import asyncio
import logging
import secrets

from aiohttp import web

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

import ai_insights
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

MENU = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 السعر الآن", callback_data="price"),
            InlineKeyboardButton(text="📊 تحليل فني", callback_data="analysis"),
        ],
        [
            InlineKeyboardButton(text="🧭 التوصية", callback_data="recommend"),
            InlineKeyboardButton(text="😱 الخوف والطمع", callback_data="fng"),
        ],
        [
            InlineKeyboardButton(text="⛓️ أون-تشين", callback_data="onchain"),
            InlineKeyboardButton(text="🌍 نظرة السوق", callback_data="market"),
        ],
        [
            InlineKeyboardButton(text="🤖 تحليل الذكاء الاصطناعي", callback_data="ai"),
        ],
    ]
)


@router.message(CommandStart())
async def cmd_start(m: Message):
    await m.answer(
        "أهلاً بك في <b>خبير توصيات البيتكوين</b> 🪙\n\n"
        "بوت يدمج بيانات +100 منصة عبر <code>ccxt</code> ومؤشرات فنية "
        "متقدمة ومؤشر الخوف والطمع وبيانات أون-تشين ليعطيك توصيات واضحة.\n\n"
        "اختر من القائمة 👇",
        reply_markup=MENU,
    )


@router.message(Command("help"))
async def cmd_help(m: Message):
    await m.answer(
        "📖 <b>الأوامر:</b>\n"
        "/start — القائمة الرئيسية\n"
        "/price — السعر الحالي من المنصات\n"
        "/analysis — تحليل فني كامل (RSI, EMA, MACD, بولينجر)\n"
        "/recommend — توصية مباشرة مع الثقة\n"
        "/feargreed — مؤشر الخوف والطمع\n"
        "/onchain — رسوم الشبكة + الهاش ريت + الصعوبة\n"
        "/market — نظرة السوق (CoinGecko)\n"
        "/ai — تحليل ذكاء اصطناعي (DeepSeek)\n"
        "/myid — معرف المحادثة (لتنبيه اليومي)",
        reply_markup=MENU,
    )


@router.message(Command("myid"))
async def cmd_myid(m: Message):
    await m.answer(f"🆔 Chat ID الخاص بك: <code>{m.chat.id}</code>")


@router.message(Command("price"))
async def cmd_price(m: Message):
    await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    try:
        price, change, exchange = await asyncio.to_thread(analysis.ticker)
        txt = f"💰 <b>سعر البيتكوين</b>\n\n$<b>{price:,.0f}</b>\n"
        if change is not None:
            icon = "🟢" if change >= 0 else "🔴"
            txt += f"التغير 24س: {icon} {change:+.2f}%\n"
        txt += f"\n🏦 المنصة: <code>{exchange}</code>"
        await m.answer(txt, reply_markup=MENU)
    except Exception as e:  # noqa: BLE001
        await m.answer(f"❌ تعذّر جلب السعر: {e}")


@router.message(Command("analysis"))
async def cmd_analysis(m: Message):
    await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    await m.answer((await asyncio.to_thread(_analyze_msg)), reply_markup=MENU)


@router.message(Command("recommend"))
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
        reply_markup=MENU,
    )


@router.message(Command("feargreed"))
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
            reply_markup=MENU,
        )
    except Exception as e:  # noqa: BLE001
        await m.answer(f"❌ تعذّر جلب المؤشر: {e}")


@router.message(Command("onchain"))
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
            reply_markup=MENU,
        )
    except Exception as e:  # noqa: BLE001
        await m.answer(f"❌ تعذّر جلب بيانات الشبكة: {e}")


@router.message(Command("market"))
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
            reply_markup=MENU,
        )
    except Exception as e:  # noqa: BLE001
        await m.answer(f"❌ تعذّر جلب بيانات السوق: {e}")


@router.message(Command("ai"))
async def cmd_ai(m: Message):
    if not config.DEEPSEEK_API_KEY:
        await m.answer(
            "🤖 <b>تحليل الذكاء الاصطناعي غير مفعّل</b>\n\n"
            "أضف متغير البيئة <code>DEEPSEEK_API_KEY</code> "
            "في لوحة Render ثم أعد النشر، أو اطلب مني تفعيله.",
            reply_markup=MENU,
        )
        return
    wait_msg = await m.answer("🤖 جاري التحليل بالذكاء الاصطناعي... (قد يأخذ ~30 ثانية)")
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


# ── أزرار القائمة ──────────────────────────────────────────────

@router.callback_query(F.data == "price")
async def cb_price(cb: CallbackQuery):
    await cmd_price(cb.message)
    await cb.answer()


@router.callback_query(F.data == "analysis")
async def cb_analysis(cb: CallbackQuery):
    await cmd_analysis(cb.message)
    await cb.answer()


@router.callback_query(F.data == "recommend")
async def cb_recommend(cb: CallbackQuery):
    await cmd_recommend(cb.message)
    await cb.answer()


@router.callback_query(F.data == "fng")
async def cb_fng(cb: CallbackQuery):
    await cmd_fng(cb.message)
    await cb.answer()


@router.callback_query(F.data == "onchain")
async def cb_onchain(cb: CallbackQuery):
    await cmd_onchain(cb.message)
    await cb.answer()


@router.callback_query(F.data == "market")
async def cb_market(cb: CallbackQuery):
    await cmd_market(cb.message)
    await cb.answer()


@router.callback_query(F.data == "ai")
async def cb_ai(cb: CallbackQuery):
    await cmd_ai(cb.message)
    await cb.answer()


# ── مساعدات ────────────────────────────────────────────────────

def _analyze_msg() -> str:
    try:
        return analysis.analyze().summary
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


async def main():
    if bot is None:
        if config.WEBHOOK_MODE:
            # بدون توكن: نخدم /health فقط حتى يضيف المستخدم BOT_TOKEN في لوحة Render
            app = web.Application()
            app.router.add_get("/health", health)
            app.router.add_post("/cron", cron)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, host="0.0.0.0", port=config.PORT)
            await site.start()
            logging.critical("BOT_TOKEN مفقود — أضفه في لوحة Render وسيشتغل البوت تلقائياً")
            await asyncio.Event().wait()
        raise RuntimeError("BOT_TOKEN غير مضبوط — ضعه في متغيرات البيئة")

    if config.WEBHOOK_MODE:
        app = web.Application()
        handler = SimpleRequestHandler(
            dispatcher=dp, bot=bot, secret_token=config.WEBHOOK_SECRET
        )
        handler.register(app, path=config.WEBHOOK_PATH)
        app.router.add_get("/health", health)
        app.router.add_post("/cron", cron)
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
