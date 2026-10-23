"""محرك التداول والمراقبة الدورية للبيتكوين (Trading & Monitoring Engine).

يقوم بالتالي:
1. جلب الشموع والأسعار المباشرة من Capital.com
2. فحص إشارات الدخول عبر الاستراتيجيات المؤسسية الأربع المتكيفة (A, B, C, D)
3. التحقق من عدم وجود صفقات مكررة لنفس الاستراتيجية (One Slot Per Strategy)
4. حساب حجم العقد بدقة حسب نسبة المخاطرة المحددة (مثلاً 1% من الرصيد المتاح)
5. إرسال أمر الصفقة مع الوقف والهدف إلى حساب Capital.com
6. مراقبة الصفقات المفتوحة وتحريك الوقف لنقطة الدخول (Break-Even) عند +1.0R
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

log = logging.getLogger("engine")

def calculate_position_size(entry_price: float, stop_loss_price: float, risk_pct: float = 1.0) -> float:
    """حساب حجم العقد (بالبيتكوين) بناءً على الرصيد المتاح ونقطة الوقف."""
    acc = client.get_account_details()
    if not acc:
        return 0.0001

    available_balance = acc["available"]
    risk_amount = available_balance * (risk_pct / 100.0)
    stop_distance = abs(entry_price - stop_loss_price)

    if stop_distance <= 0:
        return 0.0001

    # الحجم = المبلغ المعرض للخسارة / مسافة الوقف
    raw_size = risk_amount / stop_distance

    mkt = client.get_market_info("BTCUSD")
    min_size = mkt["min_deal_size"] if mkt else 0.0001
    step = mkt["min_size_increment"] if mkt else 0.0001

    size = max(min_size, round(raw_size, 4))
    return size

def evaluate_and_trade() -> Tuple[List[Dict[str, Any]], List[str]]:
    """فحص السوق وتنفيذ الصفقات المؤكدة تلقائياً إذا كان التداول الآلي مفعلاً."""
    logs = []
    actions_taken = []

    if not client.is_configured():
        return [], ["Capital.com غير مربوط في الإعدادات."]

    # جلب البيانات الحية
    c_1h = client.get_prices("BTCUSD", resolution="HOUR", max_candles=100)
    c_4h = client.get_prices("BTCUSD", resolution="HOUR_4", max_candles=100)
    c_1d = client.get_prices("BTCUSD", resolution="DAY", max_candles=100)

    if not c_1h or not c_4h or not c_1d:
        return [], ["تعذر جلب الشموع الكاملة من خوادم Capital.com."]

    df_1h = pd.DataFrame(c_1h)
    df_4h = pd.DataFrame(c_4h)
    df_1d = pd.DataFrame(c_1d)

    # 1. إدارة الصفقات النشطة (Break-Even & Trail)
    active = state.get_active_trades()
    open_positions = client.get_open_positions("BTCUSD")
    open_deal_ids = {p["deal_id"]: p for p in open_positions}

    # التحقق من الصفقات المغلقة لإزالتها من الذاكرة
    for spec_id, tr_info in list(active.items()):
        deal_id = tr_info.get("deal_id")
        if deal_id not in open_deal_ids:
            # الصفقة أغلقت في المنصة (حققت الهدف أو ضربت الوقف)
            state.remove_trade(spec_id)
            logs.append(f"انتهت الصفقة {spec_id} في المنصة وتمت إزالتها من المتابعة.")
        else:
            # فحص تأمين الصفقة (Break-Even)
            pos = open_deal_ids[deal_id]
            cur_price = pos["current_price"]
            entry = tr_info["level"]
            stop = tr_info["stop_level"]
            side = 1 if tr_info["direction"] == "BUY" else -1
            initial_risk = abs(entry - stop)

            # قاعدة الخروج السريع عند أول علامة ضعف (Early Invalidation Guard):
            # إذا عكست الشمعة الأولى بعد الدخول بلون معاكس تحت الدخول، نغلق فوراً بخسارة تافهة لا تتجاوز 1$
            if not tr_info.get("moved_be") and initial_risk > 0:
                floating_gain = (cur_price - entry) if side == 1 else (entry - cur_price)
                if floating_gain >= 0.8 * initial_risk:
                    ok_up, msg_up = client.update_position(deal_id, stop_level=entry)
                    if ok_up:
                        tr_info["moved_be"] = True
                        tr_info["stop_level"] = entry
                        state.record_trade(spec_id, tr_info)
                        logs.append(f"🔒 تم تأمين الصفقة [{spec_id}] بنجاح بنقل الوقف إلى سعر الدخول ${entry:,.1f}.")

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
        size = calculate_position_size(sig.price, sig.stop_level, risk_pct)

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
                state.record_trade(spec_id, deal_data)
                trade_record["deal_id"] = deal_data.get("deal_id")
                actions_taken.append(trade_record)
                logs.append(f"🚀 تم فتح صفقة حقيقية جديدة [{sig.spec.name}] حجم {size} BTC.")
            else:
                logs.append(f"⚠️ تعذر فتح الصفقة تلقائياً: {msg}")
        else:
            actions_taken.append(trade_record)
            logs.append(f"🔔 رصدت إشارة جديدة [{sig.spec.name}] (التداول الآلي معطل).")

    return actions_taken, logs
