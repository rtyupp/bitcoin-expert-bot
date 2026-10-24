"""اختبار تاريخي 6 أشهر (2026-04-22 → 2026-10-22) على منطق البوت الحقيقي.

يستخدم نفس دالة الفحص S.scan_signals ودالة الخروج engine.exit_reason_for،
ويحاكي الشمعة المغلقة فقط + فتحة واحدة لكل استراتيجية + Break-Even عند 0.8R.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

sys.path.insert(0, "C:/Users/lsyry/projects/bitcoin-expert-bot")

import strategy as S
from capital_trader import client
import engine as E

client.get_sentiment = lambda epic=None: None  # لا توجد بيانات معنويات تاريخية

START = pd.Timestamp("2026-04-22 00:00:00+00:00")
END = pd.Timestamp("2026-10-22 20:00:00+00:00")
SPREAD = 50.0          # سبريد BTCUSD الحقيقي المقاس من المنصة
INITIAL_BALANCE = 198.66
RISK_PCT = 1.0
MIN_SIZE = 0.0001
DAILY_WARMUP = 1200    # شموع يومية كافية لـ EMA200

MONTHS = [
    ("أبريل 2026", pd.Timestamp("2026-04-22 00:00:00+00:00"), pd.Timestamp("2026-05-01 00:00:00+00:00")),
    ("مايو 2026", pd.Timestamp("2026-05-01 00:00:00+00:00"), pd.Timestamp("2026-06-01 00:00:00+00:00")),
    ("يونيو 2026", pd.Timestamp("2026-06-01 00:00:00+00:00"), pd.Timestamp("2026-07-01 00:00:00+00:00")),
    ("يوليو 2026", pd.Timestamp("2026-07-01 00:00:00+00:00"), pd.Timestamp("2026-08-01 00:00:00+00:00")),
    ("أغسطس 2026", pd.Timestamp("2026-08-01 00:00:00+00:00"), pd.Timestamp("2026-09-01 00:00:00+00:00")),
    ("سبتمبر 2026", pd.Timestamp("2026-09-01 00:00:00+00:00"), pd.Timestamp("2026-10-01 00:00:00+00:00")),
    ("أكتوبر 2026", pd.Timestamp("2026-10-01 00:00:00+00:00"), pd.Timestamp("2026-10-23 00:00:00+00:00")),
]


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    d4 = pd.read_csv("btc_4h.csv").rename(columns={"ts": "time"})
    dd = pd.read_csv("btc_1d.csv").rename(columns={"ts": "time"})
    for df in (d4, dd):
        df["time"] = pd.to_datetime(df["time"])
    return d4.reset_index(drop=True), dd.reset_index(drop=True)


@dataclass
class Trade:
    spec: str
    side: int
    entry_time: pd.Timestamp
    entry: float
    stop: float
    target: float
    size: float
    init_stop: float = 0.0
    exit_time: pd.Timestamp | None = None
    exit: float | None = None
    reason: str = ""
    pnl: float = 0.0
    r: float = 0.0


def run(d4: pd.DataFrame, dd: pd.DataFrame, *, use_be: bool, use_spread: bool,
        fixed_size: float | None, live_bars: bool = False, verbose: bool = False) -> dict:
    bal = INITIAL_BALANCE
    active: dict[str, Trade] = {}
    trades: list[Trade] = []
    skipped = 0
    max_concurrent = 0
    equity = INITIAL_BALANCE
    curve: list[tuple[pd.Timestamp, float]] = []

    start_i = int(d4.index[d4["time"] >= START][0])
    for i in range(start_i, len(d4)):
        bar = d4.iloc[i]
        if bar["time"] > END:
            break
        now = bar["time"] + pd.Timedelta(hours=4)

        # ── الخروج على الشمعة المغلقة (بداية الشمعة) ───────────────────────
        for sid in list(active):
            tr = active[sid]
            same = tr.entry_time == bar["time"]
            hi, lo, cl = float(bar["high"]), float(bar["low"]), float(bar["close"])

            if not same:
                exit_p, reason = None, ""
                if tr.side == 1:
                    if lo <= tr.stop:
                        exit_p, reason = tr.stop, "STOP"
                    elif hi >= tr.target:
                        exit_p, reason = tr.target, "TARGET"
                else:
                    if hi >= tr.stop:
                        exit_p, reason = tr.stop, "STOP"
                    elif lo <= tr.target:
                        exit_p, reason = tr.target, "TARGET"

                if exit_p is None:
                    h4 = S.compute_indicators_4h(d4.iloc[max(0, i - 400): i + 1])
                    last = h4.iloc[-1]
                    reason = E.exit_reason_for(
                        sid if sid != "SMC" else "C", tr.side, tr.entry, cl,
                        float(last["ma20"]), float(last["atr"]),
                    )
                    if reason:
                        exit_p = cl

                if exit_p is not None:
                    gross = (exit_p - tr.entry) * tr.size if tr.side == 1 else (tr.entry - exit_p) * tr.size
                    cost = SPREAD * tr.size if use_spread else 0.0
                    tr.pnl = gross - cost
                    tr.exit, tr.exit_time, tr.reason = exit_p, bar["time"], reason
                    risk_usd = abs(tr.entry - (tr.init_stop or tr.stop)) * tr.size
                    tr.r = tr.pnl / risk_usd if risk_usd else 0.0
                    bal += tr.pnl
                    equity = bal
                    curve.append((bar["time"], bal))
                    trades.append(tr)
                    del active[sid]
                    if verbose:
                        print(f"  خروج [{sid}] {tr.entry_time:%m-%d %H:%M} → {bar['time']:%m-%d %H:%M} "
                              f"{'BUY' if tr.side == 1 else 'SELL'} {tr.entry:,.0f}→{exit_p:,.0f} "
                              f"{tr.pnl:+.2f}$ [{reason}]")

            # Break-Even (يراقب السعر كل دقيقة → يمكن أن يتحقق بنفس شمعة الدخول)
            if use_be and abs(tr.stop - tr.entry) > 0:
                risk = abs(tr.entry - tr.stop)
                gain = (hi - tr.entry) if tr.side == 1 else (tr.entry - lo)
                if gain >= 0.8 * risk and (tr.side == 1 and tr.stop < tr.entry or tr.side == -1 and tr.stop > tr.entry):
                    tr.stop = tr.entry

        # ── إشارات الدخول من نفس دالة البوت ────────────────────────────────
        d_closed = dd[(dd["time"] + pd.Timedelta(days=1)) <= now]
        if len(d_closed) < 300:
            continue
        # live_bars=True يحاكي ما يفعله البوت فعلياً: max_candles=100 فقط
        n4 = 100 if live_bars else 2000
        nd = 100 if live_bars else DAILY_WARMUP
        d_slice = d_closed.iloc[-nd:]
        sigs = S.scan_signals(d4.iloc[:0], d4.iloc[max(0, i - n4): i + 1], d_slice)

        for sig in sigs:
            sid = sig.spec_id
            if sid in active:
                skipped += 1
                continue

            entry = float(bar["close"])
            if fixed_size is not None:
                size = fixed_size
            else:
                risk_usd = bal * (RISK_PCT / 100.0)
                dist = abs(entry - sig.stop_level)
                size = max(MIN_SIZE, round(risk_usd / dist, 4)) if dist > 0 else MIN_SIZE
            tr = Trade(sid, sig.side, bar["time"], entry, sig.stop_level, sig.target_level,
                       size, init_stop=sig.stop_level)
            active[sid] = tr
            max_concurrent = max(max_concurrent, len(active))
            if verbose:
                print(f"  دخول [{sid}] {bar['time']:%m-%d %H:%M} {'BUY' if sig.side == 1 else 'SELL'} "
                      f"{entry:,.0f} وقف {sig.stop_level:,.0f} هدف {sig.target_level:,.0f} حجم {size}")

    # إغلاق المتبقي على آخر إغلاق
    last_close = float(d4.iloc[i]["close"])
    for sid, tr in list(active.items()):
        gross = (last_close - tr.entry) * tr.size if tr.side == 1 else (tr.entry - last_close) * tr.size
        tr.pnl = gross - (SPREAD * tr.size if use_spread else 0.0)
        risk_usd = abs(tr.entry - (tr.init_stop or tr.stop)) * tr.size
        tr.r = tr.pnl / risk_usd if risk_usd else 0.0
        tr.exit, tr.exit_time, tr.reason = last_close, d4.iloc[i]["time"], "OPEN_AT_END"
        bal += tr.pnl
        trades.append(tr)
        active.pop(sid)

    return {
        "trades": trades, "balance": bal, "skipped": skipped,
        "max_concurrent": max_concurrent, "curve": curve,
    }


def metrics(res: dict) -> dict:
    tr = res["trades"]
    wins = [t for t in tr if t.pnl > 0]
    losses = [t for t in tr if t.pnl <= 0]
    gp = sum(t.pnl for t in wins)
    gl = abs(sum(t.pnl for t in losses))
    peak, mdd = INITIAL_BALANCE, 0.0
    eq = INITIAL_BALANCE
    for t in sorted(tr, key=lambda x: x.exit_time):
        eq += t.pnl
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    return {
        "n": len(tr), "wins": len(wins), "losses": len(losses),
        "wr": len(wins) / len(tr) * 100 if tr else 0.0,
        "pnl": sum(t.pnl for t in tr), "pf": gp / gl if gl else float("inf"),
        "avg_win": np.mean([t.pnl for t in wins]) if wins else 0.0,
        "avg_loss": np.mean([t.pnl for t in losses]) if losses else 0.0,
        "mdd": mdd, "max_concurrent": res["max_concurrent"], "skipped": res["skipped"],
    }


def main() -> None:
    d4, dd = load()
    bh = (d4[d4["time"] <= END]["close"].iloc[-1] / d4[d4["time"] >= START]["close"].iloc[0] - 1) * 100

    print("=" * 78)
    print("اختبار تاريخي 6 أشهر — 2026-04-22 → 2026-10-22 (شمعة 4H مغلقة)")
    print(f"BTC شراء واحتفاظ خلال الفترة: {bh:+.1f}%")
    print("=" * 78)

    combos = [
        ("risk1% + BE + سبريد (الأقرب للحقيقي)", dict(use_be=True, use_spread=True, fixed_size=None)),
        ("risk1% بدون BE + سبريد", dict(use_be=False, use_spread=True, fixed_size=None)),
        ("حجم ثابت 0.002 + BE + سبريد", dict(use_be=True, use_spread=True, fixed_size=0.002)),
        ("حجم ثابت 0.002 بدون BE وبدون سبريد (منهجية 12 شهر)", dict(use_be=False, use_spread=False, fixed_size=0.002)),
        ("كما يحسبها البوت الآن: 100 شمعة فقط (risk1% + BE + سبريد)",
         dict(use_be=True, use_spread=True, fixed_size=None, live_bars=True)),
    ]
    results = {}
    for title, kw in combos:
        res = run(d4, dd, **kw)
        results[title] = res
        m = metrics(res)
        start_cap = INITIAL_BALANCE if kw["fixed_size"] is None else 40.0
        print(f"\n▶ {title}")
        print(f"  صفقات {m['n']} | فوز {m['wr']:.1f}% | PF {m['pf']:.2f} | "
              f"صافي {m['pnl']:+.2f}$ على {start_cap:.2f}$ ({(m['pnl']/start_cap)*100:+.1f}%) | "
              f"أقصى تراجع {m['mdd']:.2f}$ | أقصى صفقات متزامنة {m['max_concurrent']}")

    primary = results[combos[0][0]]
    tr = sorted(primary["trades"], key=lambda x: x.entry_time)

    print("\n" + "=" * 78)
    print("تفصيل الصفقات (risk1% + BE + سبريد):")
    print("=" * 78)
    for t in tr:
        print(f"{'✅' if t.pnl > 0 else '❌'} [{t.spec}] {'BUY ' if t.side == 1 else 'SELL'} "
              f"{t.entry_time:%m-%d %H:%M}→{t.exit_time:%m-%d %H:%M} | "
              f"{t.entry:,.0f}→{t.exit:,.0f} | {t.size:.4f} BTC | {t.pnl:+7.2f}$ ({t.r:+.2f}R) | {t.reason}")

    print("\n" + "=" * 78)
    print("حسب الاستراتيجية (risk1% + BE + سبريد):")
    print("=" * 78)
    for sid in ["A", "B", "C", "D"]:
        sub = [t for t in tr if t.spec == sid]
        if not sub:
            print(f"  [{sid}] لا صفقات")
            continue
        w = [t for t in sub if t.pnl > 0]
        gp = sum(t.pnl for t in w)
        gl = abs(sum(t.pnl for t in sub if t.pnl <= 0))
        print(f"  [{sid}] {len(sub)} صفقة | فوز {len(w)/len(sub)*100:.0f}% | "
              f"صافي {sum(t.pnl for t in sub):+.2f}$ | PF {gp/gl if gl else 999:.2f} | "
              f"متوسط R {np.mean([t.r for t in sub]):+.2f}")

    print("\n" + "=" * 78)
    print("حسب الشهر (risk1% + BE + سبريد):")
    print("=" * 78)
    for mname, s, e in MONTHS:
        sub = [t for t in tr if s <= t.entry_time < e]
        if not sub:
            print(f"  {mname}: لا صفقات | 0.00$")
            continue
        w = [t for t in sub if t.pnl > 0]
        print(f"  {mname}: {len(sub)} صفقة | فوز {len(w)/len(sub)*100:.0f}% | {sum(t.pnl for t in sub):+.2f}$")

    open_end = [t for t in tr if t.reason == "OPEN_AT_END"]
    print(f"\nملاحظات: {len(open_end)} صفقة أُغلقت قسرياً على آخر شمعة | "
          f"{primary['skipped']} إشارة فُقدت لأن الاستراتيجية كانت مشغولة | "
          f"سبريد ${SPREAD:.0f} للعقد الكامل.")


if __name__ == "__main__":
    main()
