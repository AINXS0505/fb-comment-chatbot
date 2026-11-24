import os
import sys
import csv
import io
import json
import httpx
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
                # 1. Сүүлийн постыг авах (Хугацаа хэмнэх үүднээс limit=1)
                posts_res = await client.get(
                    f"https://graph.facebook.com/v19.0/{page_id}/posts",
                    params={"limit": limit, "access_token": page_token}
                )
                posts = posts_res.json().get("data", [])

                for post in posts:
                    post_id = post["id"]
                    # 2. Тухайн постын сүүлийн 5 комментыг авах
                    comm_res = await client.get(
                        f"https://graph.facebook.com/v19.0/{post_id}/comments",
                        params={"limit": 5, "access_token": page_token}
                    )
                    comments = comm_res.json().get("data", [])

                    for c in comments:
                        cid = c["id"]
                        msg = c.get("message", "").strip()
                        sender = c.get("from", {})
                        sid = str(sender.get("id") or "")
                        sname = sender.get("name", "Үйлчлүүлэгч")

                        # Өөрийн хуудасны хариуг алгасах
                        if "huree.site" in msg.lower() or "чатаар тань илгээлээ" in msg:
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
        priv_reply = payload.custom_private_reply or settings.get("default_private_reply", ai_service.HUREE_PROMO_TEXT)

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
