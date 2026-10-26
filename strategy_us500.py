"""
محرك استراتيجيات مؤشر الأسهم الأمريكية (US500 S&P 500 Engine).
الأصل: US500 في Capital.com (سبريد 0.6 نقطة).

القواعد المعتمدة من مشروع us500-expert-bot:
1. [US500_CALL]: قنص كول بعد اكتمال كنس القاع وتأكيد شمعة صاعدة تخترق قمة شمعة الكنس.
2. [US500_PUT]: قنص بوت بعد اكتمال كنس القمة وتأكيد شمعة هابطة تكسر قاع شمعة الكنس.
3. التداول في جلسة نيويورك ولندن فقط مع نسبة مخاطرة وعائد 1:1.5.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
import pandas as pd
import numpy as np
from typing import Dict, List, Optional

@dataclass
class US500Signal:
    asset: str
    spec_id: str
    side: int  # 1 = BUY, -1 = SELL
    price: float
    stop_level: float
    target_level: float
    time: str
    reasons: List[str] = field(default_factory=list)

def compute_atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = np.maximum(h - l, np.maximum(abs(h - c.shift(1)), abs(l - c.shift(1))))
    return tr.rolling(n).mean()

def scan_us500_signals(df_15m: pd.DataFrame, df_1h: pd.DataFrame) -> List[US500Signal]:
    signals: List[US500Signal] = []
    if df_15m is None or len(df_15m) < 40 or df_1h is None or len(df_1h) < 40:
        return signals

    c_15, h_15, l_15, o_15 = df_15m["close"].astype(float), df_15m["high"].astype(float), df_15m["low"].astype(float), df_15m["open"].astype(float)
    df_15m["atr"] = compute_atr(df_15m, 14)
    df_15m["ema200"] = c_15.ewm(span=200, adjust=False).mean()
    df_15m["lo20"] = l_15.rolling(20).min().shift(1)
    df_15m["hi20"] = h_15.rolling(20).max().shift(1)

    cur = df_15m.iloc[-1]
    prev = df_15m.iloc[-2]
    atr_val = float(cur["atr"])
    cur_p = float(cur["close"])

    # قنص كول: كنس قاع 20 شمعة وإغلاق أخضر فوق القاع والسعر فوق EMA200
    call_sig = (cur["low"] < cur["lo20"]) and (cur["close"] > cur["lo20"]) and (cur["close"] > cur["open"]) and (cur["close"] > cur["ema200"])
    # قنص بوت: كنس قمة 20 شمعة وإغلاق أحمر تحت القمة والسعر تحت EMA200
    put_sig = (cur["high"] > cur["hi20"]) and (cur["close"] < cur["hi20"]) and (cur["close"] < cur["open"]) and (cur["close"] < cur["ema200"])

    if call_sig and not (prev["low"] < prev["lo20"] and prev["close"] > prev["lo20"]):
        dist = max(3.0, cur_p - float(cur["low"]) + 0.2 * atr_val)
        signals.append(US500Signal(
            asset="US500",
            spec_id="US500_CALL",
            side=1,
            price=cur_p,
            stop_level=round(cur_p - dist, 1),
            target_level=round(cur_p + 1.8 * dist, 1),
            time=str(cur.get("time", "")),
            reasons=["كنس قاع 20 شمعة 15m لمؤشر US500", "إغلاق شمعة صاعدة قوية فوق القاع المكسور", "الاتجاه العام صاعد فوق EMA200"]
        ))
    elif put_sig and not (prev["high"] > prev["hi20"] and prev["close"] < prev["hi20"]):
        dist = max(3.0, float(cur["high"]) - cur_p + 0.2 * atr_val)
        signals.append(US500Signal(
            asset="US500",
            spec_id="US500_PUT",
            side=-1,
            price=cur_p,
            stop_level=round(cur_p + dist, 1),
            target_level=round(cur_p - 1.8 * dist, 1),
            time=str(cur.get("time", "")),
            reasons=["كنس قمة 20 شمعة 15m لمؤشر US500", "إغلاق شمعة هابطة قوية تحت القمة المكسورة", "الاتجاه العام هابط تحت EMA200"]
        ))

    return signals
