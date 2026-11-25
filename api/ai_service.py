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
    model_name = settings.get("gemini_model", "gemini-3.8-flash")

    # If no API key provided, use direct Huree.site template
    if not api_key:
        return fallback_rule_based_response(
            comment_text, sender_name, extracted_phone,
            custom_public_template or settings.get("default_public_reply", HUREE_COMMENT_REPLY),
            custom_private_template or settings.get("default_private_reply", HUREE_PROMO_TEXT)
        )

    prompt = f"""
Та кино сонирхогчдод зориулсан 'Хүрээ Кино' (https://www.huree.site), 'Nice Drama Ai', 'WOW Mini Drama' хуудсуудын найрсаг онлайн зөвлөх туслах юм.
Дараах постын доор ирсэн хэрэглэгчийн коммент эсвэл чатыг шинжилж, тухайн асуултад нь ТУСГАЙЛАН, ДЭЛГЭРЭНГҮЙ, НАЙРСАГ хариулсан JSON формат үүсгэнэ үү.

[ХЭРЭГЛЭГЧИЙН НЭР]: {sender_name}
[КОММЕНТ / ЗУРВАС]: "{comment_text}"

[САЙТЫН БҮРЭН МЭДЭЭЛЭЛ]:
1. Вэбсайт: https://www.huree.site
2. Нийт киноны тоо: Манай сайт дээр 1,000 гаруй (1000+) шилдэг кино, олон ангит цуврал, mini drama бүрэн эхээрээ байгаа. Өдөр бүр шинэ кино нэмэгддэг.
3. Киноны төрөл & Чанар: Солонгос, Хятад, Монгол, Холливудын тренд болж буй шилдэг драмууд, богино хэмжээний mini drama-ууд албан ёсны Монгол дуу оруулалттай, Full HD өндөр чанартай.
4. Үнэ ба Багцууд:
   - 1 кино үзэх: 3,900₮
   - Бүх киног үзэх VIP багц: 15,900₮ (1000+ бүх киног хязгааргүй үзэх эрх)
5. Төлбөр & Хэрхэн үзэх:
   - Бүх банкны QPay-ээр шууд төлөөд 1 секундын дотор үзэх эрхээ нээнэ.
   - https://www.huree.site сайт руу ороод бүртгүүлэн, киногоо сонгоод QPay-ээр төлөөд утас, компьютер, таблетаас шууд үзэх боломжтой.

[ДҮРЭМ]:
- Хэрэв хэрэглэгч "хэдэн кинотой вэ", "хэдэн кино байна" гэвэл 1000+ шилдэг кино байгаа тухай тодорхой хариулж, сайтын линк болон үнийг хэлнэ.
- Хэрэв үнэ асуувал 1 кино 3,900₮, бүх кино 15,900₮ болон QPay төлбөрийн тухай хариулна.
- Хэрэв хаанаас яаж үзэх вэ гэвэл https://www.huree.site сайт руу ороод үзэх зааврыг өгнө.
- public_reply: 1-2 эелдэг өгүүлбэрээр асуултад нь шууд хариулаад, дэлгэрэнгүйг чатаар илгээсэн тухай бичнэ.
- private_reply: Сайтын тухай бүрэн тайлбар, асуултын дэлгэрэнгүй хариу, линк, үнэ, QPay мэдээллийг бүрэн эмх цэгцтэй илгээнэ.

Та доорх JSON бүтцээр ЗӨВХӨН цэвэр JSON буцаана (markdown кодын тэмдэглэгээгүй):
{{
  "sentiment": "positive" эсвэл "neutral" эсвэл "question" эсвэл "negative",
  "intent": "movie_count" эсвэл "price_inquiry" эсвэл "movie_link" эсвэл "site_info" эсвэл "general_inquiry",
  "phone": "8 оронтой утасны дугаар эсвэл хоосон",
  "public_reply": "Тухайн асуултад нийцсэн нийтийн эелдэг хариу",
  "private_reply": "Дэлгэрэнгүй мэдээлэл бүхий чатын хариу"
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
    txt = comment_text.lower()
    
    # 1. Киноны тоо асуусан бол
    if any(w in txt for w in ["хэдэн кино", "heden kino", "тоо", "нийт кино", "хэдэн кинотой"]):
        return {
            "sentiment": "question",
            "intent": "movie_count",
            "phone": phone,
            "public_reply": f"Сайн байна уу {sender_name}! Манай https://www.huree.site сайт дээр 1000+ (1000 гаруй) Монгол дуу оруулалттай шилдэг кино, mini drama бэлэн байгаа бөгөөд өдөр бүр шинэ кино нэмэгддэг шүү! 🍿 Дэлгэрэнгүйг чатаар илгээлээ.",
            "private_reply": (
                f"Сайн байна уу {sender_name}! 🎬🍿\n\n"
                "Манай https://www.huree.site вэбсайт дээр нийт 1,000 гаруй (1000+) Монгол дуу оруулалттай шилдэг кино, олон ангит цуврал, mini drama бүрэн эхээрээ бэлэн байгаа бөгөөд өдөр бүр шинэ тренд кинонууд тогтмол нэмэгдэж байна! ✨\n\n"
                "🔹 1 кино үзэх — 3,900₮\n"
                "🔹 Бүх киног хязгааргүй үзэх VIP багц — 15,900₮ (1000+ бүх кино багтсан)\n\n"
                "Та https://www.huree.site сайт руу ороод бүртгүүлэн, QPay-ээр шууд төлөөд 1 секундын дотор үзэх эрхээ шууд нээгээрэй! 🍿✨"
            )
}

    # 2. Сайтын тухай, ямар кинотойг асуусан бол
    if any(w in txt for w in ["ямар сайт", "юуны сайт", "ямар кино", "төрөл", "тайлбар"]):
        return {
            "sentiment": "question",
            "intent": "site_info",
            "phone": phone,
            "public_reply": f"Сайн байна уу {sender_name}! https://www.huree.site нь Монгол дуу оруулалттай 1000+ шилдэг кино, тренд mini drama үзэх онлайн сайт юм 🍿 Дэлгэрэнгүйг чатаар илгээлээ!",
            "private_reply": (
                f"Сайн байна уу {sender_name}! 🎬✨\n\n"
                "'Хүрээ Кино' (https://www.huree.site) нь үзэгчдийг байлдан дагуулж буй Солонгос, Хятад, Монгол болон Холливудын шилдэг кино, олон ангит цуврал, богино хэмжээний mini drama-уудыг албан ёсны Монгол дуу оруулалттай, Full HD өндөр чанартайгаар хүргэдэг кино сайт юм 🍿\n\n"
                "🌟 1000+ кино бэлэн бөгөөд өдөр бүр шинэ кино нэмэгдэнэ.\n"
                "🔹 1 кино — 3,900₮\n"
                "🔹 Бүх киног үзэх VIP багц — 15,900₮\n\n"
                "👉 Шууд үзэх: https://www.huree.site (QPay-ээр 1 секундэд эрхээ нээнэ)"
            )
        }

    # 3. Үнэ асуусан бол
    if any(w in txt for w in ["үнэ", "хэд вэ", "hed we", "ямар үнэтэй", "төлбөр", "үнэтэй"]):
        return {
            "sentiment": "question",
            "intent": "price_inquiry",
            "phone": phone,
            "public_reply": f"Сайн байна уу {sender_name}! 1 кино — 3,900₮, сайт дээрх 1000+ бүх киног үзэх VIP багц — 15,900₮ байгаа. Үзэх линк болон дэлгэрэнгүйг чатаар илгээлээ 🍿✨",
            "private_reply": (
                f"Сайн байна уу {sender_name}! 🎬🍿\n\n"
                "Манай https://www.huree.site сайтын үнийн мэдээлэл:\n"
                "🔹 1 кино үзэх — 3,900₮\n"
                "🔹 Бүх 1000+ киног хязгааргүй үзэх VIP багц — 15,900₮\n\n"
                "⚡ QPay-ээр шууд төлөөд 1 секундын дотор үзэх эрхээ нээнэ үү!\n"
                "👉 Үзэх холбоос: https://www.huree.site"
            )
        }

    # 4. Яаж үзэх, линк асуусан бол
    if any(w in txt for w in ["яаж үзэх", "хаанаас үзэх", "линк", "link", "үзэх үү", "хаана"]):
        return {
            "sentiment": "question",
            "intent": "movie_link",
            "phone": phone,
            "public_reply": f"Сайн байна уу {sender_name}! Кино үзэх холбоос болон дэлгэрэнгүй зааврыг чатаар илгээлээ. Та чатаа шалгаарай 🍿✨",
            "private_reply": (
                f"Сайн байна уу {sender_name}! 🍿✨\n\n"
                "Кино үзэх заавар:\n"
                "1. https://www.huree.site сайт руу орно.\n"
                "2. Бүртгүүлэх эсвэл нэвтэрнэ.\n"
                "3. Үзэх киногоо сонгоод QPay-ээр төлөхөд (1 кино 3,900₮, бүх кино 15,900₮) эрх тань 1 секундын дотор автоматаар нээгдэнэ!\n\n"
                "🎬 Вэбсайт: https://www.huree.site"
            )
        }

    # Ерөнхий эсвэл тохируулсан хариу
    return {
        "sentiment": "positive",
        "intent": "general_inquiry",
        "phone": phone,
        "public_reply": public_template or f"Сайн байна уу {sender_name}! Манай https://www.huree.site сайт дээр 1000+ кино бэлэн байгаа. Дэлгэрэнгүйг чатаар тань илгээлээ 🍿✨",
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
    Gemini AI-аар эсвэл өндөр үр дүнтэй драма загваруудаар бэлтгэх.
    """
    api_key = settings.get("gemini_api_key", "").strip()
    model_name = settings.get("gemini_model", "gemini-1.5-flash")
    clean_title = movie_title.strip() if movie_title else "Онцлох Шинэ Драма"

    # Pre-crafted viral templates for popular drama genres
    genre_lower = (genre or "").lower()
    
    if "тэрбумтан" in genre_lower or "өшөө" in genre_lower or "billionaire" in genre_lower:
        hook_1 = (
            f"🎬🔥 ШИНЭ КИНО: \"{clean_title}\"\n\n"
            f"\"Намайг ядуу гэж голж хаясан хүмүүс өнөөдөр өмнө минь сөгдөх болно...\" 👑\n\n"
            f"Үйлийн үр, эрх мэдлийн тэмцэл, хэний ч төсөөлөөгүй гал гарсан эргэлтүүдээр дүүрэн шилдэг мини цувралыг монгол дуу оруулгатайгаар бүтэн эхээр нь шууд үзээрэй! 🍿✨\n\n"
            f"👉 Шууд үзэх холбоос: https://www.huree.site\n"
            f"🔹 1 кино — 3,900₮\n"
            f"🔹 Бүх кино — 15,900₮ (1000+ кино бүгд багтсан)\n"
            f"⚡ QPay-ээр 2 секундэд төлөөд эрхээ шууд нээнэ үү!\n\n"
            f"💬 Доор 'Үзэх' гэж коммент үлдээвэл манай AI бот линкийг чатаар шууд илгээнэ!\n\n"
            f"#HureeKino #МонголКино #ШинэКино #MiniDrama #Тэрбумтан #hureesite"
        )
        hook_2 = (
            f"⚡️ Нууц тэрбумтаны гэнэтийн эргэлт: \"{clean_title}\"\n\n"
            f"Даруухан хувцасны цаана нуугдсан жинхэнэ эзэн хэн бэ? Үнэнийг мэдсэн тэдний царай ямар болох бол? 😱\n\n"
            f"🎬 1 анги нь ердөө 2 минут үргэлжлэх хамгийн донтуулагч цуврал бэлэн боллоо!\n"
            f"👉 Шууд үзэх: https://www.huree.site (QPay 3,900₮ / Бүх кино 15,900₮)\n\n"
            f"#MiniDrama #HureeSite #ӨшөөАвалт #ШинэКино"
        )
    elif "салалт" in genre_lower or "хүүхэд" in genre_lower or "divorce" in genre_lower:
        hook_1 = (
            f"🎬💔 ШИНЭ КИНО: \"{clean_title}\"\n\n"
            f"\"Хөөгдөж гарсан эхнэр 5 жилийн дараа тэрбумтаны компанийг худалдаж авахаар эргэн ирлээ... Харин түүний хөтөлж яваа хүү хэний хүүхэд вэ?\" 🥺💥\n\n"
            f"Сэтгэл хөдөлгөм, нулимс дуслуулам шилдэг хайрын драмыг чанарын өндөр түвшинд Монгол хэлээр шууд үзээрэй! 🍿\n\n"
            f"👉 Шууд үзэх: https://www.huree.site\n"
            f"🔹 1 кино — 3,900₮ | Бүх кино — 15,900₮ (1000+ кино)\n"
            f"⚡ QPay шууд төлөлттэй!\n\n"
            f"💬 Доор 'Үзэх' гэж коммент бичээрэй, линкийг чатаар илгээнэ.\n\n"
            f"#HureeKino #МонголКино #Драма #MiniDrama #Салалт #hureesite"
        )
        hook_2 = (
            f"💔 Нулимс дуслуулам бодит түүх: \"{clean_title}\"\n\n"
            f"Амьдралын хатуу шуурганд шалгарсан эхийн хайр ба өшөө авалт... 🎬 Бүрэн эхээр нь үзэх: https://www.huree.site (1 кино 3,900₮, Бүх кино 15,900₮ QPay)"
        )
    else:
        hook_1 = (
            f"🎬✨ ШИНЭ КИНО: \"{clean_title}\"\n\n"
            f"Үзэгчдийг байлдан дагуулж буй шилдэг киног бүрэн эхээр нь, чанарын өндөр түвшинд Монгол хэлээр шууд үзээрэй! 🍿\n\n"
            f"👉 Шууд үзэх холбоос: https://www.huree.site\n"
            f"🔹 1 кино — 3,900₮\n"
            f"🔹 Бүх кино — 15,900₮ (1000+ кино бүгд багтсан)\n"
            f"⚡ QPay-ээр шуурхай төлөөд эрхээ шууд нээнэ үү!\n\n"
            f"💬 Доор 'Үзэх' гэж бичвэл чатаар линк шууд илгээнэ үү!\n\n"
            f"#HureeKino #МонголКино #ШинэКино #MiniDrama #hureesite"
        )
        hook_2 = (
            f"🍿 Шинэ мини цуврал нээгдлээ: \"{clean_title}\"\n"
            f"👉 https://www.huree.site дээр QPay-ээр 3,900₮ төлөөд бүрэн эхээр нь үзээрэй!"
        )

    variations = [
        {"title": "🔥 Вирал Дэгээ (Clickbait & Шоконд оруулах)", "text": hook_1},
        {"title": "⚡ Товч & Шуурхай Reel хувилбар", "text": hook_2},
        {"title": "💳 Шууд Борлуулалт & QPay Уриалга", "text": f"🎬 \"{clean_title}\" кино гарлаа! Үзэх линк: https://www.huree.site (1 кино 3,900₮ | Бүх 1000+ кино 15,900₮ QPay). Коммент дээр 'Үзэх' гэж бичээрэй!"}
    ]

    if not api_key:
        return {"caption": hook_1, "short_caption": hook_2, "variations": variations}

    prompt = f"""
Та Facebook-ийн 6 хуудас болон олон нийтийн группүүдэд зориулсан шилдэг кино/драма сурталчилгааны пост бичигч мэргэжлийн маркетер юм.
Дараах киноны мэдээллээр Facebook-т өндөр хандалт (viral reach, share, comment) авах, сэтгэл татам монгол хэл дээрх постны тайлбар бичнэ үү.

[КИНОНЫ НЭР]: {clean_title}
[ТӨРӨЛ / ЖАНР]: {genre or 'Драма, Романс, Адал явдалт'}
[НЭМЭЛТ МЭДЭЭЛЭЛ / ТОВЧ АГУУЛГА]: {extra_details}

[ШУУД ОРУУЛАХ ШААРДЛАГА]:
- Вэбсайт линк: https://www.huree.site
- Үнэ: 1 кино — 3,900₮, Бүх кино — 15,900₮
- QPay түргэн төлбөр, 1000+ кино бэлэн байгаа тухай дурдах
- Сонирхол татах гол дэгээ (hook), оновчтой эможинууд, коммент бичих уриалга (CTA: Доор 'Үзэх' гэж бичээрэй)
- Төгсгөлд нь 4-5 холбогдох hashtag оруулах.

JSON форматаар буцаана уу:
{{
  "main_caption": "Бүх шаардлагыг хангасан шилдэг урт пост тайлбар",
  "short_caption": "Богино, хурц, видео/reel-д тохирсон тайлбар",
  "sales_caption": "QPay борлуулалт татсан хувилбар"
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
                m_cap = parsed.get("main_caption") or hook_1
                s_cap = parsed.get("short_caption") or hook_2
                sales_cap = parsed.get("sales_caption") or variations[2]["text"]
                return {
                    "caption": m_cap,
                    "short_caption": s_cap,
                    "variations": [
                        {"title": "🔥 Вирал Дэгээ (AI зохиосон шилдэг хувилбар)", "text": m_cap},
                        {"title": "⚡ Товч & Хурц Reel тайлбар", "text": s_cap},
                        {"title": "💳 Шууд Борлуулалт & QPay", "text": sales_cap}
                    ]
                }
    except Exception as e:
        print(f"craft_post_caption error: {e}")

    return {"caption": hook_1, "short_caption": hook_2, "variations": variations}
