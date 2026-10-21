"""اختبار دخاني: يجلب البيانات الحقيقية ويطبع التوصية — للتأكد أن المحرك يعمل قبل النشر."""
from analysis import analyze, ticker
from data_feeds import fear_greed, market_overview, onchain
import asyncio


def main():
    import assets

    price, change, exchange = ticker(assets.get("btc")["symbol"])
    print(f"السعر: ${price:,.0f} ({change:+.2f}% 24س) — {exchange}")

    report = analyze("4h", "btc")
    print(report.summary)

    async def feeds():
        try:
            fng = await fear_greed()
            print(f"\nالخوف والطمع: {fng['value']}/100 ({fng['ar']})")
        except Exception as e:
            print(f"\nالخوف والطمع: فشل — {e}")
        try:
            oc = await onchain()
            print(f"أون-تشين: رسوم سريعة {oc['fast']} سات/بايت | هاش ريت {oc['hashrate_eh']} EH/s | صعوبة {oc['difficulty_t']} T")
        except Exception as e:
            print(f"أون-تشين: فشل — {e}")
        try:
            mk = await market_overview()
            print(f"نظرة السوق: ${mk['price']:,.0f} | 24س {mk['change_24h']:+.1f}% | ATH {mk['ath_change']:+.1f}%")
        except Exception as e:
            print(f"نظرة السوق: فشل — {e}")

    asyncio.run(feeds())


if __name__ == "__main__":
    main()
