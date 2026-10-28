"""Configuration module for Multi-Asset Trading Bot (GBP/USD, Gold, Silver)."""
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

# Telegram
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0") or "0")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "").strip() or str(ADMIN_CHAT_ID)

# Capital.com API
CAPITAL_EMAIL = os.environ.get("CAPITAL_EMAIL", "")
CAPITAL_API_KEY = os.environ.get("CAPITAL_API_KEY", "")
CAPITAL_API_PASSWORD = os.environ.get("CAPITAL_API_PASSWORD", "")
CAPITAL_ENV = os.environ.get("CAPITAL_ENV", "demo").lower()  # demo | live
CAPITAL_AUTO_TRADE = os.environ.get("CAPITAL_AUTO_TRADE", "0") == "1"

# Risk & Strategy Settings
DEFAULT_RISK_PCT = float(os.environ.get("DEFAULT_RISK_PCT", "8.0"))
MAX_OPEN_POSITIONS = int(os.environ.get("MAX_OPEN_POSITIONS", "3"))
SIGNAL_INTERVAL_SEC = int(os.environ.get("SIGNAL_INTERVAL_SEC", "300"))
SIGNAL_COOLDOWN_MIN = int(os.environ.get("SIGNAL_COOLDOWN_MIN", "240"))
STATE_FILE = os.environ.get("STATE_FILE", str(Path(__file__).with_name("state.json")))

# Core 3 Validated Assets
ASSETS = {
    "GBPUSD": {
        "name": "GBP/USD",
        "epic": "GBPUSD",
        "asset_class": "FOREX",
        "timeframe": "4h",
        "resolution": "HOUR_4",
        "strategy": "donchian20_vol15",
        "rr": 3.0,
        "stop_mult": 2.0,
        "min_deal": 100,
        "margin_pct": 0.0333,
        "spread": 0.0001,
        "volume_mult": 1.5,
        "decimals": 5,
    },
    "GOLD": {
        "name": "Gold",
        "epic": "GOLD",
        "asset_class": "COMMODITY",
        "timeframe": "4h",
        "resolution": "HOUR_4",
        "strategy": "macd_ema200",
        "rr": 2.0,
        "stop_mult": 2.0,
        "min_deal": 0.01,
        "margin_pct": 0.05,
        "spread": 0.5,
        "volume_mult": 0.0,
        "decimals": 2,
    },
    "SILVER": {
        "name": "Silver",
        "epic": "SILVER",
        "asset_class": "COMMODITY",
        "timeframe": "4h",
        "resolution": "HOUR_4",
        "strategy": "macd_ema200",
        "rr": 2.0,
        "stop_mult": 2.0,
        "min_deal": 1.0,
        "margin_pct": 0.10,
        "spread": 0.05,
        "volume_mult": 0.0,
        "decimals": 3,
    },
    "BTCUSD": {
        "name": "Bitcoin",
        "epic": "BTCUSD",
        "asset_class": "CRYPTO",
        "timeframe": "4h",
        "resolution": "HOUR_4",
        "strategy": "bb_rsi_reversion",
        "rr": 2.0,
        "stop_mult": 1.5,
        "min_deal": 0.0001,
        "margin_pct": 0.50,
        "spread": 50.0,
        "volume_mult": 0.0,
        "decimals": 2,
    },
    "ETHUSD": {
        "name": "Ethereum",
        "epic": "ETHUSD",
        "asset_class": "CRYPTO",
        "timeframe": "4h",
        "resolution": "HOUR_4",
        "strategy": "bb_rsi_reversion",
        "rr": 2.0,
        "stop_mult": 1.5,
        "min_deal": 0.001,
        "margin_pct": 0.50,
        "spread": 2.0,
        "volume_mult": 0.0,
        "decimals": 2,
    },
    "US500": {
        "name": "S&P 500",
        "epic": "US500",
        "asset_class": "INDEX",
        "timeframe": "1h",
        "resolution": "HOUR",
        "strategy": "smc_liquidity_sweep",
        "rr": 2.5,
        "stop_mult": 1.2,
        "min_deal": 0.01,
        "margin_pct": 0.05,
        "spread": 0.4,
        "volume_mult": 0.0,
        "decimals": 2,
    },
}

def validate_config() -> list[str]:
    errors = []
    if not BOT_TOKEN:
        errors.append("BOT_TOKEN is missing in .env")
    if not ADMIN_CHAT_ID:
        errors.append("ADMIN_CHAT_ID is missing in .env")
    if not CAPITAL_EMAIL or not CAPITAL_API_KEY or not CAPITAL_API_PASSWORD:
        errors.append("Capital.com API credentials missing (EMAIL/API_KEY/PASSWORD)")
    return errors
