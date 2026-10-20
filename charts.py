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

    buy_idx = np.where(breakout_buy.values)[0]
    sell_idx = np.where(breakout_short.values)[0]
    buy_last = int(buy_idx[-1]) if len(buy_idx) else -1
    sell_last = int(sell_idx[-1]) if len(sell_idx) else -1
    direction = None
    idx = -1
    if buy_last > sell_last:
        direction, idx = "buy", buy_last
    elif sell_last > buy_last:
        direction, idx = "sell", sell_last

    events = {
        "current_price": float(c.iloc[-1]),
        "current_ts": df["ts"].iloc[-1],
        "first_entry": None,
        "second_entry": None,
        "stop_loss": None,
        "tp1": None,
        "tp2": None,
        "direction": direction,
        "signal_age_hours": None,
    }

    if idx < 0 or idx >= len(df) - 1:
        return events

    d = 1 if direction == "buy" else -1
    entry = float(c.iloc[idx])
    sd = float(atr.iloc[idx]) * 2
    events["first_entry"] = {
        "idx": int(idx),
        "price": entry,
        "ts": df["ts"].iloc[idx],
        "type": "breakout",
    }
    events["stop_loss"] = entry - d * sd
    events["tp1"] = entry + d * sd          # 1:1
    events["tp2"] = entry + d * 2 * sd      # 1:2
    events["signal_age_hours"] = int(
        (df["ts"].iloc[-1] - df["ts"].iloc[idx]).total_seconds() / 3600
    )

    # الصيد الثاني: رجعة للمتوسط (MA20) بعد الكسر
    for j in range(idx + 1, min(idx + 12, len(df))):
        if direction == "buy" and c.iloc[j] <= mid.iloc[j]:
            events["second_entry"] = {
                "idx": int(j),
                "price": float(c.iloc[j]),
                "ts": df["ts"].iloc[j],
                "type": "pullback",
            }
            break
        if direction == "sell" and c.iloc[j] >= mid.iloc[j]:
            events["second_entry"] = {
                "idx": int(j),
                "price": float(c.iloc[j]),
                "ts": df["ts"].iloc[j],
                "type": "pullback",
            }
            break

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

    ax_price.set_ylabel("السعر (USDT)", color="#bdbdbd", fontsize=9)
    ax_price.tick_params(colors="#bdbdbd")
    ax_price.legend(loc="upper left", fontsize=7, framealpha=0.25, labelcolor="#f7f7f7")
    ax_price.grid(alpha=0.15)

    # رسم نقاط الصيد
    if analysis["first_entry"]:
        fe = analysis["first_entry"]
        color = "#69f0ae" if analysis["direction"] == "buy" else "#ffab40"
        mk = "^" if analysis["direction"] == "buy" else "v"
        ax_price.scatter(fe["ts"], fe["price"], s=120, c=color, marker=mk, zorder=6, edgecolors="black", linewidths=1.2, label="أول صيد")
        ax_price.annotate(f"أول صيد {fe['price']:,.0f}", (fe["ts"], fe["price"]),
                          textcoords="offset points", xytext=(0, 14 if analysis["direction"] == "buy" else -22),
                          fontsize=8, color="white", ha="center")

    if analysis["second_entry"]:
        se = analysis["second_entry"]
        ax_price.scatter(se["ts"], se["price"], s=100, c="#ffd700", marker="o", zorder=6, edgecolors="black", linewidths=1.2, label="ثاني صيد")
        ax_price.annotate(f"ثاني صيد {se['price']:,.0f}", (se["ts"], se["price"]),
                          textcoords="offset points", xytext=(0, 14 if analysis["direction"] == "buy" else -22),
                          fontsize=8, color="white", ha="center")

    if analysis["stop_loss"]:
        ax_price.axhline(analysis["stop_loss"], color="#ef5350", ls=":", lw=1.2, alpha=0.8)
        ax_price.text(df["ts"].iloc[-1], analysis["stop_loss"], f" وقف {analysis['stop_loss']:,.0f}",
                      color="#ef5350", fontsize=7, va="center", ha="right")

    if analysis["tp1"]:
        tpcol = "#69f0ae" if analysis["direction"] == "buy" else "#ffab40"
        ax_price.axhline(analysis["tp1"], color=tpcol, ls=":", lw=1.2, alpha=0.8)
        ax_price.text(df["ts"].iloc[-1], analysis["tp1"], f" هدف1 {analysis['tp1']:,.0f}",
                      color=tpcol, fontsize=7, va="center", ha="right")

    # السعر الأخير
    plt.setp(ax_price.xaxis.get_majorticklabels(), visible=False)
    ax_price.set_title(f"{symbol} — شارت 4 ساعات", color="#f7f7f7", fontsize=11)
    last = float(c.iloc[-1])
    chg = (last / float(c.iloc[-2]) - 1) * 100
    ax_price.text(0.01, 0.02, f"{last:,.0f} USDT  ({chg:+.2f}%)",
                  transform=ax_price.transAxes, color="#f7f7f7", fontsize=9,
                  va="bottom", bbox=dict(boxstyle="round", facecolor="#212121", alpha=0.8))

    # الحجم
    ax_vol.bar(df["ts"], v, color="#78909c", alpha=0.7)
    ax_vol.set_ylabel("الحجم", color="#bdbdbd", fontsize=9)
    ax_vol.tick_params(colors="#bdbdbd")
    ax_vol.grid(alpha=0.15)

    for ax in axes:
        ax.set_facecolor("#121212")
    fig.set_facecolor("#121212")

    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=110, facecolor="#121212", edgecolor="none", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def short_message(analysis: dict, symbol: str) -> str:
    """رسالة موجزة وواضحة بصيغة HTML (متوافقة مع ParseMode.HTML)."""
    if not analysis["first_entry"]:
        return (
            f"📊 <b>{symbol}</b>\n\n"
            "لا توجد إشارة صيد حالياً.\n"
            "انتظر كسر بولينجر مع حجم >= 1.5x."
        )

    d = analysis["direction"]
    fe = analysis["first_entry"]
    se = analysis["second_entry"]
    age = analysis["signal_age_hours"]

    head = f"{'🟢' if d == 'buy' else '🔴'} <b>{symbol} — إشارة {'شراء' if d == 'buy' else 'بيع'}</b>"
    lines = [head, ""]
    lines.append(f"📍 <b>أول صيد:</b> <code>{fe['price']:,.0f}</code> ({fe['type']})")
    if se:
        lines.append(f"📍 <b>ثاني صيد:</b> <code>{se['price']:,.0f}</code> ({se['type']})")
    lines.append(f"🛑 <b>وقف:</b> <code>{analysis['stop_loss']:,.0f}</code>")
    lines.append(f"🎯 <b>هدف 1:</b> <code>{analysis['tp1']:,.0f}</code>")
    if age is not None and age >= 6:
        lines.append(f"⏳ عمر الإشارة: {age} ساعة")
    lines.append("")
    lines.append(f"💰 الحالي: <code>{analysis['current_price']:,.0f}</code>")
    lines.append("⚠️ <i>تحليل تعليمي — مو نصيحة مالية.</i>")
    return "\n".join(lines)