"""إعدادات بوت البيتكوين والتداول عبر Capital.com."""
import os

# تيليجرام
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "1819077477"))
DAILY_CHAT_ID = int(os.environ.get("DAILY_CHAT_ID", "1819077477"))

# Capital.com API
CAPITAL_EMAIL = os.environ.get("CAPITAL_EMAIL", "lsyry3247@gmail.com")
CAPITAL_API_KEY = os.environ.get("CAPITAL_API_KEY", "Iw25M1vmcgxt487o")
CAPITAL_API_PASSWORD = os.environ.get("CAPITAL_API_PASSWORD", "Ali1213141516.")
CAPITAL_ENV = os.environ.get("CAPITAL_ENV", "demo").lower()  # demo | live
AUTO_TRADE = os.environ.get("CAPITAL_AUTO_TRADE", "1") == "1"

# إدارة الصفقات
EPIC = "BTCUSD"
DEFAULT_RISK_PCT = float(os.environ.get("DEFAULT_RISK_PCT", "1.0"))  # 1% لكل صفقة
MAX_OPEN_POSITIONS = int(os.environ.get("MAX_OPEN_POSITIONS", "1"))
TRAILING_STOP_ATR_MULT = float(os.environ.get("TRAILING_STOP_ATR_MULT", "2.0"))
