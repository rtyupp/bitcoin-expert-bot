"""Candlestick and Technical Indicator Chart Generator using Pillow."""
from __future__ import annotations

import io
import math
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

import config
import strategy

BG = (18, 18, 24)
GRID = (40, 40, 50)
TEXT = (220, 220, 230)
MUTED = (140, 140, 155)
UP = (76, 217, 100)
DOWN = (255, 82, 82)
EMA20_C = (52, 152, 219)
EMA50_C = (243, 156, 18)
EMA200_C = (155, 89, 182)
DC_C = (100, 100, 120)


def _load_font(size: int):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


def render_asset_chart(asset: str, df: pd.DataFrame, summary: dict) -> bytes:
    asset_cfg = config.ASSETS[asset]
    decimals = asset_cfg["decimals"]

    df = df.tail(60).copy().reset_index(drop=True)
    n = len(df)
    if n < 2:
        return b""

    df["ema20"] = strategy.compute_ema(df, 20)
    df["ema50"] = strategy.compute_ema(df, 50)
    df["ema200"] = strategy.compute_ema(df, 200)

    if asset_cfg["strategy"] == "donchian20_vol15":
        up_dc, low_dc = strategy.compute_donchian(df, 20)
        df["dc_upper"] = up_dc
        df["dc_lower"] = low_dc

    candle_w = 12
    gap = 3
    width = n * (candle_w + gap) + 90
    height = 500
    margin_top = 45
    margin_bottom = 60
    chart_h = height - margin_top - margin_bottom

    highs = float(df["high"].max())
    lows = float(df["low"].min())
    price_range = highs - lows if highs != lows else highs * 0.01

    def y(price: float) -> int:
        return margin_top + int((highs - price) / price_range * chart_h)

    def x(i: int) -> int:
        return 70 + i * (candle_w + gap) + candle_w // 2

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    font = _load_font(11)
    font_big = _load_font(13)
    font_small = _load_font(10)

    for i in range(5):
        yy = margin_top + i * chart_h // 4
        draw.line([(70, yy), (width - 20, yy)], fill=GRID, width=1)
        px = highs - (i / 4) * price_range
        draw.text((5, yy - 7), f"{px:,.{decimals}f}", fill=MUTED, font=font_small)

    if "dc_upper" in df.columns:
        for i in range(n):
            u_val = df["dc_upper"].iloc[i]
            l_val = df["dc_lower"].iloc[i]
            if not (math.isnan(u_val) or math.isnan(l_val)):
                draw.line([(x(i), y(u_val)), (x(i), y(l_val))], fill=DC_C, width=1)

    for i in range(n - 1):
        for col, color in [("ema20", EMA20_C), ("ema50", EMA50_C), ("ema200", EMA200_C)]:
            v1, v2 = df[col].iloc[i], df[col].iloc[i + 1]
            if not (math.isnan(v1) or math.isnan(v2)):
                draw.line([(x(i), y(v1)), (x(i + 1), y(v2))], fill=color, width=2)

    for i in range(n):
        o, h, l, c = df["open"].iloc[i], df["high"].iloc[i], df["low"].iloc[i], df["close"].iloc[i]
        xi = x(i)
        color = UP if c >= o else DOWN
        draw.line([(xi, y(h)), (xi, y(l))], fill=color, width=1)
        b_top, b_bot = y(max(o, c)), y(min(o, c))
        draw.rectangle([xi - candle_w // 2, b_top, xi + candle_w // 2, max(b_top + 1, b_bot)], fill=color)

    last = df.iloc[-1]
    title_text = f"{asset_cfg['name']} ({asset_cfg['epic']}) — 4H"
    draw.text((70, 12), title_text, fill=TEXT, font=font_big)
    price_text = f"Close: {last['close']:,.{decimals}f}"
    draw.text((width - 180, 12), price_text, fill=UP if last['close'] >= last['open'] else DOWN, font=font)

    legend_y = height - 35
    legends = [("EMA20", EMA20_C), ("EMA50", EMA50_C), ("EMA200", EMA200_C)]
    if asset_cfg["strategy"] == "donchian20_vol15":
        legends.append(("Donchian20", DC_C))

    for i, (label, color) in enumerate(legends):
        lx = 70 + i * 110
        draw.line([(lx, legend_y), (lx + 25, legend_y)], fill=color, width=2)
        draw.text((lx + 30, legend_y - 7), label, fill=MUTED, font=font_small)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
