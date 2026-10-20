"""شارت الشموع اليابانية (Pillow) — خفيف على الذاكرة وواضح.

يرسم: شموع OHLC + فتائل، بولينجر، متوسط EMA20، الحجم بألوان الشموع،
نقاط الصيد (أول/ثاني)، خط الوقف والهدف، ومحاور الأسعار والتواريخ.
"""
import io
import os

from PIL import Image, ImageDraw, ImageFont

BG = (16, 18, 22)
PANEL = (22, 25, 31)
GRID = (36, 40, 48)
WHITE = (238, 240, 244)
GREY = (138, 146, 158)
UP = (38, 166, 154)      # أخضر شمعة صاعدة
DOWN = (239, 83, 80)     # أحمر شمعة هابطة
CYAN = (79, 195, 247)
YELLOW = (255, 213, 79)
GREEN = (105, 240, 174)
ORANGE = (255, 171, 64)
GOLD = (255, 215, 0)


def _font(size: int = 12, bold: bool = False):
    names = ["DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
             "arialbd.ttf" if bold else "arial.ttf"]
    dirs = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu",
            "/usr/share/fonts/TTF", "C:/Windows/Fonts"]
    for d in dirs:
        for n in names:
            p = os.path.join(d, n)
            try:
                if os.path.exists(p):
                    return ImageFont.truetype(p, size)
            except Exception:  # noqa: BLE001
                pass
    try:
        return ImageFont.load_default(size)
    except Exception:  # noqa: BLE001
        return ImageFont.load_default()


def _dashed(draw, pts, fill, width=1, dash=6, gap=4):
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        dx, dy = x2 - x1, y2 - y1
        dist = (dx * dx + dy * dy) ** 0.5
        if dist == 0:
            continue
        ux, uy = dx / dist, dy / dist
        pos = 0.0
        while pos < dist:
            end = min(pos + dash, dist)
            draw.line([(x1 + ux * pos, y1 + uy * pos), (x1 + ux * end, y1 + uy * end)],
                      fill=fill, width=width)
            pos = end + gap


def _label(draw, x, y, text, color, font, right=False, pad=5):
    tw = draw.textlength(text, font=font)
    x0 = x - tw - pad if right else x - pad
    x1 = x + pad if right else x + tw + pad
    draw.rectangle([x0, y - 2, x1, y + 15], fill=BG)
    draw.text((x0 + pad, y), text, font=font, fill=color)


def render(df, a: dict, symbol: str, strategy: str = "", live_price: float | None = None) -> bytes:
    """يرسم شارت الشموع ويرجع PNG bytes."""
    n = len(df)
    o = [float(x) for x in df["open"]]
    h = [float(x) for x in df["high"]]
    lo = [float(x) for x in df["low"]]
    c = [float(x) for x in df["close"]]
    v = [float(x) for x in df["volume"]]

    # بولينجر + EMA20 (حساب محلي خفيف)
    def sma(arr, i, w=20):
        seg = arr[max(0, i - w + 1): i + 1]
        m = sum(seg) / len(seg)
        var = sum((x - m) ** 2 for x in seg) / len(seg)
        return m, var ** 0.5

    up, mid, low_band, ema20 = [None] * n, [None] * n, [None] * n, [None] * n
    k = 2.0 / 21
    prev_ema = c[0]
    for i in range(n):
        if i >= 19:
            m, s = sma(c, i)
            mid[i] = m
            up[i] = m + 2 * s
            low_band[i] = m - 2 * s
        prev_ema = c[i] * k + prev_ema * (1 - k)
        if i >= 19:
            ema20[i] = prev_ema

    W, H = 1020, 640
    PL, PR, PT = 78, 22, 52
    price_top, price_bot = PT + 10, 452
    vol_top, vol_bot = 478, 576
    plot_w = W - PL - PR

    vals = [x for x in c + h + lo]
    vals += [x for x in up if x is not None] + [x for x in low_band if x is not None]
    for key in ("stop_loss", "tp1"):
        if a.get(key):
            vals.append(float(a[key]))
    if live_price:
        vals.append(float(live_price))
    pmin, pmax = min(vals), max(vals)
    pad = (pmax - pmin) * 0.06 or 1
    pmin -= pad
    pmax += pad

    step = plot_w / max(n, 1)
    body = max(2.0, step * 0.62)

    def X(i):
        return PL + step * (i + 0.5)

    def Y(p):
        return price_bot - (p - pmin) / (pmax - pmin) * (price_bot - price_top)

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    f_t, f_s, f_xs = _font(15, True), _font(11), _font(9)

    # خلفية منطقة السعر
    d.rectangle([PL, price_top, W - PR, price_bot], fill=PANEL)

    # شبكة أفقية + أسعار
    for i in range(5):
        p = pmin + (pmax - pmin) * i / 4
        y = Y(p)
        d.line([(PL, y), (W - PR, y)], fill=GRID, width=1)
        d.text((6, y - 6), f"{p:,.0f}", font=f_xs, fill=GREY)

    # شبكة رأسية + تواريخ
    for i in range(0, n, max(1, n // 6)):
        x = X(i)
        d.line([(x, price_top), (x, vol_bot)], fill=GRID, width=1)
        d.text((x - 13, vol_bot + 6), df["ts"].iloc[i].strftime("%d/%m"), font=f_xs, fill=GREY)

    # بولينجر
    for band, col in ((up, CYAN), (low_band, CYAN)):
        pts = [(X(i), Y(band[i])) for i in range(n) if band[i] is not None]
        _dashed(d, pts, col, 1, dash=5, gap=4)
    pts_mid = [(X(i), Y(mid[i])) for i in range(n) if mid[i] is not None]
    _dashed(d, pts_mid, YELLOW, 1, dash=3, gap=5)
    # EMA20
    pts_e = [(X(i), Y(ema20[i])) for i in range(n) if ema20[i] is not None]
    if len(pts_e) > 1:
        d.line(pts_e, fill=(120, 144, 200), width=2)

    # الشموع اليابانية
    for i in range(n):
        col = UP if c[i] >= o[i] else DOWN
        x = X(i)
        d.line([(x, Y(h[i])), (x, Y(lo[i]))], fill=col, width=1)
        y1, y2 = Y(o[i]), Y(c[i])
        top, bot = min(y1, y2), max(y1, y2)
        if bot - top < 1.5:
            bot = top + 1.5
        d.rectangle([x - body / 2, top, x + body / 2, bot], fill=col, outline=col)

    # الوقف والهدف
    if a.get("stop_loss"):
        y = Y(float(a["stop_loss"]))
        _dashed(d, [(PL, y), (W - PR, y)], DOWN, 2, dash=5, gap=4)
        _label(d, PL + 10, y - 17, f"STOP {a['stop_loss']:,.0f}", DOWN, f_s)
    if a.get("tp1"):
        y = Y(float(a["tp1"]))
        _dashed(d, [(PL, y), (W - PR, y)], GREEN, 2, dash=5, gap=4)
        _label(d, PL + 10, y + 3, f"TP {a['tp1']:,.0f}", GREEN, f_s)

    # نقاط الصيد
    fe = a.get("first_entry")
    if fe:
        x, y = X(fe["idx"]), Y(fe["price"])
        if a.get("direction") == "buy":
            d.polygon([(x, y - 13), (x - 9, y + 4), (x + 9, y + 4)], fill=GREEN, outline=(0, 0, 0))
        else:
            d.polygon([(x, y + 13), (x - 9, y - 4), (x + 9, y - 4)], fill=ORANGE, outline=(0, 0, 0))
        near_right = x > W - PR - 95
        _label(d, x, y - 38, f"ENTRY {fe['price']:,.0f}", WHITE, f_s, right=near_right)
    se = a.get("second_entry")
    if se:
        x, y = X(se["idx"]), Y(se["price"])
        d.ellipse([x - 6, y - 6, x + 6, y + 6], fill=GOLD, outline=(0, 0, 0))
        near_right = x > W - PR - 95
        _label(d, x + (11 if not near_right else -11), y - 16,
               f"ADD {se['price']:,.0f}", GOLD, f_s, right=near_right)

    # السعر اللحظي — خط "الآن"
    if live_price:
        y = Y(float(live_price))
        _dashed(d, [(PL, y), (W - PR, y)], WHITE, 2, dash=3, gap=3)
        _label(d, W - PR - 6, y - 19, f"NOW {live_price:,.2f}", WHITE, f_s, right=True)

    # الحجم
    vmax = max(v) if v else 1
    for i in range(n):
        col = UP if c[i] >= o[i] else DOWN
        hh = (v[i] / vmax) * (vol_bot - vol_top)
        x = X(i)
        d.rectangle([x - body / 2, vol_bot - hh, x + body / 2, vol_bot], fill=col)
    d.rectangle([PL, vol_top, W - PR, vol_bot], outline=GRID)

    # العنوان والسعر الحالي
    d.text((PL, 12), f"{symbol}  \u2022  4H  \u2022  Candles", font=f_t, fill=WHITE)
    last, chg = c[-1], (c[-1] / c[-2] - 1) * 100 if n > 1 else 0
    txt = f"{last:,.2f}  ({chg:+.2f}%)"
    tw = d.textlength(txt, font=f_s)
    d.text((W - PR - tw, 16), txt, font=f_s, fill=GREEN if chg >= 0 else DOWN)
    if strategy:
        d.text((PL, 32), strategy, font=f_xs, fill=GREY)

    # مفتاح
    lx = PL + 8
    for lbl, col in (("\u2014 Close", WHITE), ("\u2014 BB", CYAN), ("\u2014 EMA20", (120, 144, 200))):
        d.text((lx, price_top + 6), lbl, font=f_xs, fill=col)
        lx += 84

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
