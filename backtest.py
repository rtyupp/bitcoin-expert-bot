"""الاختبار التاريخي للمحفظة — يستخدم strategy.py نفسه (نفس كود البوت الحي).

المحاكاة على ساعة 4h، صفقة واحدة كحد أقصى لكل استراتيجية (حارس لكل استراتيجية في البوت الحي):
  - إشارة A اليومية عند إغلاق اليوم D → دخول بافتتاح أول شمعة 4h من اليوم D+1
  - إشارات C/B عند إغلاق شمعة 4h → دخول بافتتاح التالية
  - لمس الوقف والهدف في نفس الشمعة = نحسبه وقف (تحفّظ)، والفجوات تُنفّذ بسعر الافتتاح
  - تكلفة 0.12% ذهاب وعودة + تبييت 0.06% يومياً

تشغيل:  python backtest.py [csv_dir]   (بدون مسار يجلب البيانات من Binance)
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import strategy as S

COST = 0.0012
FUND_PER_DAY = 0.0006


def simulate(h4: pd.DataFrame, d1: pd.DataFrame, cost: float = COST, fund: float = FUND_PER_DAY,
             enabled: tuple[str, ...] = ("A", "C", "B")) -> pd.DataFrame:
    """كل استراتيجية لها خانة مستقلة (صفقة واحدة كحد أقصى لكل استراتيجية) — مطابق للبوت الحي."""
    parts = [_simulate_one(h4, d1, cost, fund, k) for k in enabled]
    parts = [p for p in parts if not p.empty]
    if not parts:
        return pd.DataFrame(columns=["ts", "exit_ts", "strat", "side", "entry", "exit", "risk_pct", "r", "days"])
    return pd.concat(parts).sort_values("ts").reset_index(drop=True)


def _simulate_one(h4, d1, cost, fund, only):
    enabled = (only,)
    h4 = h4.reset_index(drop=True)
    s4 = S.signals_4h(h4, d1)
    sd = S.signals_daily(d1)
    ts_idx = {t: i for i, t in enumerate(h4["ts"])}

    by_bar: dict[int, list] = {}
    if "A" in enabled:
        for i in range(S.MIN_BARS["1d"], len(sd)):
            if sd["A"].iat[i] and np.isfinite(sd["atr"].iat[i]):
                j = ts_idx.get(sd["ts"].iat[i] + pd.Timedelta(days=1))
                if j is not None and j >= S.MIN_BARS["4h"]:
                    by_bar.setdefault(j, []).append(("A", int(sd["A"].iat[i]), float(sd["atr"].iat[i])))
    n = len(h4)
    for i in range(S.MIN_BARS["4h"], n - 1):
        for k in ("C", "B"):
            if k in enabled and s4[k].iat[i] != 0:
                by_bar.setdefault(i + 1, []).append((k, int(s4[k].iat[i]), float(s4["atr"].iat[i])))

    o, h, l = h4["open"].values, h4["high"].values, h4["low"].values
    trades, pos = [], None
    for j in range(S.MIN_BARS["4h"], n):
        if pos is None and j in by_bar:
            k, side, a = sorted(by_bar[j], key=lambda p: S.SPECS[p[0]].priority)[0]
            spec = S.SPECS[k]
            e = o[j]; d = spec.stop_atr * a
            pos = {"k": k, "side": side, "e": e, "d": d, "stop": e - side * d,
                   "tp": e + side * spec.rr * d if spec.rr else None, "best": e, "j0": j}
        if pos is None:
            continue
        s, e, d, st, tp = pos["side"], pos["e"], pos["d"], pos["stop"], pos["tp"]
        exit_px = None
        if s > 0:
            if l[j] <= st:
                exit_px = min(st, o[j])
            elif tp is not None and h[j] >= tp:
                exit_px = max(tp, o[j]) if j > pos["j0"] else tp
            else:
                pos["best"] = max(pos["best"], h[j])
        else:
            if h[j] >= st:
                exit_px = max(st, o[j])
            elif tp is not None and l[j] <= tp:
                exit_px = min(tp, o[j]) if j > pos["j0"] else tp
            else:
                pos["best"] = min(pos["best"], l[j])
        if exit_px is None:
            pos["stop"] = S.trail_stop(s, e, st, d, pos["best"], S.SPECS[pos["k"]].trail_r)
            continue
        days = (j - pos["j0"] + 1) * 4 / 24
        r_net = s * (exit_px - e) / d - cost * e / d - days * fund * e / d
        trades.append({"ts": h4["ts"].iat[pos["j0"]], "exit_ts": h4["ts"].iat[j], "strat": pos["k"],
                       "side": s, "entry": e, "exit": exit_px, "risk_pct": d / e * 100, "r": r_net, "days": days})
        pos = None
    return pd.DataFrame(trades)


def stats(t: pd.DataFrame) -> dict:
    if t.empty:
        return {"n": 0}
    r = t["r"]
    eq = r.cumsum(); dd = float((eq.cummax() - eq).max())
    loss = -r[r < 0].sum()
    yrs = max((t["ts"].iloc[-1] - t["ts"].iloc[0]).days / 365.25, 0.5)
    streak = cur = 0
    for x in r:
        cur = cur + 1 if x < 0 else 0
        streak = max(streak, cur)
    return {"n": int(len(t)), "win": round(float((r > 0).mean() * 100), 1),
            "pf": round(float(r[r > 0].sum() / loss), 2) if loss else 99.0,
            "exp_r": round(float(r.mean()), 3), "total_r": round(float(r.sum()), 1),
            "max_dd_r": round(dd, 1), "per_year": round(len(t) / yrs, 1),
            "max_loss_streak": streak,
            "ret_1pct": round(float((1 + 0.01 * r).prod() - 1) * 100)}


def report(t: pd.DataFrame) -> str:
    cut = pd.Timestamp("2024-01-01", tz="UTC")
    lines = [f"{lbl:18s} {stats(p)}" for lbl, p in
             (("الكل", t), ("تدريب <2024", t[t.ts < cut]), ("خارج العينة ≥2024", t[t.ts >= cut]))]
    for k in ("A", "C", "B"):
        lines.append(f"  {k}: {stats(t[t.strat == k])}")
    yr = t.groupby(t.ts.dt.year)["r"].agg(["count", "sum"])
    lines.append("سنوياً (عدد/R): " + ", ".join(f"{y}:{int(a)}/{b:+.1f}" for y, (a, b) in yr.iterrows()))
    return "\n".join(lines)


def load(path_dir: str | None):
    if path_dir:
        h4 = pd.read_csv(f"{path_dir}/btc_4h.csv", parse_dates=["ts"])
        d1 = pd.read_csv(f"{path_dir}/btc_1d.csv", parse_dates=["ts"])
    else:
        import markets
        h4, d1 = markets.history("4h", "2018-01-01"), markets.history("1d", "2017-08-17")
    return S.closed_only(h4, "4h"), S.closed_only(d1, "1d")


if __name__ == "__main__":
    h4, d1 = load(sys.argv[1] if len(sys.argv) > 1 else None)
    t = simulate(h4, d1)
    print(f"بيانات: 4h={len(h4)} ({h4.ts.iloc[0].date()}→{h4.ts.iloc[-1].date()}), 1d={len(d1)}")
    print(report(t))
    print("تكاليف ×2:", stats(simulate(h4, d1, cost=COST * 2, fund=FUND_PER_DAY * 2)))
