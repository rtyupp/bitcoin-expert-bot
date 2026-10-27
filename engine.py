"""Execution and Lifecycle Engine for Multi-Asset Portfolio."""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from capital import client
import config
import state
import strategy

log = logging.getLogger("engine")


def _asset_context(asset: str, df: Optional[pd.DataFrame]) -> Optional[Dict[str, Any]]:
    if df is None or len(df) < 20:
        return None
    atr_v = float(strategy.compute_atr(df, 14).iloc[-1])
    ma20_v = float(df["close"].rolling(20).mean().iloc[-1])
    if math.isnan(atr_v) or math.isnan(ma20_v):
        return None
    return {
        "df": df,
        "atr": atr_v,
        "ma20": ma20_v,
        "last_time": str(df["ts"].iloc[-1]),
        "high": float(df["high"].iloc[-1]),
        "low": float(df["low"].iloc[-1]),
        "close": float(df["close"].iloc[-1]),
    }


def _trade_peak(candles: List[Dict[str, Any]], entry_candle: str, side: int, entry: float) -> float:
    if not entry_candle:
        return entry
    if side == 1:
        peak = entry
        for c in candles:
            if str(c.get("ts", "")) >= entry_candle:
                peak = max(peak, float(c.get("high", entry)))
        return peak
    peak = entry
    for c in candles:
        if str(c.get("ts", "")) >= entry_candle:
            peak = min(peak, float(c.get("low", entry)))
    return peak


def evaluate_and_trade(st: dict | None = None) -> Tuple[List[Dict[str, Any]], List[str]]:
    logs: List[str] = []
    actions_taken: List[Dict[str, Any]] = []

    if not client.is_configured():
        return [], ["Capital.com credentials not configured."]

    current_state = st if st is not None else state.load_state()

    data_frames = {}
    for asset_key, asset_cfg in config.ASSETS.items():
        epic = asset_cfg["epic"]
        try:
            df = client.fetch_ohlcv(epic, timeframe="4h", limit=300)
            data_frames[asset_key] = df
            logs.append(f"Fetched {len(df)} 4H candles for {asset_cfg['name']} ({epic})")
        except Exception as e:
            logs.append(f"Failed to fetch {asset_key}: {e}")

    ctx = {}
    for asset_key in config.ASSETS.keys():
        ctx[asset_key] = _asset_context(asset_key, data_frames.get(asset_key))

    open_positions = client.account_summary().get("positions", [])
    open_deal_ids = {p.get("deal_id") or p.get("dealId"): p for p in open_positions}

    active = state.get_active_trades(current_state)

    # 1. Manage Active Positions
    for spec_id, tr_info in list(active.items()):
        if tr_info.get("closed"):
            continue

        asset = tr_info.get("asset") or spec_id.split("_")[0]
        actx = ctx.get(asset)
        if not actx:
            continue

        deal_id = tr_info.get("deal_id")
        if deal_id and deal_id not in open_deal_ids:
            closed = state.close_trade(current_state, spec_id, reason="Closed on broker (TP/SL hit)")
            if closed:
                logs.append(f"Position {spec_id} closed on broker — PnL: ${closed.get('pnl', 0):+.2f}")
                actions_taken.append({"event": "close", **closed})
            continue

        pos = open_deal_ids.get(deal_id, {}) if deal_id else {}
        entry = float(tr_info.get("level") or 0.0)
        stop = float(tr_info.get("stop_level") or 0.0)
        side = 1 if tr_info["direction"] == "BUY" else -1
        initial_risk = abs(entry - stop)
        entry_candle = str(tr_info.get("entry_candle") or "")
        same_candle = bool(entry_candle) and entry_candle == actx["last_time"]

        peak = _trade_peak(actx["df"].to_dict("records"), entry_candle, side, entry)
        stored_peak = tr_info.get("peak")
        if stored_peak is not None:
            peak = max(peak, float(stored_peak)) if side == 1 else min(peak, float(stored_peak))
        if stored_peak is None or peak != float(stored_peak):
            state.update_trade(current_state, spec_id, peak=peak)

        exit_reason = None if same_candle else strategy.check_exit(
            asset, spec_id, side, entry, stop, peak, actx["close"], actx["atr"], entry_candle, actx["last_time"]
        )

        if exit_reason and deal_id:
            ok_close, msg_close = client.close_position(deal_id)
            if ok_close:
                pnl = float(pos.get("upl", 0.0))
                closed = state.close_trade(current_state, spec_id, reason=exit_reason, exit_price=actx["close"], pnl=pnl)
                actions_taken.append({
                    "event": "close",
                    "spec_id": spec_id,
                    "strat_name": tr_info.get("strat_name", spec_id),
                    "direction": tr_info["direction"],
                    "entry": entry,
                    "exit_price": actx["close"],
                    "reason": exit_reason,
                    "pnl": pnl,
                })
                logs.append(f"Auto-exit triggered [{spec_id}] — {exit_reason} | PnL ${pnl:+.2f}")
            else:
                logs.append(f"Failed to close [{spec_id}]: {msg_close}")
            continue

        # Break-Even check (+1.0R)
        if not tr_info.get("moved_be") and initial_risk > 0 and not same_candle and deal_id:
            bar_gain = (actx["high"] - entry) if side == 1 else (entry - actx["low"])
            if bar_gain >= 1.0 * initial_risk:
                ok_up, _ = client.update_position(deal_id, stop_level=entry)
                if ok_up:
                    state.update_trade(current_state, spec_id, moved_be=True, stop_level=entry)
                    logs.append(f"Break-even secured for [{spec_id}] at entry ${entry:,.5f}")

    # 2. Scan for New Signals
    for asset_key, asset_cfg in config.ASSETS.items():
        spec_id = asset_cfg["strategy"]
        if spec_id in active and not active[spec_id].get("closed"):
            continue

        df = data_frames.get(asset_key)
        if df is None:
            continue

        scanner = strategy.STRATEGY_SCANNERS.get(spec_id)
        signals = scanner(df, asset_cfg) if scanner else []
        for sig in signals:
            direction = "BUY" if sig.side == 1 else "SELL"
            size = strategy.calculate_position_size(asset_key, sig.price, sig.stop_level, state.get_risk_pct(current_state))

            trade_record = {
                "spec_id": sig.spec_id,
                "strat_name": sig.spec_id,
                "direction": direction,
                "entry": sig.price,
                "stop_level": sig.stop_level,
                "target_level": sig.target_level,
                "size": size,
                "time": sig.time,
                "reasons": sig.reasons,
                "asset": asset_key,
                "epic": asset_cfg["epic"],
            }

            auto_enabled = state.is_auto_trade(current_state)
            if auto_enabled:
                try:
                    deal_data = client.open_trade(
                        epic=asset_cfg["epic"],
                        direction=direction,
                        size=size,
                        stop_level=sig.stop_level,
                        profit_level=sig.target_level,
                    )
                    deal_id = deal_data.get("deal_id")
                    actx = ctx.get(asset_key)
                    full_record = {
                        **deal_data,
                        "strat_name": sig.spec_id,
                        "asset": asset_key,
                        "entry_candle": actx["last_time"] if actx else "",
                        "peak": (actx["high"] if sig.side == 1 else actx["low"]) if actx else sig.price,
                    }
                    state.record_trade(current_state, sig.spec_id, full_record)
                    trade_record["deal_id"] = deal_id
                    actions_taken.append(trade_record)
                    logs.append(f"Executed trade [{sig.spec_id}] on {asset_cfg['name']} size {size}")
                    state.set_signal_cooldown(current_state, asset_key)
                except Exception as e:
                    logs.append(f"Failed to open position for {asset_cfg['name']}: {e}")
            else:
                actions_taken.append(trade_record)
                logs.append(f"Signal generated [{sig.spec_id}] on {asset_cfg['name']} (auto-trade disabled)")
                state.set_signal_cooldown(current_state, asset_key)

    return actions_taken, logs
