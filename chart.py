"""شارت شموع 4 ساعات بـ Pillow (خفيف): EMA100 + مستويات الدخول/الوقف/الهدف."""
from __future__ import annotations

import io
import os

import pandas as pd
from PIL import Image, ImageDraw, ImageFont

import strategy as S

BG, PANEL, GRID = (14, 16, 21), (20, 23, 30), (38, 42, 52)
WHITE, GREY = (236, 239, 244), (135, 143, 156)
UP, DOWN = (38, 166, 154), (239, 83, 80)
BLUE, GREEN, ORANGE = (100, 150, 255), (105, 240, 174), (255, 171, 64)


def _font(size: int, bold: bool = False):
    names = ["DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", "arialbd.ttf" if bold else "arial.ttf"]
    for d in ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu", "C:/Windows/Fonts"):
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def render(h4: pd.DataFrame, title: str, levels: dict | None = None, bars: int = 90,
           live: float | None = None, mark_ts: pd.Timestamp | None = None) -> bytes:
    full = h4.copy()
    full["e100"] = S.ema(full["close"], 100)
    df = full.tail(bars).reset_index(drop=True)
    n = len(df)
    W, H = 1000, 600
    PL, PR, PT, PB = 70, 90, 50, 40
    vol_h = 70
    pb = H - PB - vol_h - 10
    vals = list(df["high"]) + list(df["low"])
    lv = {k: v for k, v in (levels or {}).items() if v}
    vals += list(lv.values()) + ([live] if live else [])
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.05 or 1
    lo, hi = lo - pad, hi + pad
    step = (W - PL - PR) / n
    X = lambda i: PL + step * (i + 0.5)  # noqa: E731
    Y = lambda p: pb - (p - lo) / (hi - lo) * (pb - PT)  # noqa: E731

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    f_t, f_s, f_x = _font(16, True), _font(12, True), _font(10)
    d.rectangle([PL, PT, W - PR, pb], fill=PANEL)
    for i in range(6):
        p = lo + (hi - lo) * i / 5
        d.line([(PL, Y(p)), (W - PR, Y(p))], fill=GRID)
        d.text((W - PR + 6, Y(p) - 6), f"{p:,.0f}", font=f_x, fill=GREY)
    for i in range(0, n, max(1, n // 7)):
        d.text((X(i) - 16, H - PB + 8), df["ts"].iloc[i].strftime("%d/%m"), font=f_x, fill=GREY)

    e = [(X(i), Y(v)) for i, v in enumerate(df["e100"])]
    d.line(e, fill=BLUE, width=2)
    body = max(2.0, step * 0.6)
    vmax = df["volume"].max() or 1
    for i, r in df.iterrows():
        col = UP if r["close"] >= r["open"] else DOWN
        x = X(i)
        d.line([(x, Y(r["high"])), (x, Y(r["low"]))], fill=col)
        t, b = sorted((Y(r["open"]), Y(r["close"])))
        d.rectangle([x - body / 2, t, x + body / 2, max(b, t + 1)], fill=col)
        vh = r["volume"] / vmax * vol_h
        d.rectangle([x - body / 2, H - PB - vh, x + body / 2, H - PB], fill=col)
        if mark_ts is not None and r["ts"] == mark_ts:
            d.polygon([(x, Y(r["low"]) + 6), (x - 8, Y(r["low"]) + 20), (x + 8, Y(r["low"]) + 20)], fill=GREEN)

    colors = {"entry": WHITE, "stop": DOWN, "tp": GREEN, "tp1": ORANGE}
    names = {"entry": "ENTRY", "stop": "STOP", "tp": "TARGET", "tp1": "1R"}
    for k, v in lv.items():
        if k not in colors:
            continue
        y = Y(v)
        for x0 in range(PL, W - PR, 12):
            d.line([(x0, y), (x0 + 7, y)], fill=colors[k], width=2)
        txt = f"{names[k]} {v:,.0f}"
        d.rectangle([W - PR + 2, y - 9, W - 2, y + 9], fill=colors[k])
        d.text((W - PR + 5, y - 7), txt[:13], font=_font(10, True), fill=BG)
    if live:
        y = Y(live)
        d.line([(PL, y), (W - PR, y)], fill=GREY)
        d.text((PL + 4, y - 14), f"NOW {live:,.0f}", font=f_x, fill=WHITE)
    d.text((PL, 14), title, font=f_t, fill=WHITE)
    d.text((W - PR - 150, 18), "BTC/USD · 4H · EMA100", font=f_x, fill=GREY)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
