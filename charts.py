"""رسم شارتات التحليل مع تحديد نقاط الصيد (أول/ثاني)."""
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import io
from datetime import datetime

import ccxt
import ta


def fetch_4h(symbol: str, days: int = 30):
    """جلب بيانات 4h."""
    ex = ccxt.binance()
    limit = min(days * 6, 1500)
    raw = ex.fetch_ohlcv(symbol, "4h", limit=limit)
    df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms")
    return df


def analyze_chart(df: pd.DataFrame) -> dict:
    """تحليل الرسم البياني وإرجاع نقاط الصيد."""
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    atr = ta.volatility.AverageTrueRange(h, l, c, 14).average_true_range()
    bb = ta.volatility.BollingerBands(c, 20, 2)
    up, mid, lo = bb.bollinger_hband(), bb.bollinger_mavg(), bb.bollinger_lband()
    vol20 = v.rolling(20).mean()

    # الإشارة: كسر أعلى/أدنى بولينجر + حجم
    breakout_buy = (c > up) & (v > 1.5 * vol20)
    breakout_short = (c < lo) & (v > 1.5 * vol20)

    events = {
        "symbol": "unknown",
        "current_price": float(c.iloc[-1]),
        "current_ts": df["ts"].iloc[-1],
        "first_entry": None,
        "second_entry": None,
        "stop_loss": None,
        "risk_reward": None,
        "direction": None,
    }

    if breakout_buy.any():
        idx = breakout_buy[breakout_buy].index[0]
        entry_px = float(c.iloc[idx])
        stop = float(entry_px - 2 * atr.iloc[idx])
        target = float(entry_px + 2 * atr.iloc[idx])  # TP1
        events["first_entry"] = {
            "idx": int(idx),
            "price": entry_px,
            "type": "breakout",
        }
        # الصيد الثاني: pullback للـ MA20 أو دعم
        for j in range(idx + 2, min(idx + 10, len(df) - 1)):
            if c.iloc[j] < mid.iloc[j] and v.iloc[j] > vol20.iloc[j]:
                events["second_entry"] = {
                    "idx": int(j),
                    "price": float(mid.iloc[j] * 0.995),
                    "type": "pullback",
                }
                break
        events["stop_loss"] = stop
        events["risk_reward"] = f"1:{2 * atr.iloc[idx] / (entry_px - stop):.1f}" if entry_px > stop else "1:1"
        events["direction"] = "buy"

    elif breakout_short.any():
        idx = breakout_short[breakout_short].index[0]
        entry_px = float(c.iloc[idx])
        stop = float(entry_px + 2 * atr.iloc[idx])
        target = float(entry_px - 2 * atr.iloc[idx])
        events["first_entry"] = {
            "idx": int(idx),
            "price": entry_px,
            "type": "breakout",
        }
        for j in range(idx + 2, min(idx + 10, len(df) - 1)):
            if c.iloc[j] > mid.iloc[j] and v.iloc[j] > vol20.iloc[j]:
                events["second_entry"] = {
                    "idx": int(j),
                    "price": float(mid.iloc[j] * 1.005),
                    "type": "pullback",
                }
                break
        events["stop_loss"] = stop
        events["risk_reward"] = f"1:{2 * atr.iloc[idx] / (stop - entry_px):.1f}" if stop > entry_px else "1:1"
        events["direction"] = "sell"

    return events


def plot_chart(df: pd.DataFrame, analysis: dict, symbol: str) -> bytes:
    """رسم الشارت مع تحديد نقاط الصيد، إرجاع PNG كـ bytes."""
    c = df["close"]
    h, l, v = df["high"], df["low"], df["volume"]
    atr = ta.volatility.AverageTrueRange(h, l, c, 14).average_true_range()
    bb = ta.volatility.BollingerBands(c, 20, 2)
    up, mid, lo = bb.bollinger_hband(), bb.bollinger_mavg(), bb.bollinger_lband()

    fig, axes = plt.subplots(2, 1, figsize=(10, 6), gridspec_kw={"height_ratios": [3, 1]}, sharex=True)
    ax_price, ax_vol = axes

    # السعر
    ax_price.plot(df["ts"], c, color="white", linewidth=1, label="Close")
    ax_price.plot(df["ts"], up, color="cyan", linewidth=0.8, linestyle="--", label="BB Upper")
    ax_price.plot(df["ts"], mid, color="yellow", linewidth=0.8, linestyle="-.", label="BB Mid")
    ax_price.plot(df["ts"], lo, color="red", linewidth=0.8, linestyle="--", label="BB Lower")

    ax_price.set_ylabel("Price (USDT)", color="white", fontsize=9)
    ax_price.tick_params(axis="y", colors="white")
    ax_price.legend(loc="upper left", fontsize=8, framealpha=0.3, labelcolor="white")
    ax_price.grid(alpha=0.2)

    # رسم نقاط الصيد
    if analysis["first_entry"]:
        fe = analysis["first_entry"]
        color = "lime" if analysis["direction"] == "buy" else "orange"
        ax_price.scatter(df["ts"].iloc[fe["idx"]], fe["price"], s=100, c=color, zorder=5, marker="^" if analysis["direction"]=="buy" else "v", label=f"أول صيد {fe['type']}", edgecolors="black")

    if analysis["second_entry"]:
        se = analysis["second_entry"]
        ax_price.scatter(df["ts"].iloc[se["idx"]], se["price"], s=80, c="gold", zorder=5, marker="o", label=f"ثاني صيد {se['type']}", edgecolors="black")

    if analysis["stop_loss"]:
        ax_price.axhline(analysis["stop_loss"], color="red", linestyle=":", alpha=0.7, label=f"SL {analysis['stop_loss']/1000:.1f}k")

    # الفتحة والإغلاق
    plt.setp(ax_price.xaxis.get_majorticklabels(), visible=False)
    ax_price.set_title(f"{symbol} - Entry Signals", color="white", fontsize=10, fontweight="bold")

    # السعر الأخير + مؤشرات
    last = c.iloc[-1]
    chg = (last / c.iloc[-2] - 1) * 100
    ax_price.text(0.02, 0.95, f"{last:,.0f} | {chg:+.2f}% | ATR: {atr.iloc[-1]:.0f}",
                  transform=ax_price.transAxes, color="white", fontsize=9,
                  verticalalignment="top", bbox=dict(boxstyle="round", facecolor="black", alpha=0.5))

    # الريب
    ax_vol.bar(df["ts"], v, color="gray", alpha=0.6)
    ax_vol.set_ylabel("Volume", color="white", fontsize=9)
    ax_vol.tick_params(axis="y", colors="white")
    ax_vol.set_xlabel("Time", color="white", fontsize=9)
    ax_vol.grid(alpha=0.2)
    ax_vol.set_ylim(0, v.max() * 1.5)

    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=100, facecolor="black", edgecolor="none", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def short_message(analysis: dict, symbol: str) -> str:
    """رسالة موجزة وواضحة مع النقاط."""
    if not analysis["first_entry"]:
        return f"📊 لا توجد إشارات صيد واضحة لـ {symbol} حالياً.\nانتظر حالة كسر بولينجر مع حجم كبير."

    lines = [f"📈 **{symbol} - صيد جديد**"]
    if analysis["direction"] == "buy":
        lines.append("🟢 **اتجاه الشراء**")
    else:
        lines.append("🔴 **اتجاه البيع**")

    fe = analysis["first_entry"]
    lines.append(f"\n📍 **أول صيد:** {fe['type']}")
    lines.append(f"   السعر: `{fe['price']:,.2f}`")
    if fe["type"] == "breakout":
        lines.append(f"   الوقت: `{analysis['current_ts'].strftime('%d/%m %H:%M')}`")

    if analysis["second_entry"]:
        se = analysis["second_entry"]
        lines.append(f"\n📍 **ثاني صيد:** {se['type']}")
        lines.append(f"   السعر: `{se['price']:,.2f}`")

    if analysis["stop_loss"]:
        lines.append(f"\n🛑 **وقف الخسارة:** `{analysis['stop_loss']:,.2f}`")

    if analysis["risk_reward"]:
        lines.append(f"\n📊 **نسبة المخاطرة/الربح:** 1:{analysis['risk_reward'].split(':')[1]}")

    lines.append("\n💡 **نصيحة:** استخدم الوقف، وقسم الصفقة على 1-2 نقطة.")
    lines.append("\n⚠️ هذه رسائل تحليلية، ليست موافقة مالية.")

    return "\n".join(lines)