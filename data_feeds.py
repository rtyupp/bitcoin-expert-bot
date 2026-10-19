"""مصادر بيانات خارجية: الخوف والطمع، الأون-تشين، نظرة السوق."""
import httpx

FNG_URL = "https://api.alternative.me/fng/"
MEMPOOL_URL = "https://mempool.space/api/v1/fees/recommended"
BLOCKCHAIN_URL = "https://api.blockchain.info/stats"
COINGECKO_URL = "https://api.coingecko.com/api/v3/coins/markets"
COINGECKO_GLOBAL = "https://api.coingecko.com/api/v3/global"

FNG_AR = {
    "Extreme Fear": "خوف شديد 🥶",
    "Fear": "خوف 😨",
    "Neutral": "محايد 😐",
    "Greed": "طمع 😏",
    "Extreme Greed": "طمع شديد 🤑",
}

TIMEOUT = httpx.Timeout(15.0)


async def fear_greed() -> dict:
    """مؤشر الخوف والطمع — alternative.me"""
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.get(FNG_URL, params={"limit": 1, "format": "json"})
        r.raise_for_status()
        data = r.json()["data"][0]
        cls = data["value_classification"]
        return {
            "value": int(data["value"]),
            "classification": cls,
            "ar": FNG_AR.get(cls, cls),
        }


async def onchain() -> dict:
    """رسوم الميمبول + الهاش ريت + الصعوبة."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        fees_r = await c.get(MEMPOOL_URL)
        fees_r.raise_for_status()
        fees = fees_r.json()

        stats_r = await c.get(BLOCKCHAIN_URL)
        stats_r.raise_for_status()
        stats = stats_r.json()

    return {
        "fast": fees.get("fastestFee"),
        "half": fees.get("halfHourFee"),
        "eco": fees.get("economyFee"),
        "hashrate_eh": round(float(stats.get("hash_rate", 0)) / 1e9, 1),  # GH/s → EH/s
        "difficulty_t": round(float(stats.get("difficulty", 0)) / 1e12, 1),
    }


async def market_overview() -> dict:
    """نظرة السوق من CoinGecko: السعر، التغيرات، ATH، الهيمنة."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        m_r = await c.get(
            COINGECKO_URL,
            params={
                "vs_currency": "usd",
                "ids": "bitcoin",
                "order": "market_cap_desc",
                "sparkline": "false",
                "price_change_percentage": "24h,7d",
            },
        )
        m_r.raise_for_status()
        coin = m_r.json()[0]

        g_r = await c.get(COINGECKO_GLOBAL)
        dominance = None
        if g_r.status_code == 200:
            dominance = g_r.json()["data"]["market_cap_percentage"].get("btc")

    return {
        "price": coin["current_price"],
        "change_24h": coin["price_change_percentage_24h"],
        "change_7d": coin.get("price_change_percentage_7d_in_currency")
        or coin.get("price_change_percentage_7d"),
        "high_24h": coin["high_24h"],
        "low_24h": coin["low_24h"],
        "ath": coin["ath"],
        "ath_change": coin["ath_change_percentage"],
        "market_cap": coin["market_cap"],
        "volume_24h": coin["total_volume"],
        "dominance": dominance,
    }


def fmt_big(n: float) -> str:
    if n >= 1e12:
        return f"${n / 1e12:.2f}T"
    if n >= 1e9:
        return f"${n / 1e9:.2f}B"
    if n >= 1e6:
        return f"${n / 1e6:.2f}M"
    return f"${n:,.0f}"
