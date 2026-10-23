"""توليد ورسم الشارت الاحترافي للبيتكوين بالشموع اليابانية ونقاط الدخول والمؤشرات."""
from __future__ import annotations

import io
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
from typing import Optional

from capital_trader import client

def generate_chart_image(resolution: str = "HOUR_4", num_candles: int = 40) -> bytes:
    """بناء صورة PNG لرسم الشموع اليابانية والمتوسطات الفنية مباشرة من كابيتال."""
    candles = client.get_prices("BTCUSD", resolution=resolution, max_candles=num_candles)
    if not candles:
        # شارت فارغ في حال تعذر الاتصال
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.text(0.5, 0.5, "تعذر تحميل بيانات الشارت", horizontalalignment="center")
        buf = io.BytesIO()
        plt.savefig(buf, format="png")
        plt.close(fig)
        return buf.getvalue()

    df = pd.DataFrame(candles)
    df["time"] = pd.to_datetime(df["time"])
    df.set_index("time", inplace=True)
    df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}, inplace=True)

    # حساب المتوسطات
    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()

    plots = [
        mpf.make_addplot(df["EMA20"], color="#2962FF", width=1.2),
        mpf.make_addplot(df["EMA50"], color="#FF6D00", width=1.2),
    ]

    mc = mpf.make_marketcolors(up="#089981", down="#F23645", edge="inherit", wick="inherit", volume="in")
    s = mpf.make_mpf_style(marketcolors=mc, gridstyle=":", gridcolor="#2B2B43", facecolor="#131722", edgecolor="#131722", figcolor="#131722", y_on_right=True)

    buf = io.BytesIO()
    mpf.plot(
        df,
        type="candle",
        style=s,
        addplot=plots,
        figsize=(10, 5),
        savefig=dict(fname=buf, dpi=120, bbox_inches="tight", format="png")
    )
    plt.close("all")
    buf.seek(0)
    return buf.getvalue()
