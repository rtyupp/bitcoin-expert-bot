"""مختبر تحسين الاستراتيجيات — يعيد بناء منطق scan_signals/E.exit_reason_for
على مؤشرات محسوبة مسبقاً (سريع)، ويُستخدم للبحث عن إعدادات أفضل مع تحقق
خارج العينة (out-of-sample) ونوافذ متدحرجة.

لا يغيّر أي ملف إنتاجي: الغرض منه القياس فقط.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

SPREAD = 50.0
MIN_SIZE = 0.0001
BARS_PER_YEAR_4H = 6 * 365


# ─────────────────────────── البيانات والمؤشرات ───────────────────────────

def _mfi(h, l, c, v, n=14):
    typ = (h + l + c) / 3.0
    raw = typ * v
    up = np.where(typ > np.roll(typ, 1), raw, 0.0)
    dn = np.where(typ < np.roll(typ, 1), raw, 0.0)
    up[0] = dn[0] = 0.0
    pos = pd.Series(up).rolling(n).sum().to_numpy()
    neg = pd.Series(dn).rolling(n).sum().to_numpy()
    return 100.0 - (100.0 / (1.0 + pos / (neg + 1e-9)))


def _atr(h, l, c, n=14):
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    tr[0] = h[0] - l[0]
    return pd.Series(tr).rolling(n).mean().to_numpy()


def _adx(h, l, c, n=14):
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    tr[0] = h[0] - l[0]
    pdm = np.clip(h - np.roll(h, 1), 0, None)
    mdm = np.clip(np.roll(l, 1) - l, 0, None)
    pdm[0] = mdm[0] = 0.0
    trs = pd.Series(tr).rolling(n).sum()
    pdi = 100 * pd.Series(pdm).rolling(n).sum() / (trs + 1e-9)
    mdi = 100 * pd.Series(mdm).rolling(n).sum() / (trs + 1e-9)
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi + 1e-9)
    return dx.rolling(n).mean().to_numpy()


def _ema(x, span):
    return pd.Series(x).ewm(span=span, adjust=False).mean().to_numpy()


def _rsi(c, n=14):
    d = pd.Series(c).diff()
    up = d.clip(lower=0).rolling(n).mean()
    dn = (-d.clip(upper=0)).rolling(n).mean()
    return (100 - 100 / (1 + up / (dn + 1e-9))).to_numpy()


@dataclass
class Market:
    t4: np.ndarray          # ns since epoch for 4H bar open
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    atr: np.ndarray
    ema50: np.ndarray
    ema100: np.ndarray
    ema200: np.ndarray
    e20: np.ndarray
    rsi: np.ndarray
    ma20: np.ndarray
    std20: np.ndarray
    span_a: np.ndarray
    span_b: np.ndarray
    lo30: np.ndarray
    hi30: np.ndarray
    adx: np.ndarray
    er: np.ndarray
    mfi: np.ndarray
    hi20_prev: np.ndarray
    mfi20max_prev: np.ndarray
    # daily
    dt: np.ndarray
    d_close: np.ndarray
    d_ema50: np.ndarray
    d_ema200: np.ndarray
    d_hi55: np.ndarray
    d_atr: np.ndarray
    d_idx: np.ndarray       # آخر شمعة يومية مغلقة لكل شمعة 4H
    start_ts: np.int64


def load_market(project_dir: str = ".") -> Market:
    d4 = pd.read_csv(f"{project_dir}/btc_4h.csv").rename(columns={"ts": "time"})
    dd = pd.read_csv(f"{project_dir}/btc_1d.csv").rename(columns={"ts": "time"})
    d4["time"] = pd.to_datetime(d4["time"])
    dd["time"] = pd.to_datetime(dd["time"])

    o = d4["open"].to_numpy(float)
    h = d4["high"].to_numpy(float)
    l = d4["low"].to_numpy(float)
    c = d4["close"].to_numpy(float)
    v = d4["volume"].to_numpy(float)
    atr = _atr(h, l, c)
    ma20 = pd.Series(c).rolling(20).mean().to_numpy()
    std20 = pd.Series(c).rolling(20).std().to_numpy()
    tenkan = (pd.Series(h).rolling(9).max() + pd.Series(l).rolling(9).min()) / 2
    kijun = (pd.Series(h).rolling(26).max() + pd.Series(l).rolling(26).min()) / 2
    span_a = ((tenkan + kijun) / 2).shift(26).to_numpy()
    span_b = ((pd.Series(h).rolling(52).max() + pd.Series(l).rolling(52).min()) / 2).shift(26).to_numpy()
    lo30 = pd.Series(l).rolling(30).min().shift(1).to_numpy()
    hi30 = pd.Series(h).rolling(30).max().shift(1).to_numpy()
    adx = _adx(h, l, c)
    er = (c - np.roll(c, 14))
    noise = pd.Series(np.abs(c - np.roll(c, 1))).rolling(14).sum().to_numpy()
    er = np.abs(er) / (noise + 1e-9)
    er[:15] = 0.0
    mfi = _mfi(h, l, c, v)
    hi20_prev = pd.Series(h).rolling(20).max().shift(1).to_numpy()
    mfi20max_prev = pd.Series(mfi).rolling(20).max().shift(1).to_numpy()

    dc = dd["close"].to_numpy(float)
    dh = dd["high"].to_numpy(float)
    dl = dd["low"].to_numpy(float)
    d_atr = _atr(dh, dl, dc)
    d_ema50 = _ema(dc, 50)
    d_ema200 = _ema(dc, 200)
    d_hi55 = pd.Series(dh).rolling(55).max().shift(1).to_numpy()
    dt = dd["time"].to_numpy("datetime64[ns]").astype(np.int64)

    t4 = d4["time"].to_numpy("datetime64[ns]").astype(np.int64)
    close_ns = t4 + 4 * 3600 * 10**9
    # آخر شمعة يومية حيث (افتتاح اليوم + يوم) <= وقت إغلاق الشمعة
    d_done = dt + 24 * 3600 * 10**9
    d_idx = np.searchsorted(d_done, close_ns, side="right") - 1

    return Market(t4, o, h, l, c, v, atr, _ema(c, 50), _ema(c, 100), _ema(c, 200),
                  _ema(c, 20), _rsi(c), ma20, std20, span_a, span_b, lo30, hi30, adx, er, mfi,
                  hi20_prev, mfi20max_prev,
                  dt, dc, d_ema50, d_ema200, d_hi55, d_atr, d_idx,
                  int(t4[0]))


# ─────────────────────────── الإعدادات ───────────────────────────

@dataclass(frozen=True)
class Params:
    bb_k: float = 2.0
    # [B]
    b_adx: float = 25.0
    b_er: float = 0.35
    b_mfi_up: float = 50.0
    b_mfi_dn: float = 45.0
    b_short: bool = True
    bs_adx: float = 0.0            # 0 = استخدم b_adx
    bs_er: float = 0.0             # 0 = استخدم b_er
    bs_mfi: float = 100.0          # 100 = استخدم b_mfi_dn
    bs_stop: float = 0.0           # 0 = استخدم b_stop
    bs_tp: float = 0.0             # 0 = استخدم b_tp
    b_long_only_daily_bull: bool = False
    b_stop: float = 2.0
    b_tp: float = 4.0
    b_exit: str = "ma20"          # ma20 | ma50 | chandelier2 | trail2 | none
    b_short_exit: str = "ma20"
    # [C]
    c_on: bool = True
    c_bull: bool = False          # فوق EMA200 4H
    c_ema100: bool = False        # فوق EMA100 4H (مطابق للإنتاج)
    c_daily_bull: bool = False    # فوق EMA200 اليومي
    c_stop: float = 1.5
    c_tp: float = 3.0
    c_exit: str = "trail2"
    # [D]
    d_on: bool = True
    d_mfi_up: float = 52.0
    d_mfi_dn: float = 48.0
    d_daily: str = "none"         # none | bull | trend  (الاتجاه اليومي)
    d_stop: float = 1.5
    d_tp: float = 2.5
    d_exit: str = "trail2"
    # [A]
    a_on: bool = True
    a_stop: float = 2.0
    a_tp: float = 5.0
    a_exit: str = "trail2"
    # [E] استمرار الاتجاهعلى ارتداد 4H
    e_on: bool = False
    e_stop: float = 1.5
    e_tp: float = 5.0
    e_exit: str = "ma50"
    e_need_ema_stack: bool = True
    e_rsi_max: float = 70.0
    e_bars_below: int = 1
    # [F] بيع الاتجاه الهابط المؤكد
    f_on: bool = False
    f_stop: float = 1.5
    f_tp: float = 5.0
    f_exit: str = "ma50"
    f_need_daily_bear: bool = True
    f_rsi_min: float = 30.0
    # المحفظة
    long_regime: str = "none"     # none | ema50 | ema200 (فلتر الاتجاه اليومي لكل الشراء)
    hedge_block: bool = False
    max_positions: int = 4
    risk_pct: float = 1.0
    risk_a: float = 1.0
    risk_b: float = 1.0
    risk_c: float = 1.0
    risk_d: float = 1.0
    risk_e: float = 1.0
    risk_f: float = 1.0
    be_at: float = 0.8
    max_bars: int = 0             # 0 = بلا حد زمني، وإلا إغلاق بعد N شمعة 4H


DEFAULT = Params()


# ─────────────────────────── توليد الإشارات ───────────────────────────

def make_signals(M: Market, p: Params) -> Dict[int, List[Tuple[str, int, float, float]]]:
    """ يعيد bar_index -> [(spec, side, stop, target), ...] مطابق لمنطق scan_signals. """
    n = len(M.c)
    bb_u = M.ma20 + p.bb_k * M.std20
    bb_l = M.ma20 - p.bb_k * M.std20

    prev = np.roll(np.arange(n), 1)
    prev[0] = 0
    with np.errstate(invalid="ignore"):
        b_base = (M.c > bb_u) & (M.c > M.span_a) & (M.c > M.span_b) & (M.c > M.ema200)
        b_short_base = (M.c < bb_l) & (M.c < M.span_a) & (M.c < M.span_b) & (M.c < M.ema200)
        div = (M.c > M.hi20_prev) & (M.mfi < M.mfi20max_prev - 5.0)
        b_long = b_base & (M.adx >= p.b_adx) & (M.er >= p.b_er) & (M.mfi >= p.b_mfi_up) & ~div
        bs_adx = p.bs_adx or p.b_adx
        bs_er = p.bs_er or p.b_er
        bs_mfi = p.b_mfi_dn if p.bs_mfi >= 100.0 else p.bs_mfi
        b_sh = b_short_base & (M.adx >= bs_adx) & (M.er >= bs_er) & (M.mfi <= bs_mfi)
        pst = prev
        prev_long = (M.c[pst] > bb_u[pst]) & (M.c[pst] > M.span_a[pst])
        prev_sh = (M.c[pst] < bb_l[pst]) & (M.c[pst] < M.span_a[pst])
        b_long &= ~prev_long
        b_sh &= ~prev_sh

        if p.b_long_only_daily_bull:
            b_long &= M.d_close[M.d_idx] > M.d_ema50[M.d_idx]
        if p.long_regime == "ema50":
            b_long &= M.d_close[M.d_idx] > M.d_ema50[M.d_idx]
        elif p.long_regime == "ema200":
            b_long &= M.d_close[M.d_idx] > M.d_ema200[M.d_idx]
        elif p.long_regime == "cross":
            b_long &= M.d_ema50[M.d_idx] > M.d_ema200[M.d_idx]

        if p.b_short:
            d_bear = M.d_close[M.d_idx] < M.d_ema200[M.d_idx]
            b_sh &= d_bear
        else:
            b_sh[:] = False

        c_buy = (M.l < M.lo30) & (M.c > M.lo30) & (M.c > M.o) & (M.c > M.ema100)
        if p.c_on:
            c_buy &= ~((M.l[pst] < M.lo30[pst]) & (M.c[pst] > M.lo30[pst]))
            if p.c_bull:
                c_buy &= M.c > M.ema200
            if p.c_ema100:
                c_buy &= M.c > M.ema100
            if p.c_daily_bull:
                c_buy &= M.d_close[M.d_idx] > M.d_ema50[M.d_idx]
            if p.long_regime == "ema50":
                c_buy &= M.d_close[M.d_idx] > M.d_ema50[M.d_idx]
            elif p.long_regime == "ema200":
                c_buy &= M.d_close[M.d_idx] > M.d_ema200[M.d_idx]
            elif p.long_regime == "cross":
                c_buy &= M.d_ema50[M.d_idx] > M.d_ema200[M.d_idx]
        else:
            c_buy[:] = False

        d_pump = (M.l <= bb_l) & (M.mfi > p.d_mfi_up) & (M.c > M.o)
        d_dump = (M.h >= bb_u) & (M.mfi < p.d_mfi_dn) & (M.c < M.o)
        if p.d_on:
            d_pump &= ~((M.l[pst] <= bb_l[pst]) & (M.c[pst] > M.o[pst]))
            d_dump &= ~((M.h[pst] >= bb_u[pst]) & (M.c[pst] < M.o[pst]))
            if p.d_daily != "none":
                d_up = M.d_close[M.d_idx] > M.d_ema50[M.d_idx]
                d_dn = M.d_close[M.d_idx] < M.d_ema50[M.d_idx]
                d_pump &= d_up
                d_dump &= d_dn
            if p.long_regime == "ema50":
                d_pump &= M.d_close[M.d_idx] > M.d_ema50[M.d_idx]
            elif p.long_regime == "ema200":
                d_pump &= M.d_close[M.d_idx] > M.d_ema200[M.d_idx]
            elif p.long_regime == "cross":
                d_pump &= M.d_ema50[M.d_idx] > M.d_ema200[M.d_idx]
        else:
            d_pump[:] = False
            d_dump[:] = False

        # [E] ارتداد في اتجاه صاعد مؤكد: الشمعة السابقة تحت EMA20 والآن إغلاق فوقها
        e_setup = (M.c[pst] < M.e20[pst]) & (M.c > M.e20) & (M.c > M.o) & (M.c > M.ema50)
        if p.e_bars_below > 1:
            below = np.ones(n, dtype=bool)
            for k in range(1, p.e_bars_below + 1):
                below &= M.c[np.maximum(np.arange(n) - k, 0)] < M.e20[np.maximum(np.arange(n) - k, 0)]
            e_setup &= below
        if p.e_need_ema_stack:
            e_setup &= (M.ema50 > M.ema100) & (M.ema100 > M.ema200)
        e_setup &= M.rsi <= p.e_rsi_max
        e_setup &= M.d_close[M.d_idx] > M.d_ema50[M.d_idx]
        if p.e_need_ema_stack:
            e_setup &= M.d_ema50[M.d_idx] > M.d_ema200[M.d_idx]
        if not p.e_on:
            e_setup[:] = False

        # [F] بيع في اتجاه هابط مؤكد: الشمعة السابقة فوق EMA20 والآن إغلاق تحتها
        f_setup = (M.c[pst] > M.e20[pst]) & (M.c < M.e20) & (M.c < M.o) & (M.c < M.ema50)
        if p.f_need_daily_bear:
            f_setup &= M.d_close[M.d_idx] < M.d_ema200[M.d_idx]
        f_setup &= M.rsi >= p.f_rsi_min
        f_setup &= M.c < M.ema200
        if not p.f_on:
            f_setup[:] = False

        a_buy = (M.d_close[M.d_idx] > M.d_hi55[M.d_idx]) & (M.d_close[M.d_idx] > M.d_ema200[M.d_idx])
        if p.a_on:
            a_buy &= ~(M.d_close[pst_d(M, pst)] > M.d_hi55[pst_d(M, pst)])
        else:
            a_buy[:] = False

    sigs: Dict[int, List[Tuple[str, int, float, float]]] = {}
    for i in np.flatnonzero(b_long):
        atr = M.atr[i]
        sigs.setdefault(int(i), []).append(("B", 1, round(M.c[i] - p.b_stop * atr, 2), round(M.c[i] + p.b_tp * atr, 2)))
    bs_stop = p.bs_stop or p.b_stop
    bs_tp = p.bs_tp or p.b_tp
    for i in np.flatnonzero(b_sh):
        atr = M.atr[i]
        sigs.setdefault(int(i), []).append(("B", -1, round(M.c[i] + bs_stop * atr, 2), round(M.c[i] - bs_tp * atr, 2)))
    for i in np.flatnonzero(c_buy):
        atr = M.atr[i]
        sigs.setdefault(int(i), []).append(("C", 1, round(M.c[i] - p.c_stop * atr, 2), round(M.c[i] + p.c_tp * atr, 2)))
    for i in np.flatnonzero(d_pump):
        atr = M.atr[i]
        sigs.setdefault(int(i), []).append(("D", 1, round(M.c[i] - p.d_stop * atr, 2), round(M.c[i] + p.d_tp * atr, 2)))
    for i in np.flatnonzero(d_dump):
        atr = M.atr[i]
        sigs.setdefault(int(i), []).append(("D", -1, round(M.c[i] + p.d_stop * atr, 2), round(M.c[i] - p.d_tp * atr, 2)))
    for i in np.flatnonzero(e_setup):
        atr = M.atr[i]
        sigs.setdefault(int(i), []).append(("E", 1, round(M.c[i] - p.e_stop * atr, 2), round(M.c[i] + p.e_tp * atr, 2)))
    for i in np.flatnonzero(f_setup):
        atr = M.atr[i]
        sigs.setdefault(int(i), []).append(("F", -1, round(M.c[i] + p.f_stop * atr, 2), round(M.c[i] - p.f_tp * atr, 2)))
    for i in np.flatnonzero(a_buy):
        atr = M.d_atr[M.d_idx[i]]
        didx = M.d_idx[i]
        sigs.setdefault(int(i), []).append(("A", 1, round(M.d_close[didx] - p.a_stop * atr, 2), round(M.d_close[didx] + p.a_tp * atr, 2)))
    return sigs


def pst_d(M: Market, pst: np.ndarray) -> np.ndarray:
    """فهرس الشمعة اليومية السابقة لآخر شمعة مغلقة (لمنطق عدم تكرار [A])."""
    return np.maximum(M.d_idx - 1, 0)


# ─────────────────────────── المحاكاة ───────────────────────────

@dataclass
class Trade:
    spec: str
    side: int
    entry_i: int
    entry_t: int
    entry: float
    stop: float
    target: float
    size: float
    init_stop: float
    exit_i: Optional[int] = None
    exit_t: Optional[int] = None
    exit: Optional[float] = None
    reason: str = ""
    pnl: float = 0.0
    r: float = 0.0
    peak: float = 0.0


def _exit_mode_check(mode: str, side: int, close: float, entry: float, ma20: float,
                     ma50: float, atr: float, peak: float, ma100: float = 0.0) -> bool:
    if mode == "none":
        return False
    if mode == "ma50":
        return close < ma50 if side == 1 else close > ma50
    if mode.startswith("trail"):
        if atr <= 0:
            return False
        mult = float(mode[5:])
        return close < entry - mult * atr if side == 1 else close > entry + mult * atr
    if mode.startswith("chand"):
        if atr <= 0:
            return False
        mult = float(mode[5:])
        return close < peak - mult * atr if side == 1 else close > peak + mult * atr
    if mode == "ma20":
        return close < ma20 if side == 1 else close > ma20
    if mode == "ma100":
        return close < ma100 if side == 1 else close > ma100
    raise ValueError(mode)


def simulate(M: Market, sigs: Dict[int, List[Tuple[str, int, float, float]]],
             start: pd.Timestamp, end: pd.Timestamp, p: Params = DEFAULT,
             initial_balance: float = 198.66, spread: float = SPREAD,
             max_bars_by_spec: Optional[Dict[str, int]] = None,
             funding_rates: Optional[Tuple[float, float]] = None) -> dict:
    t0 = int(start.value)
    t1 = int(end.value)
    i0 = int(np.searchsorted(M.t4, t0, side="left"))
    i1 = int(np.searchsorted(M.t4, t1, side="right"))

    bal = initial_balance
    active: Dict[str, Trade] = {}
    trades: List[Trade] = []
    max_conc = 0
    skipped = 0

    for i in range(i0, i1):
        hi, lo, cl = M.h[i], M.l[i], M.c[i]
        atr = M.atr[i]
        ma20, ma50 = M.ma20[i], M.ema50[i]

        # ── الخروج ──
        for sid in list(active):
            tr = active[sid]
            same = tr.entry_i == i
            # تحديث القمة/القاع المتحرك
            if tr.side == 1:
                tr.peak = max(tr.peak, hi)
            else:
                tr.peak = min(tr.peak, lo)

            exit_p, reason = None, ""
            if not same:
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
                    mode = (p.b_exit if sid == "B" else p.c_exit if sid == "C"
                            else p.d_exit if sid == "D" else p.e_exit if sid == "E"
                            else p.f_exit if sid == "F" else p.a_exit)
                    if sid == "B" and tr.side == -1:
                        mode = p.b_short_exit
                    if _exit_mode_check(mode, tr.side, cl, tr.entry, ma20, ma50, atr, tr.peak, M.ema100[i]):
                        exit_p, reason = cl, f"EXIT_{mode}"
                    if exit_p is None and p.max_bars and (i - tr.entry_i) >= p.max_bars:
                        exit_p, reason = cl, "TIME"

            if exit_p is not None:
                gross = (exit_p - tr.entry) * tr.size if tr.side == 1 else (tr.entry - exit_p) * tr.size
                cost = spread * tr.size
                if funding_rates:
                    rate = funding_rates[0] if tr.side == 1 else funding_rates[1]
                    cost += tr.entry * tr.size * (rate / 100.0) * max(0.0, (M.t4[i] - tr.entry_t) / 86400e9)
                tr.pnl = gross - cost
                tr.exit, tr.exit_i, tr.exit_t, tr.reason = exit_p, i, M.t4[i], reason
                risk = abs(tr.entry - tr.init_stop) * tr.size
                tr.r = tr.pnl / risk if risk else 0.0
                bal += tr.pnl
                trades.append(tr)
                del active[sid]

            # Break-Even
            if (p.be_at > 0 and not same and abs(tr.stop - tr.entry) > 0):
                risk = abs(tr.entry - tr.init_stop)
                gain = (hi - tr.entry) if tr.side == 1 else (tr.entry - lo)
                if risk > 0 and gain >= p.be_at * risk:
                    if tr.side == 1 and tr.stop < tr.entry:
                        tr.stop = tr.entry
                    elif tr.side == -1 and tr.stop > tr.entry:
                        tr.stop = tr.entry

        # ── الدخول ──
        for (sid, side, stop, target) in sigs.get(i, ()):
            if sid in active:
                skipped += 1
                continue
            if len(active) >= p.max_positions:
                skipped += 1
                continue
            if p.hedge_block and any(t.side != side for t in active.values()):
                skipped += 1
                continue
            entry = cl
            dist = abs(entry - stop)
            mult = {"A": p.risk_a, "B": p.risk_b, "C": p.risk_c, "D": p.risk_d,
                    "E": p.risk_e, "F": p.risk_f}.get(sid, 1.0)
            risk_usd = bal * (p.risk_pct / 100.0) * mult
            size = max(MIN_SIZE, round(risk_usd / dist, 4)) if dist > 0 else MIN_SIZE
            active[sid] = Trade(sid, side, i, M.t4[i], entry, stop, target, size,
                                init_stop=stop, peak=(hi if side == 1 else lo))
            max_conc = max(max_conc, len(active))

    last = min(i1, len(M.c)) - 1
    for sid, tr in list(active.items()):
        exit_p = M.c[last]
        gross = (exit_p - tr.entry) * tr.size if tr.side == 1 else (tr.entry - exit_p) * tr.size
        cost = spread * tr.size
        if funding_rates:
            rate = funding_rates[0] if tr.side == 1 else funding_rates[1]
            cost += tr.entry * tr.size * (rate / 100.0) * max(0.0, (M.t4[last] - tr.entry_t) / 86400e9)
        tr.pnl = gross - cost
        risk = abs(tr.entry - tr.init_stop) * tr.size
        tr.r = tr.pnl / risk if risk else 0.0
        tr.exit, tr.exit_i, tr.exit_t, tr.reason = exit_p, last, M.t4[last], "OPEN_AT_END"
        trades.append(tr)
        active.pop(sid)

    return {"trades": trades, "balance": bal, "max_concurrent": max_conc, "skipped": skipped}


def metrics(res: dict, initial_balance: float = 198.66) -> dict:
    tr = res["trades"]
    wins = [t for t in tr if t.pnl > 0]
    losses = [t for t in tr if t.pnl <= 0]
    gp = sum(t.pnl for t in wins)
    gl = abs(sum(t.pnl for t in losses))
    eq = peak = initial_balance
    mdd = 0.0
    for t in sorted(tr, key=lambda x: (x.exit_t or 0, x.entry_t)):
        eq += t.pnl
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    return {
        "n": len(tr), "wins": len(wins), "losses": len(losses),
        "wr": len(wins) / len(tr) * 100 if tr else 0.0,
        "pnl": sum(t.pnl for t in tr),
        "pf": gp / gl if gl else (float("inf") if gp > 0 else 0.0),
        "mdd": mdd, "max_concurrent": res["max_concurrent"], "skipped": res["skipped"],
        "ret_pct": (res["balance"] / initial_balance - 1) * 100,
    }


def per_spec(trades: Sequence[Trade]) -> Dict[str, dict]:
    out = {}
    for sid in ("A", "B", "C", "D", "E", "F"):
        sub = [t for t in trades if t.spec == sid]
        if not sub:
            out[sid] = {"n": 0, "pnl": 0.0, "pf": 0.0, "wr": 0.0}
            continue
        w = [t for t in sub if t.pnl > 0]
        gp = sum(t.pnl for t in w)
        gl = abs(sum(t.pnl for t in sub if t.pnl <= 0))
        out[sid] = {"n": len(sub), "pnl": sum(t.pnl for t in sub),
                    "pf": gp / gl if gl else (999 if gp else 0),
                    "wr": len(w) / len(sub) * 100}
    return out
