"""إعدادات الأصول — لكل أصل استراتيجيته وفلتره وهدفه (مبنية على الاختبار التاريخي).

نتائج مختبر الاستراتيجيات (strategy_lab.py، بيانات يومية، وقف 2×ATR):

البيتكوين (2018-2026، 3215 يوم):
  كسر بولينجر + حجم، هدف 1:3 → 73 صفقة | فوز 60.3% | PF 2.98 | +0.74R  ← الأفضل
  Donchian 55، هدف 1:3      → 65 صفقة | فوز 56.9% | PF 2.60 | +0.63R

الذهب (2020-2026، 2245 يوم):
  MACD + فلتر EMA200، هدف 1:2 → 48 صفقة | فوز 58.3% | PF 2.69 | +0.58R  ← الأفضل
  Donchian 55، هدف 1:2        → 39 صفقة | فوز 59.0% | PF 2.67 | +0.66R

ملاحظة: استراتيجيات الارتداد (RSI/بولينجر انعكاسي) خاسرة على الأصلين — تجنّبها.
"""

ASSETS: dict[str, dict] = {
    "btc": {
        "key": "btc",
        "symbol": "BTC/USDT",
        "name": "البيتكوين",
        "emoji": "🪙",
        # الاستراتيجية الأساسية
        "strategy": "bb_vol",
        "strategy_name": "كسر بولينجر + حجم",
        "strategy_en": "BB Breakout + Volume",
        "strategy_note": "الأقوى على البيتكوين: يدخل مع اختراق مؤكد بالحجم، هدف 1:3",
        "rr": 3.0,              # نسبة الهدف للوقف
        "stop_mult": 2.0,       # وقف = 2×ATR
        "volume_mult": 1.5,     # تأكيد الحجم
        "threshold": 4.0,       # عتبة إطلاق الصيدة
        "weights": {            # أوزان المؤشرات لهذا الأصل
            "trend": 2.0, "cross": 1.2, "rsi": 0.5,
            "macd": 0.8, "bb": 1.8, "vol": 1.2, "chg": 0.5,
        },
        "backtest": {"trades": 73, "win": 60.3, "pf": 2.98, "avg_r": 0.74},
    },
    "gold": {
        "key": "gold",
        "symbol": "PAXG/USDT",
        "name": "الذهب",
        "emoji": "🥇",
        "strategy": "macd_ema200",
        "strategy_name": "MACD + فلتر EMA200",
        "strategy_en": "MACD + EMA200 Filter",
        "strategy_note": "الأقوى على الذهب: تقاطع MACD باتجاه الاتجاه العام، هدف 1:2",
        "rr": 2.0,
        "stop_mult": 2.0,
        "volume_mult": 0.0,     # الحجم غير موثوق في الذهب الرمزي
        "threshold": 3.0,
        "weights": {
            "trend": 2.2, "cross": 0.8, "rsi": 0.5,
            "macd": 2.0, "bb": 0.6, "vol": 0.3, "chg": 0.4,
        },
        "backtest": {"trades": 48, "win": 58.3, "pf": 2.69, "avg_r": 0.58},
    },
}

DEFAULT_ASSET = "btc"


def get(key: str | None) -> dict:
    """يرجع إعدادات الأصل (الافتراضي البيتكوين)."""
    return ASSETS.get(key or DEFAULT_ASSET, ASSETS[DEFAULT_ASSET])


def keys() -> list[str]:
    return list(ASSETS)


def label(key: str) -> str:
    a = get(key)
    return f"{a['emoji']} {a['name']}"
