import hmac
import hashlib
import httpx
from typing import Dict, Any, Optional

GRAPH_API_VERSION = "v19.0"
GRAPH_API_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

def verify_signature(raw_body: bytes, signature_header: str, app_secret: str) -> bool:
    """
    Facebook Webhook-оос ирсэн хүсэлтийн X-Hub-Signature-256-г шалгаж 
    жинхэнэ Meta-ийн сервэр мөн эсэхийг баталгаажуулна.
    """
    if not app_secret or not signature_header:
        # Хэрэв app secret тохируулаагүй бол (local dev үед) түр алгасна
        return True

    try:
        if not signature_header.startswith("sha256="):
            return False
        received_hash = signature_header.split("sha256=")[1]
        expected_hash = hmac.new(
            app_secret.encode('utf-8'),
            msg=raw_body,
            digestmod=hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(received_hash, expected_hash)
    except Exception as e:
        print(f"Signature verification error: {e}")
        return False

async def send_public_comment_reply(comment_id: str, message: str, access_token: str) -> Dict[str, Any]:
    """
    Постын коммент доор нийтэд харагдах хариулт үлдээх
    POST /{comment-id}/comments
    """
    if not access_token:
        print("[MOCK / SIMULATOR] Access Token байхгүй тул бодит коммент хариу илгээгдсэнгүй.")
        return {"id": f"mock_reply_{comment_id}", "status": "simulated"}

    url = f"{GRAPH_API_URL}/{comment_id}/comments"
    payload = {
        "message": message,
        "access_token": access_token
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload)
        data = resp.json()
        if resp.status_code != 200:
            print(f"Facebook Comment Reply Error: {resp.status_code} - {data}")
        return data

async def send_private_messenger_reply(comment_id: str, message: str, access_token: str) -> Dict[str, Any]:
    """
    Хэрэглэгчийн Messenger чат руу Private Reply илгээх
    POST /me/messages
    {
      "recipient": { "comment_id": comment_id },
      "message": { "text": message }
    }
    """
    if not access_token:
        print("[MOCK / SIMULATOR] Access Token байхгүй тул бодит чат зурвас илгээгдсэнгүй.")
        return {"recipient_id": "mock_recipient", "message_id": f"mock_msg_{comment_id}", "status": "simulated"}

    url = f"{GRAPH_API_URL}/me/messages"
    payload = {
        "recipient": {
            "comment_id": comment_id
        },
        "message": {
            "text": message
        },
        "access_token": access_token
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload)
        data = resp.json()
        if resp.status_code != 200:
            print(f"Facebook Private Reply Error: {resp.status_code} - {data}")
        return data
