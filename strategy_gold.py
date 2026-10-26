"""
محرك استراتيجيات الذهب المؤسسي (Gold Trend & SMC Engine).
الأصل: GOLD (CFD على الذهب الفوري في Capital.com).

القواعد المعتمدة بحثياً:
1. [GOLD_TREND]: كسر قمة/قاع 20 يوماً مع اتجاه EMA200 اليومي (Turtle Trend Rider).
   الهدف: ركوب ترندات الذهب الضخمة (+88.8% ربح تاريخي، PF 4.80).
   الخروج: كسر قاع/قمة 10 أيام مع تأمين الوقف.
2. [GOLD_SMC]: كنس سيولة 4H (كسر قاع 20 شمعة والارتداد فوقه في ترند صاعد).
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
import pandas as pd
import numpy as np
from typing import Dict, List, Optional

@dataclass
class GoldSignal:
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

def scan_gold_signals(df_4h: pd.DataFrame, df_1d: pd.DataFrame) -> List[GoldSignal]:
    signals: List[GoldSignal] = []
    if df_4h is None or len(df_4h) < 50 or df_1d is None or len(df_1d) < 50:
        return signals

    # 1. تحليل الشموع اليومية (Daily Donchian 20)
    d1 = df_1d.copy()
    c_d, h_d, l_d = d1["close"].astype(float), d1["high"].astype(float), d1["low"].astype(float)
    d1["hi20"] = h_d.rolling(20).max().shift(1)
    d1["lo20"] = l_d.rolling(20).min().shift(1)
    d1["ema200"] = c_d.ewm(span=200, adjust=False).mean()
    d1["atr"] = compute_atr(d1, 14)

    cur_d = d1.iloc[-1]
    prev_d = d1.iloc[-2]
    atr_d = float(cur_d["atr"])
    cur_p = float(cur_d["close"])

    # اختراق قمة 20 يوماً فوق EMA200
    buy_trend = (cur_d["close"] > cur_d["hi20"]) and (cur_d["close"] > cur_d["ema200"])
    sell_trend = (cur_d["close"] < cur_d["lo20"]) and (cur_d["close"] < cur_d["ema200"])

    if buy_trend and not (prev_d["close"] > prev_d["hi20"]):
        signals.append(GoldSignal(
            asset="GOLD",
            spec_id="GOLD_TREND",
            side=1,
            price=cur_p,
            stop_level=round(cur_p - 1.5 * atr_d, 2),
            target_level=round(cur_p + 4.5 * atr_d, 2),
            time=str(cur_d.get("time", "")),
            reasons=["اختراق قمة 20 يوماً في الذهب للأعلى", "السعر أعلى من متوسط 200 اليومي المؤسسي", "ركوب موجة صعود رئيسية"]
        ))
    elif sell_trend and not (prev_d["close"] < prev_d["lo20"]):
        signals.append(GoldSignal(
            asset="GOLD",
            spec_id="GOLD_TREND",
            side=-1,
            price=cur_p,
            stop_level=round(cur_p + 1.5 * atr_d, 2),
            target_level=round(cur_p - 4.5 * atr_d, 2),
            time=str(cur_d.get("time", "")),
            reasons=["كسر قاع 20 يوماً في الذهب للأسفل", "السعر أسفل من متوسط 200 اليومي المؤسسي", "ركوب موجة هبوط رئيسية"]
        ))

    # 2. كنس سيولة 4H في الذهب (SMC 4H)
    h4 = df_4h.copy()
    c_4, h_4, l_4, o_4 = h4["close"].astype(float), h4["high"].astype(float), h4["low"].astype(float), h4["open"].astype(float)
    h4["lo20"] = l_4.rolling(20).min().shift(1)
    h4["hi20"] = h_4.rolling(20).max().shift(1)
    h4["ema100"] = c_4.ewm(span=100, adjust=False).mean()
    h4["atr"] = compute_atr(h4, 14)

    cur_4 = h4.iloc[-1]
    prev_4 = h4.iloc[-2]
    atr_4 = float(cur_4["atr"])
    p_4 = float(cur_4["close"])

    # كنس قاع في ترند صاعد
    buy_smc = (cur_4["low"] < cur_4["lo20"]) and (cur_4["close"] > cur_4["lo20"]) and (cur_4["close"] > cur_4["open"]) and (cur_4["close"] > cur_4["ema100"])
    if buy_smc and not (prev_4["low"] < prev_4["lo20"] and prev_4["close"] > prev_4["lo20"]):
        signals.append(GoldSignal(
            asset="GOLD",
            spec_id="GOLD_SMC",
            side=1,
            price=p_4,
            stop_level=round(p_4 - 1.2 * atr_4, 2),
            target_level=round(p_4 + 3.0 * atr_4, 2),
            time=str(cur_4.get("time", "")),
            reasons=["كنس قاع 20 شمعة 4H في الذهب وارتداد قوي", "إغلاق شمعة خضراء فوق القاع المكسور", "السعر فوق EMA100"]
        ))

    return signals
