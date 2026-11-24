import os
import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Any, Optional

DB_FILE = os.environ.get("DB_FILE", "bot.db")

# If running on Vercel serverless where root is read-only, fallback to /tmp
if os.environ.get("VERCEL"):
    DB_FILE = "/tmp/bot.db"

# Pre-configured 3 connected Facebook Pages
DEFAULT_PAGES = [
    {
        "page_id": "2159494444293875",
        "page_name": "Huree Kino www.huree.site",
        "access_token": "EAAQAATUnWt0BTGvFJGu1Qm59ctTj5ZCo54OQnDRKtGJYIdJYpzCMsGYOvNnW331M3MCRrGVeWPKWzyochIRyXYpPXZA2XrhfZAaZCjAkK6PZAXntW3EkqL9b0lJwdJhZALajiaKmkGZCRzFkZAzVbhHES35vayZCOjZBgi3G6MciC8IfjvFJbNt7c2B73QZBQhXGUuVTh8knDQK7IunZAHDkjwB4"
    },
    {
        "page_id": "1495236273664035",
        "page_name": "Nice Drama Ai",
        "access_token": "EAAQAATUnWt0BTKBZBU3sfEs3pyxnZAken477C1scp47ZChTz0QXTADLFTqMtJfg5tUuYp50WZCAGIKC4MZAOGghYi2DY4OUGKZA2Q7b7qhTiYwnjplPKndvAcI5ZAUZAVQHDboZAqAxJiir0SkgKCQd3MLgHwaWh0hVeDvvT85whZBhF8bvFlVsqZCrBMGIZAVbbZAcrMD11ogOImPCy76ol0SbrvZC1RJ"
    },
    {
        "page_id": "1352524827955013",
        "page_name": "WOW Mini Drama",
        "access_token": "EAAQAATUnWt0BTIZB7aKZBaYcaIiT2xZCJCGSEfiPxYH7sRmMIObszIkDLhNJQJsZBJaG8DRmlI6AlJoidN8jnNmcPMOXT9icK9yIVyld0w9nwoLuBiJjSxrZCnL19cEniTQujkPcXfuM18MTZBvBOjX8XYnDzFqzQSR7F15IPPipF7HIOnDs8UO9NXRINpHOpbHoEUbFcIo9aLfxY1hMsw4TiC"
    },
    {
        "page_id": "1508100029049981",
        "page_name": "Tenger Drama mongolia",
        "access_token": "EAAQEwsLb8KUBTDlbWJGBk6oakYPdQRtPxkdjoaFOGXo62kzHy6vVN1kJjTdTC54O1IK507SYK7D38jUejZAdemmXYMO5egLAGu5rf1o2mTFUPPREoDXQhbyNFaLOFvr1JHqM2f6chVBEbadVbIRe6Tzq7H5MpZAhj242FkvcoR2lPFEJEfP1qbQXg0AvGCHwtq1ZAcjTo8ELmhiZCTAvNsBs"
    },
    {
        "page_id": "1391701170699267",
        "page_name": "Lolo Drama",
        "access_token": "EAAQEwsLb8KUBTCWkaifeUjT8pbkRXZB2d9odzb63fLm0XgOf7wxgxbK0HV4PXtwc9M6h5vZCZBZCSGmsCoto5Yj4x9BLZAj9nSPR9ZASGZAbI1NfedyGHoLqI9Kw0p6JiEmIE6OBoDxhjAZC0uM1JA36yjZCTd4ioKMT0mMhvBZBnpqhrUfByye1JhmlXNaUZA5reOB5xsfAV1VZBTCAFYtxZAa5Q0pyX"
    },
    {
        "page_id": "849736974891001",
        "page_name": "Dornod Ai",
        "access_token": "EAAQEwsLb8KUBTIBXbTs2bP28qnL1oEBtiZCFuE8gGpZAMBM1ysnPwSW64tDit889YGSAeaqbUSJ7DtuEDyF02SaBKRRp6Kpl8p7dg0EfkcdhxqBXVRGYvSzJeay1HLkZCuzeda6j2FDt5C122oduwsr6up8K4HTXNYfZCwpRULuMWvChMqfdYaRZCBJffoZBjx0axMw2JOwlJZBCE8gHe3AZAeQW"
    }
]

HUREE_PROMO_TEXT = (
    "Сайн байна уу! 🎬🍿\n\n"
    "https://www.huree.site энэ сайтаар ороод бүртгүүлээд Монгол хэлтэй чанартай бичлэгтэй 1000+ кино Хүрээ дээр бий!\n\n"
    "🔹 1 кино — 3,900₮\n"
    "🔹 Бүх кино — 15,900₮\n\n"
    "QPay-ээр төлөөд үзэх эрхээ шууд нээгээрэй. Өдөр бүр шинэ кино нэмэгдэнэ! ✨"
)

HUREE_COMMENT_REPLY = "Сайн байна уу! Кино үзэх холбоос болон үнийн мэдээллийг хувийн чатаар тань илгээлээ. Та чатаа шалгаарай 🍿✨"

def get_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # 1. Connected Facebook Pages Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS connected_pages (
        page_id TEXT PRIMARY KEY,
        page_name TEXT NOT NULL,
        access_token TEXT NOT NULL,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Populate 3 default pages
    for p in DEFAULT_PAGES:
        cursor.execute("""
        INSERT OR REPLACE INTO connected_pages (page_id, page_name, access_token, is_active)
        VALUES (?, ?, ?, 1)
        """, (p["page_id"], p["page_name"], p["access_token"]))

    # 2. Post Configurations
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS post_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id TEXT UNIQUE,
        post_name TEXT NOT NULL,
        keywords TEXT DEFAULT '',
        public_reply_template TEXT DEFAULT '',
        private_reply_template TEXT DEFAULT '',
        use_ai INTEGER DEFAULT 1,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 3. Comments Log & Analysis
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS comments_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        comment_id TEXT UNIQUE,
        post_id TEXT,
        sender_id TEXT,
        sender_name TEXT,
        comment_text TEXT,
        sentiment TEXT,
        intent TEXT,
        public_reply TEXT,
        private_reply TEXT,
        phone_extracted TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 4. Captured Leads & Phone Numbers
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id TEXT,
        sender_name TEXT,
        phone_number TEXT,
        comment_text TEXT,
        status TEXT DEFAULT 'new',
        notes TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 5. Bot & AI Settings
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS system_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """)

    # Default settings with Huree.site details
    default_settings = {
        "ai_provider": "gemini",
        "gemini_api_key": os.environ.get("GEMINI_API_KEY", "AQ.Ab8RN6K6ZUU9JlJKaq5ZH9rrwDHPCSJVpkKUO1Age7_-Utz--Q"),
        "gemini_model": "gemini-3.5-flash-lite",
        "system_prompt": (
            "Та 'Хүрээ Кино' (https://www.huree.site), 'Nice Drama Ai', 'WOW Mini Drama' хуудсуудын найрсаг онлайн туслах юм.\n"
            "Үндсэн мэдээлэл:\n"
            "- Вэбсайт: https://www.huree.site\n"
            "- Бүртгүүлээд Монгол хэлтэй чанартай бичлэгтэй 1000+ кино үзэх боломжтой.\n"
            "- Үнэ: 1 кино — 3,900₮, Бүх кино үзэх багц — 15,900₮.\n"
            "- Төлбөр: QPay-ээр шууд төлөөд эрхээ нээнэ. Өдөр бүр шинэ кино нэмэгддэг.\n"
            "Дүрэм:\n"
            "1. Хэрэглэгчийн коммент доор (public_reply): Эелдэг найрсаг мэндчилээд, кино үзэх холбоос болон дэлгэрэнгүйг хувийн чатаар илгээсэн тухай 1 өгүүлбэрээр бичиж, чатаа шалгахыг хүснэ.\n"
            "2. Хувийн чатаар (private_reply): https://www.huree.site линк, 1 кино 3,900₮, бүх кино 15,900₮, QPay-ээр эрхээ шууд нээх мэдээллийг бүрэн дэлгэрэнгүй илгээнэ."
        ),
        "fb_page_access_token": DEFAULT_PAGES[0]["access_token"],
        "fb_verify_token": os.environ.get("VERIFY_TOKEN", "fb_chatbot_secret_verify_token"),
        "fb_app_secret": os.environ.get("APP_SECRET", "1125905093581533"),
        "default_public_reply": HUREE_COMMENT_REPLY,
        "default_private_reply": HUREE_PROMO_TEXT
    }

    for k, v in default_settings.items():
        cursor.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (k, v))

    # Add default post rule
    cursor.execute("""
    INSERT OR REPLACE INTO post_rules (id, post_id, post_name, keywords, public_reply_template, private_reply_template, use_ai, is_active)
    VALUES (1, 'default_all', 'Хүрээ Кино (www.huree.site) Автомат хариу', 'үргэлжлэл,хэд,үнэ,үзэх,линк,хаана,кино,үнэтэй,сонирхож,байна', ?, ?, 1, 1)
    """, (HUREE_COMMENT_REPLY, HUREE_PROMO_TEXT))

    conn.commit()
    conn.close()

# Page token lookup
def get_page_token(page_id: str) -> Optional[str]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT access_token FROM connected_pages WHERE page_id = ? AND is_active = 1", (page_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row["access_token"]
    for p in DEFAULT_PAGES:
        if p["page_id"] == page_id:
            return p["access_token"]
    return get_settings().get("fb_page_access_token", "")

def get_connected_pages() -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM connected_pages ORDER BY created_at ASC")
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        return DEFAULT_PAGES
    return [dict(row) for row in rows]

# Helper queries
def get_settings() -> Dict[str, str]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM system_settings")
    rows = cursor.fetchall()
    conn.close()
    return {row["key"]: row["value"] for row in rows}

def update_settings(settings: Dict[str, str]):
    conn = get_connection()
    cursor = conn.cursor()
    for k, v in settings.items():
        cursor.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (k, str(v)))
    conn.commit()
    conn.close()

def get_post_rules() -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM post_rules ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def save_post_rule(rule: Dict[str, Any]) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    if rule.get("id"):
        cursor.execute("""
        UPDATE post_rules
        SET post_id = ?, post_name = ?, keywords = ?, public_reply_template = ?,
            private_reply_template = ?, use_ai = ?, is_active = ?
        WHERE id = ?
        """, (
            rule.get("post_id"), rule.get("post_name"), rule.get("keywords", ""),
            rule.get("public_reply_template", ""), rule.get("private_reply_template", ""),
            1 if rule.get("use_ai") else 0, 1 if rule.get("is_active") else 0, rule["id"]
        ))
        rule_id = rule["id"]
    else:
        cursor.execute("""
        INSERT INTO post_rules (post_id, post_name, keywords, public_reply_template, private_reply_template, use_ai, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            rule.get("post_id"), rule.get("post_name"), rule.get("keywords", ""),
            rule.get("public_reply_template", ""), rule.get("private_reply_template", ""),
            1 if rule.get("use_ai") else 0, 1 if rule.get("is_active") else 0
        ))
        rule_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return rule_id

def delete_post_rule(rule_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM post_rules WHERE id = ?", (rule_id,))
    conn.commit()
    conn.close()

def log_comment(comment_id: str, post_id: str, sender_id: str, sender_name: str,
                comment_text: str, sentiment: str, intent: str,
                public_reply: str, private_reply: str, phone: Optional[str] = None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT OR REPLACE INTO comments_log
    (comment_id, post_id, sender_id, sender_name, comment_text, sentiment, intent, public_reply, private_reply, phone_extracted)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (comment_id, post_id, sender_id, sender_name, comment_text, sentiment, intent, public_reply, private_reply, phone))

    if phone:
        cursor.execute("""
        INSERT INTO leads (sender_id, sender_name, phone_number, comment_text, status)
        VALUES (?, ?, ?, ?, 'new')
        """, (sender_id, sender_name, phone, comment_text))

    conn.commit()
    conn.close()

def is_comment_processed(comment_id: str) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM comments_log WHERE comment_id = ?", (comment_id,))
    res = cursor.fetchone()
    conn.close()
    return res is not None

def get_recent_comments(limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM comments_log ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_leads(limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM leads ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def update_lead_status(lead_id: int, status: str, notes: str = ""):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE leads SET status = ?, notes = ? WHERE id = ?", (status, notes, lead_id))
    conn.commit()
    conn.close()

def get_dashboard_stats() -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM comments_log")
    total_comments = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM leads")
    total_leads = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM comments_log WHERE private_reply IS NOT NULL AND private_reply != ''")
    replies_sent = cursor.fetchone()[0]

    cursor.execute("SELECT sentiment, COUNT(*) as cnt FROM comments_log GROUP BY sentiment")
    sentiment_rows = cursor.fetchall()
    sentiments = {row["sentiment"] or "unknown": row["cnt"] for row in sentiment_rows}

    conn.close()
    return {
        "total_comments": total_comments,
        "total_leads": total_leads,
        "replies_sent": replies_sent,
        "sentiments": sentiments,
        "connected_pages_count": len(DEFAULT_PAGES)
    }
