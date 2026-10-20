"""رسم شارت خفيف بـ Pillow — بديل matplotlib لتوفير الذاكرة على الاستضافة المجانية.

لماذا: matplotlib عند الاستيراد + بناء font cache + الرسم يستهلك 100-200MB،
وهذا يفجّر خطة Render المجانية (512MB) → OOM kill → حلقة انهيار.
Pillow تستهلك ~15-25MB فقط والرسم أسرع.
"""
import io
import os

from PIL import Image, ImageDraw, ImageFont

BG = (18, 18, 18)
GRID = (38, 38, 38)
WHITE = (247, 247, 247)
GREY = (150, 150, 150)
CYAN = (41, 182, 246)
YELLOW = (255, 213, 79)
RED = (239, 83, 80)
GREEN = (105, 240, 174)
ORANGE = (255, 171, 64)
GOLD = (255, 215, 0)
VOLC = (120, 144, 156)


def _font(size: int = 12, bold: bool = False):
    """محاولة إيجاد خط TTF، وإلا الخط الافتراضي."""
    names = [
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "arialbd.ttf" if bold else "arial.ttf",
    ]
    dirs = [
        "/usr/share/fonts/truetype/dejavu",
        "/usr/share/fonts/dejavu",
        "/usr/share/fonts/TTF",
        "C:/Windows/Fonts",
    ]
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


def _dashed(draw, pts, fill, width=1, dash=7, gap=5):
    """رسم خط متقطع بين نقاط متتالية."""
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        dx, dy = x2 - x1, y2 - y1
        dist = (dx * dx + dy * dy) ** 0.5
        if dist == 0:
            continue
        ux, uy = dx / dist, dy / dist
        pos = 0.0
        while pos < dist:
            end = min(pos + dash, dist)
            draw.line(
                [(x1 + ux * pos, y1 + uy * pos), (x1 + ux * end, y1 + uy * end)],
                fill=fill, width=width,
            )
            pos = end + gap


def _tri(draw, x, y, size=9, up=True, fill=GREEN):
    if up:
        pts = [(x, y - size), (x - size, y + size * 0.7), (x + size, y + size * 0.7)]
    else:
        pts = [(x, y + size), (x - size, y - size * 0.7), (x + size, y - size * 0.7)]
    draw.polygon(pts, fill=fill, outline=(0, 0, 0))


def _label(draw, x, y, text, color, font, right=False, pad=4):
    """نص بخلفية داكنة — يمنع تداخله مع الخطوط ويضمن ظهوره كاملاً."""
    tw = draw.textlength(text, font=font)
    x0 = x - tw - pad if right else x - pad
    x1 = x + pad if right else x + tw + pad
    draw.rectangle([x0, y - 2, x1, y + 14], fill=BG)
    draw.text((x0 + pad, y), text, font=font, fill=color)


def render(df, a: dict, symbol: str) -> bytes:
    """يرسم الشارت ويرجع PNG bytes. خفيف وسريع."""
    n = len(df)
    closes = [float(v) for v in df["close"]]
    highs = [float(v) for v in df["high"]]
    lows = [float(v) for v in df["low"]]
    vols = [float(v) for v in df["volume"]]

    # بولينجر (20, 2)
    def _sma_std(idx, w=20):
        seg = closes[max(0, idx - w + 1): idx + 1]
        m = sum(seg) / len(seg)
        var = sum((x - m) ** 2 for x in seg) / len(seg)
        return m, var ** 0.5

    mid, up, lo = [None] * n, [None] * n, [None] * n
    for i in range(19, n):          # نتجاهل أول 19 شمعة (بدون متوسط كامل)
        m, s = _sma_std(i)
        mid[i] = m
        up[i] = m + 2 * s
        lo[i] = m - 2 * s

    W, H = 900, 560
    PL, PR, PT, PB = 74, 18, 48, 28
    price_top, price_bot = PT + 8, 402
    vol_top, vol_bot = 426, 512
    plot_w = W - PL - PR

    vals = closes + [v for v in up if v] + [v for v in lo if v]
    for k in ("stop_loss", "tp1"):
        if a.get(k):
            vals.append(float(a[k]))
    pmin, pmax = min(vals), max(vals)
    if pmax == pmin:
        pmax = pmin + 1

    def X(i):
        return PL + (plot_w * i / max(n - 1, 1))

    def Y(p):
        return price_bot - (p - pmin) / (pmax - pmin) * (price_bot - price_top)

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    f_t, f_s, f_xs = _font(15, True), _font(11), _font(9)

    # شبكة أفقية + أسعار
    for k in range(5):
        p = pmin + (pmax - pmin) * k / 4
        y = Y(p)
        d.line([(PL, y), (W - PR, y)], fill=GRID, width=1)
        d.text((6, y - 6), f"{p:,.0f}", font=f_xs, fill=GREY)

    # شبكة رأسية + تواريخ
    step = max(1, n // 5)
    for i in range(0, n, step):
        x = X(i)
        d.line([(x, price_top), (x, vol_bot)], fill=GRID, width=1)
        lbl = df["ts"].iloc[i].strftime("%d/%m")
        d.text((x - 13, vol_bot + 6), lbl, font=f_xs, fill=GREY)

    # بولينجر (من الشمعة 20 عشان المتوسط يكتمل)
    _dashed(d, [(X(i), Y(up[i])) for i in range(n) if up[i] is not None], CYAN, 1)
    _dashed(d, [(X(i), Y(lo[i])) for i in range(n) if lo[i] is not None], RED, 1)
    _dashed(d, [(X(i), Y(mid[i])) for i in range(n) if mid[i] is not None], YELLOW, 1, dash=5, gap=4)

    # السعر
    d.line([(X(i), Y(closes[i])) for i in range(n)], fill=WHITE, width=2)

    # الوقف والهدف
    if a.get("stop_loss"):
        y = Y(float(a["stop_loss"]))
        _dashed(d, [(PL, y), (W - PR, y)], RED, 2, dash=4, gap=4)
    if a.get("tp1"):
        y = Y(float(a["tp1"]))
        _dashed(d, [(PL, y), (W - PR, y)], GREEN, 2, dash=4, gap=4)

    # نقاط الصيد
    fe = a.get("first_entry")
    if fe:
        x, y = X(fe["idx"]), Y(fe["price"])
        _tri(d, x, y, 10, up=(a.get("direction") == "buy"),
             fill=GREEN if a.get("direction") == "buy" else ORANGE)
        _label(d, x - 24, y - 36, f"ENTRY {fe['price']:,.0f}", WHITE, f_s)
    se = a.get("second_entry")
    if se:
        x, y = X(se["idx"]), Y(se["price"])
        r = 7
        d.ellipse([x - r, y - r, x + r, y + r], fill=GOLD, outline=(0, 0, 0))
        _label(d, x + 12, y - 16, f"ADD {se['price']:,.0f}", GOLD, f_s)

    # تسميات الوقف والهدف — تُرسم أخيراً حتى لا يغطيها شيء
    if a.get("stop_loss"):
        _label(d, PL + 8, Y(float(a["stop_loss"])) - 16, f"STOP {a['stop_loss']:,.0f}", RED, f_s)
    if a.get("tp1"):
        _label(d, PL + 8, Y(float(a["tp1"])) + 3, f"TP1 {a['tp1']:,.0f}", GREEN, f_s)

    # الحجم
    vmax = max(vols) if vols else 1
    bw = max(1, int(plot_w / max(n, 1) * 0.7))
    for i in range(n):
        h = (vols[i] / vmax) * (vol_bot - vol_top)
        x = X(i)
        d.rectangle([x - bw // 2, vol_bot - h, x + bw // 2, vol_bot], fill=VOLC)

    # العنوان + السعر الأخير
    d.text((PL, 12), f"{symbol}  \u2014  4H", font=f_t, fill=WHITE)
    last = closes[-1]
    chg = (last / closes[-2] - 1) * 100 if n > 1 else 0
    txt = f"{last:,.2f}  ({chg:+.2f}%)"
    tw = d.textlength(txt, font=f_s)
    d.text((W - PR - tw, 16), txt, font=f_s,
           fill=GREEN if chg >= 0 else RED)

    # مفتاح
    lx = PL + 6
    for lbl, col in (("\u2014  Close", WHITE), ("\u2014  BB", CYAN)):
        d.text((lx, price_top + 4), lbl, font=f_xs, fill=col)
        lx += 78

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
