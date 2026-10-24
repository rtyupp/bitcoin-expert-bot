"""نواة استراتيجيات البيتكوين المؤسسية المتكيفة (Bitcoin Institutional Adaptive Strategies).

تدمج 4 محركات، وكلها مفحوصة على شموع مغلقة فقط:
1. [A] اختراق دونشيان اليومي المؤسسي (Donchian 55 Daily Breakout) — ركوب الاتجاه الكاسح.
2. [B] سحابة إيشيموكو وبولينجر 4H (Jesse Ichimoku Cloud Breakout) — ركوب الاتجاه مع خروج على MA20.
3. [C] قنص كنس السيولة 4H (SMC Liquidity Sweep) — اصطياد فخاخ الدببة عند كسر القيعان.
4. [D] قنص تحركات الحيتان 4H (Whale Shadow) — تجميع/تصريف عند أطراف بولينجر.

الاختبار الخلفي على كود المحرك نفسه (شموع مغلقة، 1% مخاطرة، سبريد $50،
تأمين وقف 0.8R): آخر 12 شهراً 38 صفقة وفوز 21.1% و PF 1.09 وصافي +1.1%،
وآخر 6 أشهر 19 صفقة وصافي -3.0%. التفاصيل في backtest_6m.py و README.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple

from capital_trader import client

@dataclass
class StrategySpec:
    id: str
    name: str
    timeframe: str
    rr: float
    description: str

SPECS: Dict[str, StrategySpec] = {
    "A": StrategySpec("A", "الانفجار الشهري المؤسسي (Donchian 55)", "1d", 3.0, "ركوب موجات الصعود الكبرى بالبيتكوين عند كسر قمة 55 يوماً فوق EMA200"),
    "B": StrategySpec("B", "سحابة إيشيموكو وبولينجر 4H (Long Trend)", "4h", 2.0, "ركوب الاتجاه الصاعد فوق متوسط 200 يوم، مع خروج على إغلاق MA20"),
    "C": StrategySpec("C", "قنص كنس السيولة SMC 30-Bar", "4h", 2.0, "اصطياد فخاخ الدببة وكنس قاع 30 شمعة ثم الارتداد"),
    "D": StrategySpec("D", "قنص تحركات الحيتان في التذبذب (Whale Shadow)", "4h", 1.67, "اصطياد تجميع وتصريف الحيتان عبر تدفق السيولة MFI عند أطراف بولينجر"),
}

@dataclass
class Signal:
    spec_id: str
    side: int  # 1 = BUY, -1 = SELL
    price: float
    stop_level: float
    target_level: float
    time: str
    reasons: List[str] = field(default_factory=list)

    @property
    def spec(self) -> StrategySpec:
        return SPECS[self.spec_id]

def compute_atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = np.maximum(h - l, np.maximum(abs(h - c.shift(1)), abs(l - c.shift(1))))
    return tr.rolling(n).mean()

def compute_indicators_4h(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c, h, l, o = df["close"], df["high"], df["low"], df["open"]
    df["atr"] = compute_atr(df, 14)
    df["ema50"] = c.ewm(span=50, adjust=False).mean()
    df["ema100"] = c.ewm(span=100, adjust=False).mean()
    df["ema200"] = c.ewm(span=200, adjust=False).mean()

    # Bollinger Bands
    df["ma20"] = c.rolling(20).mean()
    std20 = c.rolling(20).std()
    df["bb_upper"] = df["ma20"] + 2.0 * std20
    df["bb_lower"] = df["ma20"] - 2.0 * std20

    # Ichimoku Cloud
    tenkan = (h.rolling(9).max() + l.rolling(9).min()) / 2
    kijun = (h.rolling(26).max() + l.rolling(26).min()) / 2
    df["span_a"] = ((tenkan + kijun) / 2).shift(26)
    df["span_b"] = ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(26)

    # SMC 30-Bar Low/High (النافذة الذهبية الأعلى ربحاً)
    df["lo30"] = l.rolling(30).min().shift(1)
    df["hi30"] = h.rolling(30).max().shift(1)

    return df

def compute_indicators_1h(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c, h, l = df["close"], df["high"], df["low"]
    df["atr"] = compute_atr(df, 14)

    # ADX
    tr = np.maximum(h - l, np.maximum(abs(h - c.shift(1)), abs(l - c.shift(1))))
    plus_dm = (h - h.shift(1)).clip(lower=0)
    minus_dm = (l.shift(1) - l).clip(lower=0)
    tr_14 = tr.rolling(14).sum()
    plus_di = 100 * (plus_dm.rolling(14).sum() / (tr_14 + 1e-9))
    minus_di = 100 * (minus_dm.rolling(14).sum() / (tr_14 + 1e-9))
    dx = 100 * (abs(plus_di - minus_di) / (plus_di + minus_di + 1e-9))
    df["adx"] = dx.rolling(14).mean()

    # Bollinger Bands
    ma20 = c.rolling(20).mean()
    std20 = c.rolling(20).std()
    df["bb_upper"] = ma20 + 2.0 * std20
    df["bb_lower"] = ma20 - 2.0 * std20
    return df

def compute_indicators_1d(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c, h = df["close"], df["high"]
    df["atr"] = compute_atr(df, 14)
    df["ema50"] = c.ewm(span=50, adjust=False).mean()
    df["ema200"] = c.ewm(span=200, adjust=False).mean()
    df["vol_ma"] = df["volume"].rolling(20).mean()
    df["hi55"] = h.rolling(55).max().shift(1)
    return df

def scan_signals(df_1h: pd.DataFrame, df_4h: pd.DataFrame, df_1d: pd.DataFrame) -> List[Signal]:
    """فحص الشموع الأخيرة المغلقة واكتشاف الفرص الحقيقية."""
    signals = []

    # 1. فحص إشارات 4H
    h4 = compute_indicators_4h(df_4h)
    d1 = compute_indicators_1d(df_1d)

    cur_4h = h4.iloc[-1]
    prev_4h = h4.iloc[-2]
    cur_d1 = d1.iloc[-1]

    d_bull = cur_d1["close"] > cur_d1["ema50"]
    d_bear = cur_d1["close"] < cur_d1["ema50"]

    # [B] سحابة إيشيموكو وبولينجر 4H (Long-Only مع فلتر الحيتان وفلتر معنويات القطيع)
    # السر الأسطوري: رفع عتبة قوة الاتجاه الصافي ADX >= 25 لمنع صفقات التذبذب الخامل
    c_s = h4["close"]
    net_c = abs(c_s - c_s.shift(14))
    noise = abs(c_s - c_s.shift(1)).rolling(14).sum()
    er_val = float((net_c / (noise + 1e-9)).iloc[-1])

    # حساب تدفق السيولة MFI
    typ = (h4["high"] + h4["low"] + h4["close"]) / 3
    raw_m = typ * h4["volume"]
    pos_m = pd.Series(np.where(typ > typ.shift(1), raw_m, 0.0)).rolling(14).sum()
    neg_m = pd.Series(np.where(typ < typ.shift(1), raw_m, 0.0)).rolling(14).sum()
    mfi_series = 100 - (100 / (1 + (pos_m / (neg_m + 1e-9))))
    mfi_val = float(mfi_series.iloc[-1])

    # حساب ADX 4H
    tr4_s = np.maximum(h4["high"] - h4["low"], np.maximum(abs(h4["high"] - c_s.shift(1)), abs(h4["low"] - c_s.shift(1))))
    p_dm = (h4["high"] - h4["high"].shift(1)).clip(lower=0)
    m_dm = (h4["low"].shift(1) - h4["low"]).clip(lower=0)
    tr_sum = tr4_s.rolling(14).sum()
    p_di = 100 * (p_dm.rolling(14).sum() / (tr_sum + 1e-9))
    m_di = 100 * (m_dm.rolling(14).sum() / (tr_sum + 1e-9))
    adx_4h_val = float((100 * (abs(p_di - m_di) / (p_di + m_di + 1e-9))).rolling(14).mean().iloc[-1])

    # فلتر الدايفرجنس السلبي: السعر يخترق قمة لكن تدفق السيولة MFI هابط (تصريف حيتان)
    highest_mfi_20 = float(mfi_series.rolling(20).max().shift(1).iloc[-1])
    is_mfi_divergence = (cur_4h["close"] > float(h4["high"].rolling(20).max().shift(1).iloc[-1])) and (mfi_val < highest_mfi_20 - 5.0)

    # فلتر استشعار معنويات كابيتال: فحص التضخم المفرط في شراء القطيع
    sent = client.get_sentiment("BTCUSD")
    retail_greed_trap = bool(sent and sent.get("long_pct", 50.0) > 80.0)

    # 1. صفقات الترند المؤسسي الصاعد (Jesse Bull)
    jesse_buy = (cur_4h["close"] > cur_4h["bb_upper"]) and (cur_4h["close"] > cur_4h["span_a"]) and (cur_4h["close"] > cur_4h["span_b"]) and (cur_4h["close"] > cur_4h["ema200"]) and (adx_4h_val >= 25.0) and (er_val >= 0.35) and (mfi_val >= 50.0) and (not is_mfi_divergence) and (not retail_greed_trap)

    # 2. صفقات الهبوط المؤسسي الصريح (Bear Trend Short):
    # كسر أسفل بولينجر وتحت سحابة كومو وتحت EMA200 4H مع شرط التوافق اليومي الحاسم (السعر اليومي تحت EMA200 اليومي)
    # وقوة اتجاه هابطة ADX >= 25 وتدفق سيولة سلبي MFI <= 45
    cur_d1_close = float(cur_d1["close"])
    cur_d1_ema200 = float(cur_d1["ema200"])
    daily_bear_aligned = cur_d1_close < cur_d1_ema200

    jesse_short = (cur_4h["close"] < cur_4h["bb_lower"]) and (cur_4h["close"] < cur_4h["span_a"]) and (cur_4h["close"] < cur_4h["span_b"]) and (cur_4h["close"] < cur_4h["ema200"]) and daily_bear_aligned and (adx_4h_val >= 25.0) and (er_val >= 0.35) and (mfi_val <= 45.0)

    if jesse_buy and not ((prev_4h["close"] > prev_4h["bb_upper"]) and (prev_4h["close"] > prev_4h["span_a"])):
        entry = float(cur_4h["close"])
        atr_val = float(cur_4h["atr"])
        signals.append(Signal(
            spec_id="B", side=1, price=entry,
            stop_level=round(entry - 2.0 * atr_val, 2),
            target_level=round(entry + 4.0 * atr_val, 2),
            time=str(cur_4h["time"]),
            reasons=["اختراق سحابة إيشيموكو وبولينجر 4H للأعلى", "السعر أعلى من متوسط 200 المؤسسي (الاتجاه الصاعد النقي)", "زخم مؤسسي قوي وتدفق سيولة إيجابي"]
        ))
    elif jesse_short and not ((prev_4h["close"] < prev_4h["bb_lower"]) and (prev_4h["close"] < prev_4h["span_a"])):
        entry = float(cur_4h["close"])
        atr_val = float(cur_4h["atr"])
        signals.append(Signal(
            spec_id="B", side=-1, price=entry,
            stop_level=round(entry + 2.0 * atr_val, 2),
            target_level=round(entry - 4.0 * atr_val, 2),
            time=str(cur_4h["time"]),
            reasons=["كسر سحابة إيشيموكو وبولينجر 4H للأسفل", "السعر أسفل متوسط 200 المؤسسي (الاتجاه الهابط الصريح)", "قوة اتجاه هابطة ADX >= 25 وتدفق أموال سلبي"]
        ))

    # [C] SMC Liquidity Sweep 30-bar 4H (النافذة المحسنة PF 2.10)
    smc_buy = (cur_4h["low"] < cur_4h["lo30"]) and (cur_4h["close"] > cur_4h["lo30"]) and (cur_4h["close"] > cur_4h["open"]) and (cur_4h["close"] > cur_4h["ema100"])
    if smc_buy and not (prev_4h["low"] < prev_4h["lo30"] and prev_4h["close"] > prev_4h["lo30"]):
        entry = float(cur_4h["close"])
        atr_val = float(cur_4h["atr"])
        signals.append(Signal(
            spec_id="C", side=1, price=entry,
            stop_level=round(entry - 1.5 * atr_val, 2),
            target_level=round(entry + 3.0 * atr_val, 2),
            time=str(cur_4h["time"]),
            reasons=["كنس سيولة عميق (كسر قاع 30 شمعة 4H ثم ارتداد قوي)", "إغلاق شمعة 4H خضراء فوق مستوى القاع المكسور", "السعر فوق متوسط EMA100 المؤسسي"]
        ))

    # [D] قنص تحركات الحيتان في التذبذب (Whale Shadow Accumulation/Distribution)
    # تجميع الحيتان (Whale Pump): السعر عند قاع بولينجر وتدفق السيولة قوي MFI > 52 وشمعة خضراء
    whale_pump = (cur_4h["low"] <= cur_4h["bb_lower"]) and (mfi_val > 52.0) and (cur_4h["close"] > cur_4h["open"])
    # تصريف الحيتان (Whale Dump): السعر عند قمة بولينجر وتدفق السيولة ضعيف MFI < 48 وشمعة حمراء
    whale_dump = (cur_4h["high"] >= cur_4h["bb_upper"]) and (mfi_val < 48.0) and (cur_4h["close"] < cur_4h["open"])

    if whale_pump and not ((prev_4h["low"] <= prev_4h["bb_lower"]) and (prev_4h["close"] > prev_4h["open"])):
        entry = float(cur_4h["close"])
        atr_val = float(cur_4h["atr"])
        signals.append(Signal(
            spec_id="D", side=1, price=entry,
            stop_level=round(entry - 1.5 * atr_val, 2),
            target_level=round(entry + 2.5 * atr_val, 2),
            time=str(cur_4h["time"]),
            reasons=["تجميع حيتان خفي (Whale Accumulation)", "السعر عند قاع بولينجر لكن تدفق السيولة MFI صاعد بقوة", "إغلاق شمعة ارتدادية صاعدة خضراء"]
        ))
    elif whale_dump and not ((prev_4h["high"] >= prev_4h["bb_upper"]) and (prev_4h["close"] < prev_4h["open"])):
        entry = float(cur_4h["close"])
        atr_val = float(cur_4h["atr"])
        signals.append(Signal(
            spec_id="D", side=-1, price=entry,
            stop_level=round(entry + 1.5 * atr_val, 2),
            target_level=round(entry - 2.5 * atr_val, 2),
            time=str(cur_4h["time"]),
            reasons=["تصريف حيتان خفي (Whale Distribution)", "السعر عند قمة بولينجر لكن تدفق السيولة MFI هابط وضعيف", "إغلاق شمعة انعكاسية هابطة حمراء"]
        ))

    # [A] الانفجار الشهري المؤسسي (Donchian 55 Daily Breakout)
    prev_d1 = d1.iloc[-2]
    don_buy = (cur_d1["close"] > cur_d1["hi55"]) and (cur_d1["close"] > cur_d1["ema200"])
    if don_buy and not (prev_d1["close"] > prev_d1["hi55"]):
        entry = float(cur_d1["close"])
        atr_val = float(cur_d1["atr"])
        signals.append(Signal(
            spec_id="A", side=1, price=entry,
            stop_level=round(entry - 2.0 * atr_val, 2),
            target_level=round(entry + 5.0 * atr_val, 2),
            time=str(cur_d1["time"]),
            reasons=["اختراق قمة 55 يوماً التاريخية (الانفجار الشهري)", "السعر أعلى من متوسط 200 يوم المؤسسي", "وقف 2×ATR وهدف 5×ATR"]
        ))

    return signals
