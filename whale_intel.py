"""وحدة جلب بيانات سيولة ومراكز الحيتان المباشرة (Whale Liquidity Intelligence).

تجلب مجاناً وبدون أي مفاتيح:
1. حجم العقود المفتوحة للحيتان (Open Interest).
2. نسبة كبار المتداولين والحيتان (Top Trader Long/Short Ratio).
3. نسبة المتداولين الأفراد والقطيع (Global Retail Ratio).
4. معدل التمويل (Funding Rate).
مقارنة نسبة الحيتان بنسبة القطيع تكشف مباشرة:
- متى يجمع الحيتان في الخفاء بينما يبيع القطيع (Whale Accumulation / Buy Signal).
- متى يصرف الحيتان في القمم بينما يشتري القطيع (Whale Distribution / Sell Signal).
"""
from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any, Dict, Optional

log = logging.getLogger("whale_intelligence")

def get_whale_metrics() -> Optional[Dict[str, Any]]:
    """جلب المؤشرات الكمية لحركة وسيولة الحيتان الآن."""
    try:
        # 1. نسبة كبار المتداولين والحيتان (Top Traders)
        url_top = "https://fapi.binance.com/futures/data/topLongShortPositionRatio?symbol=BTCUSDT&period=4h&limit=2"
        req1 = urllib.request.Request(url_top, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req1, timeout=8) as r:
            top_data = json.loads(r.read().decode())
            top_now = top_data[-1]
            top_long_pct = float(top_now["longAccount"]) * 100.0
            top_short_pct = float(top_now["shortAccount"]) * 100.0
            top_ratio = float(top_now["longShortRatio"])

        # 2. نسبة صغار المتداولين والأفراد (Retail Traders)
        url_global = "https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol=BTCUSDT&period=4h&limit=2"
        req2 = urllib.request.Request(url_global, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req2, timeout=8) as r:
            global_data = json.loads(r.read().decode())
            global_now = global_data[-1]
            retail_long_pct = float(global_now["longAccount"]) * 100.0
            retail_short_pct = float(global_now["shortAccount"]) * 100.0
            retail_ratio = float(global_now["longShortRatio"])

        # 3. حجم العقود المفتوحة (Open Interest)
        url_oi = "https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT"
        req3 = urllib.request.Request(url_oi, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req3, timeout=8) as r:
            oi_data = json.loads(r.read().decode())
            open_interest_btc = float(oi_data.get("openInterest", 0.0))

        # 4. معدل التمويل (Funding Rate)
        url_fr = "https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=1"
        req4 = urllib.request.Request(url_fr, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req4, timeout=8) as r:
            fr_data = json.loads(r.read().decode())
            funding_rate = float(fr_data[0]["fundingRate"]) * 100.0 if fr_data else 0.0

        # التحليل السيكولوجي المقارن:
        # A. تجميع حيتان: كبار المتداولين يرفعون الشراء بينما الأفراد في بيع/خوف
        is_whale_accumulation = (top_ratio > 1.45) and (retail_long_pct < 65.0)

        # B. تصريف حيتان: كبار المتداولين يخفضون الشراء أو يبيعون بينما الأفراد في طمع مفرط (>70% Long)
        is_whale_distribution = (retail_long_pct > 72.0) and (top_short_pct > 35.0)

        bias = "تجميع حيتان (شراء قوي) 🟢" if is_whale_accumulation else ("تصريف حيتان (بيع وحذر) 🔴" if is_whale_distribution else "توازن نسبي ⚖️")

        return {
            "top_long_pct": round(top_long_pct, 1),
            "top_short_pct": round(top_short_pct, 1),
            "top_ratio": round(top_ratio, 2),
            "retail_long_pct": round(retail_long_pct, 1),
            "retail_short_pct": round(retail_short_pct, 1),
            "open_interest_btc": round(open_interest_btc, 1),
            "funding_rate_pct": round(funding_rate, 4),
            "is_whale_accumulation": is_whale_accumulation,
            "is_whale_distribution": is_whale_distribution,
            "bias": bias,
        }
    except Exception as e:
        log.error(f"خطأ أثناء جلب بيانات سيولة الحيتان: {e}")
        return None
