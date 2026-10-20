"""إعدادات البوت من متغيرات البيئة."""
import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
CRON_SECRET = os.environ.get("CRON_SECRET", "")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DAILY_CHAT_ID = os.environ.get("DAILY_CHAT_ID", "")  # اتركه فارغاً لتعطيل التنبيه اليومي

RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "")

WEBHOOK_PATH = "/webhook"
PORT = int(os.environ.get("PORT", "8080"))

# وضع webhook إذا كنا على Render أو أي منصة تعطي رابطاً عاماً — وإلا polling
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
if not WEBHOOK_URL and RENDER_EXTERNAL_URL:
    WEBHOOK_URL = f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}"
WEBHOOK_MODE = bool(WEBHOOK_URL)

# DeepSeek API (اختياري)
DEEPSEEK_BASE = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

ADMIN_CHAT_ID = (
    int(DAILY_CHAT_ID)
    if DAILY_CHAT_ID.strip().isdigit() and int(DAILY_CHAT_ID) > 0
    else None
)

# تنبيه الصيدة (المراقبة التلقائية للإشارات القوية)
SIGNAL_THRESHOLD = float(os.environ.get("SIGNAL_THRESHOLD", "4.0"))  # |score| ≥ هذه القيمة = صيدة
SIGNAL_COOLDOWN_MIN = int(os.environ.get("SIGNAL_COOLDOWN_MIN", "30"))  # تهدئة بين التنبيهات
SIGNAL_INTERVAL_SEC = int(os.environ.get("SIGNAL_INTERVAL_SEC", "300"))  # فترة الفحص (وضع polling)
