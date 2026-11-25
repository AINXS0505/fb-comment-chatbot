import hmac
import hashlib
import urllib.parse
import httpx
from typing import Dict, Any, Optional, List

GRAPH_API_VERSION = "v21.0"
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
    data = {"message": message}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, params=params, data=data)
            res_data = resp.json()
            print(f"[Public Reply] Status: {resp.status_code}, CommentID: {comment_id}, Response: {res_data}")
            return res_data
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
        "recipient": {"comment_id": comment_id},
        "message": {"text": message}
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, params=params, json=payload)
            res_data = resp.json()
            print(f"[Private Reply] Status: {resp.status_code}, CommentID: {comment_id}, Response: {res_data}")
            return res_data
    except Exception as e:
        print(f"[Private Reply Exception]: {e}")
        return {"error": str(e)}

async def send_direct_chat_reply(recipient_id: str, message: str, access_token: str) -> Dict[str, Any]:
    """
    Хэрэглэгчийн Messenger чат руу шууд хариулах (Direct Messenger Reply)
    POST /me/messages
    """
    if not access_token:
        print(f"[Error] Access token байхгүй байна.")
        return {"error": "Missing access token"}

    url = f"{GRAPH_API_URL}/me/messages"
    params = {"access_token": access_token}
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": message}
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, params=params, json=payload)
            res_data = resp.json()
            print(f"[Direct Chat Reply] Status: {resp.status_code}, Recipient: {recipient_id}, Response: {res_data}")
            return res_data
    except Exception as e:
        print(f"[Direct Chat Reply Exception]: {e}")
        return {"error": str(e)}

# --- NEW MULTI-PAGE PUBLISHING & DISTRIBUTION LOGIC ---

async def publish_post_to_page(
    page_id: str,
    access_token: str,
    message: str,
    media_type: str = "text",
    media_url: Optional[str] = None,
    link_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Facebook Page дээр зураг/постер, видео, эсвэл текст пост нийтлэх.
    - Image: POST /{page_id}/photos (url, caption)
    - Video: POST /{page_id}/videos (file_url, description)
    - Text/Link: POST /{page_id}/feed (message, link)
    """
    if not access_token:
        return {"success": False, "error": f"Page {page_id} access token missing"}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if media_type == "image" and media_url:
                url = f"{GRAPH_API_URL}/{page_id}/photos"
                payload = {
                    "url": media_url,
                    "caption": message,
                    "access_token": access_token
                }
                resp = await client.post(url, data=payload)
            elif media_type == "video" and media_url:
                url = f"{GRAPH_API_URL}/{page_id}/videos"
                payload = {
                    "file_url": media_url,
                    "description": message,
                    "access_token": access_token
                }
                resp = await client.post(url, data=payload)
            else:
                url = f"{GRAPH_API_URL}/{page_id}/feed"
                payload = {
                    "message": message,
                    "access_token": access_token
                }
                if link_url:
                    payload["link"] = link_url
                resp = await client.post(url, data=payload)

            data = resp.json()
            if resp.status_code == 200 and ("id" in data or "post_id" in data):
                raw_post_id = data.get("post_id") or data.get("id")
                clean_post_id = str(raw_post_id)
                if media_type == "video":
                    post_url = f"https://www.facebook.com/reel/{clean_post_id}/"
                elif media_type == "image":
                    post_url = f"https://www.facebook.com/photo.php?fbid={clean_post_id}" if "_" not in clean_post_id else f"https://www.facebook.com/{clean_post_id}"
                else:
                    post_url = f"https://www.facebook.com/{clean_post_id}" if "_" in clean_post_id else f"https://www.facebook.com/{page_id}/posts/{clean_post_id}"

                return {
                    "success": True,
                    "page_id": page_id,
                    "post_id": clean_post_id,
                    "post_url": post_url,
                    "raw_response": data
                }
            else:
                err_msg = data.get("error", {}).get("message", str(data))
                print(f"[Publish Error] Page {page_id}: {err_msg}")
                return {
                    "success": False,
                    "page_id": page_id,
                    "error": err_msg,
                    "status_code": resp.status_code
                }
    except Exception as e:
        print(f"[Publish Exception] Page {page_id}: {e}")
        return {"success": False, "page_id": page_id, "error": str(e)}

async def delete_facebook_post(post_id: str, access_token: str) -> Dict[str, Any]:
    """
    Нийтлэгдсэн постыг устгах
    DELETE /{post_id}
    """
    if not access_token:
        return {"success": False, "error": "Missing token"}
    url = f"{GRAPH_API_URL}/{post_id}"
    params = {"access_token": access_token}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(url, params=params)
            return resp.json()
    except Exception as e:
        return {"success": False, "error": str(e)}

async def post_to_facebook_group(group_id: str, access_token: str, message: str, link_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Facebook Group рүү Graph API-аар пост нийтлэх (Хэрэв тухайн группт апп холбогдсон эсвэл эрх олгогдсон бол)
    POST /{group_id}/feed
    """
    if not access_token:
        return {"success": False, "error": "Missing token"}
    url = f"{GRAPH_API_URL}/{group_id}/feed"
    payload = {
        "message": message,
        "access_token": access_token
    }
    if link_url:
        payload["link"] = link_url
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, data=payload)
            data = resp.json()
            if resp.status_code == 200 and "id" in data:
                return {"success": True, "post_id": data["id"]}
            return {"success": False, "error": data.get("error", {}).get("message", str(data))}
    except Exception as e:
        return {"success": False, "error": str(e)}

def build_group_share_links(post_url: str, caption: str, groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Смарт 1-товшилтын групп хуваалцах линкүүд үүсгэх
    """
    encoded_url = urllib.parse.quote(post_url)
    encoded_quote = urllib.parse.quote(caption[:300] if caption else "")
    general_share_url = f"https://www.facebook.com/sharer/sharer.php?u={encoded_url}&quote={encoded_quote}"

    results = []
    for g in groups:
        gid_or_url = g.get("group_url") or g.get("group_id") or ""
        group_web_url = gid_or_url if gid_or_url.startswith("http") else f"https://www.facebook.com/groups/{gid_or_url}"
        results.append({
            "id": g.get("id"),
            "name": g.get("group_name", "Facebook Group"),
            "group_url": group_web_url,
            "direct_share_url": general_share_url,
            "category": g.get("category", "Кино / Драма")
        })
    return results
