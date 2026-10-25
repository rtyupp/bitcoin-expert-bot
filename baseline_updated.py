"""الخط الأساسي على البيانات المحدّثة + مقارنة العائد/المخاطرة."""
from __future__ import annotations

from dataclasses import replace

import pandas as pd

import optimize as O
import research_v2 as R

FUND = (0.0616438, 0.0136986)
END = pd.Timestamp("2026-10-24 20:00:00", tz="UTC")
FULL = (pd.Timestamp("2018-01-01", tz="UTC"), END)
TRAIN = (pd.Timestamp("2018-01-01", tz="UTC"), pd.Timestamp("2024-01-01", tz="UTC"))
TEST = (pd.Timestamp("2024-01-01", tz="UTC"), END)
LAST12 = (pd.Timestamp("2025-10-24", tz="UTC"), END)
LAST6 = (pd.Timestamp("2026-04-24", tz="UTC"), END)

BEST = replace(
    R.PROD,
    a_on=False,
    b_exit="chand4", be_at=1.0, b_stop=0.75, b_tp=8.0, b_er=0.30, b_adx=25.0,
    c_on=True, c_stop=1.5, c_tp=4.5, c_daily_bull=False,
)


def ev(M, p, start=FULL[0], end=END):
    sigs = O.make_signals(M, p)
    return O.metrics(O.simulate(M, sigs, start, end, p, funding_rates=FUND))


def windows6(months=6):
    out, e = [], END
    step = pd.Timedelta(days=round(months * 30.44))
    s = pd.Timestamp("2019-01-01", tz="UTC")
    while e - step >= s:
        out.append((e - step, e))
        e -= step
    return out[::-1]


def main():
    M = O.load_market(".")
    print(f"آخر شمعة 4H: {pd.Timestamp(M.t4[-1], unit='ns', tz='UTC')}")
    sigs = O.make_signals(M, BEST)
    fu = O.metrics(O.simulate(M, sigs, *FULL, BEST, funding_rates=FUND))
    tr = O.metrics(O.simulate(M, sigs, *TRAIN, BEST, funding_rates=FUND))
    te = O.metrics(O.simulate(M, sigs, *TEST, BEST, funding_rates=FUND))
    l12 = O.metrics(O.simulate(M, sigs, *LAST12, BEST, funding_rates=FUND))
    l6 = O.metrics(O.simulate(M, sigs, *LAST6, BEST, funding_rates=FUND))
    print(f"BEST  كامل n={fu['n']} WR={fu['wr']:.1f} PF={fu['pf']:.2f} PnL={fu['pnl']:+.2f} "
          f"MDD={fu['mdd']:.2f} Cal={fu['pnl']/fu['mdd']:.1f}")
    print(f"      تدريب n={tr['n']} PF={tr['pf']:.2f} {tr['pnl']:+.2f} | "
          f"اختبار n={te['n']} PF={te['pf']:.2f} {te['pnl']:+.2f}")
    print(f"      12م n={l12['n']} PF={l12['pf']:.2f} {l12['pnl']:+.2f} | "
          f"6م n={l6['n']} PF={l6['pf']:.2f} {l6['pnl']:+.2f}")
    roll = [O.metrics(O.simulate(M, sigs, *w, BEST, funding_rates=FUND))["pnl"] for w in windows6()]
    print(f"  نوافذ 6م: {sum(1 for x in roll if x > 0)}/{len(roll)} خضراء | " +
          " ".join(f"{w[0]:%y-%m}:{x:+.0f}" for w, x in zip(windows6(), roll)))


if __name__ == "__main__":
    main()
