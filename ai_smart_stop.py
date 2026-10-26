"""
وحدة الوقف الذكي وإدارة المخاطر الديناميكية (AI Smart Stop & Profit Engine).

المشكلة في الوقف القديم:
1. الوقف المبدئي كان "جامداً" (0.75 ATR ضيق جداً في البيتكوين يضربه السبريد وتذبذب الذيول).
2. الوقف المتحرك (Break-Even) كان يرجع لنقطة الدخول بالملي، فأي هبوط بسيط يضرب الوقف بربح صفر أو خسارة سبريد.

حل الذكاء الاصطناعي (AI Dynamic Stop):
1. الوقف المبدئي الذكي (Structural Stop):
   - يوضع الوقف خارج "الهيكل السعري" الحقيقي (تحت أدنى قاع لآخر 3 شموع + هامش أمان للسبريد 0.3 ATR)،
     بحيث يتنفس السعر ولا تضربه الذيول العشوائية.
2. إدارة الوقف أثناء حركة السعر (Intelligent Trailing):
   - المرحلة 1 (بداية الربح +1R): لا نرجع لنقطة الدخول بالضبط، بل نرفع الوقف إلى (الدخول + تكلفة السبريد + ربح رمزي) ليصبح تداولاً مجانياً وخالياً من الخسارة (Risk-Free).
   - المرحلة 2 (الربح المتفجر +1.5R وأعلى): يلاحق الوقف قيعان الشموع الرابحة بنسبة 70% من حركة الاتجاه،
     لتأمين كاش حقيقي في الجيب إذا قرر السوق الانعكاس فجأة!
"""
from __future__ import annotations

import logging
from typing import Dict, Any, Optional, Tuple
import pandas as pd
import numpy as np

log = logging.getLogger("ai_stop_engine")

def calculate_smart_initial_stop(
    direction: str,
    entry_price: float,
    candles: pd.DataFrame,
    atr_val: float,
    spread_buffer: float = 0.0
) -> Tuple[float, float, str]:
    """
    حساب وقف خسارة ذكي مبني على الهيكل السعري (Structural Stop) بدلاً من الضرب العشوائي.
    
    المخرجات:
    (stop_level, target_level, reason)
    """
    is_buy = direction.upper() == "BUY"
    recent = candles.tail(5) # آخر 5 شمعات
    
    if is_buy:
        # قاع الهيكل الأخير
        struct_low = float(recent["low"].min())
        # الوقف تحت القاع بهامش أمان للسبريد والذبذبة
        smart_stop = round(min(entry_price - 1.2 * atr_val, struct_low - 0.25 * atr_val - spread_buffer), 2)
        risk_dist = entry_price - smart_stop
        # الهدف الذكي بنسبة 1:3 إلى 1:4
        smart_target = round(entry_price + 3.0 * risk_dist, 2)
        reason = f"وقف هيكلي ذكي أسفل قاع التذبذب (${struct_low:,.1f}) مع هامش تنفس ATR."
    else:
        struct_high = float(recent["high"].max())
        smart_stop = round(max(entry_price + 1.2 * atr_val, struct_high + 0.25 * atr_val + spread_buffer), 2)
        risk_dist = smart_stop - entry_price
        smart_target = round(entry_price - 3.0 * risk_dist, 2)
        reason = f"وقف هيكلي ذكي أعلى قمة التذبذب (${struct_high:,.1f}) مع هامش تنفس ATR."
        
    return smart_stop, smart_target, reason

def evaluate_ai_dynamic_trailing(
    direction: str,
    entry_price: float,
    current_price: float,
    peak_price: float,
    current_stop: float,
    atr_val: float,
    recent_candles: pd.DataFrame,
    spread_cost: float = 50.0
) -> Tuple[bool, float, str]:
    """
    إدارة وملاحقة الوقف بذكاء اصطناعي وفق 3 مراحل تصاعدية:
    1. حماية السبريد عند +1.0R (تأمين بدون خنق).
    2. تأمين كاش حقيقي عند +1.5R.
    3. ملاحقة القمة عند +2.5R (Lock-in 70% of gains).
    """
    if atr_val <= 0:
        return False, current_stop, ""
        
    is_buy = direction.upper() == "BUY"
    
    if is_buy:
        floating_gain = peak_price - entry_price
        gain_r = floating_gain / atr_val
        
        # المرحلة 3: ربح كبير (+2.5 ATR فأكثر) -> تأمين 70% من أقصى ربح محقق
        if gain_r >= 2.5:
            suggested_stop = round(entry_price + 0.7 * floating_gain, 2)
            if suggested_stop > current_stop and suggested_stop < current_price:
                return True, suggested_stop, f"🤖 [AI Trailing] تأمين 70% من أرباح القمة (${peak_price:,.1f}) ونقل الوقف إلى ${suggested_stop:,.1f}."
                
        # المرحلة 2: ربح متوسط (+1.5 ATR) -> تأمين ربح صافي محترم (+0.75 ATR)
        elif gain_r >= 1.5:
            suggested_stop = round(entry_price + 0.75 * atr_val, 2)
            if suggested_stop > current_stop and suggested_stop < current_price:
                return True, suggested_stop, f"🤖 [AI Trailing] تأمين ربح صافي (+0.75 ATR) عند ${suggested_stop:,.1f} لمنع ارتداد الصفقة للصفر."
                
        # المرحلة 1: بداية الربح (+1.0 ATR) -> تأمين الدخول + تغطية السبريد
        elif gain_r >= 1.0:
            suggested_stop = round(entry_price + spread_cost + 0.1 * atr_val, 2)
            if suggested_stop > current_stop and suggested_stop < current_price:
                return True, suggested_stop, f"🤖 [AI Trailing] تحويل الصفقة إلى مجانية (Risk-Free) بتأمين السبريد عند ${suggested_stop:,.1f}."
                
    else: # بيع SELL
        floating_gain = entry_price - peak_price
        gain_r = floating_gain / atr_val
        
        if gain_r >= 2.5:
            suggested_stop = round(entry_price - 0.7 * floating_gain, 2)
            if suggested_stop < current_stop and suggested_stop > current_price:
                return True, suggested_stop, f"🤖 [AI Trailing] تأمين 70% من أرباح الهبوط ونقل الوقف إلى ${suggested_stop:,.1f}."
                
        elif gain_r >= 1.5:
            suggested_stop = round(entry_price - 0.75 * atr_val, 2)
            if suggested_stop < current_stop and suggested_stop > current_price:
                return True, suggested_stop, f"🤖 [AI Trailing] تأمين ربح صافي هابط عند ${suggested_stop:,.1f} لمنع ضياع المكاسب."
                
        elif gain_r >= 1.0:
            suggested_stop = round(entry_price - spread_cost - 0.1 * atr_val, 2)
            if suggested_stop < current_stop and suggested_stop > current_price:
                return True, suggested_stop, f"🤖 [AI Trailing] تأمين السبريد في صفقة البيع عند ${suggested_stop:,.1f}."

    return False, current_stop, ""
