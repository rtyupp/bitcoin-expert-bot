"""اختبار E2E — يمرّر تحديثات تيليجرام حقيقية عبر موجّه البوت ويتحقق من كل أمر.

الاستخدام:
    set BOT_TOKEN=123456:ABC...        (Windows)
    export BOT_TOKEN=123456:ABC...     (Linux/macOS)
    set TEST_CHAT_ID=123456789
    python e2e_test.py

ملاحظة: يرسل رسائل حقيقية للمحادثة المحددة — استخدم حسابك الشخصي.
"""
import asyncio
import os
import sys
import time

TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = int(os.getenv("TEST_CHAT_ID", "0") or 0)

CASES = [
    ("/start", 12),
    ("/price", 20),
    ("/fibo", 20),
    ("/chart", 30),
    ("/gold", 30),
    ("/plan", 30),
    ("/signal", 45),
    ("/analysis", 45),
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

    for i, (text, _timeout) in enumerate(CASES, start=1):
        update = {
            "update_id": 900000 + i,
            "message": {
                "message_id": 6000 + i,
                "date": int(time.time()),
                "chat": chat,
                "from": user,
                "text": text,
                "entities": [
                    {"type": "bot_command", "offset": 0, "length": len(text.split()[0])}
                ],
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
        print(f"  {text:12s} | {status[:64]:64s} | {sec:5.1f}s")
    ok = sum(1 for _, s, _ in results if s == "OK")
    print(f"\nنجح {ok}/{len(results)}")
    await bot.bot.session.close()
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
