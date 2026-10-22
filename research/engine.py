"""محرك backtest واقعي: إشارة عند إغلاق الشمعة، دخول بافتتاح التالية، وقف/هدف داخل الشمعة
(إذا لمس الاثنين بنفس الشمعة نفترض الوقف — تحفّظ)، تكلفة ذهاب وعودة، وقف متحرك اختياري."""
import numpy as np
import pandas as pd

COST = 0.0012  # 0.12% ذهاب+عودة (سبريد كابيتال + انزلاق)


def load(tf):
    df = pd.read_csv(f"research/btc_{tf}.csv", parse_dates=["ts"])
    return df


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def atr(df, n=14):
    h, l, c = df.high, df.low, df.close
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def adx(df, n=14):
    h, l = df.high, df.low
    up, dn = h.diff(), -l.diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    a = atr(df, n)
    pdi = 100 * pd.Series(pdm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / a
    ndi = 100 * pd.Series(ndm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / a
    dx = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


def run(df, sig, stop_dist, rr=None, trail=None, max_bars=None, be_at=None, exit_sig=None):
    """sig: مصفوفة +1/-1/0 عند الإغلاق. stop_dist: مسافة الوقف بالسعر عند الإشارة.
    rr: الهدف بمضاعف R (None = بدون هدف). trail: مضاعف مسافة وقف متحرك (chandelier) بالسعر/stop.
    be_at: نقل الوقف للدخول عند +be_at R. exit_sig: مصفوفة bool للخروج عند الإغلاق."""
    o, h, l, c = df.open.values, df.high.values, df.low.values, df.close.values
    n = len(df)
    trades = []
    i = 0
    sig = np.asarray(sig); sd = np.asarray(stop_dist)
    while i < n - 2:
        s = sig[i]
        if s == 0 or not np.isfinite(sd[i]) or sd[i] <= 0:
            i += 1
            continue
        e = o[i + 1]; d = sd[i]
        stop = e - s * d
        tp = e + s * rr * d if rr else None
        best = e
        j = i + 1
        res = None
        while j < n:
            if s > 0:
                if l[j] <= stop:
                    res = (stop - e) / d; break
                if tp is not None and h[j] >= tp:
                    res = rr; break
                best = max(best, h[j])
            else:
                if h[j] >= stop:
                    res = (e - stop) / d; break
                if tp is not None and l[j] <= tp:
                    res = rr; break
                best = min(best, l[j])
            if be_at is not None and s * (best - e) >= be_at * d:
                stop = max(stop, e) if s > 0 else min(stop, e)
            if trail is not None:
                ns = best - s * trail * d
                stop = max(stop, ns) if s > 0 else min(stop, ns)
            if exit_sig is not None and exit_sig[j]:
                res = s * (c[j] - e) / d; break
            if max_bars and j - i >= max_bars:
                res = s * (c[j] - e) / d; break
            j += 1
        if res is None:
            break  # صفقة مفتوحة للنهاية
        cost_r = COST * e / d
        trades.append((df.ts.iloc[i + 1], s, res - cost_r, j - i, d / e))
        i = j  # لا تداخل
    return pd.DataFrame(trades, columns=["ts", "side", "r", "bars", "risk_pct"])


def stats(t, label=""):
    if len(t) == 0:
        return {"label": label, "n": 0}
    r = t.r
    wins = r[r > 0].sum(); loss = -r[r < 0].sum()
    eq = r.cumsum(); dd = (eq.cummax() - eq).max()
    yrs = t.groupby(t.ts.dt.year).r.sum()
    return {
        "label": label, "n": len(t), "win": round((r > 0).mean() * 100, 1),
        "pf": round(wins / loss, 2) if loss else 99, "exp": round(r.mean(), 3),
        "totR": round(r.sum(), 1), "maxDD_R": round(dd, 1),
        "pos_years": f"{(yrs > 0).sum()}/{len(yrs)}",
        "per_year": len(t) / max((t.ts.iloc[-1] - t.ts.iloc[0]).days / 365, 0.5),
    }


def split(t, cut="2024-01-01"):
    c = pd.Timestamp(cut, tz="UTC")
    return t[t.ts < c], t[t.ts >= c]
