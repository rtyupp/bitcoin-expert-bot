"""محرك التداول التلقائي واليدوي على حساب Capital.com التجريبي (Demo REST API).

يدعم:
- جلب رصيد الحساب والصفقات المفتوحة
- فتح صفقات شراء/بيع (BUY / SELL) على البيتكوين (BTCUSD) والذهب (GOLD) مع تحديد الوقف والهدف
- تعديل وقف الخسارة إلى نقطة الدخول (Break-Even) تلقائياً عند وصول الهدف الأول TP1
- إغلاق الصفقات المفتوحة
- جلب السعر اللحظي المباشر من Capital.com
"""
from __future__ import annotations

import logging
import time
import httpx
import config

BASE_URL = "https://demo-api-capital.backend-capital.com/api/v1"
EPIC_MAP = {
    "btc": "BTCUSD",
    "BTC/USDT": "BTCUSD",
    "BTCUSD": "BTCUSD",
    "gold": "GOLD",
    "PAXG/USDT": "GOLD",
    "GOLD": "GOLD",
}

DEFAULT_SIZES = {
    "BTCUSD": 0.01,  # 0.01 BTC
    "GOLD": 0.1,     # 0.1 oz Gold
}

_CLIENT = httpx.Client(timeout=httpx.Timeout(12.0, connect=5.0))
_SESSION: dict[str, str | float] = {"cst": "", "xst": "", "ts": 0.0}
_SESSION_TTL = 480.0  # 8 دقائق


def is_configured() -> bool:
    return bool(config.CAPITAL_EMAIL and config.CAPITAL_API_KEY and config.CAPITAL_API_PASSWORD)


def _epic(asset_or_symbol: str) -> str:
    return EPIC_MAP.get(asset_or_symbol, EPIC_MAP.get(asset_or_symbol.lower(), "BTCUSD"))


def _auth_headers(force: bool = False) -> dict[str, str]:
    if not is_configured():
        raise RuntimeError("بيانات حساب Capital.com غير مضبوطة")
    now = time.time()
    if not force and _SESSION["cst"] and (now - float(_SESSION["ts"])) < _SESSION_TTL:
        return {
            "CST": str(_SESSION["cst"]),
            "X-SECURITY-TOKEN": str(_SESSION["xst"]),
            "Content-Type": "application/json",
        }
    r = _CLIENT.post(
        f"{BASE_URL}/session",
        headers={"X-CAP-API-KEY": config.CAPITAL_API_KEY, "Content-Type": "application/json"},
        json={
            "identifier": config.CAPITAL_EMAIL,
            "password": config.CAPITAL_API_PASSWORD,
            "encryptedPassword": False,
        },
    )
    r.raise_for_status()
    cst = r.headers.get("CST", "")
    xst = r.headers.get("X-SECURITY-TOKEN", "")
    if not cst or not xst:
        raise RuntimeError("فشل الحصول على رموز الجلسة من Capital.com")
    _SESSION["cst"] = cst
    _SESSION["xst"] = xst
    _SESSION["ts"] = now
    return {"CST": cst, "X-SECURITY-TOKEN": xst, "Content-Type": "application/json"}


def _request(method: str, path: str, **kwargs) -> httpx.Response:
    headers = _auth_headers(force=False)
    r = _CLIENT.request(method, f"{BASE_URL}{path}", headers=headers, **kwargs)
    if r.status_code == 401:
        headers = _auth_headers(force=True)
        r = _CLIENT.request(method, f"{BASE_URL}{path}", headers=headers, **kwargs)
    r.raise_for_status()
    return r


def account_summary() -> dict:
    """يرجع بيانات الحساب التجريبي + الصفقات المفتوحة."""
    acc_data = _request("GET", "/accounts").json()
    accounts = acc_data.get("accounts") or []
    acc = accounts[0] if accounts else {}
    bal = acc.get("balance") or {}

    pos_data = _request("GET", "/positions").json()
    positions = []
    for item in pos_data.get("positions") or []:
        p = item.get("position") or {}
        m = item.get("market") or {}
        positions.append({
            "dealId": p.get("dealId"),
            "epic": m.get("epic"),
            "name": m.get("instrumentName"),
            "direction": p.get("direction"),
            "size": p.get("size"),
            "level": p.get("level"),
            "stopLevel": p.get("stopLevel"),
            "profitLevel": p.get("profitLevel"),
            "upl": p.get("upl", 0.0),
            "bid": m.get("bid"),
            "offer": m.get("offer"),
        })

    return {
        "accountId": acc.get("accountId", "—"),
        "accountName": acc.get("accountName", "Demo"),
        "balance": float(bal.get("balance", 0.0)),
        "deposit": float(bal.get("deposit", 0.0)),
        "profitLoss": float(bal.get("profitLoss", 0.0)),
        "available": float(bal.get("available", 0.0)),
        "currency": acc.get("currency", "USD"),
        "positions": positions,
    }


def live_price(symbol_or_asset: str) -> dict:
    """سعر لحظي من Capital.com."""
    epic = _epic(symbol_or_asset)
    data = _request("GET", f"/markets/{epic}").json()
    snap = data.get("snapshot") or {}
    bid = float(snap.get("bid") or 0.0)
    offer = float(snap.get("offer") or bid)
    price = (bid + offer) / 2.0 if (bid and offer) else (bid or offer)
    if price <= 0:
        raise RuntimeError(f"Capital.com لم يرجع سعراً لـ {epic}")
    pct_chg = snap.get("percentageChange")
    return {
        "price": price,
        "bid": bid,
        "offer": offer,
        "change": float(pct_chg) if pct_chg is not None else None,
        "high": float(snap.get("high") or 0.0),
        "low": float(snap.get("low") or 0.0),
        "ts": time.time(),
        "exchange": f"Capital.com ({epic})",
    }


def open_trade(
    asset_or_symbol: str,
    direction: str,
    size: float | None = None,
    stop_level: float | None = None,
    profit_level: float | None = None,
) -> dict:
    """يفتح صفقة BUY أو SELL على الحساب التجريبي في Capital.com."""
    epic = _epic(asset_or_symbol)
    side = "BUY" if direction.upper() in ("BUY", "LONG") else "SELL"
    deal_size = float(size) if size and size > 0 else DEFAULT_SIZES.get(epic, 0.01)

    # جلب السعر الحي من Capital لضمان تطابق مستويات الوقف والهدف مع سعر المنصة الفعلي
    mkt = live_price(epic)
    ref_price = mkt["offer"] if side == "BUY" else mkt["bid"]
    decimals = 2 if epic == "GOLD" else 1

    payload: dict = {
        "epic": epic,
        "direction": side,
        "size": deal_size,
        "guaranteedStop": False,
        "trailingStop": False,
    }
    if stop_level is not None and stop_level > 0:
        st = round(float(stop_level), decimals)
        if (side == "BUY" and st < ref_price) or (side == "SELL" and st > ref_price):
            payload["stopLevel"] = st
    if profit_level is not None and profit_level > 0:
        tp = round(float(profit_level), decimals)
        if (side == "BUY" and tp > ref_price) or (side == "SELL" and tp < ref_price):
            payload["profitLevel"] = tp

    r = _request("POST", "/positions", json=payload).json()
    deal_ref = r.get("dealReference", "")

    # تأكيد الصفقة وجلب dealId الفعلي
    conf = {}
    if deal_ref:
        try:
            conf = _request("GET", f"/confirms/{deal_ref}").json()
        except Exception:  # noqa: BLE001
            logging.exception("تعذّر جلب تأكيد الصفقة %s", deal_ref)

    status = conf.get("dealStatus", "ACCEPTED")
    reason = conf.get("reason", "")
    if status == "REJECTED":
        raise RuntimeError(f"رُفض الأمر من Capital.com: {reason}")

    # في Capital.com، dealId الخاص بالـ position المفتوحة يكون في affectedDeals
    deal_id = conf.get("dealId")
    for ad in conf.get("affectedDeals") or []:
        if ad.get("status") in ("OPENED", "AMENDED"):
            deal_id = ad.get("dealId") or deal_id

    return {
        "ok": True,
        "epic": epic,
        "direction": side,
        "size": deal_size,
        "level": float(conf.get("level") or ref_price),
        "dealId": deal_id,
        "dealReference": deal_ref,
        "stopLevel": payload.get("stopLevel"),
        "profitLevel": payload.get("profitLevel"),
        "status": status,
    }


def update_position_levels(
    deal_id: str,
    stop_level: float | None = None,
    profit_level: float | None = None,
    epic: str = "BTCUSD",
) -> bool:
    """يحدث مستوى وقف الخسارة و/أو الهدف لصفقة قائمة (مثلاً نقل الوقف لنقطة الدخول عند TP1)."""
    decimals = 2 if epic == "GOLD" else 1
    body: dict = {"guaranteedStop": False, "trailingStop": False}
    if stop_level is not None:
        body["stopLevel"] = round(float(stop_level), decimals)
    if profit_level is not None:
        body["profitLevel"] = round(float(profit_level), decimals)
    try:
        _request("PUT", f"/positions/{deal_id}", json=body)
        return True
    except Exception:  # noqa: BLE001
        logging.exception("فشل تحديث مستويات الصفقة %s على Capital.com", deal_id)
        return False


def move_stop_to_breakeven(asset_or_symbol: str, entry_price: float | None = None) -> int:
    """ينقل وقف الخسارة إلى سعر افتتاح الصفقة (Break-Even) لكل الصفقات المفتوحة على هذا الأصل."""
    epic = _epic(asset_or_symbol)
    summary = account_summary()
    updated = 0
    for pos in summary["positions"]:
        if pos["epic"] != epic:
            continue
        be_level = float(pos["level"]) if pos.get("level") else entry_price
        if not be_level:
            continue
        ok = update_position_levels(
            pos["dealId"],
            stop_level=be_level,
            profit_level=pos.get("profitLevel"),
            epic=epic,
        )
        if ok:
            updated += 1
    return updated


def close_position(deal_id: str) -> dict:
    """يغلق صفقة محددة عبر dealId."""
    r = _request("DELETE", f"/positions/{deal_id}").json()
    return {"ok": True, "dealReference": r.get("dealReference")}


def close_all(asset_or_symbol: str | None = None) -> int:
    """يغلق كل الصفقات المفتوحة (أو صفقات أصل معيّن)."""
    target_epic = _epic(asset_or_symbol) if asset_or_symbol else None
    summary = account_summary()
    closed = 0
    for pos in summary["positions"]:
        if target_epic and pos["epic"] != target_epic:
            continue
        try:
            close_position(pos["dealId"])
            closed += 1
        except Exception:  # noqa: BLE001
            logging.exception("تعذّر إغلاق الصفقة %s", pos["dealId"])
    return closed
