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

# إدارة المخاطر
ACCOUNT_SIZE = float(os.environ.get("ACCOUNT_SIZE", "0"))  # حجم المحفظة بالدولار (0 = غير مضبوط)
RISK_PERCENT = float(os.environ.get("RISK_PERCENT", "1.0"))  # نسبة المخاطرة لكل صفقة

# DeepSeek API (اختياري)
DEEPSEEK_BASE = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

try:
    ADMIN_CHAT_ID = int(DAILY_CHAT_ID.strip()) if DAILY_CHAT_ID.strip() else None
except ValueError:
    ADMIN_CHAT_ID = None

# تنبيه الصيدة (المراقبة التلقائية للإشارات القوية)
SIGNAL_THRESHOLD = float(os.environ.get("SIGNAL_THRESHOLD", "4.0"))  # |score| ≥ هذه القيمة = صيدة
SIGNAL_MIN_AGREEMENT = int(os.environ.get("SIGNAL_MIN_AGREEMENT", "1"))  # أدنى عدد أطر متوافقة (1=مطفى — backtest أظهر عدم فائدته)
SIGNAL_COOLDOWN_MIN = int(os.environ.get("SIGNAL_COOLDOWN_MIN", "30"))  # تهدئة بين التنبيهات
SIGNAL_INTERVAL_SEC = int(os.environ.get("SIGNAL_INTERVAL_SEC", "300"))  # فترة الفحص (وضع polling)

# Capital.com Demo API (للتداول الآلي واليدوي على الحساب التجريبي)
CAPITAL_EMAIL = os.environ.get("CAPITAL_EMAIL", "")
CAPITAL_API_KEY = os.environ.get("CAPITAL_API_KEY", "")
CAPITAL_API_PASSWORD = os.environ.get("CAPITAL_API_PASSWORD", "")
CAPITAL_AUTO_TRADE = os.environ.get("CAPITAL_AUTO_TRADE", "1") == "1"

