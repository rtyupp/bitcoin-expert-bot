"""Capital.com REST API Client for GBP/USD, Gold, and Silver."""
from __future__ import annotations

import logging
import threading
import time
import httpx
import pandas as pd
import config

BASE_URLS = {
    "demo": "https://demo-api-capital.backend-capital.com/api/v1",
    "live": "https://api-capital.backend-capital.com/api/v1",
}

RESOLUTION_MAP = {
    "1m": "MINUTE",
    "5m": "MINUTE_5",
    "15m": "MINUTE_15",
    "30m": "MINUTE_30",
    "1h": "HOUR",
    "4h": "HOUR_4",
    "1d": "DAY",
}

_CLIENT = httpx.Client(timeout=httpx.Timeout(14.0, connect=6.0))
_AUTH_LOCK = threading.Lock()
_SESSION: dict[str, str | float] = {"cst": "", "xst": "", "ts": 0.0, "fail_until": 0.0}
_SESSION_TTL = 540.0  # 9 minutes

_PRICE_CACHE: dict[str, tuple[float, dict]] = {}
_OHLCV_CACHE: dict[tuple[str, str, int], tuple[float, pd.DataFrame]] = {}

log = logging.getLogger("capital")


def is_configured() -> bool:
    return bool(config.CAPITAL_EMAIL and config.CAPITAL_API_KEY and config.CAPITAL_API_PASSWORD)


def _base_url() -> str:
    return BASE_URLS.get(config.CAPITAL_ENV, BASE_URLS["demo"])


def _auth_headers(force: bool = False) -> dict[str, str]:
    if not is_configured():
        raise RuntimeError("Capital.com credentials not configured in config.py / .env")
    with _AUTH_LOCK:
        now = time.time()
        if not force and _SESSION["cst"] and (now - float(_SESSION["ts"])) < _SESSION_TTL:
            return {
                "CST": str(_SESSION["cst"]),
                "X-SECURITY-TOKEN": str(_SESSION["xst"]),
                "Content-Type": "application/json",
            }
        if now < float(_SESSION.get("fail_until", 0.0)):
            if _SESSION["cst"]:
                return {
                    "CST": str(_SESSION["cst"]),
                    "X-SECURITY-TOKEN": str(_SESSION["xst"]),
                    "Content-Type": "application/json",
                }
            raise RuntimeError("Capital.com rate-limit cooldown active")

        r = _CLIENT.post(
            f"{_base_url()}/session",
            headers={"X-CAP-API-KEY": config.CAPITAL_API_KEY, "Content-Type": "application/json"},
            json={
                "identifier": config.CAPITAL_EMAIL,
                "password": config.CAPITAL_API_PASSWORD,
                "encryptedPassword": False,
            },
        )
        if r.status_code == 429:
            _SESSION["fail_until"] = now + 30.0
            if _SESSION["cst"]:
                return {
                    "CST": str(_SESSION["cst"]),
                    "X-SECURITY-TOKEN": str(_SESSION["xst"]),
                    "Content-Type": "application/json",
                }
        r.raise_for_status()
        cst = r.headers.get("CST", "")
        xst = r.headers.get("X-SECURITY-TOKEN", "")
        if not cst or not xst:
            raise RuntimeError("Failed to receive session tokens from Capital.com")
        _SESSION["cst"] = cst
        _SESSION["xst"] = xst
        _SESSION["ts"] = now
        return {"CST": cst, "X-SECURITY-TOKEN": xst, "Content-Type": "application/json"}


def _request(method: str, path: str, **kwargs) -> httpx.Response:
    headers = _auth_headers(force=False)
    r = _CLIENT.request(method, f"{_base_url()}{path}", headers=headers, **kwargs)
    if r.status_code == 401:
        headers = _auth_headers(force=True)
        r = _CLIENT.request(method, f"{_base_url()}{path}", headers=headers, **kwargs)
    r.raise_for_status()
    return r


def _bid(d: dict | None) -> float:
    if not d:
        return 0.0
    b = d.get("bid")
    a = d.get("ask")
    return float(b if b is not None else (a or 0.0))


def get_market_info(epic: str) -> dict | None:
    try:
        data = _request("GET", f"/markets/{epic}").json()
        snap = data.get("snapshot") or {}
        inst = data.get("instrument") or {}
        rules = data.get("dealingRules") or {}
        bid = float(snap.get("bid") or 0.0)
        offer = float(snap.get("offer") or bid)
        return {
            "epic": epic,
            "name": inst.get("instrumentName", epic),
            "bid": bid,
            "offer": offer,
            "price": bid if bid > 0 else offer,
            "spread": round(offer - bid, 5),
            "status": snap.get("marketStatus", "TRADEABLE"),
            "min_deal_size": rules.get("minDealSize", {}).get("value", 0.01),
        }
    except Exception as e:
        log.error(f"get_market_info({epic}) error: {e}")
        return None


def live_price(epic: str) -> dict:
    now = time.time()
    cached = _PRICE_CACHE.get(epic)
    if cached and (now - cached[0]) < 2.0:
        return cached[1]

    data = _request("GET", f"/markets/{epic}").json()
    snap = data.get("snapshot") or {}
    bid = float(snap.get("bid") or 0.0)
    offer = float(snap.get("offer") or bid)
    price = bid if bid > 0 else offer
    pct_chg = snap.get("percentageChange")
    res = {
        "price": price,
        "bid": bid,
        "offer": offer,
        "spread": round(offer - bid, 5),
        "mid": (bid + offer) / 2.0 if (bid and offer) else price,
        "change": float(pct_chg) if pct_chg is not None else None,
        "high": float(snap.get("high") or 0.0),
        "low": float(snap.get("low") or 0.0),
        "ts": now,
        "epic": epic,
    }
    _PRICE_CACHE[epic] = (now, res)
    return res


def fetch_ohlcv(epic: str, timeframe: str = "4h", limit: int = 300) -> pd.DataFrame:
    res = RESOLUTION_MAP.get(timeframe, "HOUR_4")
    max_bars = min(max(int(limit), 20), 1000)
    cache_key = (epic, res, max_bars)
    now = time.time()
    cached = _OHLCV_CACHE.get(cache_key)
    if cached and (now - cached[0]) < 15.0:
        return cached[1].copy()

    data = _request("GET", f"/prices/{epic}", params={"resolution": res, "max": max_bars}).json()
    prices = data.get("prices") or []
    if not prices:
        raise RuntimeError(f"Capital.com returned no candles for {epic}")

    rows = []
    for p in prices:
        ts_str = p.get("snapshotTimeUTC") or p.get("snapshotTime")
        rows.append((
            ts_str,
            _bid(p.get("openPrice")),
            _bid(p.get("highPrice")),
            _bid(p.get("lowPrice")),
            _bid(p.get("closePrice")),
            float(p.get("lastTradedVolume") or 0.0),
        ))

    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"])
    _OHLCV_CACHE[cache_key] = (now, df)
    return df.copy()


def account_summary() -> dict:
    acc_data = _request("GET", "/accounts").json()
    acc = (acc_data.get("accounts") or [{}])[0]
    bal = acc.get("balance") or {}

    pos_data = _request("GET", "/positions").json()
    positions = []
    for item in pos_data.get("positions") or []:
        p = item.get("position") or {}
        m = item.get("market") or {}
        deal_id = p.get("dealId")
        positions.append({
            "deal_id": deal_id,
            "dealId": deal_id,
            "epic": m.get("epic"),
            "name": m.get("instrumentName"),
            "direction": p.get("direction"),
            "size": p.get("size"),
            "level": p.get("level"),
            "stopLevel": p.get("stopLevel"),
            "profitLevel": p.get("profitLevel"),
            "upl": p.get("upl", 0.0),
        })

    return {
        "accountId": acc.get("accountId", "—"),
        "balance": float(bal.get("balance", 0.0)),
        "profitLoss": float(bal.get("profitLoss", 0.0)),
        "available": float(bal.get("available", 0.0)),
        "deposit": float(bal.get("deposit", 0.0)),
        "positions": positions,
    }


def open_trade(
    epic: str,
    direction: str,
    size: float,
    stop_level: float | None = None,
    profit_level: float | None = None,
) -> dict:
    side = "BUY" if direction.upper() in ("BUY", "LONG") else "SELL"
    mkt = live_price(epic)
    ref_price = mkt["offer"] if side == "BUY" else mkt["bid"]

    asset_cfg = config.ASSETS.get(epic, {})
    decimals = asset_cfg.get("decimals", 2)

    payload: dict = {
        "epic": epic,
        "direction": side,
        "size": float(size),
        "guaranteedStop": False,
        "trailingStop": False,
    }
    if stop_level is not None:
        st = round(float(stop_level), decimals)
        if (side == "BUY" and st < ref_price) or (side == "SELL" and st > ref_price):
            payload["stopLevel"] = st
    if profit_level is not None:
        tp = round(float(profit_level), decimals)
        if (side == "BUY" and tp > ref_price) or (side == "SELL" and tp < ref_price):
            payload["profitLevel"] = tp

    r = _request("POST", "/positions", json=payload).json()
    deal_ref = r.get("dealReference", "")
    conf = {}
    if deal_ref:
        try:
            conf = _request("GET", f"/confirms/{deal_ref}").json()
        except Exception:
            log.exception("Confirm fetch failed for %s", deal_ref)

    if conf.get("dealStatus") == "REJECTED":
        raise RuntimeError(f"Order rejected: {conf.get('reason')}")

    deal_id = conf.get("dealId")
    for ad in conf.get("affectedDeals") or []:
        if ad.get("status") in ("OPENED", "AMENDED"):
            deal_id = ad.get("dealId") or deal_id

    return {
        "ok": True,
        "epic": epic,
        "direction": side,
        "size": float(size),
        "level": float(conf.get("level") or ref_price),
        "deal_id": deal_id,
        "dealId": deal_id,
        "stopLevel": payload.get("stopLevel"),
        "profitLevel": payload.get("profitLevel"),
    }


def update_position(deal_id: str, stop_level: float | None = None, profit_level: float | None = None) -> tuple[bool, str]:
    payload = {}
    if stop_level is not None:
        payload["stopLevel"] = round(float(stop_level), 5)
    if profit_level is not None:
        payload["profitLevel"] = round(float(profit_level), 5)
    if not payload:
        return False, "No update payload"
    r = _request("PUT", f"/positions/{deal_id}", json=payload).json()
    if r.get("dealStatus") == "REJECTED":
        return False, r.get("reason", "Rejected")
    return True, "OK"


def close_position(deal_id: str) -> tuple[bool, str]:
    try:
        r = _request("DELETE", f"/positions/{deal_id}").json()
        return True, str(r.get("dealReference", "OK"))
    except Exception as e:
        return False, str(e)


def close_all(epic: str | None = None) -> int:
    summary = account_summary()
    closed = 0
    for p in summary["positions"]:
        if epic is None or p["epic"] == epic:
            ok, _ = close_position(p["deal_id"])
            if ok:
                closed += 1
    return closed


class _Client:
    is_configured = staticmethod(is_configured)
    get_market_info = staticmethod(get_market_info)
    live_price = staticmethod(live_price)
    fetch_ohlcv = staticmethod(fetch_ohlcv)
    account_summary = staticmethod(account_summary)
    open_trade = staticmethod(open_trade)
    update_position = staticmethod(update_position)
    close_position = staticmethod(close_position)
    close_all = staticmethod(close_all)

client = _Client()
