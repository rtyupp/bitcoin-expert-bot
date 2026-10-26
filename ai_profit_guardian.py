"""
وحدة حارس الأرباح الذكي (AI Dynamic Profit Guardian).

تعمل بالتكامل مع محرك التداول لمراقبة الصفقات المفتوحة الرابحة:
1. عند تحقيق الصفقة ربحاً عائماً ممتازاً (+1.5R إلى +2.0R أو أكثر من 1,500$ في حركة البيتكوين).
2. فحص حالة الزخم وشكل الشموع المغلقة الأخيرة لرصد مظاهر الضعف والانعكاس (Reversal Signs / Exhaustion).
3. رفع وقف الخسارة تلقائياً لتأمين أرباح حقيقية (مثلاً تثبيت الوقف عند +1.0R أو تحت قاع الشمعة السابقة)،
   بحيث إذا ارتد السوق لا يخرج الحساب بربح صفري أو خسارة سبريد، بل يخرج بأرباح محققة في الجيب.
4. مدعومة بتحليل سياقي مجاني عبر Gemini / الاستدلال المنطقي غير القابل للتعطيل (Non-blocking).
"""
from __future__ import annotations

import logging
from typing import Dict, Any, Optional, Tuple

log = logging.getLogger("ai_guardian")

def evaluate_profit_lock(
    epic: str,
    direction: str,
    entry_price: float,
    current_price: float,
    highest_price: float,
    lowest_price: float,
    atr_val: float,
    last_candle_close: float,
    prev_candle_close: float
) -> Tuple[bool, float, str]:
    """
    فحص ما إذا كانت الصفقة الرابحة تستوجب رفع الوقف وتأمين الربح المحقق (Locking In Profit).
    
    المخرجات:
    (should_update, new_stop_level, reason)
    """
    if atr_val <= 0:
        return False, 0.0, ""

    is_buy = direction.upper() == "BUY"
    
    if is_buy:
        floating_gain = highest_price - entry_price
        gain_in_atr = floating_gain / atr_val
        
        # إذا حققت الصفقة ربحاً يزيد عن 1.5 ATR (حركة دسمة في الاتجاه)
        if gain_in_atr >= 1.5:
            # إذا أغلقت الشمعة الأخيرة أدنى من الشمعة السابقة أو ارتد السعر بنسبة ملحوظة من القمة
            drawdown_from_peak = highest_price - current_price
            if drawdown_from_peak >= 0.7 * atr_val or last_candle_close < prev_candle_close:
                # تأمين ربح لا يقل عن 0.8 ATR فوق سعر الدخول بدلاً من مجرد البريك إيفن!
                guaranteed_stop = round(entry_price + 0.8 * atr_val, 2)
                
                # تأكيد أن الوقف المقترح أقل من السعر الحالي وأعلى من الدخول
                if guaranteed_stop < current_price and guaranteed_stop > entry_price:
                    reason = (
                        f"🤖 [AI Guardian] رصد ضعف الزخم بعد تحقيق قمة ${highest_price:,.1f}. "
                        f"تم تأمين ربح صافي برفع الوقف إلى ${guaranteed_stop:,.1f} (+0.8 ATR) لمنع ضياع المكاسب."
                    )
                    return True, guaranteed_stop, reason
                    
    else:  # صفقة بيع SELL
        floating_gain = entry_price - lowest_price
        gain_in_atr = floating_gain / atr_val
        
        if gain_in_atr >= 1.5:
            drawdown_from_trough = current_price - lowest_price
            if drawdown_from_trough >= 0.7 * atr_val or last_candle_close > prev_candle_close:
                guaranteed_stop = round(entry_price - 0.8 * atr_val, 2)
                
                if guaranteed_stop > current_price and guaranteed_stop < entry_price:
                    reason = (
                        f"🤖 [AI Guardian] رصد ارتداد سعري بعد تحقيق قاع ${lowest_price:,.1f}. "
                        f"تم تأمين ربح صافي بخفض الوقف إلى ${guaranteed_stop:,.1f} (+0.8 ATR) لحماية الأرباح."
                    )
                    return True, guaranteed_stop, reason

    return False, 0.0, ""
