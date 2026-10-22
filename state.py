"""حالة دائمة (JSON ذرّي): الصفقات النشطة لكل استراتيجية، السجل، آخر شمعة معالجة، الإعدادات."""
from __future__ import annotations

import json
import os
import threading

import config

_LOCK = threading.RLock()
_DEFAULT = {"active": {}, "history": [], "last_bar": {}, "settings": {}}


def load() -> dict:
    with _LOCK:
        try:
            with open(config.STATE_FILE, encoding="utf-8") as f:
                d = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            d = {}
        for k, v in _DEFAULT.items():
            d.setdefault(k, type(v)())
        return d


def save(d: dict) -> None:
    with _LOCK:
        tmp = config.STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1, default=str)
        os.replace(tmp, config.STATE_FILE)


def setting(name: str, default):
    return load()["settings"].get(name, default)


def set_setting(name: str, value) -> None:
    with _LOCK:
        d = load()
        d["settings"][name] = value
        save(d)


def auto_trade() -> bool:
    return bool(setting("auto_trade", config.AUTO_TRADE))


def risk_pct() -> float:
    return float(setting("risk_pct", config.RISK_PCT))
