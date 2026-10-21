"""أسعار وشموع مباشرة عبر REST (بدون ccxt) — طلب واحد لكل استدعاء.

لماذا أسرع بكثير من ccxt؟
  • لا load_markets (كان يعاد كل مرة مع ccxt → ثواني ضائعة)
  • لا rate-limiter مصطنع
  • اتصال HTTP دائم مشترك يعاد استخدامه بين الطلبات (keep-alive)
  • مهلة قصيرة 8ث مع 3 مصادر بديلة تلقائياً (binance → bybit → okx)

الأشكال المعادة مطابقة لواجهة ccxt القديمة حتى لا يتغير أي مستدعي.
"""
import time

import httpx
import pandas as pd

TIMEOUT = httpx.Timeout(8.0, connect=4.0)
HEADERS = {"User-Agent": "btc-gold-bot/2.0", "Accept": "application/json"}

SOURCES = ("binance", "bybit", "okx")
_GOOD: str | None = None

# اتصال مشترك دائم — thread-safe في httpx
_CLIENT = httpx.Client(timeout=TIMEOUT, headers=HEADERS)

_BYBIT_TF = {
    "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30", "1h": "60",
    "2h": "120", "4h": "240", "6h": "360", "12h": "720", "1d": "D", "1w": "W",
}
_OKX_TF = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1H",
    "2h": "2H", "4h": "4H", "6h": "6H", "12h": "12H", "1d": "1D", "1w": "1W",
}


def _order(symbol: str) -> tuple[str, ...]:
    base, _ = _pair(symbol)
    # bybit لا يسرد PAXG — وفّر محاولة فاشلة مؤكدة على الذهب
    pref = ("binance", "okx", "bybit") if base == "PAXG" else SOURCES
    if _GOOD and _GOOD in pref:
        return (_GOOD,) + tuple(s for s in pref if s != _GOOD)
    return pref


def _mark(src: str) -> None:
    global _GOOD
    _GOOD = src


def _pair(symbol: str) -> tuple[str, str]:
    parts = symbol.split("/")
    base = (parts[0] or "BTC").upper()
    quote = (parts[1] if len(parts) > 1 else "USDT").upper()
    return base, quote


def _get(url: str, **params):
    r = _CLIENT.get(url, params=params)
    r.raise_for_status()
    return r.json()


# ── الشموع ──
def _klines_binance(base: str, quote: str, tf: str, limit: int):
    j = _get(
        "https://api.binance.com/api/v3/klines",
        symbol=f"{base}{quote}", interval=tf, limit=min(int(limit), 1000),
    )
    if not isinstance(j, list) or not j:
        raise ValueError("لا بيانات")
    return [(int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])) for k in j]


def _klines_bybit(base: str, quote: str, tf: str, limit: int):
    interval = _BYBIT_TF.get(tf)
    if not interval:
        raise ValueError(f"فريم {tf} غير مدعوم في bybit")
    j = _get(
        "https://api.bybit.com/v5/market/kline",
        category="spot", symbol=f"{base}{quote}", interval=interval, limit=min(int(limit), 1000),
    )
    rows = (j.get("result") or {}).get("list") or []
    if not rows:
        raise ValueError("لا بيانات")
    rows.reverse()  # bybit يرجّع الأحدث أولاً
    return [(int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])) for k in rows]


def _klines_okx(base: str, quote: str, tf: str, limit: int):
    bar = _OKX_TF.get(tf)
    if not bar:
        raise ValueError(f"فريم {tf} غير مدعوم في okx")
    j = _get(
        "https://www.okx.com/api/v5/market/candles",
        instId=f"{base}-{quote}", bar=bar, limit=str(min(int(limit), 300)),
    )
    rows = j.get("data") or []
    if not rows:
        raise ValueError("لا بيانات")
    rows.reverse()  # okx يرجّع الأحدث أولاً
    # صف OKX: [ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm]
    return [(int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])) for k in rows]


_KLINES = {"binance": _klines_binance, "bybit": _klines_bybit, "okx": _klines_okx}


# ── التكتكر (آخر سعر + تغير 24س + أعلى/أدنى) ──
def _tick_binance(base: str, quote: str):
    j = _get("https://api.binance.com/api/v3/ticker/24hr", symbol=f"{base}{quote}")
    return (
        float(j["lastPrice"]),
        float(j.get("priceChangePercent") or 0.0),
        float(j.get("highPrice") or 0.0),
        float(j.get("lowPrice") or 0.0),
    )


def _tick_bybit(base: str, quote: str):
    j = _get("https://api.bybit.com/v5/market/tickers", category="spot", symbol=f"{base}{quote}")
    t = (j.get("result") or {}).get("list") or [None]
    t = t[0]
    if not t or not t.get("lastPrice"):
        raise ValueError("لا بيانات")
    return (
        float(t["lastPrice"]),
        float(t.get("price24hPcnt") or 0.0) * 100.0,  # bybit يرجّع كسر عشري
        float(t.get("highPrice24h") or 0.0),
        float(t.get("lowPrice24h") or 0.0),
    )


def _tick_okx(base: str, quote: str):
    j = _get("https://www.okx.com/api/v5/market/ticker", instId=f"{base}-{quote}")
    d = (j.get("data") or [None])[0]
    if not d or not d.get("last"):
        raise ValueError("لا بيانات")
    last, open24 = float(d["last"]), float(d.get("open24h") or 0.0)
    chg = (last - open24) / open24 * 100.0 if open24 else 0.0
    return last, chg, float(d.get("high24h") or 0.0), float(d.get("low24h") or 0.0)


_TICKS = {"binance": _tick_binance, "bybit": _tick_bybit, "okx": _tick_okx}


# ── الواجهة العامة (مطابقة القديم) ──
def fetch_ohlcv(symbol: str, timeframe: str = "1h", limit: int = 250):
    """جلب الشموع — يبدأ من المصدر الناجح سابقاً. يرجّع (DataFrame, المصدر)."""
    base, quote = _pair(symbol)
    errors = []
    for src in _order(symbol):
        try:
            rows = _KLINES[src](base, quote, timeframe, limit)
            if not rows:
                raise ValueError("لا بيانات")
            df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
            df["ts"] = pd.to_datetime(df["ts"], unit="ms")
            _mark(src)
            return df, src
        except Exception as err:  # noqa: BLE001
            errors.append(f"{src}: {type(err).__name__}")
    raise RuntimeError("تعذّر جلب البيانات من كل المنصات: " + "; ".join(errors))


def tick(symbol: str) -> tuple[float, float, float, float, str]:
    """(السعر، تغير 24س %، أعلى 24س، أدنى 24س، المصدر)."""
    base, quote = _pair(symbol)
    errors = []
    for src in _order(symbol):
        try:
            price, chg, high, low = _TICKS[src](base, quote)
            _mark(src)
            return price, chg, high, low, src
        except Exception as err:  # noqa: BLE001
            errors.append(f"{src}: {type(err).__name__}")
    raise RuntimeError("تعذّر جلب السعر من كل المنصات: " + "; ".join(errors))


def ticker(symbol: str) -> tuple[float, float | None, str]:
    """السعر الحالي + تغير 24س + المصدر."""
    price, chg, _, _, src = tick(symbol)
    return price, chg, src


def live_ticker(symbol: str) -> dict:
    """سعر لحظي كامل + أعلى/أدنى 24س + طابع زمني."""
    price, chg, high, low, src = tick(symbol)
    return {
        "price": price,
        "change": chg,
        "high": high,
        "low": low,
        "ts": time.time(),
        "exchange": src,
    }
