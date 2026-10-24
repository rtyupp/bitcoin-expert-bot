"""واجهة متكاملة مع Capital.com REST API.

تغطي كامل الإمكانيات:
- إدارة الجلسة وتخزين التوكن التلقائي (Session Caching)
- جلب الرصيد والهامش والأرباح الحالية
- جلب الأسعار اللحظية، الشموع التاريخية، ومشاعر المتداولين (Sentiment)
- فتح صفقات السوق مع وقف الخسارة والهدف
- التحقق من تأكيد التنفيذ (Deal Confirmation)
- تعديل الصفقات (تحريك الوقف / Break-Even / إغلاق الصفقة)
"""
from __future__ import annotations

import os
import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
import requests
from typing import Any, Dict, List, Optional, Tuple

import config

log = logging.getLogger("capital_trader")

_URLS = {
    "demo": "https://demo-api-capital.backend-capital.com/api/v1",
    "live": "https://api-capital.backend-capital.com/api/v1",
}

_SESSION_FILE = os.path.join(os.path.dirname(__file__), ".session.json")

# مدة كل إطار زمني بالثواني (تُستخدم لاستبعاد الشمعة الجارية غير المكتملة)
_RESOLUTION_SECONDS = {
    "MINUTE": 60,
    "MINUTE_5": 300,
    "MINUTE_15": 900,
    "MINUTE_30": 1800,
    "HOUR": 3600,
    "HOUR_4": 14400,
    "DAY": 86400,
    "WEEK": 604800,
}


def _candle_start_utc(value: Any) -> Optional[datetime]:
    """تحويل snapshotTimeUTC إلى datetime واعٍ بالمنطقة الزمنية (UTC)."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

class CapitalClient:
    def __init__(self):
        self.base_url = _URLS.get(config.CAPITAL_ENV, _URLS["demo"])
        self.api_key = config.CAPITAL_API_KEY
        self.email = config.CAPITAL_EMAIL
        self.password = config.CAPITAL_API_PASSWORD
        self._cst: Optional[str] = None
        self._x_security_token: Optional[str] = None
        self._token_time: float = 0.0
        self._lock = threading.Lock()
        self._load_cached_session()

    def is_configured(self) -> bool:
        return bool(self.api_key and self.email and self.password)

    def _load_cached_session(self):
        if os.path.exists(_SESSION_FILE):
            try:
                with open(_SESSION_FILE, "r") as f:
                    data = json.load(f)
                    self._cst = data.get("cst")
                    self._x_security_token = data.get("xst")
                    self._token_time = float(data.get("ts", 0.0))
            except Exception:
                pass

    def _save_cached_session(self):
        try:
            with open(_SESSION_FILE, "w") as f:
                json.dump({
                    "cst": self._cst,
                    "xst": self._x_security_token,
                    "ts": self._token_time
                }, f)
        except Exception:
            pass

    def _headers(self, with_session: bool = True) -> Dict[str, str]:
        headers = {
            "X-CAP-API-KEY": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if with_session and self._cst and self._x_security_token:
            headers["CST"] = self._cst
            headers["X-SECURITY-TOKEN"] = self._x_security_token
        return headers

    def ensure_session(self, force: bool = False) -> bool:
        """يضمن وجود جلسة نشطة، ويجددها إذا قاربت على الانتهاء (أكثر من 8 دقائق)."""
        if not self.is_configured():
            log.warning("بيانات Capital.com غير مكتملة في الإعدادات.")
            return False

        with self._lock:
            now = time.time()
            if not force and self._cst and self._x_security_token and (now - self._token_time < 500):
                return True

            url = f"{self.base_url}/session"
            payload = {"identifier": self.email, "password": self.password}
            try:
                resp = requests.post(url, json=payload, headers=self._headers(with_session=False), timeout=15)
                if resp.status_code == 200:
                    self._cst = resp.headers.get("CST")
                    self._x_security_token = resp.headers.get("X-SECURITY-TOKEN")
                    self._token_time = now
                    self._save_cached_session()
                    log.info("تم تسجيل الدخول وتحديث جلسة Capital.com بنجاح.")
                    return True
                elif resp.status_code == 429 and self._cst and self._x_security_token:
                    log.warning("طلب الجلسة واجه 429 (Too Many Requests)، استمرار بالتوكن المخزن.")
                    return True
                else:
                    log.error(f"فشل إنشاء جلسة Capital.com: {resp.status_code} - {resp.text}")
                    return False
            except Exception as e:
                log.error(f"خطأ اتصال أثناء فتح جلسة Capital.com: {e}")
                return False

    def _request(self, method: str, endpoint: str, **kwargs) -> Optional[requests.Response]:
        if not self.ensure_session():
            return None

        url = f"{self.base_url}{endpoint}"
        headers = self._headers(with_session=True)
        if "headers" in kwargs:
            headers.update(kwargs.pop("headers"))

        try:
            resp = requests.request(method, url, headers=headers, timeout=kwargs.pop("timeout", 15), **kwargs)
            if resp.status_code == 401:
                # انتهت الجلسة، نجدد لمرة واحدة
                log.info("رمز الجلسة منتهي (401)، إعادة تسجيل الدخول...")
                if self.ensure_session(force=True):
                    headers = self._headers(with_session=True)
                    resp = requests.request(method, url, headers=headers, timeout=15, **kwargs)
            return resp
        except Exception as e:
            log.error(f"خطأ أثناء طلب {endpoint}: {e}")
            return None

    # ── 1. بيانات الحساب ──────────────────────────────────────────

    def get_account_details(self) -> Optional[Dict[str, Any]]:
        """جلب الرصيد، الهامش المتاح، والأرباح/الخسائر العائمة."""
        resp = self._request("GET", "/accounts")
        if not resp or resp.status_code != 200:
            return None
        data = resp.json()
        accounts = data.get("accounts", [])
        if not accounts:
            return None
        acc = accounts[0]
        bal = acc.get("balance", {})
        return {
            "account_id": acc.get("accountId"),
            "account_name": acc.get("accountName"),
            "status": acc.get("status"),
            "balance": float(bal.get("balance", 0.0)),
            "deposit": float(bal.get("deposit", 0.0)),
            "available": float(bal.get("available", 0.0)),
            "profit_loss": float(bal.get("profitLoss", 0.0)),
            "currency": acc.get("currency", "USD"),
        }

    # ── 2. بيانات السوق والأسعار ─────────────────────────────────

    def get_market_info(self, epic: str = config.EPIC) -> Optional[Dict[str, Any]]:
        """جلب تفاصيل وقواعد التداول والسعر اللحظي للأصل."""
        resp = self._request("GET", f"/markets/{epic}")
        if not resp or resp.status_code != 200:
            return None
        data = resp.json()
        inst = data.get("instrument", {})
        rules = data.get("dealingRules", {})
        snap = data.get("snapshot", {})

        return {
            "epic": epic,
            "name": inst.get("name", epic),
            "status": snap.get("marketStatus"),
            "bid": float(snap.get("bid", 0.0)),
            "offer": float(snap.get("offer", 0.0)),
            "spread": round(float(snap.get("offer", 0.0)) - float(snap.get("bid", 0.0)), 2),
            "min_deal_size": float(rules.get("minDealSize", {}).get("value", 0.0001)),
            "min_size_increment": float(rules.get("minSizeIncrement", {}).get("value", 0.0001)),
            "min_stop_distance": float(rules.get("minStopOrProfitDistance", {}).get("value", 0.0)),
            "trailing_stop_available": rules.get("trailingStopsPreference") != "NOT_AVAILABLE",
        }

    def get_sentiment(self, epic: str = config.EPIC) -> Optional[Dict[str, float]]:
        """معنويات المتداولين (Sentiment) الحقيقية من Capital.com."""
        resp = self._request("GET", f"/clientsentiment/{epic}")
        if not resp or resp.status_code != 200:
            return None
        data = resp.json()
        return {
            "long_pct": float(data.get("longPositionPercentage", 50.0)),
            "short_pct": float(data.get("shortPositionPercentage", 50.0)),
        }

    def get_prices(
        self,
        epic: str = config.EPIC,
        resolution: str = "HOUR_4",
        max_candles: int = 100,
        closed_only: bool = True,
    ) -> List[Dict[str, Any]]:
        """جلب شموع الأسعار (MINUTE, MINUTE_5, MINUTE_15, HOUR, HOUR_4, DAY).

        closed_only=True يستبعد الشمعة الجارية غير المكتملة حتى لا تُبنى الإشارات
        على سعر لحظي متغيّر (يطابق منطق الباكتست على شموع مغلقة).
        """
        resp = self._request("GET", f"/prices/{epic}?resolution={resolution}&max={max_candles}")
        if not resp or resp.status_code != 200:
            return []
        data = resp.json()
        raw_prices = data.get("prices", [])
        period = _RESOLUTION_SECONDS.get(resolution.upper())
        now = datetime.now(timezone.utc)

        candles = []
        for p in raw_prices:
            # أسعار الإغلاق والافتتاح والمتوسط
            c = p.get("closePrice", {})
            o = p.get("openPrice", {})
            h = p.get("highPrice", {})
            l = p.get("lowPrice", {})
            start = _candle_start_utc(p.get("snapshotTimeUTC"))
            if closed_only and period and start is not None:
                if start + timedelta(seconds=period) > now:
                    continue
            candles.append({
                "time": p.get("snapshotTime"),
                "time_utc": p.get("snapshotTimeUTC"),
                "open": float(o.get("bid", 0.0) or o.get("ask", 0.0)),
                "high": float(h.get("bid", 0.0) or h.get("ask", 0.0)),
                "low": float(l.get("bid", 0.0) or l.get("ask", 0.0)),
                "close": float(c.get("bid", 0.0) or c.get("ask", 0.0)),
                "volume": float(p.get("lastTradedVolume", 1.0)),
            })
        return candles

    # ── 3. إدارة وتنفيذ الصفقات ───────────────────────────────────

    def get_open_positions(self, epic: Optional[str] = config.EPIC) -> List[Dict[str, Any]]:
        """جلب الصفقات المفتوحة حالياً."""
        resp = self._request("GET", "/positions")
        if not resp or resp.status_code != 200:
            return []
        data = resp.json()
        items = data.get("positions", [])
        res = []
        for item in items:
            pos = item.get("position", {})
            mkt = item.get("market", {})
            if epic and pos.get("epic") != epic:
                continue
            res.append({
                "deal_id": pos.get("dealId"),
                "epic": pos.get("epic"),
                "direction": pos.get("direction"),  # BUY | SELL
                "size": float(pos.get("size", 0.0)),
                "level": float(pos.get("level", 0.0)),  # entry price
                "stop_level": float(pos.get("stopLevel") or 0.0),
                "profit_level": float(pos.get("profitLevel") or 0.0),
                "upl": float(pos.get("upl", 0.0)),  # Unrealized PnL
                "created_date": pos.get("createdDate"),
                "current_price": float(mkt.get("bid", 0.0) if pos.get("direction") == "BUY" else mkt.get("offer", 0.0)),
            })
        return res

    def open_position(
        self,
        direction: str,
        size: float,
        epic: str = config.EPIC,
        stop_level: Optional[float] = None,
        profit_level: Optional[float] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """فتح صفقة سوق مع تأكيد التنفيذ."""
        direction = direction.upper()
        if direction not in ("BUY", "SELL"):
            return False, "الاتجاه يجب أن يكون BUY أو SELL", None

        # جلب معلومات السوق للتحقق من الحدود
        mkt = self.get_market_info(epic)
        if not mkt:
            return False, "تعذر جلب معلومات السوق للتأكد من الأسعار", None

        min_deal = mkt["min_deal_size"]
        if size < min_deal:
            size = min_deal

        payload: Dict[str, Any] = {
            "epic": epic,
            "direction": direction,
            "size": size,
            "guaranteedStop": False,
            "trailingStop": False,
        }

        if stop_level:
            payload["stopLevel"] = round(stop_level, 2)
        if profit_level:
            payload["profitLevel"] = round(profit_level, 2)

        resp = self._request("POST", "/positions", json=payload)
        if not resp:
            return False, "فشل الاتصال بخادم كابيتال لفتح الصفقة", None

        if resp.status_code not in (200, 201):
            return False, f"رفضت المنصة الأمر ({resp.status_code}): {resp.text}", None

        data = resp.json()
        deal_ref = data.get("dealReference")
        if not deal_ref:
            return False, "لم يتم استلام dealReference من المنصة", None

        # تأكيد التنفيذ عبر GET /confirms/{dealReference}
        confirm = self._confirm_deal(deal_ref)
        if confirm and confirm.get("status") == "SUCCESS":
            affected = confirm.get("affectedDeals", [])
            real_deal_id = affected[0].get("dealId") if affected else deal_ref
            return True, f"تم فتح الصفقة بنجاح (معرف: {real_deal_id})", {
                "deal_id": real_deal_id,
                "deal_reference": deal_ref,
                "direction": direction,
                "size": size,
                "level": confirm.get("level"),
                "stop_level": stop_level,
                "profit_level": profit_level,
            }
        else:
            reason = confirm.get("reason", "UNKNOWN") if confirm else "timeout"
            return False, f"فشل تأكيد تنفيذ الصفقة في المنصة: {reason}", None

    def _confirm_deal(self, deal_reference: str, max_retries: int = 5) -> Optional[Dict[str, Any]]:
        """التحقق من حالة تنفيذ الأمر عبر dealReference."""
        for _ in range(max_retries):
            time.sleep(0.5)
            resp = self._request("GET", f"/confirms/{deal_reference}")
            if resp and resp.status_code == 200:
                data = resp.json()
                if data.get("status"):
                    return data
        return None

    def update_position(
        self,
        deal_id: str,
        stop_level: Optional[float] = None,
        profit_level: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """تعديل وقف الخسارة أو الهدف لصفقة قائمة (Break-Even أو Trailing Stop)."""
        payload: Dict[str, Any] = {}
        if stop_level is not None:
            payload["stopLevel"] = round(stop_level, 2)
        if profit_level is not None:
            payload["profitLevel"] = round(profit_level, 2)

        if not payload:
            return False, "لا توجد حقول لتعديلها"

        resp = self._request("PUT", f"/positions/{deal_id}", json=payload)
        if not resp or resp.status_code != 200:
            msg = resp.text if resp else "لا يوجد استجابة"
            return False, f"فشل تعديل الصفقة: {msg}"

        return True, "تم تعديل الصفقة بنجاح"

    def close_position(self, deal_id: str) -> Tuple[bool, str]:
        """إغلاق صفقة قائمة بالكامل."""
        resp = self._request("DELETE", f"/positions/{deal_id}")
        if not resp or resp.status_code != 200:
            msg = resp.text if resp else "لا يوجد استجابة"
            return False, f"فشل إغلاق الصفقة: {msg}"
        return True, "تم إغلاق الصفقة بنجاح"

# كائن مشترك للاستخدام في كافة ملفات المشروع
client = CapitalClient()
