"""الإعدادات من متغيرات البيئة."""
import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
_chat = os.environ.get("DAILY_CHAT_ID", "").strip()
try:
    ADMIN_CHAT_ID = int(_chat) if _chat else None
except ValueError:
    ADMIN_CHAT_ID = None

# Capital.com Demo
CAPITAL_EMAIL = os.environ.get("CAPITAL_EMAIL", "")
CAPITAL_API_KEY = os.environ.get("CAPITAL_API_KEY", "")
CAPITAL_API_PASSWORD = os.environ.get("CAPITAL_API_PASSWORD", "")

# الافتراضيات (قابلة للتغيير من البوت وتُحفظ في state.json)
AUTO_TRADE = os.environ.get("CAPITAL_AUTO_TRADE", "1") == "1"
RISK_PCT = float(os.environ.get("RISK_PCT", "1.0"))  # مخاطرة كل صفقة % من رصيد كابيتال

# المحرك
LOOP_SEC = int(os.environ.get("LOOP_SEC", "60"))
MAX_ENTRY_SLIP_R = 0.5   # تجاهل الإشارة إذا ابتعد السعر أكثر من 0.5R عن سعر الإشارة (تأخر)
MAX_SIGNAL_AGE_H = 6     # تجاهل إشارة 4h أقدم من 6 ساعات منذ الإغلاق (يومي: 26 ساعة)

STATE_FILE = os.environ.get("STATE_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json"))
