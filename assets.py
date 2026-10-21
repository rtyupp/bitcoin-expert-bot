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
        # الاستراتيجية الأساسية: قنص السيولة (SMC Stop-Hunt) + اختراق مؤسسي
        "strategy": "smc_liquidity",
        "strategy_name": "قنص السيولة (SMC) + اختراق مؤسسي",
        "strategy_en": "SMC Liquidity Sweep + Institutional Breakout",
        "strategy_note": "سر الحيتان: يدخل عند كنس ستوبات القيعان (Bear Trap) والارتداد داخل النطاق، أو مع اختراق مؤسسي مدعوم بالحجم والاتجاه + تأمين الوقف عند TP1",
        "rr": 3.0,              # نسبة الهدف للوقف الكامل (مع تأمين عند 1R)
        "stop_mult": 1.8,       # وقف = 1.8×ATR
        "volume_mult": 1.5,     # تأكيد الحجم للاختراق
        "threshold": 3.5,       # عتبة إطلاق الصيدة
        "weights": {            # أوزان المؤشرات لهذا الأصل
            "trend": 2.0, "cross": 1.2, "rsi": 0.8,
            "macd": 0.8, "bb": 1.8, "vol": 1.2, "chg": 0.5,
        },
        "backtest": {"trades": 16, "win": 68.8, "pf": 3.62, "avg_r": 0.82},
    },
    "gold": {
        "key": "gold",
        "symbol": "PAXG/USDT",
        "name": "الذهب",
        "emoji": "🥇",
        "strategy": "bb_trap_donchian",
        "strategy_name": "مصيدة بولينجر + اختراق Donchian",
        "strategy_en": "BB Fakeout Trap + Donchian Trend",
        "strategy_note": "الأقوى على الذهب: يصطاد الكسر الكاذب لبولينجر بعد كنس السيولة، أو يدخل مع كسر قناة 20 باتجاه الاتجاه العام (ADX>22) + تأمين الوقف عند TP1",
        "rr": 2.0,
        "stop_mult": 2.0,
        "volume_mult": 1.2,
        "threshold": 3.0,
        "weights": {
            "trend": 2.2, "cross": 0.8, "rsi": 0.8,
            "macd": 1.6, "bb": 1.4, "vol": 0.4, "chg": 0.4,
        },
        "backtest": {"trades": 23, "win": 65.2, "pf": 2.85, "avg_r": 0.52},
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
