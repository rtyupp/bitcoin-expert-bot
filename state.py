"""State persistence module for Multi-Asset Bot."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import config

_lock = threading.Lock()


def _default_state() -> dict:
    return {
        "auto_trade": config.CAPITAL_AUTO_TRADE,
        "risk_pct": config.DEFAULT_RISK_PCT,
        "active_trades": {},
        "signal_cooldowns": {},
    }


def load_state() -> dict:
    p = Path(config.STATE_FILE)
    if p.exists():
        try:
            with _lock:
                data = json.loads(p.read_text(encoding="utf-8"))
            default = _default_state()
            for k, v in default.items():
                data.setdefault(k, v)
            return data
        except Exception:
            pass
    return _default_state()


def save_state(state: dict) -> None:
    p = Path(config.STATE_FILE)
    try:
        with _lock:
            p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def get_active_trades(state: dict) -> dict:
    return state.get("active_trades", {})


def record_trade(state: dict, spec_id: str, deal_data: dict) -> None:
    if "active_trades" not in state:
        state["active_trades"] = {}
    state["active_trades"][spec_id] = {
        **deal_data,
        "opened_at": time.time(),
        "moved_be": False,
        "peak": deal_data.get("peak"),
    }
    save_state(state)


def update_trade(state: dict, spec_id: str, **kwargs) -> None:
    if spec_id in state.get("active_trades", {}):
        state["active_trades"][spec_id].update(kwargs)
        save_state(state)


def close_trade(state: dict, spec_id: str, reason: str = "", exit_price: float = 0.0, pnl: float = 0.0) -> dict | None:
    trade = state.get("active_trades", {}).pop(spec_id, None)
    if trade:
        trade.update({
            "closed_at": time.time(),
            "close_reason": reason,
            "exit_price": exit_price,
            "pnl": pnl,
        })
        save_state(state)
    return trade


def is_auto_trade(state: dict) -> bool:
    return bool(state.get("auto_trade", config.CAPITAL_AUTO_TRADE))


def set_auto_trade(state: dict, enabled: bool) -> None:
    state["auto_trade"] = bool(enabled)
    save_state(state)


def get_risk_pct(state: dict) -> float:
    return float(state.get("risk_pct", config.DEFAULT_RISK_PCT))


def set_risk_pct(state: dict, pct: float) -> None:
    state["risk_pct"] = float(pct)
    save_state(state)


def check_signal_cooldown(state: dict, asset: str, cooldown_min: int) -> bool:
    last_ts = state.get("signal_cooldowns", {}).get(asset, 0.0)
    return (time.time() - last_ts) >= (cooldown_min * 60)


def set_signal_cooldown(state: dict, asset: str) -> None:
    if "signal_cooldowns" not in state:
        state["signal_cooldowns"] = {}
    state["signal_cooldowns"][asset] = time.time()
    save_state(state)
