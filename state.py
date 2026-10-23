"""إدارة وتخزين حالة الصفقات والتداول والتحكم التلقائي."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

log = logging.getLogger("state")
_STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")
_LOCK = threading.Lock()

DEFAULT_STATE: Dict[str, Any] = {
    "auto_trade": True,
    "risk_pct": 1.0,
    "active_trades": {},  # مفتاح: spec_id -> {deal_id, direction, entry, stop, tp, moved_be}
    "history": [],
    "last_check_ts": 0,
}

def load_state() -> Dict[str, Any]:
    with _LOCK:
        if not os.path.exists(_STATE_FILE):
            return dict(DEFAULT_STATE)
        try:
            with open(_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {**DEFAULT_STATE, **data}
        except Exception as e:
            log.error(f"خطأ في قراءة state.json: {e}")
            return dict(DEFAULT_STATE)

def save_state(state: Dict[str, Any]):
    with _LOCK:
        try:
            with open(_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.error(f"خطأ في كتابة state.json: {e}")

def set_auto_trade(enabled: bool) -> bool:
    st = load_state()
    st["auto_trade"] = bool(enabled)
    save_state(st)
    return st["auto_trade"]

def is_auto_trade() -> bool:
    return bool(load_state().get("auto_trade", True))

def set_risk_pct(pct: float) -> float:
    st = load_state()
    st["risk_pct"] = max(0.1, min(5.0, float(pct)))
    save_state(st)
    return st["risk_pct"]

def get_risk_pct() -> float:
    return float(load_state().get("risk_pct", 1.0))

def record_trade(spec_id: str, deal_data: Dict[str, Any]):
    st = load_state()
    st["active_trades"][spec_id] = {
        **deal_data,
        "spec_id": spec_id,
        "timestamp": time.time(),
        "moved_be": False,
    }
    save_state(st)

def remove_trade(spec_id: str):
    st = load_state()
    if spec_id in st["active_trades"]:
        del st["active_trades"][spec_id]
        save_state(st)

def get_active_trades() -> Dict[str, Any]:
    return load_state().get("active_trades", {})
