import os
import sys
import csv
import io
import json
from pathlib import Path
from fastapi import FastAPI, Request, Response, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any

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
