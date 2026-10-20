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
    ("📊 التحليل", 60),
    ("🧭 التوصية", 40),
    ("🕯️ الشارت", 60),
    ("🛡 خطة الصفقة", 45),
    ("📐 فيبوناتشي", 40),
    ("🥇 الذهب", 15),
    ("📊 التحليل", 60),
    ("🕯️ الشارت", 60),
    ("🛡 خطة الصفقة", 45),
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
        t0 = time.time()
        try:
            await bot.dp.feed_update(bot.bot, Update.model_validate(update))
            results.append((text, "OK", time.time() - t0))
        except Exception as e:  # noqa: BLE001
            results.append((text, f"FAIL {type(e).__name__}: {e}", time.time() - t0))

    print("\n===== نتيجة الاختبار =====")
    for text, status, sec in results:
        print(f"  {text:16s} | {status[:60]:60s} | {sec:5.1f}s")
    ok = sum(1 for _, s, _ in results if s == "OK")
    print(f"\nنجح {ok}/{len(results)}")
    await bot.bot.session.close()
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
