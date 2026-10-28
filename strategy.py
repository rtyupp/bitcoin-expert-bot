"""Strategy Module: Validated 4H Institutional Edge for GBP/USD, Gold, and Silver."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Tuple
import numpy as np
import pandas as pd
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.volatility import AverageTrueRange, DonchianChannel, BollingerBands
from ta.momentum import RSIIndicator

import config


@dataclass
class AssetSignal:
    asset: str
    spec_id: str
    side: int  # 1 = BUY, -1 = SELL
    price: float
    stop_level: float
    target_level: float
    time: str
    reasons: List[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


def compute_atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"].astype(float), df["low"].astype(float), df["close"].astype(float)
    return AverageTrueRange(h, l, c, n).average_true_range()


def compute_adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"].astype(float), df["low"].astype(float), df["close"].astype(float)
    return ADXIndicator(h, l, c, n).adx()


def compute_er(df: pd.DataFrame, n: int = 16) -> pd.Series:
    c = df["close"].astype(float)
    change = (c - c.shift(n)).abs()
    volatility = (c - c.shift(1)).abs().rolling(n).sum()
    return change / (volatility + 1e-9)


def compute_volume_ratio(df: pd.DataFrame, n: int = 20) -> pd.Series:
    vol = df["volume"].astype(float)
    vol_ma = vol.rolling(n).mean()
    return vol / (vol_ma + 1e-9)


def compute_macd(df: pd.DataFrame) -> Tuple[pd.Series, pd.Series, pd.Series]:
    m = MACD(df["close"].astype(float))
    return m.macd(), m.macd_signal(), m.macd_diff()


def compute_ema(df: pd.DataFrame, period: int) -> pd.Series:
    return EMAIndicator(df["close"].astype(float), period).ema_indicator()


def compute_donchian(df: pd.DataFrame, n: int = 20) -> Tuple[pd.Series, pd.Series]:
    h, l, c = df["high"].astype(float), df["low"].astype(float), df["close"].astype(float)
    dc = DonchianChannel(h, l, c, n)
    return dc.donchian_channel_hband().shift(1), dc.donchian_channel_lband().shift(1)


def detect_regime(df_4h: pd.DataFrame) -> Tuple[str, dict]:
    if len(df_4h) < 50:
        return "UNKNOWN", {}

    adx_series = compute_adx(df_4h, 14)
    er_series = compute_er(df_4h, 16)
    ema20_series = compute_ema(df_4h, 20)
    ema50_series = compute_ema(df_4h, 50)
    ema200_series = compute_ema(df_4h, 200)

    adx = adx_series.iloc[-1]
    er = er_series.iloc[-1]
    ema20 = ema20_series.iloc[-1]
    ema50 = ema50_series.iloc[-1]
    ema200 = ema200_series.iloc[-1]
    close = df_4h["close"].iloc[-1]

    metrics = {
        "adx": round(float(adx), 1) if not np.isnan(adx) else 0,
        "er": round(float(er), 3) if not np.isnan(er) else 0,
        "ema20": float(ema20),
        "ema50": float(ema50),
        "ema200": float(ema200),
        "close": float(close),
    }

    if np.isnan(adx) or np.isnan(er):
        return "UNKNOWN", metrics

    if close > ema200 and ema20 > ema50 and er >= 0.25:
        return "TRENDING_UP", metrics
    elif close < ema200 and ema20 < ema50 and er >= 0.25:
        return "TRENDING_DOWN", metrics
    elif er < 0.20 and adx < 20:
        return "RANGING", metrics
    else:
        return "CHOPPY", metrics


def scan_donchian20_vol15(df_4h: pd.DataFrame, asset_cfg: dict) -> List[AssetSignal]:
    signals: List[AssetSignal] = []
    if len(df_4h) < 50:
        return signals

    dc_upper, dc_lower = compute_donchian(df_4h, 20)
    atr = compute_atr(df_4h, 14)
    vol_ratio = compute_volume_ratio(df_4h, 20)
    regime, metrics = detect_regime(df_4h)

    if regime not in ("TRENDING_UP", "TRENDING_DOWN"):
        return signals

    i = -2
    close = df_4h["close"].iloc[i]
    vol_r = vol_ratio.iloc[i]
    atr_v = atr.iloc[i]

    if np.isnan(atr_v) or atr_v <= 0 or np.isnan(vol_r):
        return signals

    rr = asset_cfg["rr"]
    stop_mult = asset_cfg["stop_mult"]
    vol_thresh = asset_cfg["volume_mult"]
    decimals = asset_cfg["decimals"]

    if close > dc_upper.iloc[i] and vol_r > vol_thresh:
        entry = close
        stop = entry - stop_mult * atr_v
        target = entry + rr * stop_mult * atr_v
        signals.append(AssetSignal(
            asset=asset_cfg["epic"],
            spec_id="donchian20_vol15",
            side=1,
            price=round(entry, decimals),
            stop_level=round(stop, decimals),
            target_level=round(target, decimals),
            time=str(df_4h["ts"].iloc[i]),
            reasons=[
                f"Donchian 20 Breakout UP ({entry:.5f} > {dc_upper.iloc[i]:.5f})",
                f"Volume Confirmation: {vol_r:.2f}x (Threshold {vol_thresh}x)",
                f"Regime: {regime} (ADX={metrics['adx']}, ER={metrics['er']})",
            ],
            meta={**metrics, "atr": round(float(atr_v), decimals), "vol_ratio": round(float(vol_r), 2)}
        ))
    elif close < dc_lower.iloc[i] and vol_r > vol_thresh:
        entry = close
        stop = entry + stop_mult * atr_v
        target = entry - rr * stop_mult * atr_v
        signals.append(AssetSignal(
            asset=asset_cfg["epic"],
            spec_id="donchian20_vol15",
            side=-1,
            price=round(entry, decimals),
            stop_level=round(stop, decimals),
            target_level=round(target, decimals),
            time=str(df_4h["ts"].iloc[i]),
            reasons=[
                f"Donchian 20 Breakout DOWN ({entry:.5f} < {dc_lower.iloc[i]:.5f})",
                f"Volume Confirmation: {vol_r:.2f}x (Threshold {vol_thresh}x)",
                f"Regime: {regime} (ADX={metrics['adx']}, ER={metrics['er']})",
            ],
            meta={**metrics, "atr": round(float(atr_v), decimals), "vol_ratio": round(float(vol_r), 2)}
        ))

    return signals


def scan_macd_ema200(df_4h: pd.DataFrame, asset_cfg: dict) -> List[AssetSignal]:
    signals: List[AssetSignal] = []
    if len(df_4h) < 50:
        return signals

    macd_line, signal_line, _ = compute_macd(df_4h)
    ema200 = compute_ema(df_4h, 200)
    atr = compute_atr(df_4h, 14)
    regime, metrics = detect_regime(df_4h)

    if regime not in ("TRENDING_UP", "TRENDING_DOWN"):
        return signals

    i = -2
    close = df_4h["close"].iloc[i]
    atr_v = atr.iloc[i]
    macd_curr = macd_line.iloc[i]
    macd_prev = macd_line.iloc[i-1]
    sig_curr = signal_line.iloc[i]
    sig_prev = signal_line.iloc[i-1]
    ema200_v = ema200.iloc[i]

    if np.isnan(atr_v) or atr_v <= 0 or np.isnan(macd_curr) or np.isnan(sig_curr) or np.isnan(ema200_v):
        return signals

    rr = asset_cfg["rr"]
    stop_mult = asset_cfg["stop_mult"]
    decimals = asset_cfg["decimals"]

    if macd_prev <= sig_prev and macd_curr > sig_curr and close > ema200_v:
        entry = close
        stop = entry - stop_mult * atr_v
        target = entry + rr * stop_mult * atr_v
        signals.append(AssetSignal(
            asset=asset_cfg["epic"],
            spec_id="macd_ema200",
            side=1,
            price=round(entry, decimals),
            stop_level=round(stop, decimals),
            target_level=round(target, decimals),
            time=str(df_4h["ts"].iloc[i]),
            reasons=[
                f"MACD Bullish Cross: {macd_curr:.5f} > {sig_curr:.5f}",
                f"Macro Filter: Close {close:.2f} > EMA200 {ema200_v:.2f}",
                f"Regime: {regime} (ADX={metrics['adx']}, ER={metrics['er']})",
            ],
            meta={**metrics, "atr": round(float(atr_v), decimals)}
        ))
    elif macd_prev >= sig_prev and macd_curr < sig_curr and close < ema200_v:
        entry = close
        stop = entry + stop_mult * atr_v
        target = entry - rr * stop_mult * atr_v
        signals.append(AssetSignal(
            asset=asset_cfg["epic"],
            spec_id="macd_ema200",
            side=-1,
            price=round(entry, decimals),
            stop_level=round(stop, decimals),
            target_level=round(target, decimals),
            time=str(df_4h["ts"].iloc[i]),
            reasons=[
                f"MACD Bearish Cross: {macd_curr:.5f} < {sig_curr:.5f}",
                f"Macro Filter: Close {close:.2f} < EMA200 {ema200_v:.2f}",
                f"Regime: {regime} (ADX={metrics['adx']}, ER={metrics['er']})",
            ],
            meta={**metrics, "atr": round(float(atr_v), decimals)}
        ))

    return signals


def scan_bb_rsi_reversion(df_4h: pd.DataFrame, asset_cfg: dict) -> List[AssetSignal]:
    signals: List[AssetSignal] = []
    if len(df_4h) < 50:
        return signals

    c = df_4h["close"].astype(float)
    h = df_4h["high"].astype(float)
    l = df_4h["low"].astype(float)

    bb = BollingerBands(c, 20, 2.5)
    bb_upper = bb.bollinger_hband()
    bb_lower = bb.bollinger_lband()
    rsi_series = RSIIndicator(c, 14).rsi()
    adx_series = compute_adx(df_4h, 14)
    atr = compute_atr(df_4h, 14)
    atr_p90 = atr.rolling(100).quantile(0.90)
    regime, metrics = detect_regime(df_4h)

    i = -2
    close = c.iloc[i]
    high = h.iloc[i]
    low = l.iloc[i]
    atr_v = atr.iloc[i]
    atr_cap = atr_p90.iloc[i]
    rsi_v = rsi_series.iloc[i]
    adx_v = adx_series.iloc[i]
    bb_u = bb_upper.iloc[i]
    bb_l = bb_lower.iloc[i]

    # Hummingbot risk rule: ignore entries during extreme volatility spikes (>90th percentile ATR)
    if np.isnan(atr_v) or atr_v <= 0 or np.isnan(rsi_v) or np.isnan(adx_v) or adx_v >= 30:
        return signals
    if not np.isnan(atr_cap) and atr_v > atr_cap:
        return signals

    rr = asset_cfg["rr"]
    stop_mult = asset_cfg["stop_mult"]
    decimals = asset_cfg["decimals"]

    # Bullish Extreme Reversion: low pierced lower BB 2.5, closed back inside, RSI < 35
    if low <= bb_l and close > bb_l and rsi_v < 35:
        entry = close
        stop = entry - stop_mult * atr_v
        target = entry + rr * stop_mult * atr_v
        signals.append(AssetSignal(
            asset=asset_cfg["epic"],
            spec_id="bb_rsi_reversion",
            side=1,
            price=round(entry, decimals),
            stop_level=round(stop, decimals),
            target_level=round(target, decimals),
            time=str(df_4h["ts"].iloc[i]),
            reasons=[
                f"Bollinger Extreme Bounce: Low touched {bb_l:.2f} and closed at {close:.2f}",
                f"RSI Oversold Rebound: RSI={rsi_v:.1f} (<35)",
                f"Non-trending Filter: ADX={adx_v:.1f} (<30)",
            ],
            meta={**metrics, "atr": round(float(atr_v), decimals), "rsi": round(float(rsi_v), 1), "adx": round(float(adx_v), 1)}
        ))
    # Bearish Extreme Reversion: high pierced upper BB 2.5, closed back inside, RSI > 65
    elif high >= bb_u and close < bb_u and rsi_v > 65:
        entry = close
        stop = entry + stop_mult * atr_v
        target = entry - rr * stop_mult * atr_v
        signals.append(AssetSignal(
            asset=asset_cfg["epic"],
            spec_id="bb_rsi_reversion",
            side=-1,
            price=round(entry, decimals),
            stop_level=round(stop, decimals),
            target_level=round(target, decimals),
            time=str(df_4h["ts"].iloc[i]),
            reasons=[
                f"Bollinger Extreme Rejection: High touched {bb_u:.2f} and closed at {close:.2f}",
                f"RSI Overbought Reversal: RSI={rsi_v:.1f} (>65)",
                f"Non-trending Filter: ADX={adx_v:.1f} (<30)",
            ],
            meta={**metrics, "atr": round(float(atr_v), decimals), "rsi": round(float(rsi_v), 1), "adx": round(float(adx_v), 1)}
        ))

    return signals


STRATEGY_SCANNERS = {
    "donchian20_vol15": scan_donchian20_vol15,
    "macd_ema200": scan_macd_ema200,
    "bb_rsi_reversion": scan_bb_rsi_reversion,
}


def calculate_position_size(asset: str, entry_price: float, stop_loss_price: float, risk_pct: float = 8.0) -> float:
    from capital import client
    acc = client.account_summary()
    available_balance = float(acc.get("available") or 1000.0)
    # Small account dynamic scaling: minimum $2.00 risk to prevent micro-penny trading
    risk_amount = max(2.0, available_balance * (risk_pct / 100.0))
    stop_distance = abs(entry_price - stop_loss_price)
    min_size = config.ASSETS[asset]["min_deal"]

    if stop_distance <= 0:
        return min_size

    raw_size = risk_amount / stop_distance
    if asset in ("GBPUSD",):
        return max(min_size, round(raw_size, 0))
    elif asset in ("GOLD", "US500"):
        return max(min_size, round(raw_size, 2))
    elif asset == "SILVER":
        return max(min_size, round(raw_size, 1))
    elif asset == "BTCUSD":
        return max(min_size, round(raw_size, 4))
    elif asset == "ETHUSD":
        return max(min_size, round(raw_size, 3))
    return max(min_size, round(raw_size, 2))


def check_exit(asset: str, spec_id: str, side: int, entry: float, stop: float,
               peak: float, current_close: float, atr: float, entry_candle: str, last_candle: str) -> str | None:
    if asset == "GBPUSD":
        if side == 1 and atr > 0 and current_close < peak - 4.0 * atr:
            return "إغلاق تحت القمة بمقدار 4×ATR (شاندلير)"
        if side == -1 and atr > 0 and current_close > peak + 4.0 * atr:
            return "إغلاق فوق القاع بمقدار 4×ATR (شاندلير)"
    else:
        if side == 1 and atr > 0 and current_close < entry - 2.0 * atr:
            return "إغلاق تحت الدخول بمقدار 2×ATR"
        if side == -1 and atr > 0 and current_close > entry + 2.0 * atr:
            return "إغلاق فوق الدخول بمقدار 2×ATR"
    return None


def get_asset_summary(df_4h: pd.DataFrame, asset_cfg: dict) -> dict:
    if len(df_4h) < 50:
        return {"error": "بيانات غير كافية"}

    regime, metrics = detect_regime(df_4h)
    close = df_4h["close"].iloc[-1]
    atr = compute_atr(df_4h, 14).iloc[-1]
    decimals = asset_cfg["decimals"]

    extra = {}
    if asset_cfg["strategy"] == "donchian20_vol15":
        dc_upper, dc_lower = compute_donchian(df_4h, 20)
        vol_r = compute_volume_ratio(df_4h, 20).iloc[-1]
        extra = {
            "dc_upper": round(float(dc_upper.iloc[-1]), decimals),
            "dc_lower": round(float(dc_lower.iloc[-1]), decimals),
            "vol_ratio": round(float(vol_r), 2),
            "vol_threshold": asset_cfg["volume_mult"],
        }
    elif asset_cfg["strategy"] == "macd_ema200":
        m_line, s_line, hist = compute_macd(df_4h)
        e200 = compute_ema(df_4h, 200).iloc[-1]
        extra = {
            "macd": round(float(m_line.iloc[-1]), 5),
            "signal": round(float(s_line.iloc[-1]), 5),
            "histogram": round(float(hist.iloc[-1]), 5),
            "ema200": round(float(e200), decimals),
        }
    elif asset_cfg["strategy"] == "bb_rsi_reversion":
        bb = BollingerBands(df_4h["close"].astype(float), 20, 2.5)
        rsi_series = RSIIndicator(df_4h["close"].astype(float), 14).rsi()
        extra = {
            "bb_upper": round(float(bb.bollinger_hband().iloc[-1]), decimals),
            "bb_lower": round(float(bb.bollinger_lband().iloc[-1]), decimals),
            "rsi": round(float(rsi_series.iloc[-1]), 1),
        }

    return {
        "asset": asset_cfg["name"],
        "epic": asset_cfg["epic"],
        "price": round(float(close), decimals),
        "regime": regime,
        "atr": round(float(atr), decimals) if not np.isnan(atr) else 0,
        "adx": metrics.get("adx", 0),
        "er": metrics.get("er", 0),
        "strategy": asset_cfg["strategy"],
        **extra,
    }
