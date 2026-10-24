"""إعدادات بوت البيتكوين والتداول عبر Capital.com.

جميع الأسرار تُقرأ من متغيرات البيئة فقط (GitHub Secrets أو ملف .env محلي مستثنى من Git).
"""
import os
from pathlib import Path

_ENV_FILE = Path(__file__).with_name(".env")


def _load_env_file() -> None:
    if not _ENV_FILE.exists():
        return
    for raw in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()

# تيليجرام
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
DAILY_CHAT_ID = int(os.environ.get("DAILY_CHAT_ID", "0") or "0")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "") or DAILY_CHAT_ID)

# Capital.com API
CAPITAL_EMAIL = os.environ.get("CAPITAL_EMAIL", "")
CAPITAL_API_KEY = os.environ.get("CAPITAL_API_KEY", "")
CAPITAL_API_PASSWORD = os.environ.get("CAPITAL_API_PASSWORD", "")
CAPITAL_ENV = os.environ.get("CAPITAL_ENV", "demo").lower()  # demo | live
AUTO_TRADE = os.environ.get("CAPITAL_AUTO_TRADE", "1") == "1"

# إدارة الصفقات
EPIC = "BTCUSD"
DEFAULT_RISK_PCT = float(os.environ.get("DEFAULT_RISK_PCT", "1.0"))  # 1% لكل صفقة
MAX_OPEN_POSITIONS = int(os.environ.get("MAX_OPEN_POSITIONS", "1"))
TRAILING_STOP_ATR_MULT = float(os.environ.get("TRAILING_STOP_ATR_MULT", "2.0"))
