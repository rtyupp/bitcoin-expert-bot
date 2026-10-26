"""محرك التداول والمراقبة الدورية للبيتكوين (Trading & Monitoring Engine).

يقوم بالتالي:
1. جلب الشموع والأسعار المباشرة من Capital.com
2. فحص إشارات الدخول عبر الاستراتيجيتين النشطتين (B, C) مع فلتر جودة الشمعة
3. التحقق من عدم وجود صفقات مكررة لنفس الاستراتيجية (One Slot Per Strategy)
4. حساب حجم العقد بدقة حسب نسبة المخاطرة المحددة (مثلاً 1% من الرصيد المتاح)
5. إرسال أمر الصفقة مع الوقف والهدف إلى حساب Capital.com
6. مراقبة الصفقات المفتوحة وتنفيذ قواعد الخروج على الشمعة المغلقة
   (شاندلير 4×ATR لـ[B]، و2×ATR تحت الدخول لـ[C]) وتحريك الوقف عند +1.0R
7. إرسال تنبيهات تفصيلية وفورية عبر تيليجرام
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from capital_trader import client
import config
import state
import strategy as S
import strategy_gold as SG
import strategy_us500 as SU
import ai_profit_guardian as AIG
import ai_smart_stop as AIS

log = logging.getLogger("engine")

def calculate_position_size(epic: str, entry_price: float, stop_loss_price: float, risk_pct: float = 1.0) -> float:
    """حساب حجم العقد بناءً على الرصيد المتاح ونقطة الوقف لكل أصل."""
    acc = client.get_account_details()
    if not acc:
        return 0.0001 if epic == "BTCUSD" else 0.01

    available_balance = acc["available"]
    risk_amount = available_balance * (risk_pct / 100.0)
    stop_distance = abs(entry_price - stop_loss_price)

    if stop_distance <= 0:
        return 0.0001 if epic == "BTCUSD" else 0.01

    raw_size = risk_amount / stop_distance
    mkt = client.get_market_info(epic)
    min_size = mkt["min_deal_size"] if mkt else (0.0001 if epic == "BTCUSD" else 0.01)

    if epic == "BTCUSD":
        size = max(min_size, round(raw_size, 4))
    else:
        size = max(min_size, round(raw_size, 2))
    return size

def exit_reason_for(
    spec_id: str,
    side: int,
    entry: float,
    close: float,
    peak: float,
    ma20: float,
    atr_val: float,
) -> Optional[str]:
    """قاعدة الخروج على الشمعة المغلقة، مطابقة للاختبار التاريخي.

    - [B]: خروج شاندلير 4×ATR (إغلاق تحت أعلى قمة محققة منذ الدخول بمقدار 4×ATR).
    - [C]: إغلاق تحت الدخول بمقدار 2×ATR.
    - [A] (معطّلة): إغلاق 4H تحت EMA50.
    - كل البيع (صفقات قديمة): إغلاق 4H فوق MA20.
    """
    if side == 1:
        if spec_id == "B":
            if atr_val > 0 and close < peak - 4.0 * atr_val:
                return "إغلاق تحت قمة الصفقة بمقدار 4×ATR (شاندلير)"
        elif spec_id == "C":
            if atr_val > 0 and close < entry - 2.0 * atr_val:
                return "إغلاق تحت الدخول بمقدار 2×ATR"
    else:
        if close > ma20:
            return "إغلاق 4H فوق MA20"
    return None


def trade_peak(candles: List[Dict[str, Any]], entry_candle: str, side: int, entry: float) -> float:
    """أعلى قمة (أو أدنى قاع) محققة منذ شمعة الدخول — مطابق لباكتست شاندلير."""
    if side == 1:
        peak = entry
        for c in candles:
            if str(c.get("time", "")) >= entry_candle:
                peak = max(peak, float(c["high"]))
        return peak
    peak = entry
    for c in candles:
        if str(c.get("time", "")) >= entry_candle:
            peak = min(peak, float(c["low"]))
    return peak



def evaluate_and_trade() -> Tuple[List[Dict[str, Any]], List[str]]:
    """فحص السوق وتنفيذ الصفقات المؤكدة تلقائياً إذا كان التداول الآلي مفعلاً."""
    logs = []
    actions_taken = []

    if not client.is_configured():
        return [], ["Capital.com غير مربوط في الإعدادات."]

    # جلب البيانات الحية — 4H و اليومي يحتاجان أكثر من 200 شمعة لتسخين EMA200
    c_1h = client.get_prices("BTCUSD", resolution="HOUR", max_candles=100)
    c_4h = client.get_prices("BTCUSD", resolution="HOUR_4", max_candles=300)
    c_1d = client.get_prices("BTCUSD", resolution="DAY", max_candles=400)

    if not c_1h or not c_4h or not c_1d:
        return [], ["تعذر جلب الشموع الكاملة من خوادم Capital.com."]

    df_1h = pd.DataFrame(c_1h)
    df_4h = pd.DataFrame(c_4h)
    df_1d = pd.DataFrame(c_1d)

    # مؤشرات الشمعة المغلقة الأخيرة (تستخدم لقرارات الخروج)
    h4 = S.compute_indicators_4h(df_4h)
    last_4h = h4.iloc[-1]
    ma20_val = float(last_4h["ma20"])
    atr_4h_val = float(last_4h["atr"])
    last_candle_time = str(last_4h["time"])

    # 1. إدارة الصفقات النشطة (Exit Rules & Break-Even)
    active = state.get_active_trades()
    open_positions = client.get_open_positions("BTCUSD")
    open_deal_ids = {p["deal_id"]: p for p in open_positions}

    # التحقق من الصفقات المغلقة لإزالتها من الذاكرة
    for spec_id, tr_info in list(active.items()):
        deal_id = tr_info.get("deal_id")
        if deal_id not in open_deal_ids:
            # الصفقة أغلقت في المنصة (حققت الهدف أو ضربت الوقف)
            state.close_trade(spec_id, reason="أُغلقت في المنصة (هدف/وقف)")
            logs.append(f"انتهت الصفقة {spec_id} في المنصة وتمت إزالتها من المتابعة.")
            continue

        pos = open_deal_ids[deal_id]
        entry = float(tr_info.get("level") or 0.0)
        stop = float(tr_info.get("stop_level") or 0.0)
        side = 1 if tr_info["direction"] == "BUY" else -1
        initial_risk = abs(entry - stop)

        # لا نقيّم الخروج على نفس الشمعة التي دخلنا بها (مطابقة للباكتست)
        same_candle = tr_info.get("entry_candle") == last_candle_time
        peak = trade_peak(c_4h, str(tr_info.get("entry_candle") or last_candle_time), side, entry)
        stored_peak = tr_info.get("peak")
        if stored_peak is not None:
            peak = max(peak, float(stored_peak)) if side == 1 else min(peak, float(stored_peak))
        if stored_peak is None or peak != float(stored_peak):
            state.update_trade(spec_id, peak=peak)
        exit_reason = None if same_candle else exit_reason_for(
            spec_id, side, entry, float(last_4h["close"]), peak, ma20_val, atr_4h_val
        )

        if exit_reason:
            ok_close, msg_close = client.close_position(deal_id)
            if ok_close:
                pnl = float(pos.get("upl", 0.0))
                state.close_trade(
                    spec_id,
                    reason=exit_reason,
                    exit_price=float(last_4h["close"]),
                    pnl=pnl,
                )
                actions_taken.append({
                    "event": "close",
                    "spec_id": spec_id,
                    "strat_name": tr_info.get("strat_name", spec_id),
                    "direction": tr_info["direction"],
                    "entry": entry,
                    "exit_price": float(last_4h["close"]),
                    "reason": exit_reason,
                    "pnl": pnl,
                })
                logs.append(
                    f"🚪 إغلاق تلقائي [{spec_id}] — {exit_reason} | "
                    f"الدخول ${entry:,.1f} → الإغلاق ${float(last_4h['close']):,.1f} | "
                    f"PnL {pnl:+.2f}$"
                )
            else:
                logs.append(f"⚠️ فشل إغلاق الصفقة [{spec_id}] تلقائياً: {msg_close}")
            continue

        # فحص تأمين الصفقة (Break-Even) على الشمعة المغلقة — مطابق للباكتست
        if not tr_info.get("moved_be") and initial_risk > 0 and not same_candle:
            bar_gain = (float(last_4h["high"]) - entry) if side == 1 else (entry - float(last_4h["low"]))
            if bar_gain >= 1.0 * initial_risk:
                ok_up, msg_up = client.update_position(deal_id, stop_level=entry)
                if ok_up:
                    tr_info["moved_be"] = True
                    tr_info["stop_level"] = entry
                    state.update_trade(spec_id, moved_be=True, stop_level=entry)
                    logs.append(f"🔒 تم تأمين الصفقة [{spec_id}] بنجاح بنقل الوقف إلى سعر الدخول ${entry:,.1f}.")

        # 🤖 نظام الوقف الذكي والتأمين التدريجي (AI Smart Trailing)
        cur_px = float(pos.get("current_price") or last_4h["close"])
        cur_stop = float(tr_info.get("stop_level") or stop)
        should_ai_update, ai_new_stop, ai_reason = AIS.evaluate_ai_dynamic_trailing(
            direction=tr_info["direction"],
            entry_price=entry,
            current_price=cur_px,
            peak_price=peak,
            current_stop=cur_stop,
            atr_val=atr_4h_val,
            recent_candles=df_4h,
            spread_cost=50.0
        )
        if should_ai_update and ai_new_stop != cur_stop:
            ok_ai, msg_ai = client.update_position(deal_id, stop_level=ai_new_stop)
            if ok_ai:
                tr_info["stop_level"] = ai_new_stop
                state.update_trade(spec_id, stop_level=ai_new_stop)
                logs.append(ai_reason)

    # 2. فحص إشارات الدخول الجديدة
    signals = S.scan_signals(df_1h, df_4h, df_1d)

    auto_trade_enabled = state.is_auto_trade()
    risk_pct = state.get_risk_pct()

    for sig in signals:
        spec_id = sig.spec_id
        # التحقق مما إذا كانت الاستراتيجية لديها صفقة مفتوحة بالفعل
        if spec_id in active:
            continue

        direction = "BUY" if sig.side == 1 else "SELL"
        size = calculate_position_size("BTCUSD", sig.price, sig.stop_level, risk_pct)

        trade_record = {
            "spec_id": spec_id,
            "strat_name": sig.spec.name,
            "direction": direction,
            "entry": sig.price,
            "stop_level": sig.stop_level,
            "target_level": sig.target_level,
            "size": size,
            "time": sig.time,
            "reasons": sig.reasons,
        }

        if auto_trade_enabled:
            ok, msg, deal_data = client.open_position(
                direction=direction,
                size=size,
                epic="BTCUSD",
                stop_level=sig.stop_level,
                profit_level=sig.target_level,
            )
            if ok and deal_data:
                deal_data = {
                    **deal_data,
                    "strat_name": sig.spec.name,
                    "entry_candle": last_candle_time,
                    "peak": float(last_4h["high"]) if sig.side == 1 else float(last_4h["low"]),
                }
                state.record_trade(spec_id, deal_data)
                trade_record["deal_id"] = deal_data.get("deal_id")
                actions_taken.append(trade_record)
                logs.append(f"🚀 تم فتح صفقة حقيقية جديدة [{sig.spec.name}] حجم {size} BTC.")
            else:
                logs.append(f"⚠️ تعذر فتح الصفقة تلقائياً: {msg}")
        else:
            actions_taken.append(trade_record)
            logs.append(f"🔔 رصدت إشارة جديدة [{sig.spec.name}] (التداول الآلي معطل).")

    # 3. فحص إشارات الذهب (GOLD)
    g_4h = client.get_prices("GOLD", resolution="HOUR_4", max_candles=200)
    g_1d = client.get_prices("GOLD", resolution="DAY", max_candles=300)
    if g_4h and g_1d:
        gold_sigs = SG.scan_gold_signals(pd.DataFrame(g_4h), pd.DataFrame(g_1d))
        for gsig in gold_sigs:
            if gsig.spec_id in active:
                continue
            g_dir = "BUY" if gsig.side == 1 else "SELL"
            g_size = calculate_position_size("GOLD", gsig.price, gsig.stop_level, risk_pct)
            if auto_trade_enabled:
                ok, msg, deal_data = client.open_position(
                    direction=g_dir, size=g_size, epic="GOLD",
                    stop_level=gsig.stop_level, profit_level=gsig.target_level
                )
                if ok and deal_data:
                    state.record_trade(gsig.spec_id, {**deal_data, "strat_name": gsig.spec_id, "asset": "GOLD"})
                    logs.append(f"🥇 تم فتح صفقة حقيقية جديدة بالذهب [{gsig.spec_id}] حجم {g_size} أونصة.")
            else:
                logs.append(f"🔔 إشارة ذهب جديدة [{gsig.spec_id}] (الآلي معطل).")

    # 4. فحص إشارات مؤشر الأسهم الأمريكية (US500)
    u_15m = client.get_prices("US500", resolution="MINUTE_15", max_candles=60)
    u_1h = client.get_prices("US500", resolution="HOUR", max_candles=100)
    if u_15m and u_1h:
        us_sigs = SU.scan_us500_signals(pd.DataFrame(u_15m), pd.DataFrame(u_1h))
        for usig in us_sigs:
            if usig.spec_id in active:
                continue
            u_dir = "BUY" if usig.side == 1 else "SELL"
            u_size = calculate_position_size("US500", usig.price, usig.stop_level, risk_pct)
            if auto_trade_enabled:
                ok, msg, deal_data = client.open_position(
                    direction=u_dir, size=u_size, epic="US500",
                    stop_level=usig.stop_level, profit_level=usig.target_level
                )
                if ok and deal_data:
                    state.record_trade(usig.spec_id, {**deal_data, "strat_name": usig.spec_id, "asset": "US500"})
                    logs.append(f"🇺🇸 تم فتح صفقة مؤشر أسهم جديدة [{usig.spec_id}] حجم {u_size} عقد.")
            else:
                logs.append(f"🔔 إشارة US500 جديدة [{usig.spec_id}] (الآلي معطل).")

    return actions_taken, logs
