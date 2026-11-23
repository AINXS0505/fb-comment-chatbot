import os
import sys
import csv
import io
from pathlib import Path
from fastapi import FastAPI, Request, Response, HTTPException, Query, BackgroundTasks
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
async def receive_fb_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Facebook-ээс коммент болон мессежийн өөрчлөлт ирэх POST хүсэлт
    """
    raw_body = await request.body()
    signature = request.headers.get("x-hub-signature-256", "")

    settings = database.get_settings()
    app_secret = settings.get("fb_app_secret", "")

    # Meta гарын үсэг шалгах
    if app_secret and not facebook_service.verify_signature(raw_body, signature, app_secret):
        print("[Facebook Webhook] Хүчингүй гарын үсэг (Invalid signature) ирлээ.")
        return Response(content="Invalid signature", status_code=403)

    try:
        body = await request.json()
    except Exception:
        return Response(content="Invalid JSON", status_code=400)

    # Facebook 5 секундийн дотор 200 OK авах ёстой тул ар талд ажиллахаар (BackgroundTasks) илгээнэ
    background_tasks.add_task(process_webhook_event, body, settings)
    return Response(content="EVENT_RECEIVED", status_code=200)


async def process_webhook_event(body: Dict[str, Any], settings: Dict[str, str]):
    """
    Ирсэн Facebook үйл явдлыг шалгаж, коммент мөн бол AI-аар хариулуулах функц
    """
    if body.get("object") != "page":
        return

    page_token = settings.get("fb_page_access_token", "")

    for entry in body.get("entry", []):
        page_id = entry.get("id")
        for change in entry.get("changes", []):
            field = change.get("field")
            val = change.get("value", {})

            # Зөвхөн шинээр нэмэгдсэн коммент мөн эсэхийг шалгах
            if field == "feed" and val.get("item") == "comment" and val.get("verb") == "add":
                comment_id = val.get("comment_id")
                post_id = val.get("post_id") or "default_all"
                sender = val.get("from", {})
                sender_id = sender.get("id")
                sender_name = sender.get("name", "Үйлчлүүлэгч")
                comment_text = val.get("message", "").strip()

                # Хуудас өөрийнхөө комментод давхар хариулахаас сэргийлэх
                if sender_id == page_id:
                    continue

                # Давхардаж боловсруулагдахаас сэргийлэх (Deduplication)
                if database.is_comment_processed(comment_id):
                    continue

                # Тохирох дүрмийг олох
                post_rules = database.get_post_rules()
                matched_rule = None
                for r in post_rules:
                    if r["is_active"] and (r["post_id"] == post_id or r["post_id"] == "default_all"):
                        matched_rule = r
                        break

                post_name = matched_rule["post_name"] if matched_rule else "Ерөнхий пост"
                custom_public = matched_rule["public_reply_template"] if matched_rule else ""
                custom_private = matched_rule["private_reply_template"] if matched_rule else ""

                # AI шинжилгээ ба хариу бэлдэх
                analysis = await ai_service.analyze_and_generate_replies(
                    comment_text=comment_text,
                    sender_name=sender_name,
                    post_name=post_name,
                    settings=settings,
                    custom_public_template=custom_public,
                    custom_private_template=custom_private
                )

                # Нийтийн коммент хариу илгээх
                if analysis.get("public_reply"):
                    await facebook_service.send_public_comment_reply(
                        comment_id=comment_id,
                        message=analysis["public_reply"],
                        access_token=page_token
                    )

                # Хувийн чатаар зурвас илгээх (Private Reply)
                if analysis.get("private_reply"):
                    await facebook_service.send_private_messenger_reply(
                        comment_id=comment_id,
                        message=analysis["private_reply"],
                        access_token=page_token
                    )

                # Өгөгдлийн санд лог хадгалах & утасны дугаарыг бүртгэх
                database.log_comment(
                    comment_id=comment_id,
                    post_id=post_id,
                    sender_id=sender_id,
                    sender_name=sender_name,
                    comment_text=comment_text,
                    sentiment=analysis.get("sentiment", "neutral"),
                    intent=analysis.get("intent", "general"),
                    public_reply=analysis.get("public_reply", ""),
                    private_reply=analysis.get("private_reply", ""),
                    phone=analysis.get("phone")
                )


# --- REST API ENDPOINTS FOR DASHBOARD ---
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
    """
    Facebook холбох шаардлагагүйгээр Dashboard дээр шууд AI хариуг турших
    """
    settings = database.get_settings()
    analysis = await ai_service.analyze_and_generate_replies(
        comment_text=payload.comment_text,
        sender_name=payload.sender_name,
        post_name=payload.post_name,
        settings=settings
    )

    # Симуляци хийсэн туршилтыг лог болгон хадгалж харуулах
    mock_comment_id = f"sim_{int(os.times().system * 1000)}"
    database.log_comment(
        comment_id=mock_comment_id,
        post_id="simulator_test",
        sender_id="mock_user_1",
        sender_name=payload.sender_name,
        comment_text=payload.comment_text,
        sentiment=analysis.get("sentiment", "neutral"),
        intent=analysis.get("intent", "general"),
        public_reply=analysis.get("public_reply", ""),
        private_reply=analysis.get("private_reply", ""),
        phone=analysis.get("phone")
    )

    return analysis
