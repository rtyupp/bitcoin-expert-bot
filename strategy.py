"""نظام توصيات البيتكوين — نفس الكود يُستخدم في الاختبار التاريخي وفي البوت الحي.

ثلاث استراتيجيات اجتازت اختبار خارج العينة (تدريب 2018-2023، تحقق 2024-2026) بعد التكاليف:

  A) اختراق دونشيان اليومي  — كسر قمة 55 يوم + حجم ≥1.3× + فوق EMA200 → شراء، وقف 2×ATR، هدف 2R
  C) قنص السيولة 4 ساعات    — كنس قاع 24 شمعة ثم إغلاق أخضر فوقه، فوق EMA100، نظام يومي صاعد قوي → شراء، وقف 1.5×ATR، هدف 2R
  B) ارتداد RSI(2) 4 ساعات  — تشبّع بيعي RSI2<10 فوق EMA100 في نظام يومي صاعد (أو تشبّع شرائي تحت EMA100 في نظام هابط → بيع)،
                               وقف 2×ATR ثم وقف متحرك على بُعد 2R من أفضل سعر

قواعد التوقيت (لا تسريب للمستقبل):
  - الإشارة تُحسب عند إغلاق الشمعة، والدخول بافتتاح الشمعة التالية.
  - النظام اليومي لشمعة 4h يُؤخذ من آخر يوم مكتمل قبل يوم الشمعة.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# ── المؤشرات ─────────────────────────────────────────────────────

def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    out = out.where(dn > 0, 100.0)
    return out.where((up > 0) | (dn > 0), 50.0)


# ── تعريف الاستراتيجيات ─────────────────────────────────────────

@dataclass(frozen=True)
class Spec:
    key: str
    name: str
    tf: str
    stop_atr: float        # الوقف = stop_atr × ATR
    rr: float | None       # الهدف بمضاعف R (None = بدون هدف ثابت)
    trail_r: float | None  # وقف متحرك على بُعد trail_r × R من أفضل سعر
    priority: int          # الأولوية عند تزامن إشارتين (الأقل أولاً)
    desc: str = ""


SPECS: dict[str, Spec] = {
    "A": Spec("A", "اختراق دونشيان اليومي", "1d", 2.0, 2.0, None, 1,
              "كسر قمة 55 يوماً بحجم مرتفع فوق EMA200 — يركب موجات الصعود الكبرى"),
    "C": Spec("C", "قنص السيولة (4س)", "4h", 1.5, 2.0, None, 2,
              "كنس ستوبات قاع 24 شمعة ثم ارتداد قوي داخل ترند يومي صاعد — فخ الدببة"),
    "B": Spec("B", "ارتداد RSI2 مع الترند (4س)", "4h", 2.0, None, 2.0, 3,
              "شراء التصحيحات الحادة في الترند الصاعد وبيع الارتدادات في الهابط، مع وقف متحرك"),
}

MIN_BARS = {"1d": 260, "4h": 260}


def daily_regime(d1: pd.DataFrame) -> pd.DataFrame:
    """أعمدة النظام اليومي لكل يوم (محسوبة بإغلاق ذلك اليوم)."""
    c = d1["close"]
    e20, e50, e200 = ema(c, 20), ema(c, 50), ema(c, 200)
    out = pd.DataFrame({"ts": d1["ts"]})
    out["bull"] = ((c > e50) & (e50 > e50.shift(5))).values
    out["bull_strong"] = ((c > e200) & (e20 > e50)).values
    out["bear"] = ((c < e50) & (e50 < e50.shift(5)) & (c < e200)).values
    return out


def regime_for(h4: pd.DataFrame, d1: pd.DataFrame) -> pd.DataFrame:
    """يربط كل شمعة 4h بنظام آخر يوم مكتمل قبل يومها."""
    reg = daily_regime(d1)
    reg = reg.assign(ts=pd.to_datetime(reg["ts"] + pd.Timedelta(days=1), utc=True))  # قيمة اليوم D متاحة من بداية D+1
    day = h4[["ts"]].assign(day=pd.to_datetime(h4["ts"].dt.floor("D"), utc=True))
    reg_day = reg.rename(columns={"ts": "day"})
    # توحيد نوع التواريخ لتجنب خطأ incompatible merge keys في pandas 2/3
    day["day"] = day["day"].astype("datetime64[ns, UTC]")
    reg_day["day"] = reg_day["day"].astype("datetime64[ns, UTC]")
    m = pd.merge_asof(day.sort_values("day"), reg_day.sort_values("day"), on="day", direction="backward")
    m = m.sort_values("day").reset_index(drop=True)
    for col in ("bull", "bull_strong", "bear"):
        m[col] = m[col].astype("boolean").fillna(False).astype(bool)
    return m[["bull", "bull_strong", "bear"]]


def signals_daily(d1: pd.DataFrame) -> pd.DataFrame:
    """الاستراتيجية A على الإطار اليومي. ترجع sig و atr لكل شمعة."""
    c = d1["close"]
    a = atr(d1)
    hi55 = d1["high"].rolling(55).max().shift()
    v20 = d1["volume"].rolling(20).mean()
    e200 = ema(c, 200)
    long = (c > hi55) & (c > e200) & (d1["volume"] > 1.3 * v20)
    return pd.DataFrame({"ts": d1["ts"], "A": np.where(long, 1, 0), "atr": a.values})


def signals_4h(h4: pd.DataFrame, d1: pd.DataFrame) -> pd.DataFrame:
    """الاستراتيجيتان C و B على 4 ساعات."""
    c, o, l, h = h4["close"], h4["open"], h4["low"], h4["high"]
    a = atr(h4)
    e100 = ema(c, 100)
    r2 = rsi(c, 2)
    reg = regime_for(h4, d1)

    lo24 = l.rolling(24).min().shift()
    sig_c = (l < lo24) & (c > lo24) & (c > o) & (c > e100) & reg["bull_strong"].values

    b_long = (r2 < 10) & (c > e100) & reg["bull"].values
    b_short = (r2 > 90) & (c < e100) & reg["bear"].values
    sig_b = np.where(b_long, 1, np.where(b_short, -1, 0))

    return pd.DataFrame({"ts": h4["ts"], "C": np.where(sig_c, 1, 0), "B": sig_b, "atr": a.values,
                         "rsi2": r2.values, "ema100": e100.values,
                         "bull": reg["bull"].values, "bull_strong": reg["bull_strong"].values,
                         "bear": reg["bear"].values})


# ── إشارة حية ───────────────────────────────────────────────────

@dataclass
class Signal:
    strategy: str
    side: int                 # 1 شراء / -1 بيع
    bar_ts: pd.Timestamp      # وقت افتتاح الشمعة التي أعطت الإشارة
    ref_price: float          # سعر إغلاق شمعة الإشارة
    atr: float
    stop_dist: float
    reasons: list[str] = field(default_factory=list)

    @property
    def spec(self) -> Spec:
        return SPECS[self.strategy]

    def levels(self, entry: float) -> dict:
        s, d = self.side, self.stop_dist
        out = {"entry": entry, "stop": entry - s * d, "risk_pct": d / entry * 100}
        if self.spec.rr:
            out["tp"] = entry + s * self.spec.rr * d
        out["tp1"] = entry + s * d  # 1R للمعلومية
        return out


def closed_only(df: pd.DataFrame, tf: str, now: pd.Timestamp | None = None) -> pd.DataFrame:
    """يحذف الشمعة غير المكتملة."""
    now = now or pd.Timestamp.now(tz="UTC")
    step = pd.Timedelta(tf.replace("d", "D").replace("h", "h"))
    return df[df["ts"] + step <= now].reset_index(drop=True)


def latest_signals(h4: pd.DataFrame, d1: pd.DataFrame) -> list[Signal]:
    """إشارات آخر شمعة مكتملة (البيانات يجب أن تكون شموعاً مكتملة فقط)."""
    out: list[Signal] = []
    if len(d1) >= MIN_BARS["1d"]:
        sd = signals_daily(d1)
        last = sd.iloc[-1]
        if last["A"] != 0:
            row = d1.iloc[-1]
            hi55 = d1["high"].iloc[-56:-1].max()
            out.append(Signal("A", 1, row["ts"], float(row["close"]), float(last["atr"]),
                              SPECS["A"].stop_atr * float(last["atr"]), [
                                  f"إغلاق يومي ${row['close']:,.0f} فوق قمة 55 يوم ${hi55:,.0f}",
                                  f"حجم {row['volume'] / d1['volume'].iloc[-21:-1].mean():.1f}× المتوسط",
                                  "السعر فوق EMA200 اليومي (ترند كبير صاعد)",
                              ]))
    if len(h4) >= MIN_BARS["4h"] and len(d1) >= 210:
        s4 = signals_4h(h4, d1)
        last = s4.iloc[-1]
        row = h4.iloc[-1]
        a = float(last["atr"])
        if last["C"] != 0:
            lo24 = h4["low"].iloc[-25:-1].min()
            out.append(Signal("C", 1, row["ts"], float(row["close"]), a, SPECS["C"].stop_atr * a, [
                f"كنس قاع 24 شمعة (${lo24:,.0f}) بذيل إلى ${row['low']:,.0f}",
                "إغلاق أخضر عاد فوق مستوى السيولة",
                "فوق EMA100 والنظام اليومي صاعد قوي",
            ]))
        if last["B"] != 0:
            side = int(last["B"])
            out.append(Signal("B", side, row["ts"], float(row["close"]), a, SPECS["B"].stop_atr * a, [
                f"RSI(2) = {last['rsi2']:.1f} — {'تشبّع بيعي' if side > 0 else 'تشبّع شرائي'} حاد",
                f"السعر {'فوق' if side > 0 else 'تحت'} EMA100 ({last['ema100']:,.0f})",
                f"النظام اليومي {'صاعد' if side > 0 else 'هابط'}",
            ]))
    out.sort(key=lambda s: s.spec.priority)
    return out


def market_state(h4: pd.DataFrame, d1: pd.DataFrame) -> dict:
    """ملخص حالة السوق الحالية (للعرض)."""
    s4 = signals_4h(h4, d1)
    last = s4.iloc[-1]
    c = d1["close"]
    e50, e200 = ema(c, 50).iloc[-1], ema(c, 200).iloc[-1]
    hi55 = d1["high"].iloc[-55:].max()
    reg = "صاعد قوي 🟢" if last["bull_strong"] and last["bull"] else "صاعد 🟢" if last["bull"] else \
          "هابط 🔴" if last["bear"] else "محايد ⚪"
    return {
        "price": float(h4["close"].iloc[-1]),
        "regime": reg,
        "bull": bool(last["bull"]), "bear": bool(last["bear"]), "bull_strong": bool(last["bull_strong"]),
        "rsi2": float(last["rsi2"]), "ema100_4h": float(last["ema100"]),
        "ema50_d": float(e50), "ema200_d": float(e200), "hi55_d": float(hi55),
        "atr_4h": float(last["atr"]), "dist_hi55_pct": (hi55 / float(c.iloc[-1]) - 1) * 100,
    }


# ── إدارة الصفقة (مشتركة بين الاختبار والحي) ─────────────────────

def trail_stop(side: int, entry: float, stop: float, stop_dist: float, best: float, trail_r: float | None) -> float:
    """يحسب الوقف الجديد: لا يتراجع أبداً، يتحرك على بُعد trail_r×R من أفضل سعر."""
    if not trail_r:
        return stop
    ns = best - side * trail_r * stop_dist
    return max(stop, ns) if side > 0 else min(stop, ns)
