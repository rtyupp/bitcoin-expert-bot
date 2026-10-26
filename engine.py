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
import math
import time
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from capital_trader import client
import config
import state
import strategy as S
import strategy_gold as SG
import strategy_us500 as SU
import strategy_us100 as SN
import ai_profit_guardian as AIG
import ai_smart_stop as AIS

log = logging.getLogger("engine")

def calculate_position_size(epic: str, entry_price: float, stop_loss_price: float, risk_pct: float = 1.0, is_a_plus: bool = False) -> float:
    """حساب حجم العقد بناءً على الرصيد المتاح ونقطة الوقف، مع ميزة A+ Sizing التكيفية."""
    acc = client.get_account_details()
    if not acc:
        return 0.0001 if epic == "BTCUSD" else 0.01

    # رفع المخاطرة للصفقات الذهبية المتوافقة مع الاتجاه الأكبر A+ (حتى 3.0% - 3.5%)
    effective_risk_pct = min(3.5, risk_pct * 1.75) if is_a_plus else risk_pct

    available_balance = acc["available"]
    risk_amount = available_balance * (effective_risk_pct / 100.0)
    stop_distance = abs(entry_price - stop_loss_price)

    if stop_distance <= 0:
        return 0.0001 if epic == "BTCUSD" else 0.01

    raw_size = risk_amount / stop_distance
    mkt = client.get_market_info(epic)
    min_size = mkt["min_deal_size"] if mkt else (0.0001 if epic == "BTCUSD" else 0.01)

    if epic in ["BTCUSD", "US100"]:
        size = max(min_size, round(raw_size, 4 if epic == "BTCUSD" else 3))
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
    asset: str = "BTCUSD",
) -> Optional[str]:
    """قاعدة الخروج على الشمعة المغلقة، مطابقة للاختبار التاريخي.

    - [B]: خروج شاندلير 4×ATR (إغلاق تحت أعلى قمة محققة منذ الدخول بمقدار 4×ATR).
    - [C]: إغلاق تحت الدخول بمقدار 2×ATR.
    - [A] (معطّلة): إغلاق 4H تحت EMA50.
    - كل البيع (صفقات BTC القديمة): إغلاق 4H فوق MA20.

    أصول GOLD/US500/US100 تُدار خروجها عبر وقف/هدف المنصة (والوقف الذكي)،
    لذا لا تُطبَّق عليها قواعد BTC حتى لا تُغلق بخطأ بناءً على شموع أصل آخر.
    """
    if asset != "BTCUSD":
        return None
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
    if not entry_candle:
        return entry
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


# تكلفة السبريد التقريبية لكل أصل بوحدات السعر (تُستخدم في تأمين السبريد)
SPREAD_COST = {"BTCUSD": 50.0, "GOLD": 0.35, "US500": 0.6, "US100": 2.0}


def _trade_asset(tr_info: Dict[str, Any], spec_id: str) -> str:
    """تحديد الأصل الذي تنتمي إليه الصفقة (مع توافق الصفقات القديمة)."""
    asset = tr_info.get("asset") or tr_info.get("epic")
    if asset:
        return str(asset).upper()
    if spec_id.startswith("GOLD"):
        return "GOLD"
    if spec_id.startswith("US100"):
        return "US100"
    if "US500" in spec_id or spec_id.startswith("SNIPER"):
        return "US500"
    return "BTCUSD"


def _asset_context(asset: str, df: Optional[pd.DataFrame]) -> Optional[Dict[str, Any]]:
    """ATR و MA20 وآخر شمعة مغلقة للأصل نفسه (بدل استخدام شموع BTC لكل الأصول)."""
    if df is None or len(df) < 20:
        return None
    if asset == "BTCUSD":
        ind = S.compute_indicators_4h(df)
        atr_v = float(ind["atr"].iloc[-1])
        ma20_v = float(ind["ma20"].iloc[-1])
    else:
        atr_v = float(S.compute_atr(df, 14).iloc[-1])
        ma20_v = float(df["close"].rolling(20).mean().iloc[-1])
    if math.isnan(atr_v) or math.isnan(ma20_v):
        return None
    return {
        "df": df,
        "atr": atr_v,
        "ma20": ma20_v,
        "last_time": str(df["time"].iloc[-1]),
        "high": float(df["high"].iloc[-1]),
        "low": float(df["low"].iloc[-1]),
        "close": float(df["close"].iloc[-1]),
    }



def evaluate_and_trade() -> Tuple[List[Dict[str, Any]], List[str]]:
    """فحص السوق وتنفيذ الصفقات المؤكدة تلقائياً إذا كان التداول الآلي مفعلاً."""
    logs = []
    actions_taken = []

    if not client.is_configured():
        return [], ["Capital.com غير مربوط في الإعدادات."]

    # جلب البيانات الحية لكل الأصول — 4H واليومي يحتاجان أكثر من 200 شمعة لتسخين EMA200
    c_1h = client.get_prices("BTCUSD", resolution="HOUR", max_candles=100)
    c_4h = client.get_prices("BTCUSD", resolution="HOUR_4", max_candles=300)
    c_1d = client.get_prices("BTCUSD", resolution="DAY", max_candles=400)
    g_4h = client.get_prices("GOLD", resolution="HOUR_4", max_candles=200)
    g_1d = client.get_prices("GOLD", resolution="DAY", max_candles=300)
    u_15m = client.get_prices("US500", resolution="MINUTE_15", max_candles=200)
    u_1h = client.get_prices("US500", resolution="HOUR", max_candles=150)
    n_1h = client.get_prices("US100", resolution="HOUR", max_candles=250)

    if not c_1h or not c_4h or not c_1d:
        return [], ["تعذر جلب الشموع الكاملة من خوادم Capital.com."]

    df_1h = pd.DataFrame(c_1h)
    df_4h = pd.DataFrame(c_4h)
    df_1d = pd.DataFrame(c_1d)
    df_g4h = pd.DataFrame(g_4h) if g_4h else None
    df_g1d = pd.DataFrame(g_1d) if g_1d else None
    df_u15 = pd.DataFrame(u_15m) if u_15m else None
    df_u1h = pd.DataFrame(u_1h) if u_1h else None
    df_n1h = pd.DataFrame(n_1h) if n_1h else None

    # سياق كل أصل على فريم إدارة صفقته (بدل استخدام شموع BTC لكل الأصول)
    ctx = {
        "BTCUSD": _asset_context("BTCUSD", df_4h),
        "GOLD": _asset_context("GOLD", df_g4h),
        "US500": _asset_context("US500", df_u15),
        "US100": _asset_context("US100", df_n1h),
    }
    btc_ctx = ctx["BTCUSD"]
    if not btc_ctx:
        return [], ["بيانات BTCUSD غير كافية لحساب المؤشرات."]

    # 1. إدارة الصفقات النشطة (Exit Rules & Break-Even)
    active = state.get_active_trades()
    open_positions = client.get_open_positions(None)
    if open_positions is None:
        logs.append("⚠️ تعذر جلب الصفقات المفتوحة من Capital.com — تخطي إدارة الصفقات في هذه الدورة.")
        open_deal_ids = None
    else:
        open_deal_ids = {p["deal_id"]: p for p in open_positions}

    # التحقق من الصفقات المغلقة لإزالتها من الذاكرة
    for spec_id, tr_info in list(active.items()):
        if open_deal_ids is None:
            break
        deal_id = tr_info.get("deal_id")
        if deal_id not in open_deal_ids:
            # الصفقة أغلقت في المنصة (حققت الهدف أو ضربت الوقف)
            state.close_trade(spec_id, reason="أُغلقت في المنصة (هدف/وقف)")
            logs.append(f"انتهت الصفقة {spec_id} في المنصة وتمت إزالتها من المتابعة.")
            continue

        asset = _trade_asset(tr_info, spec_id)
        actx = ctx.get(asset)
        if not actx:
            logs.append(f"⚠️ بيانات {asset} غير متاحة — تخطي إدارة الصفقة [{spec_id}] هذه الدورة.")
            continue

        pos = open_deal_ids[deal_id]
        entry = float(tr_info.get("level") or 0.0)
        stop = float(tr_info.get("stop_level") or 0.0)
        side = 1 if tr_info["direction"] == "BUY" else -1
        initial_risk = abs(entry - stop)

        entry_candle = str(tr_info.get("entry_candle") or "")
        if not tr_info.get("asset"):
            state.update_trade(spec_id, asset=asset)

        # لا نقيّم الخروج على نفس الشمعة التي دخلنا بها (مطابقة للباكتست)
        same_candle = bool(entry_candle) and entry_candle == actx["last_time"]
        peak = trade_peak(actx["df"].to_dict("records"), entry_candle, side, entry)
        stored_peak = tr_info.get("peak")
        if stored_peak is not None:
            peak = max(peak, float(stored_peak)) if side == 1 else min(peak, float(stored_peak))
        if stored_peak is None or peak != float(stored_peak):
            state.update_trade(spec_id, peak=peak)
        exit_reason = None if same_candle else exit_reason_for(
            spec_id, side, entry, actx["close"], peak, actx["ma20"], actx["atr"], asset
        )

        if exit_reason:
            ok_close, msg_close = client.close_position(deal_id)
            if ok_close:
                pnl = float(pos.get("upl", 0.0))
                state.close_trade(
                    spec_id,
                    reason=exit_reason,
                    exit_price=actx["close"],
                    pnl=pnl,
                )
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
                logs.append(
                    f"🚪 إغلاق تلقائي [{spec_id}] — {exit_reason} | "
                    f"الدخول ${entry:,.1f} → الإغلاق ${actx['close']:,.1f} | "
                    f"PnL {pnl:+.2f}$"
                )
            else:
                logs.append(f"⚠️ فشل إغلاق الصفقة [{spec_id}] تلقائياً: {msg_close}")
            continue

        # فحص تأمين الصفقة (Break-Even) على الشمعة المغلقة — مطابق للباكتست
        if not tr_info.get("moved_be") and initial_risk > 0 and not same_candle:
            bar_gain = (actx["high"] - entry) if side == 1 else (entry - actx["low"])
            if bar_gain >= 1.0 * initial_risk:
                ok_up, msg_up = client.update_position(deal_id, stop_level=entry)
                if ok_up:
                    tr_info["moved_be"] = True
                    tr_info["stop_level"] = entry
                    state.update_trade(spec_id, moved_be=True, stop_level=entry)
                    logs.append(f"🔒 تم تأمين الصفقة [{spec_id}] بنجاح بنقل الوقف إلى سعر الدخول ${entry:,.1f}.")

        # 🤖 نظام الوقف الذكي والتأمين التدريجي (AI Smart Trailing)
        cur_px = float(pos.get("current_price") or actx["close"])
        cur_stop = float(tr_info.get("stop_level") or stop)
        should_ai_update, ai_new_stop, ai_reason = AIS.evaluate_ai_dynamic_trailing(
            direction=tr_info["direction"],
            entry_price=entry,
            current_price=cur_px,
            peak_price=peak,
            current_stop=cur_stop,
            atr_val=actx["atr"],
            recent_candles=actx["df"],
            spread_cost=SPREAD_COST.get(asset, 0.0)
        )
        if should_ai_update and ai_new_stop != cur_stop:
            ok_ai, msg_ai = client.update_position(deal_id, stop_level=ai_new_stop)
            if ok_ai:
                tr_info["stop_level"] = ai_new_stop
                state.update_trade(spec_id, stop_level=ai_new_stop)
                logs.append(ai_reason)

    # لا نفتح صفقات جديدة دون معرفة الصفقات المفتوحة (منع التكرار عند فشل الـ API)
    if open_deal_ids is None:
        logs.append("⚠️ تخطي فتح صفقات جديدة لعدم توفر قائمة الصفقات المفتوحة.")
        return actions_taken, logs

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
                    "asset": "BTCUSD",
                    "entry_candle": btc_ctx["last_time"],
                    "peak": btc_ctx["high"] if sig.side == 1 else btc_ctx["low"],
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
    if df_g4h is not None and df_g1d is not None:
        gctx = ctx["GOLD"]
        gold_sigs = SG.scan_gold_signals(df_g4h, df_g1d)
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
                    state.record_trade(gsig.spec_id, {
                        **deal_data,
                        "strat_name": gsig.spec_id,
                        "asset": "GOLD",
                        "entry_candle": gctx["last_time"] if gctx else "",
                        "peak": (gctx["high"] if gsig.side == 1 else gctx["low"]) if gctx else gsig.price,
                    })
                    logs.append(f"🥇 تم فتح صفقة حقيقية جديدة بالذهب [{gsig.spec_id}] حجم {g_size} أونصة.")
            else:
                logs.append(f"🔔 إشارة ذهب جديدة [{gsig.spec_id}] (الآلي معطل).")

    # 4. فحص إشارات مؤشر الأسهم الأمريكية (US500)
    if df_u15 is not None and df_u1h is not None:
        uctx = ctx["US500"]
        us_sigs = SU.scan_us500_signals(df_u15, df_u1h)
        for usig in us_sigs:
            if usig.spec_id in active:
                continue
            u_dir = "BUY" if usig.side == 1 else "SELL"
            # صفقات التأكيد المؤسسي في US500 هي A+ Setup
            is_a_plus = "CONFIRM" in usig.spec_id
            u_size = calculate_position_size("US500", usig.price, usig.stop_level, risk_pct, is_a_plus=is_a_plus)
            if auto_trade_enabled:
                ok, msg, deal_data = client.open_position(
                    direction=u_dir, size=u_size, epic="US500",
                    stop_level=usig.stop_level, profit_level=usig.target_level
                )
                if ok and deal_data:
                    state.record_trade(usig.spec_id, {
                        **deal_data,
                        "strat_name": usig.spec_id,
                        "asset": "US500",
                        "entry_candle": uctx["last_time"] if uctx else "",
                        "peak": (uctx["high"] if usig.side == 1 else uctx["low"]) if uctx else usig.price,
                    })
                    tier_str = "🌟 [A+ Setup]" if is_a_plus else ""
                    logs.append(f"🇺🇸 تم فتح صفقة مؤشر أسهم جديدة {tier_str} [{usig.spec_id}] حجم {u_size} عقد.")
            else:
                logs.append(f"🔔 إشارة US500 جديدة [{usig.spec_id}] (الآلي معطل).")

    # 5. فحص إشارات مؤشر ناسداك (US100)
    if df_n1h is not None:
        nctx = ctx["US100"]
        nasdaq_sigs = SN.scan_nasdaq_signals(df_n1h)
        for nsig in nasdaq_sigs:
            if nsig.spec_id in active:
                continue
            n_dir = "BUY" if nsig.side == 1 else "SELL"
            # ترند ناسداك يعتبر فرصة ممتازة A+ Setup
            n_size = calculate_position_size("US100", nsig.price, nsig.stop_level, risk_pct, is_a_plus=True)
            if auto_trade_enabled:
                ok, msg, deal_data = client.open_position(
                    direction=n_dir, size=n_size, epic="US100",
                    stop_level=nsig.stop_level, profit_level=nsig.target_level
                )
                if ok and deal_data:
                    state.record_trade(nsig.spec_id, {
                        **deal_data,
                        "strat_name": nsig.spec_id,
                        "asset": "US100",
                        "entry_candle": nctx["last_time"] if nctx else "",
                        "peak": (nctx["high"] if nsig.side == 1 else nctx["low"]) if nctx else nsig.price,
                    })
                    logs.append(f"💻 تم فتح صفقة ناسداك جديدة 🌟 [A+ Setup] [{nsig.spec_id}] حجم {n_size} عقد.")
            else:
                logs.append(f"🔔 إشارة ناسداك US100 جديدة [{nsig.spec_id}] (الآلي معطل).")

    return actions_taken, logs
