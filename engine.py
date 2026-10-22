"""المحرك المؤسسي للبيتكوين: يفحص الشموع المكتملة (Daily, 4H)، يطلق التوصيات، ينفّذها على Capital.com، ويدير الصفقات بالوقف المتحرك.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass

import pandas as pd

import capital_trader
import config
import markets
import state
import strategy as S

log = logging.getLogger("engine")


@dataclass
class Event:
    kind: str          # "open" | "skip" | "close" | "trail" | "error"
    trade: dict
    text: str = ""


def load_data() -> tuple[pd.DataFrame, pd.DataFrame, str]:
    h4, src = markets.candles("4h", 400)
    d1, _ = markets.candles("1d", 400)
    return S.closed_only(h4, "4h"), S.closed_only(d1, "1d"), src


def _capital_on() -> bool:
    return capital_trader.is_configured()


def live_quote() -> dict:
    if _capital_on():
        try:
            q = capital_trader.live_price("btc")
            return {"bid": q["bid"], "offer": q["offer"], "src": "capital"}
        except Exception as e:  # noqa: BLE001
            log.warning("Capital quote failed: %s", e)
    t = markets.ticker()
    return {"bid": t["price"], "offer": t["price"], "src": t["src"].lower()}


def _age_ok(sig: S.Signal, now: pd.Timestamp) -> bool:
    max_age = pd.Timedelta(hours=26 if sig.spec.tf == "1d" else config.MAX_SIGNAL_AGE_H)
    step = pd.Timedelta(days=1) if sig.spec.tf == "1d" else pd.Timedelta(hours=4)
    return now - (sig.bar_ts + step) <= max_age


def _size(balance: float, risk_pct: float, stop_dist: float) -> float:
    raw = balance * risk_pct / 100.0 / stop_dist
    return max(0.0001, math.floor(raw * 10_000) / 10_000)


def open_from_signal(sig: S.Signal, now: pd.Timestamp | None = None, quote: dict | None = None) -> Event:
    now = now or pd.Timestamp.now(tz="UTC")
    st = state.load()
    if sig.strategy in st["active"]:
        return Event("skip", {"strategy": sig.strategy}, "الاستراتيجية لديها صفقة مفتوحة")
    if not _age_ok(sig, now):
        return Event("skip", {"strategy": sig.strategy}, "إشارة قديمة")
    q = quote or live_quote()
    entry = q["offer"] if sig.side > 0 else q["bid"]
    basis = 0.0
    if q["src"] == "capital":
        try:
            basis = ((q["bid"] + q["offer"]) / 2) - markets.ticker()["price"]
        except Exception:  # noqa: BLE001
            basis = 0.0
    slip = sig.side * (entry - (sig.ref_price + basis))
    if slip > config.MAX_ENTRY_SLIP_R * sig.stop_dist:
        return Event("skip", {"strategy": sig.strategy},
                     f"السعر ابتعد {slip / sig.stop_dist:.2f}R عن الإشارة — فاتت الفرصة")
    lv = sig.levels(entry)
    trade = {
        "strategy": sig.strategy, "side": sig.side, "bar_ts": str(sig.bar_ts), "opened": str(now),
        "entry": entry, "stop": lv["stop"], "init_stop": lv["stop"], "tp": lv.get("tp"),
        "stop_dist": sig.stop_dist, "basis": basis, "best": entry, "reasons": sig.reasons,
        "mode": "paper", "dealId": None, "size": None, "risk_usd": None,
    }
    if _capital_on() and state.auto_trade():
        try:
            bal = capital_trader.account_summary()["available"]
            size = _size(bal, state.risk_pct(), sig.stop_dist)
            res = capital_trader.open_trade("btc", "BUY" if sig.side > 0 else "SELL", size,
                                            lv["stop"], lv.get("tp"), allow_multiple=True)
            trade.update(mode="capital", dealId=res.get("dealId"), size=res["size"],
                         entry=float(res["level"]), risk_usd=round(res["size"] * sig.stop_dist, 2))
            if res.get("stopLevel"):
                trade["stop"] = trade["init_stop"] = float(res["stopLevel"])
            if res.get("profitLevel"):
                trade["tp"] = float(res["profitLevel"])
            trade["best"] = trade["entry"]
        except Exception as e:  # noqa: BLE001
            log.exception("فشل فتح الصفقة على Capital")
            trade["capital_error"] = str(e)[:200]
    with state._LOCK:
        st = state.load()
        st["active"][sig.strategy] = trade
        state.save(st)
    return Event("open", trade)


def scan(h4: pd.DataFrame, d1: pd.DataFrame, now: pd.Timestamp | None = None) -> list[Event]:
    now = now or pd.Timestamp.now(tz="UTC")
    st = state.load()
    events: list[Event] = []
    marks = {"A": str(d1["ts"].iloc[-1]), "C": str(h4["ts"].iloc[-1]), "B": str(h4["ts"].iloc[-1])}
    new = {k for k, v in marks.items() if st["last_bar"].get(k) != v}
    if not new:
        return events
    for sig in S.latest_signals(h4, d1):
        if sig.strategy in new:
            try:
                events.append(open_from_signal(sig, now))
            except Exception as e:  # noqa: BLE001
                log.exception("open failed")
                events.append(Event("error", {"strategy": sig.strategy}, str(e)[:200]))
    with state._LOCK:
        st = state.load()
        for k in new:
            st["last_bar"][k] = marks[k]
        state.save(st)
    return events


def _close(k: str, trade: dict, exit_px: float, reason: str, pnl_usd: float | None = None) -> Event:
    r = trade["side"] * (exit_px - trade["entry"]) / trade["stop_dist"]
    if pnl_usd is not None and trade.get("risk_usd"):
        r = pnl_usd / trade["risk_usd"]
    rec = {**trade, "exit": exit_px, "closed": str(pd.Timestamp.now(tz="UTC")), "r": round(r, 2),
           "reason": reason, "pnl_usd": pnl_usd}
    with state._LOCK:
        st = state.load()
        st["active"].pop(k, None)
        st["history"].append(rec)
        st["history"] = st["history"][-300:]
        state.save(st)
    return Event("close", rec)


def manage(h4: pd.DataFrame, now: pd.Timestamp | None = None) -> list[Event]:
    events: list[Event] = []
    st = state.load()
    if not st["active"]:
        return events
    h1, _ = markets.candles("1h", 200, ttl=30)
    for k, tr in list(st["active"].items()):
        spec = S.SPECS[k]
        s, opened = tr["side"], pd.Timestamp(tr["opened"])
        try:
            if tr["mode"] == "capital" and tr.get("dealId"):
                pos = capital_trader.get_position(tr["dealId"])
                if pos is None:
                    pnl = capital_trader.realized_pnl(tr["dealId"])
                    px = tr["tp"] if (pnl or 0) > 0 and tr.get("tp") else tr["stop"]
                    events.append(_close(k, tr, float(px), "أُغلقت في Capital.com", pnl))
                    continue
            else:
                after = h1[h1["ts"] + pd.Timedelta(hours=1) > opened]
                hit = None
                for _, b in after.iterrows():
                    lo, hi = b["low"] + tr["basis"], b["high"] + tr["basis"]
                    if (s > 0 and lo <= tr["stop"]) or (s < 0 and hi >= tr["stop"]):
                        hit = (tr["stop"], "ضرب الوقف"); break
                    if tr.get("tp") and ((s > 0 and hi >= tr["tp"]) or (s < 0 and lo <= tr["tp"])):
                        hit = (tr["tp"], "تحقق الهدف 🎯"); break
                if hit:
                    events.append(_close(k, tr, float(hit[0]), hit[1]))
                    continue
            if spec.trail_r:
                bars = h4[h4["ts"] >= opened.floor("4h")]
                if len(bars):
                    ext = (bars["high"].max() if s > 0 else bars["low"].min()) + tr["basis"]
                    best = max(tr["best"], ext) if s > 0 else min(tr["best"], ext)
                    ns = S.trail_stop(s, tr["entry"], tr["stop"], tr["stop_dist"], best, spec.trail_r)
                    if abs(ns - tr["stop"]) >= 0.05 * tr["stop_dist"]:
                        ok = True
                        if tr["mode"] == "capital" and tr.get("dealId"):
                            ok = capital_trader.update_position_levels(tr["dealId"], stop_level=ns,
                                                                       profit_level=tr.get("tp"), epic="BTCUSD")
                        if ok:
                            old = tr["stop"]
                            with state._LOCK:
                                cur = state.load()
                                if k in cur["active"]:
                                    cur["active"][k].update(stop=ns, best=best)
                                    state.save(cur)
                            events.append(Event("trail", {**tr, "stop": ns, "old_stop": old}))
                    elif best != tr["best"]:
                        with state._LOCK:
                            cur = state.load()
                            if k in cur["active"]:
                                cur["active"][k]["best"] = best
                                state.save(cur)
        except Exception as e:  # noqa: BLE001
            log.exception("manage %s failed", k)
            events.append(Event("error", tr, str(e)[:200]))
    return events


def history_stats(hist: list[dict]) -> dict:
    if not hist:
        return {"n": 0}
    r = [h["r"] for h in hist]
    w = [x for x in r if x > 0]; l_ = [-x for x in r if x < 0]
    return {"n": len(r), "win": round(len(w) / len(r) * 100, 1), "total_r": round(sum(r), 2),
            "pf": round(sum(w) / sum(l_), 2) if l_ else None}


def tick() -> list[Event]:
    t0 = time.time()
    h4, d1, _ = load_data()
    ev = manage(h4) + scan(h4, d1)
    log.info("tick %.1fs events=%d", time.time() - t0, len(ev))
    return ev
