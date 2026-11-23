import hmac
import hashlib
import httpx
from typing import Dict, Any, Optional

GRAPH_API_VERSION = "v19.0"
GRAPH_API_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

def verify_signature(raw_body: bytes, signature_header: str, app_secret: str) -> bool:
    """
    Facebook Webhook-оос ирсэн хүсэлтийн X-Hub-Signature-256-г шалгах
    """
    if not app_secret or not signature_header:
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
        print(f"[Error] Access token байхгүй байна.")
        return {"error": "Missing access token"}

    url = f"{GRAPH_API_URL}/{comment_id}/comments"
    params = {"access_token": access_token}
    payload = {"message": message}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, params=params, json=payload)
            data = resp.json()
            print(f"[Public Reply] Status: {resp.status_code}, CommentID: {comment_id}, Response: {data}")
            return data
    except Exception as e:
        print(f"[Public Reply Exception]: {e}")
        return {"error": str(e)}

async def send_private_messenger_reply(comment_id: str, message: str, access_token: str) -> Dict[str, Any]:
    """
    Хэрэглэгчийн Messenger чат руу Private Reply илгээх
    POST /me/messages
    """
    if not access_token:
        print(f"[Error] Access token байхгүй байна.")
        return {"error": "Missing access token"}

    url = f"{GRAPH_API_URL}/me/messages"
    params = {"access_token": access_token}
    payload = {
        "recipient": {
            "comment_id": comment_id
        },
        "message": {
            "text": message
        }
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, params=params, json=payload)
            data = resp.json()
            print(f"[Private Reply] Status: {resp.status_code}, CommentID: {comment_id}, Response: {data}")
            return data
    except Exception as e:
        print(f"[Private Reply Exception]: {e}")
        return {"error": str(e)}
