import os
import sys
import csv
import io
import json
import httpx
import asyncio
from pathlib import Path
from fastapi import FastAPI, Request, Response, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from api import database
from api import ai_service
from api import facebook_service

app = FastAPI(title="Facebook Comment AI Bot & CRM", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize DB on module load
database.init_db()

# Load Dashboard HTML safely
def get_dashboard_html() -> str:
    possible_paths = [
        BASE_DIR / "templates" / "index.html",
        Path("templates/index.html"),
        Path("/var/task/templates/index.html"),
        Path(__file__).parent.parent / "templates" / "index.html"
    ]
    for p in possible_paths:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                pass
    return "<h1>Admin Dashboard</h1><p>Template loading fallback.</p>"

# --- WEB UI ROUTES ---
@app.get("/", response_class=HTMLResponse)
@app.get("/api", response_class=HTMLResponse)
@app.get("/api/index", response_class=HTMLResponse)
@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    return HTMLResponse(content=get_dashboard_html())

@app.get("/privacy", response_class=HTMLResponse)
@app.get("/terms", response_class=HTMLResponse)
async def privacy_policy():
    possible_paths = [
        BASE_DIR / "templates" / "privacy.html",
        Path("templates/privacy.html"),
        Path("/var/task/templates/privacy.html"),
        Path(__file__).parent.parent / "templates" / "privacy.html"
    ]
    for p in possible_paths:
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Privacy Policy</h1><p>https://www.huree.site</p>")

# --- FACEBOOK WEBHOOK ENDPOINTS ---
@app.get("/api/webhook")
@app.get("/webhook")
async def verify_fb_webhook(request: Request):
    """
    Facebook Webhook баталгаажуулах GET хүсэлт
    """
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    settings = database.get_settings()
    expected_token = settings.get("fb_verify_token")

    if mode == "subscribe" and token == expected_token:
        print(f"[Facebook Webhook] Амжилттай баталгаажлаа! Challenge: {challenge}")
        return Response(content=challenge, media_type="text/plain")

    print(f"[Facebook Webhook] Баталгаажуулалт амжилтгүй. Ирсэн: {token}, Хүлээж буй: {expected_token}")
    return Response(content="Forbidden", status_code=403)


@app.post("/api/webhook")
@app.post("/webhook")
async def receive_fb_webhook(request: Request):
    """
    Facebook-ээс коммент болон мессежийн өөрчлөлт ирэх POST хүсэлт.
    Vercel serverless орчинд ажиллахын тулд synchronously await хийж гүйцэтгэнэ.
    """
    raw_body = await request.body()
    settings = database.get_settings()

    try:
        body = await request.json()
        print(f"[Webhook Event Received]: {json.dumps(body)}")
    except Exception:
        return Response(content="Invalid JSON", status_code=400)

    # Serverless дээр background task хөлддөг тул шууд await хийж гүйцэтгэнэ
    try:
        await process_webhook_event(body, settings)
    except Exception as e:
        print(f"[Webhook Process Error]: {e}")

    return Response(content="EVENT_RECEIVED", status_code=200)


async def process_webhook_event(body: Dict[str, Any], settings: Dict[str, str]):
    """
    Ирсэн Facebook үйл явдлыг шалгаж, коммент мөн бол шууд хариулах функц
    """
    if body.get("object") != "page":
        return

    default_public_reply = settings.get("default_public_reply", ai_service.HUREE_COMMENT_REPLY)
    default_private_reply = settings.get("default_private_reply", ai_service.HUREE_PROMO_TEXT)

    for entry in body.get("entry", []):
        page_id = str(entry.get("id"))
        # Тухайн хуудасны Page Access Token-г дуудах
        page_token = database.get_page_token(page_id) or settings.get("fb_page_access_token", "")

        # --- 1. DIRECT MESSENGER CHAT (Шууд Messenger чатаар ирсэн зурваст хариулах) ---
        for msg_event in entry.get("messaging", []):
            sender_id = str(msg_event.get("sender", {}).get("id") or "")
            if sender_id == page_id or not sender_id:
                continue
            msg_obj = msg_event.get("message", {})
            if msg_obj.get("is_echo"):
                continue
            msg_id = str(msg_obj.get("mid") or "")
            msg_text = str(msg_obj.get("text") or "").strip()
            if not msg_text or not msg_id:
                continue

            if database.is_comment_processed(msg_id):
                continue

            print(f"[Processing Direct Messenger]: Page: {page_id}, Sender: {sender_id}, Text: {msg_text}")
            analysis = await ai_service.analyze_and_generate_replies(
                comment_text=msg_text,
                sender_name="Үйлчлүүлэгч",
                post_name="Facebook Messenger Чаат",
                settings=settings,
                custom_public_template=default_public_reply,
                custom_private_template=default_private_reply
            )
            chat_reply_msg = analysis.get("private_reply") or default_private_reply

            if page_token:
                await facebook_service.send_direct_chat_reply(
                    recipient_id=sender_id,
                    message=chat_reply_msg,
                    access_token=page_token
                )

            database.log_comment(
                comment_id=msg_id,
                post_id="direct_chat",
                sender_id=sender_id,
                sender_name="Чат хэрэглэгч",
                comment_text=msg_text,
                sentiment=analysis.get("sentiment", "neutral"),
                intent=analysis.get("intent", "chat_query"),
                public_reply="[Direct Messenger Chat]",
                private_reply=chat_reply_msg,
                phone=analysis.get("phone")
            )

        # --- 2. POST COMMENTS (Постын коммент дээр хариулах) ---
        for change in entry.get("changes", []):
            field = change.get("field")
            val = change.get("value", {})

            # Зөвхөн коммент мөн эсэхийг шалгах (item == comment эсвэл comment_id байгаа эсэх)
            is_comment = (val.get("item") == "comment") or ("comment_id" in val)
            verb = val.get("verb", "add")

            if is_comment and verb in ["add", "edited", None]:
                comment_id = str(val.get("comment_id") or val.get("id") or "")
                post_id = str(val.get("post_id") or "default_all")
                sender = val.get("from", {})
                sender_id = str(sender.get("id") or "")
                sender_name = sender.get("name", "Үйлчлүүлэгч")
                comment_text = str(val.get("message") or "").strip()

                if not comment_id:
                    continue

                # Хуудасны өөрийн комментод хариулж loop үүсгэхээс сэргийлэх
                if sender_id == page_id:
                    continue

                # Ботын өөрийн хариулсан комментод давхар хариулж loop үүсгэхээс сэргийлэх
                if "huree.site" in comment_text.lower() or "чатаар тань илгээлээ" in comment_text:
                    print(f"[Skip self bot reply]: {comment_id}")
                    continue

                # Давхардаж боловсруулагдахаас сэргийлэх (Deduplication)
                if database.is_comment_processed(comment_id):
                    print(f"[Skip already processed comment]: {comment_id}")
                    continue

                print(f"[Processing Comment]: Page: {page_id}, CommentID: {comment_id}, User: {sender_name}, Text: {comment_text}")

                # AI шинжилгээ болон утасны дугаар шалгах
                analysis = await ai_service.analyze_and_generate_replies(
                    comment_text=comment_text,
                    sender_name=sender_name,
                    post_name="Хүрээ Кино",
                    settings=settings,
                    custom_public_template=default_public_reply,
                    custom_private_template=default_private_reply
                )

                public_reply_msg = analysis.get("public_reply") or default_public_reply
                private_reply_msg = analysis.get("private_reply") or default_private_reply

                # 1. Нийтийн коммент хариу илгээх (Public Comment Reply)
                if page_token:
                    pub_res = await facebook_service.send_public_comment_reply(
                        comment_id=comment_id,
                        message=public_reply_msg,
                        access_token=page_token
                    )
                    print(f"[Public Reply Result]: {pub_res}")

                # 2. Хувийн чатаар зурвас илгээх (Private Reply)
                if page_token:
                    priv_res = await facebook_service.send_private_messenger_reply(
                        comment_id=comment_id,
                        message=private_reply_msg,
                        access_token=page_token
                    )
                    print(f"[Private Reply Result]: {priv_res}")

                # 3. Өгөгдлийн санд бүртгэх
                database.log_comment(
                    comment_id=comment_id,
                    post_id=post_id,
                    sender_id=sender_id,
                    sender_name=sender_name,
                    comment_text=comment_text,
                    sentiment=analysis.get("sentiment", "neutral"),
                    intent=analysis.get("intent", "movie_link"),
                    public_reply=public_reply_msg,
                    private_reply=private_reply_msg,
                    phone=analysis.get("phone")
                )


# --- REST API ENDPOINTS FOR DASHBOARD ---
@app.get("/api/pages")
@app.get("/pages")
async def get_pages():
    return database.get_connected_pages()

@app.get("/api/stats")
@app.get("/stats")
async def get_stats():
    return database.get_dashboard_stats()

@app.get("/api/comments")
@app.get("/comments")
async def get_comments(limit: int = 50):
    return database.get_recent_comments(limit)

@app.get("/api/rules")
@app.get("/rules")
async def get_rules():
    return database.get_post_rules()

class PostRuleSchema(BaseModel):
    id: Optional[int] = None
    post_id: str
    post_name: str
    keywords: Optional[str] = ""
    public_reply_template: Optional[str] = ""
    private_reply_template: Optional[str] = ""
    use_ai: Optional[int] = 1
    is_active: Optional[int] = 1

@app.post("/api/rules")
@app.post("/rules")
async def save_rule(rule: PostRuleSchema):
    rule_id = database.save_post_rule(rule.dict())
    return {"status": "ok", "rule_id": rule_id}

@app.delete("/api/rules/{rule_id}")
@app.delete("/rules/{rule_id}")
async def delete_rule(rule_id: int):
    database.delete_post_rule(rule_id)
    return {"status": "ok"}

@app.get("/api/leads")
@app.get("/leads")
async def get_leads(limit: int = 50):
    return database.get_leads(limit)

class LeadStatusSchema(BaseModel):
    status: str
    notes: Optional[str] = ""

@app.post("/api/leads/{lead_id}/status")
@app.post("/leads/{lead_id}/status")
async def update_lead(lead_id: int, payload: LeadStatusSchema):
    database.update_lead_status(lead_id, payload.status, payload.notes or "")
    return {"status": "ok"}

@app.get("/api/leads/export-csv")
@app.get("/leads/export-csv")
async def export_leads_csv():
    leads = database.get_leads(limit=1000)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Хэрэглэгчийн Нэр", "Утасны Дугаар", "Коммент", "Төлөв", "Тэмдэглэл", "Огноо"])
    for l in leads:
        writer.writerow([l["id"], l["sender_name"], l["phone_number"], l["comment_text"], l["status"], l["notes"], l["created_at"]])
    
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads_export.csv"}
    )

@app.get("/api/settings")
@app.get("/settings")
async def get_settings():
    return database.get_settings()

@app.post("/api/settings")
@app.post("/settings")
async def update_settings(payload: Dict[str, Any]):
    database.update_settings(payload)
    return {"status": "ok"}

# --- MOBILE REMOTE COMMAND & AUTO-SYNC ENDPOINTS ---
@app.get("/api/sync-comments")
@app.post("/api/sync-comments")
@app.get("/sync-comments")
@app.post("/sync-comments")
async def sync_recent_comments(limit: int = 1):
    """
    Гар утаснаас эсвэл автомат цагаар сүүлийн постын комментуудыг шалгаж 
    хариулаагүй үлдсэн комментууд руу шууд хариу илгээх функц (Хурдан 5-8 сек-д багтана)
    """
    settings = database.get_settings()
    pages = database.get_connected_pages()
    results = []

    default_pub = settings.get("default_public_reply", ai_service.HUREE_COMMENT_REPLY)
    default_priv = settings.get("default_private_reply", ai_service.HUREE_PROMO_TEXT)

    async with httpx.AsyncClient(timeout=8.0) as client:
        for p in pages:
            page_id = p["page_id"]
            page_token = p["access_token"]
            page_name = p["page_name"]

            try:
                # 1. Сүүлийн нийтлэгдсэн постууд болон видео/reels-г зэрэг авах
                all_target_nodes = []
                posts_res = await client.get(
                    f"https://graph.facebook.com/v21.0/{page_id}/posts",
                    params={"limit": limit, "access_token": page_token}
                )
                if posts_res.status_code == 200:
                    all_target_nodes.extend(posts_res.json().get("data", []))

                vids_res = await client.get(
                    f"https://graph.facebook.com/v21.0/{page_id}/videos",
                    params={"limit": limit, "access_token": page_token}
                )
                if vids_res.status_code == 200:
                    all_target_nodes.extend(vids_res.json().get("data", []))

                for post in all_target_nodes:
                    post_id = post["id"]
                    # 2. Тухайн постын сүүлийн 5 комментыг авах
                    comm_res = await client.get(
                        f"https://graph.facebook.com/v21.0/{post_id}/comments",
                        params={"limit": 5, "access_token": page_token}
                    )
                    comments = comm_res.json().get("data", [])

                    for c in comments:
                        cid = c["id"]
                        msg = c.get("message", "").strip()
                        sender = c.get("from", {})
                        sid = str(sender.get("id") or "")
                        sname = sender.get("name", "Үйлчлүүлэгч")

                        # Өөрийн хуудасны коммент болон өөрийн хариуг алгасах
                        if sid == page_id or "huree.site" in msg.lower() or "чатаар тань илгээлээ" in msg:
                            continue

                        # Хэрэв өмнө нь боловсруулагдаагүй бол шууд хариулах
                        if not database.is_comment_processed(cid):
                            # Нийтийн коммент хариу
                            await facebook_service.send_public_comment_reply(cid, default_pub, page_token)
                            # Messenger чат хариу
                            await facebook_service.send_private_messenger_reply(cid, default_priv, page_token)

                            database.log_comment(
                                comment_id=cid,
                                post_id=post_id,
                                sender_id=sid,
                                sender_name=sname,
                                comment_text=msg,
                                sentiment="positive",
                                intent="movie_link",
                                public_reply=default_pub,
                                private_reply=default_priv,
                                phone=ai_service.extract_phone_number(msg)
                            )
                            results.append({"comment_id": cid, "message": msg, "status": "replied"})
            except Exception as e:
                print(f"Sync error for {page_name}: {e}")

    return {"status": "ok", "new_replies_sent": len(results), "details": results}

@app.get("/api/command")
@app.post("/api/command")
@app.get("/command")
@app.post("/command")
async def execute_mobile_command(
    set_price_single: Optional[str] = None,
    set_price_all: Optional[str] = None,
    set_link: Optional[str] = None,
    set_public_reply: Optional[str] = None,
    bot_enabled: Optional[str] = None
):
    """
    Гар утаснаас URL эсвэл параметрээр комманд өгч тохиргоог шууд өөрчлөх
    """
    settings = database.get_settings()
    updates = {}

    if bot_enabled is not None:
        updates["bot_enabled"] = "true" if bot_enabled.lower() in ["true", "1", "on"] else "false"

    if set_public_reply:
        updates["default_public_reply"] = set_public_reply

    if set_price_single or set_price_all or set_link:
        link = set_link or "https://www.huree.site"
        p_single = set_price_single or "3,900₮"
        p_all = set_price_all or "15,900₮"

        updates["default_private_reply"] = (
            f"Сайн байна уу! 🎬🍿\n\n"
            f"{link} энэ сайтаар ороод бүртгүүлээд Монгол хэлтэй чанартай бичлэгтэй 1000+ кино Хүрээ дээр бий!\n\n"
            f"🔹 1 кино — {p_single}\n"
            f"🔹 Бүх кино — {p_all}\n\n"
            f"QPay-ээр төлөөд үзэх эрхээ шууд нээгээрэй. Өдөр бүр шинэ кино нэмэгдэнэ! ✨"
        )

    if updates:
        database.update_settings(updates)

    return {"status": "ok", "applied_commands": updates, "current_settings": database.get_settings()}

class SimulateRequest(BaseModel):
    sender_name: str
    post_name: str
    comment_text: str

@app.post("/api/simulate")
@app.post("/simulate")
async def test_simulate(payload: SimulateRequest):
    settings = database.get_settings()
    analysis = await ai_service.analyze_and_generate_replies(
        comment_text=payload.comment_text,
        sender_name=payload.sender_name,
        post_name=payload.post_name,
        settings=settings
    )

    mock_comment_id = f"sim_{int(os.times().system * 1000)}"
    database.log_comment(
        comment_id=mock_comment_id,
        post_id="simulator_test",
        sender_id="mock_user_1",
        sender_name=payload.sender_name,
        comment_text=payload.comment_text,
        sentiment=analysis.get("sentiment", "neutral"),
        intent=analysis.get("intent", "movie_link"),
        public_reply=analysis.get("public_reply", ""),
        private_reply=analysis.get("private_reply", ""),
        phone=analysis.get("phone")
    )

    return analysis

# --- MULTI-PAGE PUBLISHING & SMART VIRAL DISTRIBUTION ENDPOINTS ---

class MultiPublishRequest(BaseModel):
    page_ids: List[str]  # List of page IDs, or ["all"]
    message: str
    media_type: Optional[str] = "text"  # "text", "image", "video"
    media_url: Optional[str] = None
    link_url: Optional[str] = "https://www.huree.site"
    boost_preset: Optional[str] = "standard"  # "standard", "vip", "chat_cta", "qpay_fast", "custom"
    auto_create_rule: Optional[bool] = True
    custom_public_reply: Optional[str] = None
    custom_private_reply: Optional[str] = None

@app.post("/api/publish-multi")
@app.post("/publish-multi")
async def publish_multi_pages(payload: MultiPublishRequest):
    """
    Сонгосон бүх Facebook хуудсуудад нэг зэрэг зураг/постер, видео, текст нийтлэх,
    тус бүрд нь комманд өгч тохируулах ба группын автомат share линкүүд үүсгэх.
    """
    settings = database.get_settings()
    all_pages = database.get_connected_pages()

    # Сонгогдсон хуудсуудыг шүүх
    if "all" in payload.page_ids or len(payload.page_ids) == 0:
        target_pages = all_pages
    else:
        target_ids = [str(x) for x in payload.page_ids]
        target_pages = [p for p in all_pages if str(p["page_id"]) in target_ids]

    if not target_pages:
        raise HTTPException(status_code=400, detail="Нийтлэх хуудас сонгогдоогүй байна.")

    # Message formatting by boost preset
    final_message = payload.message.strip()
    if payload.boost_preset == "standard":
        if "huree.site" not in final_message.lower():
            final_message += "\n\n🎬 Үзэх холбоос: https://www.huree.site (1 кино 3,900₮ | Бүх кино 15,900₮ QPay)"
    elif payload.boost_preset == "vip":
        if "huree.site" not in final_message.lower():
            final_message += "\n\n🔥 VIP киноны эрхээ QPay-ээр шуурхай нээн үзээрэй: https://www.huree.site (1000+ кино бэлэн)"
    elif payload.boost_preset == "chat_cta":
        final_message += "\n\n💬 Кино үзэх холбоосыг шууд авахын тулд доор 'Үзэх' гэж коммент бичээрэй! Манай AI бот чатаар шууд илгээнэ 🍿✨"
    elif payload.boost_preset == "qpay_fast":
        final_message += "\n\n⚡ QPay-ээр шууд төлөөд 1 кино 3,900₮, бүх кино 15,900₮-өөр үзээрэй: https://www.huree.site"

    # Auto-reply templates to bind to this post
    pub_reply = payload.custom_public_reply or "Сайн байна уу! Кино үзэх холбоос болон үнийн дэлгэрэнгүйг хувийн чатаар тань илгээлээ. Та чатаа шалгаарай 🍿✨"
    if payload.boost_preset == "vip":
        priv_reply = (
            "Сайн байна уу! 🔥\n\n"
            "VIP киноны урамшуулал зарлагдлаа! https://www.huree.site сайтаар ороод 1000+ киноноос хүссэнээ үзээрэй.\n\n"
            "🔹 1 кино — 3,900₮\n"
            "🔹 Бүх кино — 15,900₮\n\n"
            "QPay-ээр шууд төлөөд эрхээ нээнэ үү! 🎬✨"
        )
    else:
        priv_reply = payload.custom_private_reply or settings.get("default_private_reply", database.HUREE_PROMO_TEXT)

    results = []
    first_post_url = ""

    for page in target_pages:
        pid = str(page["page_id"])
        pname = page["page_name"]
        token = page["access_token"]

        pub_res = await facebook_service.publish_post_to_page(
            page_id=pid,
            access_token=token,
            message=final_message,
            media_type=payload.media_type or "text",
            media_url=payload.media_url,
            link_url=payload.link_url
        )

        if pub_res.get("success"):
            post_id = pub_res["post_id"]
            post_url = pub_res["post_url"]
            if not first_post_url:
                first_post_url = post_url

            # Record into published_posts database
            database.save_published_post(
                page_id=pid,
                page_name=pname,
                post_id=post_id,
                post_url=post_url,
                message=final_message,
                media_type=payload.media_type or "text",
                media_url=payload.media_url,
                boost_command=payload.boost_preset
            )

            # Auto create rule for this post ID so comments are auto-replied!
            if payload.auto_create_rule:
                database.save_post_rule({
                    "post_id": post_id,
                    "post_name": f"{pname} - Шинэ пост ({datetime.now().strftime('%m/%d %H:%M')})",
                    "keywords": "үргэлжлэл,хэд,үнэ,үзэх,линк,хаана,кино,сонирхож,байна,багц,qpay",
                    "public_reply_template": pub_reply,
                    "private_reply_template": priv_reply,
                    "use_ai": 1,
                    "is_active": 1
                })

            results.append({
                "success": True,
                "page_id": pid,
                "page_name": pname,
                "post_id": post_id,
                "post_url": post_url
            })
        else:
            results.append({
                "success": False,
                "page_id": pid,
                "page_name": pname,
                "error": pub_res.get("error", "Failed to publish")
            })

    # Group Share Links for viral group distribution
    groups = database.get_facebook_groups()
    share_url_target = first_post_url or (results[0].get("post_url") if results and results[0].get("success") else "https://www.huree.site")
    group_shares = facebook_service.build_group_share_links(share_url_target, final_message, groups)

    return {
        "status": "ok",
        "published_count": sum(1 for r in results if r.get("success")),
        "total_targets": len(target_pages),
        "results": results,
        "first_post_url": share_url_target,
        "group_shares": group_shares
    }

# --- DIRECT BROWSER-TO-FACEBOOK RESUMABLE CHUNKED UPLOAD (500MB+ SUPPORT) ---

class VideoUploadStartRequest(BaseModel):
    file_size: int
    page_id: Optional[str] = "2159494444293875" # Default to Huree Kino

@app.post("/api/video-upload/start")
@app.post("/video-upload/start")
async def start_video_upload_endpoint(payload: VideoUploadStartRequest):
    """
    Хөтчөөс Facebook рүү шууд 500MB+ видео хэсэгчлэн (Chunked) хуулах сесс эхлүүлэх
    """
    all_pages = database.get_connected_pages()
    primary = next((p for p in all_pages if str(p["page_id"]) == str(payload.page_id)), None)
    if not primary:
        primary = all_pages[0] if all_pages else None
    if not primary:
        raise HTTPException(status_code=400, detail="Холбогдсон хуудас олдсонгүй")

    pid = str(primary["page_id"])
    tok = primary["access_token"]

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"https://graph.facebook.com/v21.0/{pid}/videos",
            data={
                "upload_phase": "start",
                "file_size": payload.file_size,
                "access_token": tok
            }
        )
        data = resp.json()
        if "upload_session_id" in data:
            return {
                "success": True,
                "page_id": pid,
                "access_token": tok,
                "video_id": data.get("video_id"),
                "upload_session_id": data["upload_session_id"],
                "start_offset": int(data.get("start_offset", 0)),
                "end_offset": int(data.get("end_offset", 10485760))
            }
        else:
            raise HTTPException(status_code=400, detail=data.get("error", {}).get("message", str(data)))

class VideoUploadFinishRequest(BaseModel):
    primary_page_id: str
    upload_session_id: str
    video_id: str
    target_page_ids: List[str]
    message: str
    boost_preset: Optional[str] = "standard"
    auto_create_rule: Optional[bool] = True
    custom_public_reply: Optional[str] = None
    custom_private_reply: Optional[str] = None

@app.post("/api/video-upload/finish-and-replicate")
@app.post("/video-upload/finish-and-replicate")
async def finish_and_replicate_video_endpoint(payload: VideoUploadFinishRequest):
    """
    Үндсэн хуудсанд бүрэн хуулагдсан 500MB видеог баталгаажуулж,
    Facebook-ийн дотоод өндөр хурдны CDN-ээр бусад хуудсуудад 2 секундэд түгээх
    """
    all_pages = database.get_connected_pages()
    primary = next((p for p in all_pages if str(p["page_id"]) == str(payload.primary_page_id)), None)
    if not primary:
        primary = all_pages[0]
    pid = str(primary["page_id"])
    pname = primary["page_name"]
    tok = primary["access_token"]

    # Message formatting
    final_message = payload.message.strip()
    if payload.boost_preset == "standard" and "huree.site" not in final_message.lower():
        final_message += "\n\n🎬 Үзэх холбоос: https://www.huree.site (1 кино 3,900₮ | Бүх кино 15,900₮ QPay)"
    elif payload.boost_preset == "vip" and "huree.site" not in final_message.lower():
        final_message += "\n\n🔥 VIP киноны эрхээ QPay-ээр шуурхай нээн үзээрэй: https://www.huree.site (1000+ кино бэлэн)"
    elif payload.boost_preset == "chat_cta":
        final_message += "\n\n💬 Кино үзэх холбоосыг шууд авахын тулд доор 'Үзэх' гэж коммент бичээрэй! Манай AI бот чатаар шууд илгээнэ 🍿✨"
    elif payload.boost_preset == "qpay_fast":
        final_message += "\n\n⚡ QPay-ээр шууд төлөөд 1 кино 3,900₮, бүх кино 15,900₮-өөр үзээрэй: https://www.huree.site"

    # Finish upload on primary page
    async with httpx.AsyncClient(timeout=30.0) as client:
        await client.post(
            f"https://graph.facebook.com/v21.0/{pid}/videos",
            data={
                "upload_phase": "finish",
                "upload_session_id": payload.upload_session_id,
                "description": final_message,
                "access_token": tok
            }
        )

    primary_post_url = f"https://www.facebook.com/reel/{payload.video_id}/"
    database.save_published_post(
        page_id=pid,
        page_name=pname,
        post_id=payload.video_id,
        post_url=primary_post_url,
        message=final_message,
        media_type="video",
        boost_command=payload.boost_preset or "standard"
    )

    # Auto-create rule for primary post
    settings = database.get_settings()
    if payload.auto_create_rule:
        pub_reply = payload.custom_public_reply or settings.get("default_public_reply", "Сайн байна уу! Чатаар дэлгэрэнгүй мэдээлэл болон үзэх линк илгээлээ.")
        priv_reply = payload.custom_private_reply or settings.get("default_private_reply", database.HUREE_PROMO_TEXT)
        database.save_post_rule({
            "post_id": payload.video_id,
            "post_name": f"{pname} - Шинэ видео ({datetime.now().strftime('%m/%d %H:%M')})",
            "keywords": "үргэлжлэл,хэд,үнэ,үзэх,линк,хаана,кино,сонирхож,байна,багц,qpay",
            "public_reply_template": pub_reply,
            "private_reply_template": priv_reply,
            "use_ai": 1,
            "is_active": 1
        })

    results = [{
        "success": True,
        "page_id": pid,
        "page_name": pname,
        "post_id": payload.video_id,
        "post_url": primary_post_url
    }]

    # Target pages filter
    target_ids = [str(x) for x in payload.target_page_ids]
    if "all" in target_ids:
        remaining_pages = [p for p in all_pages if str(p["page_id"]) != pid]
    else:
        remaining_pages = [p for p in all_pages if str(p["page_id"]) in target_ids and str(p["page_id"]) != pid]

    # Explicitly whitelist all target pages on Meta for crossposting
    try:
        allow_payload = [{"page_id": str(p["page_id"]), "allow": True} for p in remaining_pages]
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"https://graph.facebook.com/v21.0/{payload.video_id}",
                data={
                    "allow_crossposting_for_pages": json.dumps(allow_payload),
                    "access_token": tok
                }
            )
    except Exception as allow_err:
        print(f"[Allow Crossposting Warning]: {allow_err}")

    # Replicate instantly across all selected pages using Facebook Native Crossposting API (<1s per page, handles 500MB+)
    async with httpx.AsyncClient(timeout=30.0) as client:
        for p in remaining_pages:
            r_pid = str(p["page_id"])
            r_name = p["page_name"]
            r_tok = p["access_token"]

            r_post_id = None
            err_msg = None

            try:
                cp_res = await client.post(
                    f"https://graph.facebook.com/v21.0/{r_pid}/videos",
                    data={
                        "crossposted_video_id": payload.video_id,
                        "description": final_message,
                        "access_token": r_tok
                    }
                )
                cp_data = cp_res.json()
                if cp_res.status_code == 200 and ("id" in cp_data or "post_id" in cp_data):
                    r_post_id = str(cp_data.get("post_id") or cp_data.get("id"))
                else:
                    raw_err = cp_data.get("error", {}).get("message", "Crosspost failed")
                    if "No permission due to music rights" in raw_err:
                        err_msg = "Meta дууны эрх илрүүлсэн тул зөвхөн Facebook сайт дээрээс Share хийж болно"
                    else:
                        err_msg = raw_err
            except Exception as e:
                err_msg = str(e)

            if r_post_id:
                r_post_url = f"https://www.facebook.com/reel/{r_post_id}/"
                database.save_published_post(
                    page_id=r_pid,
                    page_name=r_name,
                    post_id=r_post_id,
                    post_url=r_post_url,
                    message=final_message,
                    media_type="video",
                    boost_command=payload.boost_preset or "standard"
                )
                if payload.auto_create_rule:
                    database.save_post_rule({
                        "post_id": r_post_id,
                        "post_name": f"{r_name} - Шинэ видео ({datetime.now().strftime('%m/%d %H:%M')})",
                        "keywords": "үргэлжлэл,хэд,үнэ,үзэх,линк,хаана,кино,сонирхож,байна,багц,qpay",
                        "public_reply_template": pub_reply,
                        "private_reply_template": priv_reply,
                        "use_ai": 1,
                        "is_active": 1
                    })
                results.append({
                    "success": True,
                    "page_id": r_pid,
                    "page_name": r_name,
                    "post_id": r_post_id,
                    "post_url": r_post_url
                })
            else:
                results.append({
                    "success": False,
                    "page_id": r_pid,
                    "page_name": r_name,
                    "error": err_msg or "Failed to replicate"
                })

    groups = database.get_facebook_groups()
    group_shares = facebook_service.build_group_share_links(primary_post_url, final_message, groups)

    return {
        "status": "ok",
        "published_count": sum(1 for r in results if r.get("success")),
        "total_targets": len(results),
        "results": results,
        "first_post_url": primary_post_url,
        "group_shares": group_shares
    }


@app.get("/api/post-metrics/{post_id}")
@app.get("/post-metrics/{post_id}")
async def get_post_metrics_endpoint(post_id: str, page_id: Optional[str] = None):
    """
    Facebook Graph API-аас постын бодит үзэлт (views), лайк (likes),
    сэтгэгдэл (comments), видео төлвийг шууд татаж авах
    """
    all_pages = database.get_connected_pages()
    tok = None
    if page_id:
        p = next((x for x in all_pages if str(x["page_id"]) == str(page_id)), None)
        if p:
            tok = p["access_token"]
    if not tok:
        tok = all_pages[0]["access_token"]

    clean_post_id = post_id.split("_")[-1] if "_" in post_id else post_id

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            url = f"https://graph.facebook.com/v21.0/{clean_post_id}"
            params = {
                "fields": "id,views,likes.summary(true),comments.summary(true),status",
                "access_token": tok
            }
            res = await client.get(url, params=params)
            if res.status_code == 200:
                data = res.json()
                views = data.get("views", 0)
                likes = data.get("likes", {}).get("summary", {}).get("total_count", 0)
                comments = data.get("comments", {}).get("summary", {}).get("total_count", 0)
                v_status = data.get("status", {}).get("video_status", "ready")
                return {
                    "success": True,
                    "post_id": clean_post_id,
                    "views": views,
                    "likes": likes,
                    "comments": comments,
                    "video_status": v_status
                }
            else:
                return {"success": False, "error": res.text, "views": 0, "likes": 0, "comments": 0}
        except Exception as e:
            return {"success": False, "error": str(e), "views": 0, "likes": 0, "comments": 0}


class ReCrosspostRequest(BaseModel):
    video_id: str
    target_page_ids: List[str]
    message: Optional[str] = ""
    boost_preset: Optional[str] = "standard"
    auto_create_rule: Optional[bool] = True

@app.post("/api/crosspost-existing")
@app.post("/crosspost-existing")
async def crosspost_existing_endpoint(payload: ReCrosspostRequest):
    """
    Өмнө нийтлэгдсэн бичлэгийг дахин татаж хуулахгүйгээр Facebook Crossposting API-аар
    сонгосон бусад хуудсуудад 0.5 секундэд шууд нийтлэх
    """
    all_pages = database.get_connected_pages()
    clean_vid_id = payload.video_id.split("_")[-1] if "_" in payload.video_id else payload.video_id

    msg = (payload.message or "").strip()
    if not msg:
        p_tok = all_pages[0]["access_token"]
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                g_res = await client.get(f"https://graph.facebook.com/v21.0/{clean_vid_id}", params={"fields": "description", "access_token": p_tok})
                if g_res.status_code == 200:
                    msg = g_res.json().get("description", "")
            except Exception:
                pass
    if not msg:
        msg = "🎬✨ ШИНЭ КИНО: Үзэх холбоос: https://www.huree.site (1 кино 3,900₮ | Бүх кино 15,900₮ QPay)"

    target_ids = [str(x) for x in payload.target_page_ids]
    if "all" in target_ids:
        pages_to_post = all_pages
    else:
        pages_to_post = [p for p in all_pages if str(p["page_id"]) in target_ids]

    results = []
    settings = database.get_settings()
    pub_reply = settings.get("default_public_reply", "Сайн байна уу! Чатаар дэлгэрэнгүй мэдээлэл болон үзэх линк илгээлээ.")
    priv_reply = settings.get("default_private_reply", database.HUREE_PROMO_TEXT)

    # Whitelist pages on Meta before crossposting
    try:
        p_tok = all_pages[0]["access_token"]
        allow_payload = [{"page_id": str(p["page_id"]), "allow": True} for p in pages_to_post]
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"https://graph.facebook.com/v21.0/{clean_vid_id}",
                data={
                    "allow_crossposting_for_pages": json.dumps(allow_payload),
                    "access_token": p_tok
                }
            )
    except Exception as allow_err:
        print(f"[Allow Crossposting Warning]: {allow_err}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        for p in pages_to_post:
            r_pid = str(p["page_id"])
            r_name = p["page_name"]
            r_tok = p["access_token"]

            try:
                cp_res = await client.post(
                    f"https://graph.facebook.com/v21.0/{r_pid}/videos",
                    data={
                        "crossposted_video_id": clean_vid_id,
                        "description": msg,
                        "access_token": r_tok
                    }
                )
                cp_data = cp_res.json()
                if cp_res.status_code == 200 and ("id" in cp_data or "post_id" in cp_data):
                    r_post_id = str(cp_data.get("post_id") or cp_data.get("id"))
                    r_post_url = f"https://www.facebook.com/reel/{r_post_id}/"
                    database.save_published_post(
                        page_id=r_pid,
                        page_name=r_name,
                        post_id=r_post_id,
                        post_url=r_post_url,
                        message=msg,
                        media_type="video",
                        boost_command=payload.boost_preset or "standard"
                    )
                    if payload.auto_create_rule:
                        database.save_post_rule({
                            "post_id": r_post_id,
                            "post_name": f"{r_name} - Crosspost ({datetime.now().strftime('%m/%d %H:%M')})",
                            "keywords": "үргэлжлэл,хэд,үнэ,үзэх,линк,хаана,кино,сонирхож,байна,багц,qpay",
                            "public_reply_template": pub_reply,
                            "private_reply_template": priv_reply,
                            "use_ai": 1,
                            "is_active": 1
                        })
                    results.append({"success": True, "page_name": r_name, "page_id": r_pid, "post_id": r_post_id, "post_url": r_post_url})
                else:
                    raw_err = cp_data.get("error", {}).get("message", "Crosspost failed")
                    if "No permission due to music rights" in raw_err:
                        err_msg = "Meta дууны эрх илрүүлсэн тул зөвхөн Facebook сайт дээрээс Share хийж болно"
                    else:
                        err_msg = raw_err
                    results.append({"success": False, "page_name": r_name, "page_id": r_pid, "error": err_msg})
            except Exception as e:
                results.append({"success": False, "page_name": r_name, "page_id": r_pid, "error": str(e)})

    return {
        "status": "ok",
        "published_count": sum(1 for r in results if r.get("success")),
        "total_targets": len(results),
        "results": results
    }


@app.get("/api/published-posts")
@app.get("/published-posts")
async def get_published_posts_endpoint(limit: int = 50):
    """Сүүлд нийтлэгдсэн постуудын түүх авах"""
    return database.get_published_posts(limit)

@app.delete("/api/published-posts/{row_id}")
@app.delete("/published-posts/{row_id}")
async def delete_published_post_endpoint(row_id: int):
    database.delete_published_post(row_id)
    return {"status": "ok"}

@app.get("/api/groups")
@app.get("/groups")
async def get_groups_endpoint():
    """Холбогдсон зорилтот Facebook группүүдийг авах"""
    return database.get_facebook_groups()

class GroupCreateRequest(BaseModel):
    group_name: str
    group_url: str
    category: Optional[str] = "Кино & Сонирхогчид"

@app.post("/api/groups")
@app.post("/groups")
async def add_group_endpoint(payload: GroupCreateRequest):
    """Шинэ зорилтот Facebook групп нэмэх"""
    gid = database.save_facebook_group(payload.group_name, payload.group_url, payload.category or "Кино")
    return {"status": "ok", "id": gid}

@app.delete("/api/groups/{group_id}")
@app.delete("/groups/{group_id}")
async def delete_group_endpoint(group_id: int):
    database.delete_facebook_group(group_id)
    return {"status": "ok"}

class CaptionCraftRequest(BaseModel):
    movie_title: str
    genre: Optional[str] = "Драма, Кино"
    extra_details: Optional[str] = ""

@app.post("/api/ai-craft-caption")
@app.post("/ai-craft-caption")
async def ai_craft_caption_endpoint(payload: CaptionCraftRequest):
    """
    Gemini 3.5 AI-аар Facebook постын татах хүчтэй, үнэ & линктэй монгол текст үүсгэх
    """
    settings = database.get_settings()
    res = await ai_service.craft_post_caption(
        movie_title=payload.movie_title,
        genre=payload.genre or "Драма",
        extra_details=payload.extra_details or "",
        settings=settings
    )
    return res
