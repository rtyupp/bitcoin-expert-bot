"""بوت خبير التداول — قسمان منفصلان (بيتكوين / ذهب) لكل واحد استراتيجيته."""
import ctypes
import os

# ── تقليل استهلاك الذاكرة على glibc (Render/Actions) ──
os.environ.setdefault("MALLOC_ARENA_MAX", "2")
try:
    ctypes.CDLL("libc.so.6").mallopt(-8, 2)  # M_ARENA_MAX
except Exception:  # noqa: BLE001
    pass

import asyncio
import logging
import secrets
import time
from html import escape as _h
from concurrent.futures import ThreadPoolExecutor

from aiohttp import web

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import BufferedInputFile, KeyboardButton, Message, ReplyKeyboardMarkup
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

import ai_insights
import capital_trader
import markets
import alerts
import analysis
import assets
import charts
import config
import data_feeds
import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

if config.BOT_TOKEN:
    bot: Bot | None = Bot(
        token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
else:
    bot = None

dp = Dispatcher()
router = Router()
dp.include_router(router)

# قسم كل محادثة: btc أو gold
_section: dict[int, str] = {}

# قفل واحد لبناء الشارت — يمنع تراكم الطلبات وارتفاع الذاكرة
_chart_lock = asyncio.Lock()


def _sec(chat_id: int) -> str:
    return _section.get(chat_id, assets.DEFAULT_ASSET)


def main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🪙 البيتكوين"), KeyboardButton(text="🥇 الذهب")],
            [KeyboardButton(text="💼 حساب كابيتال"), KeyboardButton(text="🌍 السوق")],
            [KeyboardButton(text="😱 الخوف والطمع"), KeyboardButton(text="⛓️ أون-تشين")],
            [KeyboardButton(text="🤖 الذكاء الاصطناعي"), KeyboardButton(text="❓ المساعدة")],
        ],
        resize_keyboard=True,
        input_field_placeholder="اختر السوق أولاً 👇",
    )


def section_kb(asset: str) -> ReplyKeyboardMarkup:
    name = assets.get(asset)["name"]
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🧭 القرار"), KeyboardButton(text="📊 التحليل")],
            [KeyboardButton(text="🕯️ الشارت"), KeyboardButton(text="💰 السعر اللحظي")],
            [KeyboardButton(text="🟢 شراء تجريبي"), KeyboardButton(text="🔴 بيع تجريبي")],
            [KeyboardButton(text="💼 حساب كابيتال"), KeyboardButton(text="🛡 خطة الصفقة")],
            [KeyboardButton(text="📐 فيبوناتشي"), KeyboardButton(text="⏰ تنبيه سعر")],
            [KeyboardButton(text="🤖 النموذج"), KeyboardButton(text="🔀 تغيير الأصل")],
        ],
        resize_keyboard=True,
        input_field_placeholder=f"قسم {name} — اختر أمراً",
    )


def kb(chat_id: int) -> ReplyKeyboardMarkup:
    return section_kb(_sec(chat_id))


# ── القوائم ────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(m: Message):
    await m.answer(
        "🪙🥇 <b>خبير التداول — بيتكوين + ذهب</b>\n\n"
        "كل سوق له <b>استراتيجيته المؤسسية الخاصة</b> (مع تأمين الوقف عند الهدف الأول 🔒):\n"
        "• 🪙 البيتكوين: قنص السيولة (SMC Stop-Hunt) + اختراق مؤسسي (فوز 69%، PF 3.62)\n"
        "• 🥇 الذهب: التدفق المؤسسي (SMC 10-Bar + مصيدة بولينجر + EMA20) (فوز 67%، PF 3.00)\n\n"
        "اختر السوق من الأزرار 👇",
        reply_markup=main_kb(),
    )


@router.message(Command("menu"))
@router.message(F.text == "🔀 تغيير الأصل")
async def cmd_menu(m: Message):
    _section.pop(m.chat.id, None)
    await m.answer("اختر السوق:", reply_markup=main_kb())


@router.message(Command("btc"))
@router.message(F.text == "🪙 البيتكوين")
async def cmd_btc(m: Message):
    await _enter_section(m, "btc")


@router.message(Command("gold"))
@router.message(F.text == "🥇 الذهب")
async def cmd_gold(m: Message):
    await _enter_section(m, "gold")


async def _enter_section(m: Message, key: str) -> None:
    _section[m.chat.id] = key
    cfg = assets.get(key)
    bt = cfg["backtest"]
    await m.answer(
        f"{cfg['emoji']} <b>قسم {cfg['name']}</b> — {cfg['symbol']}\n\n"
        f"🎯 الاستراتيجية: <b>{cfg['strategy_name']}</b>\n"
        f"<i>{cfg['strategy_note']}</i>\n\n"
        f"📊 نتائج الاختبار التاريخي:\n"
        f"• {bt['trades']} صفقة | فوز {bt['win']}% | PF {bt['pf']}\n"
        f"• متوسط الصفقة: +{bt['avg_r']}R | الهدف 1:{cfg['rr']:.0f}\n",
        reply_markup=section_kb(key),
    )


@router.message(Command("help"))
@router.message(F.text == "❓ المساعدة")
async def cmd_help(m: Message):
    await m.answer(
        "📖 <b>طريقة الاستخدام</b>\n\n"
        "1) اختر السوق: 🪙 البيتكوين أو 🥇 الذهب\n"
        "2) تظهر أزرار القسم الخاص به:\n"
        "   • 🧭 القرار — الحالة الآن + نظام السوق + احتمال النموذج\n"
        "   • 📊 التحليل — لوحة كاملة + فيبوناتشي\n"
        "   • 🕯️ الشارت — شموع يابانية + نقاط الصيد\n"
        "   • 🛡 خطة الصفقة — دخول/وقف/أهداف/حجم\n"
        "   • 🤖 النموذج — تفاصيل نموذج التعلّم وأداؤه (AUC)\n"
        "   • 📐 فيبوناتشي — مستويات الدعم والمقاومة\n"
        "   • ⏰ تنبيه سعر — تنبيه عند سعر محدد\n"
        "   • ⚙️ الإعدادات — رأس المال ونسبة المخاطرة\n"
        "   • 🔀 تغيير الأصل — رجوع للقائمة الرئيسية\n\n"
        "أوامر عامة: /decision /ml /price /market /feargreed /onchain /ai /myid\n"
        "⚠️ ليست نصيحة مالية.",
        reply_markup=kb(m.chat.id),
    )


@router.message(Command("myid"))
async def cmd_myid(m: Message):
    await m.answer(f"🆔 Chat ID: <code>{m.chat.id}</code>", reply_markup=kb(m.chat.id))


# ── التحليل والتوصية ────────────────────────────────────────────

@router.message(Command("analysis"))
@router.message(F.text == "📊 التحليل")
async def cmd_analysis(m: Message):
    await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    key = _sec(m.chat.id)
    try:
        txt = await asyncio.to_thread(analysis.multi_summary, key)
    except Exception as e:  # noqa: BLE001
        txt = f"❌ تعذّر التحليل: {_h(str(e))}"
    await m.answer(txt, reply_markup=kb(m.chat.id))


@router.message(Command("recommend"))
@router.message(Command("decision"))
@router.message(F.text.in_({"🧭 التوصية", "🧭 القرار"}))
async def cmd_recommend(m: Message):
    await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    key = _sec(m.chat.id)
    cfg = assets.get(key)
    try:
        d = await asyncio.to_thread(analysis.decision, key)
    except Exception as e:  # noqa: BLE001
        await m.answer(f"❌ تعذّر القرار: {_h(str(e))}", reply_markup=kb(m.chat.id))
        return
    if not d["active"]:
        # لا إشارة قوية الآن → نتجنب إزعاج المستخدم برسالة تفصيلية
        await m.answer("⚪ لا إشارة صيد حقيقية حالياً ⏸", reply_markup=kb(m.chat.id))
        return
    prob = f"{d['prob_up']:.1%}" if d["prob_up"] is not None else "—"
    auc = d["ml_metrics"]["auc"] if d["ml_metrics"] else "—"
    reg = d["regime"]
    await m.answer(
        f"{cfg['emoji']} <b>{d['name']} — {d['stance_ar']}</b>\n\n"
        f"💰 السعر: <b>${d['price']:,.2f}</b>\n"
        f"🎯 الاستراتيجية: {d['strategy']}\n"
        f"📌 الحالة: <b>{d['strategy_label']}</b> ({d['strategy_score']:+.1f}) — نشطة الآن ✅\n"
        f"🌊 النظام: <b>{reg.get('name')}</b> (كفاءة {reg.get('efficiency')})\n"
        f"🤖 النموذج: احتمال صعود <b>{prob}</b> (AUC {auc})\n"
        f"🎚 الثقة: <b>{d['confidence']}%</b>\n\n"
        f"<b>الأسباب:</b>\n"
        + "\n".join(f"  • {r}" for r in d["reasons"][:4])
        + "\n\n⚠️ <i>ليست نصيحة مالية.</i>",
        reply_markup=kb(m.chat.id),
    )


@router.message(Command("ml"))
@router.message(F.text == "🤖 النموذج")
async def cmd_ml(m: Message):
    await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    key = _sec(m.chat.id)
    cfg = assets.get(key)
    try:
        mv = await asyncio.to_thread(analysis.ml_view, key)
    except Exception as e:  # noqa: BLE001
        await m.answer(f"❌ تعذّر تحميل النموذج: {_h(str(e))}", reply_markup=kb(m.chat.id))
        return
    ml, reg = mv.get("ml", {}), mv.get("regime", {})
    if not ml.get("ok"):
        await m.answer(f"⚠️ النموذج غير متاح: {ml.get('reason', '—')}", reply_markup=kb(m.chat.id))
        return
    met = ml["metrics"]
    others = "\n".join(f"  • {k}: AUC <code>{v['auc']}</code>" for k, v in ml["all_models"].items())
    ens = "\n".join(
        f"  • {k}: {v:.1%} (وزن {ml.get('weights', {}).get(k, 0):.2f})"
        for k, v in ml.get("model_probs", {}).items()
    )
    prob = f"{ml['prob_up']:.1%}"
    await m.answer(
        f"🤖 <b>نموذج التوقع — {cfg['name']}</b>\n\n"
        f"النموذج الأفضل: <b>{ml['model']}</b>\n"
        f"الأفق: {ml['horizon']} شموع 4h = 24 ساعة\n"
        f"عينات: {ml['n_samples']} | ميزات: {len(ml['features'])}\n"
        f"احتمال الصعود (مزج مرجّح): <b>{prob}</b>\n\n"
        f"🧩 <b>مزج النماذج:</b>\n{ens}\n\n"
        f"📊 <b>تحقق زمني ({met['folds']} أقسام):</b>\n"
        f"  • AUC: <code>{met['auc']}</code>\n"
        f"  • الدقة: <code>{met['acc']:.1%}</code>\n"
        f"  • Brier: <code>{met['brier']}</code>\n\n"
        f"🔍 مقارنة النماذج:\n{others}\n\n"
        f"🌊 <b>نظام السوق:</b> {reg.get('name')}\n"
        f"  {reg.get('note')}\n"
        f"  كفاءة الاتجاه {reg.get('efficiency')} | ATR% {reg.get('atr_pct')}% | "
        f"فوق EMA200: {'نعم' if reg.get('above_ema200') else 'لا'}\n\n"
        f"💡 AUC = 0.50 عشوائي، >0.60 جيد جداً في الأسواق.",
        reply_markup=kb(m.chat.id),
    )


@router.message(Command("price"))
@router.message(F.text.in_({"💰 السعر اللحظي", "🔄"}))
async def cmd_price(m: Message):
    await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    key = _sec(m.chat.id)
    cfg = assets.get(key)
    try:
        t = await asyncio.to_thread(markets.best_live_price, cfg["symbol"])
        fresh = max(0, int(time.time() - t["ts"]))
        txt = (
            f"{cfg['emoji']} <b>{cfg['name']} — سعر لحظي</b>\n\n"
            f"$<b>{t['price']:,.2f}</b>\n"
        )
        if t["change"] is not None:
            txt += f"التغير 24س: {'🟢' if t['change'] >= 0 else '🔴'} {t['change']:+.2f}%\n"
        if t["high"] and t["low"]:
            txt += f"أعلى/أدنى 24س: <code>{t['high']:,.2f} / {t['low']:,.2f}</code>\n"
        txt += (
            f"\n🕐 <i>تحديث قبل {fresh} ثانية</i> · 🏦 <code>{t['exchange']}</code>\n"
            "اضغط 💰 السعر اللحظي لإعادة التحديث"
        )
        await m.answer(txt, reply_markup=kb(m.chat.id))
    except Exception as e:  # noqa: BLE001
        await m.answer(f"❌ تعذّر جلب السعر: {_h(str(e))}", reply_markup=kb(m.chat.id))


@router.message(Command("fibo"))
@router.message(F.text == "📐 فيبوناتشي")
async def cmd_fibo(m: Message):
    await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    key = _sec(m.chat.id)
    cfg = assets.get(key)
    try:
        df, _ = await asyncio.to_thread(analysis.fetch_ohlcv, cfg["symbol"], "1h", 250)
        fib = analysis.fib_levels(df)
        price = float(df["close"].iloc[-1])
        lines = [f"📐 <b>فيبوناتشي — {cfg['name']}</b>", "", f"💰 الحالي: <b>${price:,.2f}</b>", ""]
        for k in ("0.000", "0.236", "0.382", "0.500", "0.618", "0.786", "1.000"):
            tag = " ⬆️ دعم" if fib[k] < price else " ⬇️ مقاومة"
            lines.append(f"• {k}: <code>${fib[k]:,.2f}</code>{tag}")
        lines += ["", "⚠️ <i>ليست نصيحة مالية.</i>"]
        await m.answer("\n".join(lines), reply_markup=kb(m.chat.id))
    except Exception as e:  # noqa: BLE001
        await m.answer(f"❌ تعذّر حساب المستويات: {_h(str(e))}", reply_markup=kb(m.chat.id))


# ── الشارت ─────────────────────────────────────────────────────

@router.message(Command("chart"))
@router.message(F.text == "🕯️ الشارت")
async def cmd_chart(m: Message):
    await bot.send_chat_action(m.chat.id, ChatAction.UPLOAD_PHOTO)
    await _send_chart(m, _sec(m.chat.id))


async def _send_chart(m: Message, key: str) -> None:
    """يبني شارت الشموع ويرسله — بقفل واحد لتجنّب ارتفاع الذاكرة."""
    cfg = assets.get(key)
    try:
        live = await asyncio.to_thread(analysis.live_ticker, cfg["symbol"])
        async with _chart_lock:
            df = await asyncio.to_thread(charts.fetch_4h, cfg["symbol"], 20)
            ana = await asyncio.to_thread(charts.analyze_chart, df, key)
            png = await asyncio.to_thread(charts.plot_chart, df, ana, cfg["symbol"], live["price"])
        dec = await asyncio.to_thread(analysis.decision, key)
        msg = charts.short_message(ana, cfg["symbol"], dec, live)
        _trim_memory()
        # aiogram 3 يطلب InputFile — الـ bytes الخام تُرفض
        photo = BufferedInputFile(png, filename=f"{cfg['key']}_chart.png")
        await m.answer_photo(photo=photo, caption=msg, reply_markup=section_kb(key),
                             parse_mode=ParseMode.HTML)
    except Exception as e:  # noqa: BLE001
        logging.exception("فشل بناء الشارت لـ %s", key)
        await m.answer(f"❌ تعذّر بناء الشارت: {_h(str(e))}", reply_markup=section_kb(key))


# ── إدارة المخاطر ──────────────────────────────────────────────

@router.message(Command("setup"))
async def cmd_setup(m: Message):
    import math

    if config.ADMIN_CHAT_ID and m.chat.id != config.ADMIN_CHAT_ID:
        await m.answer("⛔ ضبط رأس المال متاح للمالك فقط")
        return
    parts = m.text.split()
    if len(parts) < 2:
        await _setup_help(m)
        return
    raw = parts[1].replace(",", "").replace("$", "").strip().lower()
    mult = 1_000.0 if raw.endswith("k") else 1_000_000.0 if raw.endswith("m") else 1.0
    raw = raw[:-1] if mult > 1 else raw
    try:
        amount = float(raw) * mult
        if not math.isfinite(amount) or amount <= 0:
            raise ValueError
    except ValueError:
        await m.answer("❌ مبلغ غير صحيح. مثال: <code>/setup 10000</code> أو <code>/setup 10k</code>", reply_markup=kb(m.chat.id))
        return
    settings.set_account(amount)
    rp = settings.risk_pct()
    if len(parts) >= 3:
        try:
            rp = float(parts[2])
            if not math.isfinite(rp) or not 0 < rp <= 100:
                raise ValueError
            settings.set_risk(rp)
        except ValueError:
            pass
    await m.answer(
        f"⚙️ <b>تم الحفظ</b>\n\n💼 رأس المال: <code>${amount:,.0f}</code>\n"
        f"🎯 المخاطرة: <code>{rp:.1f}%</code> لكل صفقة\n\nاضغط 🛡 خطة الصفقة.",
        reply_markup=kb(m.chat.id),
    )


@router.message(F.text == "⚙️ الإعدادات")
async def txt_setup(m: Message):
    await _setup_help(m)


async def _setup_help(m: Message):
    acct = settings.account_size()
    rp = settings.risk_pct()
    await m.answer(
        f"⚙️ <b>إدارة المخاطر</b>\n\n"
        f"💼 رأس المال: <code>${acct:,.0f}</code>{' (غير مضبوط)' if acct == 0 else ''}\n"
        f"🎯 المخاطرة: <code>{rp:.1f}%</code> لكل صفقة\n\n"
        f"<code>/setup 10000</code> — رأس مال 10 آلاف\n"
        f"<code>/setup 10000 2</code> — مع مخاطرة 2%",
        reply_markup=kb(m.chat.id),
    )


@router.message(Command("plan"))
@router.message(F.text == "🛡 خطة الصفقة")
async def cmd_plan(m: Message):
    await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    key = _sec(m.chat.id)
    cfg = assets.get(key)
    try:
        d = await asyncio.to_thread(analysis.decision, key)
    except Exception as e:  # noqa: BLE001
        await m.answer(f"❌ تعذّر التحليل: {_h(str(e))}", reply_markup=kb(m.chat.id))
        return
    direction = "long" if d["stance"] != "short" else "short"
    stop_mult = cfg.get("stop_mult", 1.8)
    plan = analysis.risk_plan(
        d["price"], direction, d["atr"], settings.account_size(), settings.risk_pct(), rr=cfg["rr"], stop_mult=stop_mult
    )
    sign = 1 if direction == "long" else -1
    lines = [
        f"{cfg['emoji']} <b>خطة {cfg['name']}</b> — الحالة: <b>{d['stance_ar']}</b>",
        f"🎯 {cfg['strategy_name']} · ثقة {d['confidence']}%",
        "",
        f"📌 {d['strategy_label']} ({d['strategy_score']:+.1f})"
        + ("" if d["active"] else " — ⏸ لا إشارة نشطة الآن"),
        f"💰 الدخول: <code>${plan['entry']:,.2f}</code>",
        f"🛑 الوقف: <code>${plan['stop']:,.2f}</code> ({stop_mult:g}×ATR)",
        "",
        "🎯 <b>الأهداف (ينقل الوقف للدخول عند TP1):</b>",
    ]
    for name, price in plan["targets"].items():
        pct = sign * (price - plan["entry"]) / plan["entry"] * 100
        lines.append(f"  • {name}: <code>${price:,.2f}</code> ({pct:+.1f}%)")
    lines.append("")
    if "qty" in plan:
        lines.append("💼 <b>حجم الصفقة:</b>")
        lines.append(
            f"  • رأس المال ${plan['account_size']:,.0f} | مخاطرة {plan['risk_pct']:.1f}% "
            f"= ${plan['risk_amount']:,.0f}"
        )
        lines.append(f"  • الكمية: <code>{plan['qty']:.5f}</code> (≈ ${plan['qty_usd']:,.0f})")
        if plan.get("capped"):
            lines.append("  ⚠️ خُفّضت الكمية — أكبر من محفظتك.")
    else:
        lines.append("💡 اضبط محفظتك بـ /setup لحساب الكمية.")
    lines += ["", "⚠️ <i>ليست نصيحة مالية.</i>"]
    try:
        await m.answer("\n".join(lines), reply_markup=kb(m.chat.id))
    except Exception as e:
        logging.exception("فشل إرسال خطة الصفقة")
        # لا نرسل بديل لتجنب فشل آخر
        return


# ── تنبيهات السعر ──────────────────────────────────────────────

@router.message(Command("alert"))
@router.message(F.text == "⏰ تنبيه سعر")
async def cmd_alert(m: Message):
    key = _sec(m.chat.id)
    cfg = assets.get(key)
    text = (m.text or "").strip()
    parts = text.split()
    if text == "⏰ تنبيه سعر" or len(parts) < 2:
        await m.answer(
            f"⏰ <b>تنبيه سعر — {cfg['name']}</b>\n\n"
            f"أرسل: <code>/alert 85000</code>\n"
            f"للعملة الحالية: {cfg['symbol']}",
            reply_markup=kb(m.chat.id),
        )
        return
    import math

    raw = parts[1].replace(",", "").replace("$", "").strip().lower()
    mult = 1_000.0 if raw.endswith("k") else 1_000_000.0 if raw.endswith("m") else 1.0
    raw = raw[:-1] if mult > 1 else raw
    try:
        target = float(raw) * mult
        if not math.isfinite(target) or target <= 0:
            raise ValueError
    except ValueError:
        await m.answer("❌ سعر غير صحيح. مثال: <code>/alert 85000</code> أو <code>/alert 85k</code>", reply_markup=kb(m.chat.id))
        return
    if len(alerts.list_alerts(m.chat.id)) >= 20:
        await m.answer("⚠️ الحد الأقصى 20 تنبيهاً — احذف القديمة بـ /alerts", reply_markup=kb(m.chat.id))
        return
    try:
        cur, _, _ = await asyncio.to_thread(analysis.ticker, cfg["symbol"])
    except Exception as e:  # noqa: BLE001
        await m.answer(f"❌ تعذّر جلب السعر: {_h(str(e))}", reply_markup=kb(m.chat.id))
        return
    direction = "up" if target > cur else "down"
    alerts.set_alert(m.chat.id, target, direction, key)
    await m.answer(
        f"⏰ <b>تم ضبط التنبيه</b>\n\n{cfg['emoji']} {cfg['name']}\n"
        f"🎯 الهدف: <code>${target:,.2f}</code> "
        f"({'فوق' if direction == 'up' else 'تحت'} ${cur:,.2f})\n\nتنبيهاتك: /alerts",
        reply_markup=kb(m.chat.id),
    )


@router.message(Command("alerts"))
async def cmd_alerts(m: Message):
    items = alerts.list_alerts(m.chat.id)
    if not items:
        await m.answer("📭 لا توجد تنبيهات.\n\nلإضافة: <code>/alert 85000</code>",
                       reply_markup=kb(m.chat.id))
        return
    lines = ["⏰ <b>تنبيهاتك:</b>\n"]
    for i, a in enumerate(items, 1):
        nm = assets.get(a.get("asset", "btc"))["name"]
        arrow = "📈 فوق" if a["direction"] == "up" else "📉 تحت"
        lines.append(f"{i}. {nm}: <code>${a['price']:,.2f}</code> — {arrow}")
    lines.append("\nللحذف: /delalerts")
    try:
        await m.answer("\n".join(lines), reply_markup=kb(m.chat.id))
    except Exception:
        logging.exception("فشل إرسال قائمة التنبيهات")
        return


@router.message(Command("delalerts"))
async def cmd_delalerts(m: Message):
    n = alerts.clear_alerts(m.chat.id)
    await m.answer(f"🗑 حذفت {n} تنبيه.", reply_markup=kb(m.chat.id))


# ── حساب Capital.com التجريبي (Demo Trading) ──────────────────────

def _is_owner(chat_id: int) -> bool:
    return not config.ADMIN_CHAT_ID or chat_id == config.ADMIN_CHAT_ID


@router.message(Command("capital"))
@router.message(F.text == "💼 حساب كابيتال")
async def cmd_capital(m: Message):
    if not _is_owner(m.chat.id):
        await m.answer("⛔ خاص بمالك البوت فقط.")
        return
    if not capital_trader.is_configured():
        await m.answer("⚠️ حساب Capital.com غير مضبوط في الإعدادات.", reply_markup=kb(m.chat.id))
        return
    await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    try:
        s = await asyncio.to_thread(capital_trader.account_summary)
    except Exception as e:  # noqa: BLE001
        await m.answer(f"❌ تعذّر الاتصال بـ Capital.com: {_h(str(e))}", reply_markup=kb(m.chat.id))
        return
    pl_icon = "🟢" if s["profitLoss"] >= 0 else "🔴"
    lines = [
        "💼 <b>حساب Capital.com التجريبي (Demo)</b>",
        f"🆔 رقم الحساب: <code>{s['accountId']}</code>",
        "",
        f"💰 الرصيد الإجمالي: <b>${s['balance']:,.2f}</b>",
        f"💵 المتاح للتداول: <code>${s['available']:,.2f}</code>",
        f"{pl_icon} الربح/الخسارة العائمة: <b>${s['profitLoss']:+,.2f}</b>",
        f"🤖 التداول التلقائي مع الصيدات: <b>{'مفعّل ✅' if config.CAPITAL_AUTO_TRADE else 'متوقف ⏸'}</b>",
        "",
    ]
    pos = s["positions"]
    if not pos:
        lines.append("📭 <i>لا توجد صفقات مفتوحة حالياً.</i>")
    else:
        lines.append(f"📊 <b>الصفقات المفتوحة ({len(pos)}):</b>")
        for i, p in enumerate(pos, 1):
            d_icon = "🟢 شراء" if p["direction"] == "BUY" else "🔴 بيع"
            upl = p["upl"] or 0.0
            st_txt = f" | وقف <code>{p['stopLevel']}</code>" if p.get("stopLevel") else ""
            tp_txt = f" | هدف <code>{p['profitLevel']}</code>" if p.get("profitLevel") else ""
            lines.append(
                f"{i}. <b>{p['epic']}</b> ({d_icon} × <code>{p['size']}</code>) @ <code>${p['level']:,.2f}</code>"
                f"{st_txt}{tp_txt} → <b>${upl:+,.2f}</b>"
            )
        lines.append("\nلإغلاق كل الصفقات: /closeall")
    lines.append("للشراء/البيع المباشر: اضغط 🟢 شراء تجريبي أو 🔴 بيع تجريبي")
    await m.answer("\n".join(lines), reply_markup=kb(m.chat.id))


async def _exec_demo_order(m: Message, direction: str) -> None:
    if not _is_owner(m.chat.id):
        await m.answer("⛔ التداول متاح للمالك فقط.")
        return
    if not capital_trader.is_configured():
        await m.answer("⚠️ حساب Capital.com غير مضبوط.", reply_markup=kb(m.chat.id))
        return
    await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    key = _sec(m.chat.id)
    cfg = assets.get(key)
    parts = (m.text or "").split()
    custom_size = None
    if len(parts) >= 2 and parts[0].startswith("/"):
        try:
            custom_size = float(parts[1])
        except ValueError:
            pass
    try:
        # نحسب الوقف والهدف حسب ATR فريم الساعة لإرفاقهما مع الصفقة تلقائياً
        df, _ = await asyncio.to_thread(analysis.fetch_ohlcv, cfg["symbol"], "1h", 60)
        atr = float(analysis.indicators(df)["atr"].iloc[-2])
        mkt = await asyncio.to_thread(capital_trader.live_price, key)
        side = "BUY" if direction == "long" else "SELL"
        entry_ref = mkt["offer"] if side == "BUY" else mkt["bid"]
        d = 1 if side == "BUY" else -1
        sd = atr * cfg["stop_mult"]
        stop_lvl = entry_ref - d * sd
        tp_lvl = entry_ref + d * cfg["rr"] * sd

        res = await asyncio.to_thread(
            capital_trader.open_trade, key, side, custom_size, stop_lvl, tp_lvl
        )
        word = "شراء 🟢" if side == "BUY" else "بيع 🔴"
        await m.answer(
            f"✅ <b>تم تنفيذ صفقة {word} في Capital.com (Demo)</b>\n\n"
            f"{cfg['emoji']} الأصل: <b>{cfg['name']} ({res['epic']})</b>\n"
            f"📦 الحجم: <code>{res['size']}</code>\n"
            f"📍 سعر التنفيذ: <b>${res['level']:,.2f}</b>\n"
            f"🛑 وقف الخسارة: <code>${res.get('stopLevel') or stop_lvl:,.2f}</code>\n"
            f"🎯 هدف الربح: <code>${res.get('profitLevel') or tp_lvl:,.2f}</code>\n"
            f"🆔 رقم العقد: <code>{res.get('dealId') or res.get('dealReference')}</code>\n\n"
            f"لعرض المحفظة والصفقات: اضغط 💼 حساب كابيتال",
            reply_markup=kb(m.chat.id),
        )
    except Exception as e:  # noqa: BLE001
        await m.answer(f"❌ فشل تنفيذ الصفقة: {_h(str(e))}", reply_markup=kb(m.chat.id))


@router.message(Command("buy"))
@router.message(F.text == "🟢 شراء تجريبي")
async def cmd_buy(m: Message):
    await _exec_demo_order(m, "long")


@router.message(Command("sell"))
@router.message(F.text == "🔴 بيع تجريبي")
async def cmd_sell(m: Message):
    await _exec_demo_order(m, "short")


@router.message(Command("closeall"))
async def cmd_closeall(m: Message):
    if not _is_owner(m.chat.id):
        await m.answer("⛔ خاص بمالك البوت فقط.")
        return
    await bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    try:
        n = await asyncio.to_thread(capital_trader.close_all)
        await m.answer(f"✅ تم إغلاق <b>{n}</b> صفقة مفتوحة في Capital.com.", reply_markup=kb(m.chat.id))
    except Exception as e:  # noqa: BLE001
        await m.answer(f"❌ تعذّر إغلاق الصفقات: {_h(str(e))}", reply_markup=kb(m.chat.id))


# ── بيانات السوق ───────────────────────────────────────────────

@router.message(Command("feargreed"))
@router.message(F.text == "😱 الخوف والطمع")
async def cmd_fng(m: Message):
    try:
        fng = await data_feeds.fear_greed()
        bar = "🟥" * (fng["value"] // 20) + "⬜" * (5 - fng["value"] // 20)
        await m.answer(
            f"😱 <b>الخوف والطمع</b>\n\nالقيمة: <b>{fng['value']}/100</b>\n"
            f"الحالة: <b>{fng['ar']}</b>\n{bar}",
            reply_markup=kb(m.chat.id),
        )
    except Exception as e:  # noqa: BLE001
        await m.answer(f"❌ تعذّر جلب المؤشر: {_h(str(e))}", reply_markup=kb(m.chat.id))


@router.message(Command("onchain"))
@router.message(F.text == "⛓️ أون-تشين")
async def cmd_onchain(m: Message):
    try:
        oc = await data_feeds.onchain()
        await m.answer(
            f"⛓️ <b>شبكة البيتكوين</b>\n\n"
            f"⚡ الرسوم (سات/بايت): سريع <code>{oc['fast']}</code> | "
            f"متوسط <code>{oc['half']}</code> | اقتصادي <code>{oc['eco']}</code>\n"
            f"🖥 الهاش ريت: <code>{oc['hashrate_eh']} EH/s</code>\n"
            f"⛏ الصعوبة: <code>{oc['difficulty_t']} T</code>",
            reply_markup=kb(m.chat.id),
        )
    except Exception as e:  # noqa: BLE001
        await m.answer(f"❌ تعذّر جلب بيانات الشبكة: {_h(str(e))}", reply_markup=kb(m.chat.id))


@router.message(Command("market"))
@router.message(F.text == "🌍 السوق")
async def cmd_market(m: Message):
    try:
        mk = await data_feeds.market_overview()
        await m.answer(
            f"🌍 <b>نظرة السوق</b>\n\n"
            f"💰 البيتكوين: <b>${mk['price']:,.0f}</b>\n"
            f"📅 24س: {mk['change_24h']:+.1f}% | 7 أيام: {mk['change_7d']:+.1f}%\n"
            f"🏔 القمة: <b>${mk['ath']:,.0f}</b> ({mk['ath_change']:+.1f}%)\n"
            f"💎 القيمة السوقية: <code>{data_feeds.fmt_big(mk['market_cap'])}</code>\n"
            f"🔄 الحجم 24س: <code>{data_feeds.fmt_big(mk['volume_24h'])}</code>",
            reply_markup=kb(m.chat.id),
        )
    except Exception as e:  # noqa: BLE001
        await m.answer(f"❌ تعذّر جلب بيانات السوق: {_h(str(e))}", reply_markup=kb(m.chat.id))


@router.message(Command("ai"))
@router.message(F.text == "🤖 الذكاء الاصطناعي")
async def cmd_ai(m: Message):
    if not config.DEEPSEEK_API_KEY:
        await m.answer("🤖 غير مفعّل — أضف <code>DEEPSEEK_API_KEY</code>.", reply_markup=kb(m.chat.id))
        return
    key = _sec(m.chat.id)
    cfg = assets.get(key)
    wait = await m.answer("🤖 جاري التحليل... (~30 ثانية)")
    try:
        report = await asyncio.to_thread(analysis.analyze, "1h", key)
        fng = market = None
        try:
            fng = await data_feeds.fear_greed()
            market = await data_feeds.market_overview()
        except Exception:  # noqa: BLE001
            pass
        ctx = ai_insights.build_context(report.summary, fng, market)
        text = await ai_insights.ai_analysis(ctx)
        await wait.edit_text(f"🤖 <b>تحليل {cfg['name']}</b>\n\n{_h(text) if text else 'لم يصل رد.'}")
    except Exception as e:  # noqa: BLE001
        await wait.edit_text(f"❌ فشل التحليل: {_h(str(e))}")


# ── مساعدات وتشخيص ────────────────────────────────────────────

def _trim_memory() -> None:
    """يرجّع الذاكرة الحرة للنظام (glibc) — مهم بعد عمليات pandas."""
    try:
        import gc

        gc.collect()
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:  # noqa: BLE001
        pass


async def _memory_keeper() -> None:
    while True:
        await asyncio.sleep(60)
        _trim_memory()


async def health(request: web.Request) -> web.Response:
    if bot is None:
        return web.Response(status=503, text="BOT_TOKEN missing")
    return web.Response(text="OK")


async def memcheck(request: web.Request) -> web.Response:
    if request.query.get("trim"):
        _trim_memory()
    try:
        vals = {}
        with open("/proc/self/status", encoding="utf-8") as f:
            for line in f:
                if line.startswith(("VmRSS:", "VmHWM:", "VmPeak:")):
                    k, vv = line.split(":", 1)
                    vals[k] = vv.strip()
        return web.Response(
            text=(
                f"RSS: {vals.get('VmRSS', '?')}\n"
                f"Peak: {vals.get('VmHWM', '?')}\n"
                f"Threads: {__import__('threading').active_count()}\n"
            )
        )
    except Exception as e:  # noqa: BLE001
        return web.Response(status=500, text=f"n/a: {e}")


async def selftest(request: web.Request) -> web.Response:
    """اختبار كامل للأصلين: جلب → تحليل → شارت، مع قياس الذاكرة."""
    import time

    def rss() -> str:
        try:
            with open("/proc/self/status", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return line.split(":", 1)[1].strip()
        except Exception:  # noqa: BLE001
            pass
        return "?"

    out = ["OK"]
    before = rss()
    for key in assets.keys():
        cfg = assets.get(key)
        t0 = time.time()
        try:
            df = await asyncio.to_thread(charts.fetch_4h, cfg["symbol"], 20)
            ana = await asyncio.to_thread(charts.analyze_chart, df, key)
            png = await asyncio.to_thread(charts.plot_chart, df, ana, cfg["symbol"])
            fe = ana["first_entry"]
            out.append(
                f"{key}: candles={len(df)} dir={ana['direction']} "
                f"entry={fe['price'] if fe else None} stop={ana['stop_loss']} "
                f"tp={ana['tp1']} png={len(png)} t={time.time() - t0:.1f}s"
            )
        except Exception as e:  # noqa: BLE001
            out.append(f"{key}: FAIL {type(e).__name__}: {e}")
    _trim_memory()
    out.append(f"rss_before={before} rss_after={rss()}")
    return web.Response(text="\n".join(out))


async def cron(request: web.Request) -> web.Response:
    if bot is None:
        return web.Response(status=503, text="BOT_TOKEN missing")
    secret = request.headers.get("X-Cron-Secret", "")
    if not config.CRON_SECRET or not secrets.compare_digest(
        secret.encode("utf-8"), config.CRON_SECRET.encode("utf-8")
    ):
        return web.Response(status=403, text="forbidden")
    if not config.ADMIN_CHAT_ID:
        return web.Response(text="DAILY_CHAT_ID غير مضبوط")
    try:
        await alerts.check_and_alert(bot)
        lines = ["🌅 <b>ملخص يومي</b>"]
        for key in assets.keys():
            cfg = assets.get(key)
            try:
                r = await asyncio.to_thread(analysis.analyze, "4h", key)
                lines.append(
                    f"{cfg['emoji']} {cfg['name']}: <b>${r.price:,.2f}</b> — "
                    f"{r.recommendation} ({r.final_score:+.1f})"
                )
            except Exception:  # noqa: BLE001
                lines.append(f"{cfg['emoji']} {cfg['name']}: غير متوفر")
        await bot.send_message(config.ADMIN_CHAT_ID, "\n".join(lines), parse_mode=ParseMode.HTML)
    except Exception as e:  # noqa: BLE001
        logging.exception("digest failed")
        return web.Response(status=500, text=str(e))
    return web.Response(text="ok")


async def signal_check(request: web.Request) -> web.Response:
    if bot is None:
        return web.Response(status=503, text="BOT_TOKEN missing")
    secret = request.headers.get("X-Cron-Secret", "")
    if not config.CRON_SECRET or not secrets.compare_digest(
        secret.encode("utf-8"), config.CRON_SECRET.encode("utf-8")
    ):
        return web.Response(status=403, text="forbidden")
    return web.json_response(await alerts.check_and_alert(bot))


def _add_routes(app: web.Application) -> None:
    app.router.add_get("/health", health)
    app.router.add_get("/mem", memcheck)
    app.router.add_get("/selftest", selftest)
    app.router.add_post("/cron", cron)
    app.router.add_post("/signal-check", signal_check)


async def main():
    asyncio.get_running_loop().set_default_executor(
        ThreadPoolExecutor(max_workers=3, thread_name_prefix="io")
    )
    if bot is None:
        if config.WEBHOOK_MODE:
            app = web.Application()
            _add_routes(app)
            runner = web.AppRunner(app)
            await runner.setup()
            await web.TCPSite(runner, host="0.0.0.0", port=config.PORT).start()
            logging.critical("BOT_TOKEN مفقود")
            await asyncio.Event().wait()
        raise RuntimeError("BOT_TOKEN غير مضبوط")

    _bg_tasks = [  # مراجع قوية — بدونها قد تُجمع المهام كقمامة
        asyncio.create_task(alerts.watcher_loop(bot)),
        asyncio.create_task(_memory_keeper()),
    ]

    if config.WEBHOOK_MODE:
        if not config.WEBHOOK_SECRET:
            raise RuntimeError("WEBHOOK_SECRET مطلوب في وضع الويبهوك (حماية من التحديثات المزورة)")
        app = web.Application()
        handler = SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=config.WEBHOOK_SECRET)
        handler.register(app, path=config.WEBHOOK_PATH)
        _add_routes(app)
        setup_application(app, dp, bot=bot)
        await bot.set_webhook(config.WEBHOOK_URL, secret_token=config.WEBHOOK_SECRET,
                              drop_pending_updates=False)
        logging.info("Webhook: %s", config.WEBHOOK_URL)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, host="0.0.0.0", port=config.PORT).start()
        await asyncio.Event().wait()
    else:
        logging.info("وضع polling — لإيقافه Ctrl+C")
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
