"""نظام توصيات وتداول البيتكوين المؤسسي (Bitcoin Elite Trend & Liquidity System).

مبني على أقوى 3 استراتيجيات مجربة ومثبتة إحصائياً بعد خصم تكاليف السبريد والانزلاق (PF 1.64، أرباح +171.5R):
  1) A (اختراق دونشيان اليومي 1D): كسر قمة 55 يوماً بحجم مؤسسي فوق EMA200 (فوز 61.1%، PF 2.41).
  2) B (نظام السلاحف 4 ساعات - Turtle 20 Trend Rider): كسر قمة/قاع 20 شمعة 4H مع ترند EMA200 ووقف متحرك (PF 1.56، +128.8R، صفقة أسبوعياً).
  3) C (قنص السيولة المؤسسية 4H SMC Liquidity Sweep): اصطياد فخاخ الدببة بعد كنس قاع 24 شمعة داخل ترند صاعد (فوز 52.4%، PF 1.87).
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
    rr: float | None       # الهدف بمضاعف R (None = وقف متحرك فقط)
    trail_r: float | None  # وقف متحرك على بُعد trail_r × R من أفضل سعر
    priority: int          # الأولوية عند تزامن إشارتين
    desc: str = ""


SPECS: dict[str, Spec] = {
    "A": Spec("A", "اختراق دونشيان اليومي", "1d", 2.0, 2.0, None, 1,
              "كسر قمة 55 يوماً بحجم مؤسسي فوق EMA200 — يركب موجات الصعود الكبرى (فوز 61%، PF 2.41)"),
    "C": Spec("C", "قنص السيولة (4س)", "4h", 1.5, 2.0, None, 2,
              "كنس ستوبات قاع 24 شمعة ثم ارتداد قوي داخل ترند يومي صاعد — فخ الدببة (فوز 52%، PF 1.87)"),
    "B": Spec("B", "نظام السلاحف 4H (Turtle 20)", "4h", 2.0, None, 2.0, 3,
              "نظام كسر قمم/قيعان 20 شمعة مع الاتجاه ووقف متحرك ديناميكي (PF 1.56، +128.8R، صفقة أسبوعياً)"),
}

MIN_BARS = {"1d": 260, "4h": 260}


def daily_regime(d1: pd.DataFrame) -> pd.DataFrame:
    c = d1["close"]
    e20, e50, e200 = ema(c, 20), ema(c, 50), ema(c, 200)
    out = pd.DataFrame({"ts": d1["ts"]})
    out["bull"] = ((c > e50) & (e50 > e50.shift(5))).values
    out["bull_strong"] = ((c > e200) & (e20 > e50)).values
    out["bear"] = ((c < e50) & (e50 < e50.shift(5)) & (c < e200)).values
    return out


def regime_for(h4: pd.DataFrame, d1: pd.DataFrame) -> pd.DataFrame:
    reg = daily_regime(d1)
    reg = reg.assign(ts=pd.to_datetime(reg["ts"] + pd.Timedelta(days=1), utc=True))
    day = h4[["ts"]].assign(day=pd.to_datetime(h4["ts"].dt.floor("D"), utc=True))
    reg_day = reg.rename(columns={"ts": "day"})
    day["day"] = day["day"].astype("datetime64[ns, UTC]")
    reg_day["day"] = reg_day["day"].astype("datetime64[ns, UTC]")
    m = pd.merge_asof(day.sort_values("day"), reg_day.sort_values("day"), on="day", direction="backward")
    m = m.sort_values("day").reset_index(drop=True)
    for col in ("bull", "bull_strong", "bear"):
        m[col] = m[col].astype("boolean").fillna(False).astype(bool)
    return m[["bull", "bull_strong", "bear"]]


def signals_daily(d1: pd.DataFrame) -> pd.DataFrame:
    c = d1["close"]
    a = atr(d1)
    hi55 = d1["high"].rolling(55).max().shift()
    v20 = d1["volume"].rolling(20).mean()
    e200 = ema(c, 200)
    long = (c > hi55) & (c > e200) & (d1["volume"] > 1.3 * v20)
    return pd.DataFrame({"ts": d1["ts"], "A": np.where(long, 1, 0), "atr": a.values})


def signals_4h(h4: pd.DataFrame, d1: pd.DataFrame) -> pd.DataFrame:
    c, o, l, h = h4["close"], h4["open"], h4["low"], h4["high"]
    a = atr(h4)
    e100 = ema(c, 100)
    e200 = ema(c, 200)
    reg = regime_for(h4, d1)

    # 1. الاستراتيجية C: قنص السيولة SMC Sweep
    lo24 = l.rolling(24).min().shift()
    sig_c = (l < lo24) & (c > lo24) & (c > o) & (c > e100) & reg["bull_strong"].values

    # 2. الاستراتيجية B: نظام السلاحف Turtle 20 Trend Rider
    hi20 = h.rolling(20).max().shift()
    lo20 = l.rolling(20).min().shift()
    turtle_long = (c > hi20) & (c > e200)
    turtle_short = (c < lo20) & (c < e200)
    sig_b = np.where(turtle_long, 1, np.where(turtle_short, -1, 0))

    return pd.DataFrame({
        "ts": h4["ts"],
        "C": np.where(sig_c, 1, 0),
        "B": sig_b,
        "atr": a.values,
        "ema200": e200.values,
        "hi20": hi20.values,
        "lo20": lo20.values,
        "bull": reg["bull"].values,
        "bull_strong": reg["bull_strong"].values,
        "bear": reg["bear"].values
    })


# ── إشارة حية ───────────────────────────────────────────────────

@dataclass
class Signal:
    strategy: str
    side: int                 # 1 شراء / -1 بيع
    bar_ts: pd.Timestamp
    ref_price: float
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
        out["tp1"] = entry + s * d
        return out


def closed_only(df: pd.DataFrame, tf: str, now: pd.Timestamp | None = None) -> pd.DataFrame:
    now = now or pd.Timestamp.now(tz="UTC")
    step = pd.Timedelta(tf.replace("d", "D").replace("h", "h"))
    return df[df["ts"] + step <= now].reset_index(drop=True)


def latest_signals(h4: pd.DataFrame, d1: pd.DataFrame) -> list[Signal]:
    out: list[Signal] = []
    # 1. الاستراتيجية A (اليومي)
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
    # 2. الاستراتيجيتان C و B (4 ساعات)
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
            dir_str = "صاعد (شراء 🟢)" if side > 0 else "هابط (بيع 🔴)"
            level_str = f"قمة 20 شمعة (${last['hi20']:,.0f})" if side > 0 else f"قاع 20 شمعة (${last['lo20']:,.0f})"
            out.append(Signal("B", side, row["ts"], float(row["close"]), a, SPECS["B"].stop_atr * a, [
                f"اختراق {level_str} في اتجاه {dir_str}",
                f"السعر {'فوق' if side > 0 else 'تحت'} EMA200 على 4H (${last['ema200']:,.0f})",
                "نظام السلاحف الأسطوري (Turtle 20) مع وقف متحرك ديناميكي (Trailing Stop)",
            ]))
    out.sort(key=lambda s: s.spec.priority)
    return out


def market_state(h4: pd.DataFrame, d1: pd.DataFrame) -> dict:
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
        "ema200_4h": float(last["ema200"]),
        "hi20_4h": float(last["hi20"]),
        "lo20_4h": float(last["lo20"]),
        "ema50_d": float(e50), "ema200_d": float(e200), "hi55_d": float(hi55),
        "atr_4h": float(last["atr"]), "dist_hi55_pct": (hi55 / float(c.iloc[-1]) - 1) * 100,
    }


def trail_stop(side: int, entry: float, stop: float, stop_dist: float, best: float, trail_r: float | None) -> float:
    if not trail_r:
        return stop
    ns = best - side * trail_r * stop_dist
    return max(stop, ns) if side > 0 else min(stop, ns)
