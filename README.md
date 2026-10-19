# 🪙 خبير توصيات البيتكوين — Bitcoin Expert Bot

بوت تيليجرام يعطي توصيات بيتكوين مبنية على تحليل فني حقيقي + بيانات سوق + بيانات أون-تشين + مؤشر الخوف والطمع، جاهز للنشر على **Render** بضغطة واحدة.

## 🏆 المشاريع المدمجة (أقوى المكتبات في مجالها)

| المكتبة | المستودع | النجوم | الدور |
|---|---|---|---|
| aiogram | [aiogram/aiogram](https://github.com/aiogram/aiogram) | ~5.9k ⭐ | إطار تيليجرام async حديث |
| ccxt | [ccxt/ccxt](https://github.com/ccxt/ccxt) | ~44.5k ⭐ | بيانات موحدة من +100 منصة |
| ta | [bukosabino/ta](https://github.com/bukosabino/ta) | ~5.2k ⭐ | المؤشرات الفنية (RSI/EMA/MACD/بولينجر) |
| freqtrade (مرجع) | [freqtrade/freqtrade](https://github.com/freqtrade/freqtrade) | ~55.6k ⭐ | منطق التوصيات مستوحى من استراتيجياته |

مصادر البيانات المجانية: **alternative.me** (الخوف والطمع) · **mempool.space** (رسوم الشبكة) · **blockchain.info** (الهاش ريت) · **CoinGecko** (نظرة السوق).

## ⚙️ الميزات

- `/price` — السعر اللحظي من المنصات (تحويل تلقائي بين Binance/OKX/Bybit/Kraken/Coinbase)
- `/analysis` — تحليل فني كامل: RSI(14)، EMA20/50/200، MACD، بولينجر، دعم/مقاومة، حجم
- `/recommend` — توصية مباشرة (شراء قوي/شراء/محايد/بيع/بيع قوي) مع نسبة ثقة ووقف خسارة مقترح (2×ATR)
- `/feargreed` — مؤشر الخوف والطمع مع شريط مرئي
- `/onchain` — رسوم الميمبول + الهاش ريت + الصعوبة
- `/market` — السعر، التغير 24س/7أيام، القمة التاريخية، القيمة السوقية، الهيمنة
- `/ai` — تحليل خبير بالذكاء الاصطناعي (DeepSeek، اختياري)
- 🌅 تنبيه يومي مجدول (اختياري عبر Render Cron)

### منطق التوصية
نظام نقاط يزن 7 إشارات (الاتجاه، تقاطع EMA، RSI، MACD، بولينجر، الحجم، تغير 24س) → درجة من -9.5 إلى +9.5 → توصية + ثقة + وقف خسارة.

## 🚀 النشر على Render (3 دقائق)

### 1) أنشئ البوت في BotFather
1. افتح [@BotFather](https://t.me/BotFather) في تيليجرام
2. أرسل `/newbot` واختر الاسم واليوزر
3. انسخ التوكن (شكل: `123456:ABC...`) — **لا ترسله لأحد**

### 2) انشر عبر Blueprint
1. سجّل في [render.com](https://render.com) (مجاني، بحساب GitHub)
2. من اللوحة: **New + → Blueprint**
3. اختر المستودع `rtyupp/bitcoin-expert-bot` → سيقرأ `render.yaml` تلقائياً
4. سيطلب إدخال المتغيرات الناقصة → الصق **BOT_TOKEN** فقط
5. **Apply** → يبني وينشر خلال ~3 دقائق

> الخدمة تعمل بنظام **webhook** على رابطها العام — تيليجرام يوقظها تلقائياً مع كل رسالة، فلا تنام فعلياً، وتبقى مجانية.

### 3) (اختياري) التنبيه اليومي
1. ابدأ محادثة مع بوتك وأرسل `/myid` → انسخ الرقم
2. في Render: خدمة `bitcoin-expert-bot` → **Environment** → أضف `DAILY_CHAT_ID` بالرقم
3. **Cron Jobs → New Cron Job** → الأمر:
   `curl -s -X POST "https://bitcoin-expert-bot.onrender.com/cron" -H "X-Cron-Secret: $CRON_SECRET"`
   (متغير CRON_SECRET موجود تلقائياً في الخدمة) — حدد التوقيت مثلاً `0 6 * * *`

### 4) (اختياري) الذكاء الاصطناعي
أضف `DEEPSEEK_API_KEY` في Environment → أعد النشر → استخدم `/ai`.

## 🖥 تشغيل محلي

```bash
pip install -r requirements.txt
export BOT_TOKEN=123456:ABC...   # أو set BOT_TOKEN=... في Windows
python bot.py                    # يعمل بوضع polling تلقائياً
python smoke_test.py             # اختبار المحرك بدون تيليجرام
```

## ⚠️ إخلاء مسؤولية
هذا البوت لأغراض تعليمية وتحليلية فقط — **ليس نصيحة مالية**. تداول الكريبتو عالي المخاطر.
