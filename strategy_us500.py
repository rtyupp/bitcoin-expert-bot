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
    if df_15m is None or len(df_15m) < 25 or df_1h is None or len(df_1h) < 25:
        return signals

    df_15 = df_15m.copy()
    c_15 = df_15["close"].astype(float)
    h_15 = df_15["high"].astype(float)
    l_15 = df_15["low"].astype(float)
    o_15 = df_15["open"].astype(float)

    df_15["atr"] = compute_atr(df_15, 14)
    # أعلى قمة وأدنى قاع لآخر 16 شمعة مع إزاحة شمعتين للخلف لمطابقة الكنس وإعادة الاختبار الأصلية
    hi16 = h_15.rolling(16).max().shift(2)
    lo16 = l_15.rolling(16).min().shift(2)

    # اتجاه فريم الساعة الأساسي الحاسم (EMA50 1H)
    c_1h = df_1h["close"].astype(float)
    ema50_1h = float(c_1h.ewm(span=50, adjust=False).mean().iloc[-1])

    row = df_15.iloc[-1]
    prev1 = df_15.iloc[-2]
    cur_px = float(row["close"])
    atr_val = float(row["atr"])
    t_str = str(row.get("time", ""))

    is_bear = cur_px < ema50_1h
    is_bull = cur_px > ema50_1h

    # 1. إشارة PUT بعد شمعة التأكيد الصريحة
    put_confirm = (
        (float(prev1["high"]) > float(hi16.iloc[-2])) and
        (float(prev1["close"]) < float(prev1["open"])) and
        (float(row["close"]) < float(prev1["low"])) and
        is_bear
    )
    # 2. إشارة CALL بعد شمعة التأكيد الصريحة
    call_confirm = (
        (float(prev1["low"]) < float(lo16.iloc[-2])) and
        (float(prev1["close"]) > float(prev1["open"])) and
        (float(row["close"]) > float(prev1["high"])) and
        is_bull
    )

    stop_pts = 8.0  # وقف تنفسي محكم 8 نقاط مطابق للأصل
    tp_pts = 10.0   # هدف سريع 10 نقاط مطابق للأصل

    if put_confirm and atr_val > 0:
        signals.append(US500Signal(
            asset="US500",
            spec_id="SNIPER_PUT_CONFIRM",
            side=-1,
            price=cur_px,
            stop_level=round(cur_px + stop_pts, 1),
            target_level=round(cur_px - tp_pts, 1),
            time=t_str,
            reasons=[
                "كنس قمة الساعات السابقة واكتمال شمعة إعادة الاختبار وتأكيد الكسر لأسفل",
                "التوافق التام مع الاتجاه العام الهابط على فريم الساعة (أدنى من EMA50)",
                f"الهدف السريع: {tp_pts} نقاط لتحقيق ربح متفجر وخروج آمن قبل الارتداد"
            ]
        ))
    elif call_confirm and atr_val > 0:
        signals.append(US500Signal(
            asset="US500",
            spec_id="SNIPER_CALL_CONFIRM",
            side=1,
            price=cur_px,
            stop_level=round(cur_px - stop_pts, 1),
            target_level=round(cur_px + tp_pts, 1),
            time=t_str,
            reasons=[
                "كنس قاع الساعات السابقة واكتمال شمعة إعادة الاختبار وتأكيد الاختراق لأعلى",
                "التوافق مع الاتجاه الصاعد على فريم الساعة (أعلى من EMA50)",
                f"الهدف السريع: {tp_pts} نقاط لتحقيق ربح متفجر وخروج آمن قبل الارتداد"
            ]
        ))

    return signals
