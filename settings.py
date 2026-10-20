"""إعدادات المستخدم المحفوظة (حجم المحفظة + نسبة المخاطرة)."""
import json
import os

import config

FILE = os.path.join(os.path.dirname(__file__), "settings.json")


def load() -> dict:
    try:
        with open(FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def save(d: dict) -> None:
    try:
        with open(FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass


def account_size() -> float:
    v = load().get("account_size")
    return float(v) if v else config.ACCOUNT_SIZE


def risk_pct() -> float:
    v = load().get("risk_pct")
    return float(v) if v else config.RISK_PERCENT


def set_account(amount: float) -> None:
    d = load()
    d["account_size"] = amount
    save(d)


def set_risk(pct: float) -> None:
    d = load()
    d["risk_pct"] = pct
    save(d)
