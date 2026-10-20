"""مختبر الاستراتيجيات — يقارن 10 استراتيجيات على البيتكوين والذهب بمنطق خروج موحّد.

المنهجية:
- بيانات يومية (BTC من 2018، PAXG من 2020)
- دخول عند إغلاق الشمعة (بدون lookahead)
- وقف 2×ATR، هدف 2:1، أقصى احتفاظ 30 شمعة
- صفقة واحدة في نفس الوقت (i = exit_idx + 1)
- لو لمس الوقف والهدف في نفس الشمعة → نفترض الوقف أولاً (متحفظ)
"""
import ccxt
import numpy as np
import pandas as pd
import ta

EXCHANGES = ("binance", "okx", "bybit", "kraken", "coinbase")


def fetch(symbol: str, timeframe: str = "1d") -> pd.DataFrame:
    for eid in EXCHANGES:
        try:
            ex = getattr(ccxt, eid)({"enableRateLimit": True, "timeout": 20000})
            since = ex.parse8601("2018-01-01T00:00:00Z")
            now = ex.milliseconds()
            frames = []
            while since < now:
                raw = ex.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
                if not raw:
                    break
                frames.append(raw)
                since = raw[-1][0] + 1
                if len(raw) < 1000:
                    break
            data = [c for f in frames for c in f]
            if len(data) < 300:
                continue
            df = pd.DataFrame(data, columns=["ts", "open", "high", "low", "close", "volume"])
            df = df.drop_duplicates("ts").reset_index(drop=True)
            df["ts"] = pd.to_datetime(df["ts"], unit="ms")
            return df
        except Exception:  # noqa: BLE001
            continue
    raise RuntimeError(f"تعذّر جلب {symbol}")


# ── المؤشرات ──────────────────────────────────────────────────

def indicators(df: pd.DataFrame) -> dict:
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    atr = ta.volatility.AverageTrueRange(h, l, c, 14).average_true_range()
    bb = ta.volatility.BollingerBands(c, 20, 2)
    ema20 = ta.trend.EMAIndicator(c, 20).ema_indicator()
    ema50 = ta.trend.EMAIndicator(c, 50).ema_indicator()
    ema200 = ta.trend.EMAIndicator(c, 200).ema_indicator()
    rsi = ta.momentum.RSIIndicator(c, 14).rsi()
    macd = ta.trend.MACD(c)
    adx = ta.trend.ADXIndicator(h, l, c, 14).adx()
    vol20 = v.rolling(20).mean()
    # Donchian
    don20_hi = h.rolling(20).max().shift(1)
    don20_lo = l.rolling(20).min().shift(1)
    don55_hi = h.rolling(55).max().shift(1)
    don55_lo = l.rolling(55).min().shift(1)

    # Supertrend (10, 3) — النسخة القياسية بحمل النطاقات
    st_atr = ta.volatility.AverageTrueRange(h, l, c, 10).average_true_range()
    hl2 = (h + l) / 2
    ub = (hl2 + 3 * st_atr).values
    lb = (hl2 - 3 * st_atr).values
    cv = c.values
    n = len(cv)
    fub = np.full(n, np.nan)
    flb = np.full(n, np.nan)
    direction = np.zeros(n)
    for i in range(1, n):
        if np.isnan(ub[i]) or np.isnan(ub[i - 1]):
            continue
        fub[i] = ub[i] if (ub[i] < fub[i - 1] or cv[i - 1] > fub[i - 1]) else fub[i - 1]
        flb[i] = lb[i] if (lb[i] > flb[i - 1] or cv[i - 1] < flb[i - 1]) else flb[i - 1]
        if cv[i] > fub[i]:
            direction[i] = 1
        elif cv[i] < flb[i]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
    st_dir = pd.Series(direction, index=c.index).replace(0, np.nan)

    return {
        "atr": atr, "bb_up": bb.bollinger_hband(), "bb_mid": bb.bollinger_mavg(),
        "bb_lo": bb.bollinger_lband(), "ema20": ema20, "ema50": ema50, "ema200": ema200,
        "rsi": rsi, "macd": macd.macd(), "macd_sig": macd.macd_signal(), "adx": adx,
        "vol20": vol20, "vol": v,
        "don20_hi": don20_hi, "don20_lo": don20_lo,
        "don55_hi": don55_hi, "don55_lo": don55_lo,
        "st_dir": st_dir,
    }


# ── المحاكي ───────────────────────────────────────────────────

def simulate(df: pd.DataFrame, ind: dict, sig: np.ndarray, rr=2.0, stop_mult=2.0, max_hold=30):
    c = df["close"].values
    hi = df["high"].values
    lo = df["low"].values
    atr = ind["atr"].values
    n = len(c)
    trades = []
    i = 250
    while i < n - 1:
        d = int(sig[i]) if not pd.isna(sig[i]) else 0
        if d == 0 or pd.isna(atr[i]) or atr[i] <= 0:
            i += 1
            continue
        entry = c[i]
        sd = stop_mult * atr[i]
        stop = entry - d * sd
        target = entry + d * rr * sd
        exit_idx = min(i + max_hold, n - 1)
        won = None
        for j in range(i + 1, min(i + 1 + max_hold, n)):
            if d == 1:
                if lo[j] <= stop:
                    won, exit_idx = False, j
                    break
                if hi[j] >= target:
                    won, exit_idx = True, j
                    break
            else:
                if hi[j] >= stop:
                    won, exit_idx = False, j
                    break
                if lo[j] <= target:
                    won, exit_idx = True, j
                    break
        trades.append(rr if won else (-1.0 if won is False else d * (c[exit_idx] - entry) / sd))
        i = exit_idx + 1
    return trades


def stats(trades: list[float]) -> dict:
    if not trades:
        return {"n": 0}
    a = np.array(trades)
    wins = a[a > 0]
    losses = a[a < 0]
    gp, gl = wins.sum(), -losses.sum()
    # أقصى تراجع بالوحدات R
    eq = np.cumsum(a)
    peak = np.maximum.accumulate(eq)
    dd = float((peak - eq).max()) if len(eq) else 0.0
    return {
        "n": len(a),
        "win": len(wins) / len(a) * 100,
        "pf": gp / gl if gl > 0 else float("inf"),
        "avg": float(a.mean()),
        "total": float(a.sum()),
        "dd": dd,
        "max_loss_streak": int(max((len(list(g)) for k, g in __import__("itertools").groupby(a < 0) if k), default=0)),
    }


# ── الاستراتيجيات ────────────────────────────────────────────

def strategies(df: pd.DataFrame, ind: dict) -> dict:
    c, v = df["close"], df["volume"]
    out = {}

    # 1) كسر بولينجر + حجم (الحالية)
    s = np.where((c > ind["bb_up"]) & (v > 1.5 * ind["vol20"]), 1,
                 np.where((c < ind["bb_lo"]) & (v > 1.5 * ind["vol20"]), -1, 0))
    out["1. كسر بولينجر + حجم (الحالية)"] = s

    # 2) كسر بولينجر (زخم)
    out["2. كسر بولينجر (زخم)"] = np.where(c > ind["bb_up"], 1, np.where(c < ind["bb_lo"], -1, 0))

    # 3) Donchian 20
    out["3. Donchian 20"] = np.where(c > ind["don20_hi"], 1, np.where(c < ind["don20_lo"], -1, 0))

    # 4) Donchian 20 + حجم
    out["4. Donchian 20 + حجم"] = np.where(
        (c > ind["don20_hi"]) & (v > 1.5 * ind["vol20"]), 1,
        np.where((c < ind["don20_lo"]) & (v > 1.5 * ind["vol20"]), -1, 0))

    # 5) Donchian 55 (تيرتل طويل)
    out["5. Donchian 55"] = np.where(c > ind["don55_hi"], 1, np.where(c < ind["don55_lo"], -1, 0))

    # 6) Supertrend (10,3) تحوّل الاتجاه
    st = ind["st_dir"]
    out["6. Supertrend (10,3)"] = np.where(st.diff() > 0, 1, np.where(st.diff() < 0, -1, 0))

    # 7) EMA 20/50 تقاطع
    out["7. تقاطع EMA 20/50"] = np.where(
        (ind["ema20"] > ind["ema50"]) & (ind["ema20"].shift(1) <= ind["ema50"].shift(1)), 1,
        np.where((ind["ema20"] < ind["ema50"]) & (ind["ema20"].shift(1) >= ind["ema50"].shift(1)), -1, 0))

    # 8) MACD تقاطع + فلتر EMA200
    macd_up = (ind["macd"] > ind["macd_sig"]) & (ind["macd"].shift(1) <= ind["macd_sig"].shift(1))
    macd_dn = (ind["macd"] < ind["macd_sig"]) & (ind["macd"].shift(1) >= ind["macd_sig"].shift(1))
    out["8. MACD + فلتر EMA200"] = np.where(
        macd_up & (c > ind["ema200"]), 1, np.where(macd_dn & (c < ind["ema200"]), -1, 0))

    # 9) ارتداد بولينجر (انعكاسي)
    out["9. ارتداد بولينجر (انعكاسي)"] = np.where(c < ind["bb_lo"], 1, np.where(c > ind["bb_up"], -1, 0))

    # 10) RSI 30/70 (انعكاسي)
    out["10. RSI 30/70 (انعكاسي)"] = np.where(
        (ind["rsi"] < 30) & (ind["rsi"].shift(1) >= 30), 1,
        np.where((ind["rsi"] > 70) & (ind["rsi"].shift(1) <= 70), -1, 0))

    # 11) Donchian 20 + فلتر اتجاه EMA200
    out["11. Donchian 20 + EMA200"] = np.where(
        (c > ind["don20_hi"]) & (c > ind["ema200"]), 1,
        np.where((c < ind["don20_lo"]) & (c < ind["ema200"]), -1, 0))

    # 12) Donchian 20 + ADX>20
    out["12. Donchian 20 + ADX>20"] = np.where(
        (c > ind["don20_hi"]) & (ind["adx"] > 20), 1,
        np.where((c < ind["don20_lo"]) & (ind["adx"] > 20), -1, 0))

    # 13) ارتداد بولينجر + فلتر تذبذب (ADX<25)
    out["13. ارتداد بولينجر + ADX<25"] = np.where(
        (c < ind["bb_lo"]) & (ind["adx"] < 25), 1,
        np.where((c > ind["bb_up"]) & (ind["adx"] < 25), -1, 0))

    return out


def run(symbol: str, label: str) -> None:
    print(f"\n{'='*78}\n{label}  ({symbol})\n{'='*78}")
    df = fetch(symbol)
    print(f"بيانات: {len(df)} يوم | {df['ts'].iloc[0].date()} → {df['ts'].iloc[-1].date()}")
    ret = df["close"].pct_change().dropna()
    print(f"تقلب يومي: {ret.abs().mean()*100:.2f}% | عائد الشراء والاحتفاظ: "
          f"{(df['close'].iloc[-1]/df['close'].iloc[0]-1)*100:+.0f}%")
    ind = indicators(df)

    rows = []
    for name, sig in strategies(df, ind).items():
        for rr, tag in ((2.0, "1:2"), (3.0, "1:3")):
            tr = simulate(df, ind, sig, rr=rr)
            st = stats(tr)
            if st["n"] == 0:
                continue
            rows.append((name, tag, st))

    rows.sort(key=lambda r: (r[2]["pf"], r[2]["avg"]), reverse=True)
    print(f"\n{'الاستراتيجية':38s} {'هدف':5s} {'#':>4s} {'فوز%':>6s} {'PF':>6s} {'متوسطR':>8s} {'تراجعR':>8s}")
    print("-" * 78)
    for name, tag, s in rows:
        print(f"{name:38s} {tag:5s} {s['n']:4d} {s['win']:6.1f} {s['pf']:6.2f} "
              f"{s['avg']:+8.2f} {s['dd']:8.1f}")
    return rows


if __name__ == "__main__":
    btc = run("BTC/USDT", "🪙 البيتكوين")
    gold = run("PAXG/USDT", "🥇 الذهب")
