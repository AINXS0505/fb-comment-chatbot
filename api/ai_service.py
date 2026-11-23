import re
import json
import httpx
from typing import Dict, Any, Optional

MONGOLIAN_PHONE_REGEX = re.compile(r'(?:\+?976[\s-]?)?(?:[89][0-9]{7}|7[0-9]{7})')

def extract_phone_number(text: str) -> Optional[str]:
    """Монгол утасны дугаарыг (8 оронтой) коммент дотроос илрүүлэх"""
    if not text:
        return None
    # Remove extra spaces/hyphens inside potential numbers
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
    1. Sentiment (Эерэг, Сөрөг, Асуулт, Төвийг сахисан)
    2. Intent (Үнэ, Хүргэлт, Захиалга, Ерөнхий)
    3. Утасны дугаар
    4. Байгалийн найрсаг монгол хэлээрх нийтийн коммент хариу
    5. Messenger-ээр явуулах дэлгэрэнгүй хувийн зурвас үүсгэх
    """
    extracted_phone = extract_phone_number(comment_text)
    api_key = settings.get("gemini_api_key", "").strip()
    system_prompt = settings.get("system_prompt", "")
    model_name = settings.get("gemini_model", "gemini-1.5-flash")

    # If no API key provided, use intelligent fallback rule-based system
    if not api_key:
        return fallback_rule_based_response(
            comment_text, sender_name, extracted_phone,
            custom_public_template or settings.get("default_public_reply", ""),
            custom_private_template or settings.get("default_private_reply", "")
        )

    prompt = f"""
Та Facebook хуудасны мэргэжлийн, найрсаг монгол зөвлөх туслах юм.
Дараах постын доор ирсэн хэрэглэгчийн комментыг шинжилж, JSON форматаар хариу өгнө үү.

[ПОСТЫН НЭР/СЭДЭВ]: {post_name}
[ХЭРЭГЛЭГЧИЙН НЭР]: {sender_name}
[КОММЕНТ]: "{comment_text}"

[СИСТЕМИЙН ЗААВАР / ДҮРЭМ]:
{system_prompt}

Та доорх JSON бүтцээр ЗӨВХӨН цэвэр JSON буцаана (markdown тэмдэглэгээгүй):
{{
  "sentiment": "positive" эсвэл "neutral" эсвэл "question" эсвэл "negative",
  "intent": "price_inquiry" эсвэл "delivery_inquiry" эсвэл "order_request" эсвэл "general_inquiry",
  "phone": "8 оронтой утасны дугаар эсвэл хоосон",
  "public_reply": "Коммент доор нийтэд харагдах 1-2 өгүүлбэр, эелдэг, дулаан өнгө аястай, Messenger чатаа шалгахыг уриалсан хариу",
  "private_reply": "Хэрэглэгчийн хувийн Messenger чат руу очих дэлгэрэнгүй, асуултад нь хариулсан, туслахад бэлэн хариу зурвас"
}}
"""

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.3,
                    "responseMimeType": "application/json"
                }
            }
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                text_content = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                # Clean possible markdown wrap
                if text_content.startswith("```json"):
                    text_content = text_content[7:]
                if text_content.endswith("```"):
                    text_content = text_content[:-3]
                
                result = json.loads(text_content.strip())
                if extracted_phone and not result.get("phone"):
                    result["phone"] = extracted_phone

                return {
                    "sentiment": result.get("sentiment", "neutral"),
                    "intent": result.get("intent", "general_inquiry"),
                    "phone": result.get("phone") or extracted_phone,
                    "public_reply": result.get("public_reply") or "Сайн байна уу! Дэлгэрэнгүйг чатаар илгээлээ 😊",
                    "private_reply": result.get("private_reply") or "Сайн байна уу! Танд туслахад бэлэн байна."
                }
            else:
                print(f"Gemini API error: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"AI Generation exception: {e}")

    # Fallback if AI fails or times out
    return fallback_rule_based_response(
        comment_text, sender_name, extracted_phone,
        custom_public_template or settings.get("default_public_reply", ""),
        custom_private_template or settings.get("default_private_reply", "")
    )


def fallback_rule_based_response(
    comment_text: str,
    sender_name: str,
    phone: Optional[str],
    public_template: str,
    private_template: str
) -> Dict[str, Any]:
    """API түлхүүр байхгүй эсвэл сүлжээ тасарсан үед ажиллах найдвартай ухаалаг fallback"""
    lower = comment_text.lower()
    
    # Sentiment & Intent checks
    if any(w in lower for w in ["үнэ", "une", "hed", "хэд", "hdsen", "үнэтэй"]):
        intent = "price_inquiry"
        sentiment = "question"
        public_reply = f"Сайн байна уу {sender_name}! Үнийн мэдээлэл болон урамшууллыг чатаар илгээлээ, та чатаа шалгаарай 😊"
        private_reply = f"Сайн байна уу {sender_name}! Манай бүтээгдэхүүний дэлгэрэнгүй үнийн санал болон боломжуудыг сонирхож байгаад баярлалаа. Танд тодруулах зүйл байвал чөлөөтэй асуугаарай."
    elif any(w in lower for w in ["хүргэлт", "hurgelt", "хаана", "haana", "орон нутаг"]):
        intent = "delivery_inquiry"
        sentiment = "question"
        public_reply = f"Сайн байна уу {sender_name}! Хүргэлтийн нөхцөлийн мэдээллийг чатаар хүргэлээ 🚚"
        private_reply = f"Сайн байна уу {sender_name}! Бид хот дотор болон хөдөө орон нутагт найдвартай хүргэлт хийж байна. Та хүлээн авах хаягаа үлдээнэ үү."
    elif phone or any(w in lower for w in ["авья", "avii", "zahirya", "захиалах", "авах"]):
        intent = "order_request"
        sentiment = "positive"
        public_reply = f"Баярлалаа {sender_name}! Захиалгыг бүртгэж чатаар баталгаажуулахаар мэдээлэл илгээлээ ✨"
        private_reply = f"Баярлалаа {sender_name}! Таны захиалгыг хүлээн авлаа. Манай менежер тантай удахгүй холбогдож баталгаажуулна."
    else:
        intent = "general_inquiry"
        sentiment = "neutral"
        public_reply = public_template or f"Сайн байна уу {sender_name}! Таны чат руу дэлгэрэнгүй мэдээлэл илгээлээ 😊"
        private_reply = private_template or f"Сайн байна уу {sender_name}! Манай хуудсанд хандсанд баярлалаа. Танд ямар чиглэлээр туслах вэ?"

    return {
        "sentiment": sentiment,
        "intent": intent,
        "phone": phone,
        "public_reply": public_reply,
        "private_reply": private_reply
    }
