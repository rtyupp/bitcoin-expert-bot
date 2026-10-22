"""بيانات البيتكوين: شموع Binance (المصدر الذي اختُبرت عليه الاستراتيجيات) مع بدائل Bybit ثم OKX."""
from __future__ import annotations

import time

import httpx
import pandas as pd

_CLIENT = httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0),
                       headers={"User-Agent": "btc-signals/3.0", "Accept": "application/json"})
_BYBIT_TF = {"1h": "60", "4h": "240", "1d": "D"}
_OKX_TF = {"1h": "1H", "4h": "4H", "1d": "1Dutc"}
_TF_MS = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


def _get(url: str, **params):
    r = _CLIENT.get(url, params=params)
    r.raise_for_status()
    return r.json()


def _binance(tf: str, limit: int, start_ms: int | None = None):
    p = {"symbol": "BTCUSDT", "interval": tf, "limit": min(limit, 1000)}
    if start_ms is not None:
        p["startTime"] = start_ms
    j = _get("https://api.binance.com/api/v3/klines", **p)
    return [(int(k[0]), *map(float, k[1:6])) for k in j]


def _bybit(tf: str, limit: int):
    j = _get("https://api.bybit.com/v5/market/kline", category="spot", symbol="BTCUSDT",
             interval=_BYBIT_TF[tf], limit=min(limit, 1000))
    rows = (j.get("result") or {}).get("list") or []
    return [(int(k[0]), *map(float, k[1:6])) for k in reversed(rows)]


def _okx(tf: str, limit: int):
    out, after = [], None
    while len(out) < limit:
        p = {"instId": "BTC-USDT", "bar": _OKX_TF[tf], "limit": "300"}
        if after:
            p["after"] = after
        rows = _get("https://www.okx.com/api/v5/market/history-candles", **p).get("data") or []
        if not rows:
            break
        out += rows
        after = rows[-1][0]
    return [(int(k[0]), *map(float, k[1:6])) for k in reversed(out[:limit])]


def _frame(rows) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)


_CACHE: dict[tuple[str, int], tuple[float, pd.DataFrame, str]] = {}


def candles(tf: str, limit: int = 400, ttl: float = 60.0) -> tuple[pd.DataFrame, str]:
    """آخر `limit` شمعة (تشمل الشمعة الجارية). يرجع (DataFrame, المصدر)."""
    key = (tf, limit)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1].copy(), hit[2]
    errors = []
    for name, fn in (("binance", _binance), ("bybit", _bybit), ("okx", _okx)):
        try:
            rows = fn(tf, limit)
            if len(rows) < min(limit, 300) * 0.9:
                raise ValueError(f"شموع قليلة {len(rows)}")
            df = _frame(rows)
            _CACHE[key] = (time.time(), df, name)
            return df.copy(), name
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {type(e).__name__} {e}"[:120])
    raise RuntimeError("تعذّر جلب الشموع: " + " | ".join(errors))


def history(tf: str, start: str) -> pd.DataFrame:
    """تاريخ كامل من Binance منذ `start` (للاختبار التاريخي)."""
    t = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    rows = []
    while True:
        r = _binance(tf, 1000, t)
        if not r:
            break
        rows += r
        t = r[-1][0] + _TF_MS[tf]
        if len(r) < 1000:
            break
    return _frame(rows)


def ticker() -> dict:
    """آخر سعر + تغير 24 ساعة."""
    try:
        j = _get("https://api.binance.com/api/v3/ticker/24hr", symbol="BTCUSDT")
        return {"price": float(j["lastPrice"]), "change": float(j["priceChangePercent"]),
                "high": float(j["highPrice"]), "low": float(j["lowPrice"]), "src": "Binance"}
    except Exception:  # noqa: BLE001
        j = _get("https://api.bybit.com/v5/market/tickers", category="spot", symbol="BTCUSDT")
        t = j["result"]["list"][0]
        return {"price": float(t["lastPrice"]), "change": float(t["price24hPcnt"]) * 100,
                "high": float(t["highPrice24h"]), "low": float(t["lowPrice24h"]), "src": "Bybit"}
