"""اختبار E2E — يمرّر تحديثات تيليجرام حقيقية عبر موجّه البوت لكل قسم وأزراره.

الاستخدام:
    set BOT_TOKEN=123456:ABC...
    set TEST_CHAT_ID=123456789
    python e2e_test.py
"""
import asyncio
import os
import sys
import time

TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = int(os.getenv("TEST_CHAT_ID", "0") or 0)

# (النص المرسل، سقف الزمن المتوقع بالثواني)
CASES = [
    ("/start", 15),
    ("🪙 البيتكوين", 15),
    ("🧭 القرار", 70),
    ("📊 التحليل", 70),
    ("🕯️ الشارت", 90),
    ("🛡 خطة الصفقة", 70),
    ("🤖 النموذج", 70),
    ("📐 فيبوناتشي", 45),
    ("🥇 الذهب", 15),
    ("🧭 القرار", 70),
    ("🕯️ الشارت", 90),
    ("🤖 النموذج", 70),
    ("🔀 تغيير الأصل", 15),
]


async def main() -> int:
    if not TOKEN or not CHAT_ID:
        print("✗ لازم تضبط BOT_TOKEN و TEST_CHAT_ID")
        return 2

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import bot
    from aiogram.types import Update

    user = {"id": CHAT_ID, "is_bot": False, "first_name": "Test"}
    chat = {"id": CHAT_ID, "type": "private", "first_name": "Test"}
    results = []

    # اعتراض على مستوى الجلسة (aiogram يمنع تعديل الميثودات على نسخة البوت)
    calls: list[tuple[str, object]] = []
    _sess = bot.bot.session
    _orig = _sess.make_request

    async def _spy(bot_obj, method, timeout=None):
        res = await _orig(bot_obj, method, timeout=timeout)
        calls.append((method.__api_method__, res))
        return res

    _sess.make_request = _spy

    for i, (text, _limit) in enumerate(CASES, start=1):
        update = {
            "update_id": 910000 + i,
            "message": {
                "message_id": 7000 + i,
                "date": int(time.time()),
                "chat": chat,
                "from": user,
                "text": text,
                "entities": (
                    [{"type": "bot_command", "offset": 0, "length": len(text)}]
                    if text.startswith("/") else []
                ),
            },
        }
        calls.clear()
        t0 = time.time()
        try:
            await bot.dp.feed_update(bot.bot, Update.model_validate(update))
            bad = []
            photo_ok = False
            for api, res in calls:
                txt = getattr(res, "text", None) or getattr(res, "caption", None) or ""
                if api in ("sendMessage", "sendPhoto", "editMessageText") and str(txt).startswith("❌"):
                    bad.append(str(txt))
                if api == "sendPhoto" and getattr(res, "photo", None):
                    photo_ok = True
            if bad:
                results.append((text, f"FAIL {bad[0][:70]}", time.time() - t0))
            else:
                tag = "OK 📷" if photo_ok else "OK"
                results.append((text, tag, time.time() - t0))
        except Exception as e:  # noqa: BLE001
            results.append((text, f"FAIL {type(e).__name__}: {e}", time.time() - t0))

    print("\n===== نتيجة الاختبار =====")
    for text, status, sec in results:
        print(f"  {text:16s} | {status[:60]:60s} | {sec:5.1f}s")
    ok = sum(1 for _, s, _ in results if s.startswith("OK"))
    print(f"\nنجح {ok}/{len(results)}")
    await bot.bot.session.close()
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
