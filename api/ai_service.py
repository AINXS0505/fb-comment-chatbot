import re
import json
import httpx
from typing import Dict, Any, Optional

MONGOLIAN_PHONE_REGEX = re.compile(r'(?:\+?976[\s-]?)?(?:[89][0-9]{7}|7[0-9]{7})')

HUREE_PROMO_TEXT = (
    "Сайн байна уу! 🎬🍿\n\n"
    "https://www.huree.site энэ сайтаар ороод бүртгүүлээд Монгол хэлтэй чанартай бичлэгтэй 1000+ кино Хүрээ дээр бий!\n\n"
    "🔹 1 кино — 3,900₮\n"
    "🔹 Бүх кино — 15,900₮\n\n"
    "QPay-ээр төлөөд үзэх эрхээ шууд нээгээрэй. Өдөр бүр шинэ кино нэмэгдэнэ! ✨"
)

HUREE_COMMENT_REPLY = "Сайн байна уу! Кино үзэх холбоос болон үнийн дэлгэрэнгүйг хувийн чатаар тань илгээлээ. Та чатаа шалгаарай 🍿✨"

def extract_phone_number(text: str) -> Optional[str]:
    """Монгол утасны дугаарыг (8 оронтой) коммент дотроос илрүүлэх"""
    if not text:
        return None
    cleaned = re.sub(r'(\d)[\s-](\d)', r'\1\2', text)
    matches = MONGOLIAN_PHONE_REGEX.findall(cleaned)
    if matches:
        num = matches[0].replace('+976', '').replace('-', '').strip()
        if len(num) == 8:
            return num
    return None

async def analyze_and_generate_replies(
    comment_text: str,
    sender_name: str,
    post_name: str,
    settings: Dict[str, str],
    custom_public_template: str = "",
    custom_private_template: str = ""
) -> Dict[str, Any]:
    """
    Gemini эсвэл OpenAI API ашиглан:
    1. Sentiment & Intent
    2. Утасны дугаар
    3. Huree.site-ийн мэдээлэл бүхий найрсаг коммент хариу
    4. Messenger-ээр явуулах дэлгэрэнгүй киноны линк, үнийн санал
    """
    extracted_phone = extract_phone_number(comment_text)
    api_key = settings.get("gemini_api_key", "").strip()
    system_prompt = settings.get("system_prompt", "")
    model_name = settings.get("gemini_model", "gemini-3.5-flash-lite")

    # If no API key provided, use direct Huree.site template
    if not api_key:
        return fallback_rule_based_response(
            comment_text, sender_name, extracted_phone,
            custom_public_template or settings.get("default_public_reply", HUREE_COMMENT_REPLY),
            custom_private_template or settings.get("default_private_reply", HUREE_PROMO_TEXT)
        )

    prompt = f"""
Та кино сонирхогчдод зориулсан 'Хүрээ Кино' (www.huree.site), 'Nice Drama Ai', 'WOW Mini Drama' хуудсуудын найрсаг онлайн зөвлөх туслах юм.
Дараах постын доор ирсэн хэрэглэгчийн комментыг шинжилж, JSON форматаар хариу өгнө үү.

[ПОСТЫН НЭР]: {post_name}
[ХЭРЭГЛЭГЧИЙН НЭР]: {sender_name}
[КОММЕНТ]: "{comment_text}"

[ҮНДСЭН МЭДЭЭЛЭЛ]:
- Вэбсайт: https://www.huree.site
- Монгол хэлтэй, өндөр чанартай 1000+ кино Хүрээ дээр бий.
- Үнэ: 1 кино — 3,900₮, Бүх кино үзэх багц — 15,900₮
- Төлбөр: QPay-ээр шууд төлөөд үзэх эрхээ нээнэ. Өдөр бүр шинэ кино нэмэгдэнэ.

Та доорх JSON бүтцээр ЗӨВХӨН цэвэр JSON буцаана (markdown тэмдэглэгээгүй):
{{
  "sentiment": "positive" эсвэл "neutral" эсвэл "question" эсвэл "negative",
  "intent": "price_inquiry" эсвэл "movie_link" эсвэл "order_request" эсвэл "general_inquiry",
  "phone": "8 оронтой утасны дугаар эсвэл хоосон",
  "public_reply": "Сайн байна уу {sender_name}! Кино үзэх холбоос болон үнийн дэлгэрэнгүйг хувийн чатаар тань илгээлээ. Та чатаа шалгаарай 🍿✨",
  "private_reply": "{HUREE_PROMO_TEXT}"
}}
"""

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.2,
                    "responseMimeType": "application/json"
                }
            }
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                text_content = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                if text_content.startswith("```json"):
                    text_content = text_content[7:]
                if text_content.endswith("```"):
                    text_content = text_content[:-3]

                result = json.loads(text_content.strip())
                if extracted_phone and not result.get("phone"):
                    result["phone"] = extracted_phone

                return {
                    "sentiment": result.get("sentiment", "neutral"),
                    "intent": result.get("intent", "movie_link"),
                    "phone": result.get("phone") or extracted_phone,
                    "public_reply": result.get("public_reply") or HUREE_COMMENT_REPLY,
                    "private_reply": result.get("private_reply") or HUREE_PROMO_TEXT
                }
            else:
                print(f"Gemini API error: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"AI Generation exception: {e}")

    # Fallback
    return fallback_rule_based_response(
        comment_text, sender_name, extracted_phone,
        custom_public_template or settings.get("default_public_reply", HUREE_COMMENT_REPLY),
        custom_private_template or settings.get("default_private_reply", HUREE_PROMO_TEXT)
    )


def fallback_rule_based_response(
    comment_text: str,
    sender_name: str,
    phone: Optional[str],
    public_template: str,
    private_template: str
) -> Dict[str, Any]:
    return {
        "sentiment": "question" if any(w in comment_text.lower() for w in ["хэд", "үнэ", "үзэх", "линк", "хаана"]) else "positive",
        "intent": "movie_link",
        "phone": phone,
        "public_reply": public_template or f"Сайн байна уу {sender_name}! Кино үзэх холбоос болон дэлгэрэнгүй мэдээллийг чатаар илгээлээ. Та чатаа шалгаарай 🍿✨",
        "private_reply": private_template or HUREE_PROMO_TEXT
    }

async def craft_post_caption(
    movie_title: str,
    genre: str,
    extra_details: str,
    settings: Dict[str, str]
) -> Dict[str, Any]:
    """
    Facebook хуудас болон группүүдэд зориулсан вирал, сонирхол татахуйц киноны пост текстийг
    Gemini 3.5 AI-аар бэлтгэх.
    """
    api_key = settings.get("gemini_api_key", "").strip()
    model_name = settings.get("gemini_model", "gemini-3.5-flash-lite")

    fallback_caption = (
        f"🎬✨ ШИНЭ КИНО: {movie_title or 'Онцлох бүтээл'}\n\n"
        f"Үзэгчдийг байлдан дагуулж буй шилдэг киног бүрэн эхээр нь, чанарын өндөр түвшинд Монгол хэлээр шууд үзээрэй! 🍿\n\n"
        f"👉 Шууд үзэх холбоос: https://www.huree.site\n"
        f"🔹 1 кино — 3,900₮\n"
        f"🔹 Бүх кино — 15,900₮ (1000+ кино бүгд багтсан)\n"
        f"⚡ QPay-ээр шуурхай төлөөд эрхээ шууд нээнэ үү!\n\n"
        f"#HureeKino #МонголКино #ШинэКино #MiniDrama #hureesite"
    )

    if not api_key:
        return {"caption": fallback_caption, "variations": [fallback_caption]}

    prompt = f"""
Та Facebook-ийн 6 хуудас болон олон нийтийн группүүдэд зориулсан шилдэг кино/драма сурталчилгааны пост бичигч мэргэжлийн маркетер юм.
Дараах киноны мэдээллээр Facebook-т өндөр хандалт (viral reach, share, comment) авах, сэтгэл татам монгол хэл дээрх постны тайлбар бичнэ үү.

[КИНОНЫ НЭР]: {movie_title}
[ТӨРӨЛ / ЖАНР]: {genre or 'Драма, Романс, Адал явдалт'}
[НЭМЭЛТ МЭДЭЭЛЭЛ / ТОВЧ АГУУЛГА]: {extra_details}

[ШУУД ОРУУЛАХ ШААРДЛАГА]:
- Вэбсайт линк: https://www.huree.site
- Үнэ: 1 кино — 3,900₮, Бүх кино — 15,900₮
- QPay түргэн төлбөр, 1000+ кино бэлэн байгаа тухай дурдах
- Сонирхол татах гол дэгээ (hook), оновчтой эможинууд, коммент бичих уриалга (CTA)
- Төгсгөлд нь 4-5 холбогдох hashtag оруулах.

JSON форматаар буцаана уу:
{{
  "main_caption": "Бүх шаардлагыг хангасан шилдэг пост тайлбар",
  "short_caption": "Богино, хурц, видео/reel-д тохирсон тайлбар"
}}
"""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.7,
                    "responseMimeType": "application/json"
                }
            }
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                text_content = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                if text_content.startswith("```json"):
                    text_content = text_content[7:]
                if text_content.endswith("```"):
                    text_content = text_content[:-3]
                parsed = json.loads(text_content.strip())
                return {
                    "caption": parsed.get("main_caption") or fallback_caption,
                    "short_caption": parsed.get("short_caption") or fallback_caption
                }
    except Exception as e:
        print(f"craft_post_caption error: {e}")

    return {"caption": fallback_caption, "short_caption": fallback_caption}
