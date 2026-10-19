"""تحليل ذكاء اصطناعي عبر DeepSeek API (اختياري — يعمل فقط إذا وُجد DEEPSEEK_API_KEY)."""
import httpx

import config

SYSTEM_PROMPT = (
    "أنت محلل بيتكوين محترف بخبرة 15 سنة في الأسواق المالية. "
    "ستصلك بيانات فنية وسوقية، وقدّم تحليلاً عربياً موجزاً وواضحاً يتضمن: "
    "1) قراءة الوضع الحالي، 2) السيناريوهات المحتملة (صاعد/هابط/عرضي) مع نسب تقريبية، "
    "3) توصية واضحة (شراء/انتظار/بيع) مع مستويات دخول ووقف خسارة مقترحة. "
    "استخدم أرقاماً دقيقة من البيانات المعطاة، واختم دائماً بتحذير أن التحليل ليس نصيحة مالية. "
    "الرد بالعربية وبأسلوب خبير مباشر."
)


async def ai_analysis(context: str) -> str | None:
    """يرجع نص التحليل أو None إذا لم يكن المفتاح مضبوطاً."""
    if not config.DEEPSEEK_API_KEY:
        return None

    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0)) as c:
        r = await c.post(
            config.DEEPSEEK_BASE,
            headers={
                "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": context},
                ],
                "temperature": 0.7,
                "max_tokens": 800,
            },
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


def build_context(report_summary: str, fng: dict | None, market: dict | None) -> str:
    """يجمع بيانات البوت في نص واحد يُرسل للموديل."""
    parts = [
        "بيانات بيتكوين الحالية:",
        report_summary,
    ]
    if fng:
        parts.append(
            f"مؤشر الخوف والطمع: {fng['value']}/100 ({fng['classification']})"
        )
    if market:
        parts.append(
            "نظرة السوق: "
            f"السعر ${market['price']:,.0f}، تغير 24س {market['change_24h']:+.1f}%، "
            f"تغير 7أيام {market['change_7d']:+.1f}%، "
            f"قاع ATH {market['ath_change']:+.1f}%، "
            f"هيمنة البيتكوين {market['dominance']:.1f}%، "
            f"حجم التداول ${market['volume_24h'] / 1e9:.1f}B"
        )
    return "\n".join(parts)
