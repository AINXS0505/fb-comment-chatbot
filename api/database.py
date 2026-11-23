import os
import sqlite3
from datetime import datetime
from typing import List, Dict, Any, Optional

DB_FILE = os.environ.get("DB_FILE", "bot.db")

# If running on Vercel serverless where root is read-only, fallback to /tmp
if os.environ.get("VERCEL"):
    DB_FILE = "/tmp/bot.db"

def get_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # 1. Post Configurations
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

    # 2. Comments Log & Analysis
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

    # 3. Captured Leads & Phone Numbers
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

    # 4. Bot & AI Settings
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS system_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """)

    # Default settings if not exists
    default_settings = {
        "ai_provider": "gemini",
        "gemini_api_key": os.environ.get("GEMINI_API_KEY", ""),
        "gemini_model": "gemini-1.5-flash",
        "system_prompt": (
            "Та Facebook хуудасны найрсаг, мэргэжлийн борлуулалтын зөвлөх туслах юм. "
            "Хэрэглэгчийн бичсэн комментыг ойлгож, монгол хэлээр эелдэг, дулаан өнгө аясаар хариулна. "
            "Хэрэв үнэ болон дэлгэрэнгүй асуусан бол хувийн чатаар мэдээлэл илгээсэн болохыг хэлж, чатаа шалгахыг хүснэ. "
            "Комментоос утасны дугаар илэрвэл талархаж, тун удахгүй холбогдоно гэдгээ мэдэгдэнэ."
        ),
        "fb_page_access_token": os.environ.get("PAGE_ACCESS_TOKEN", ""),
        "fb_verify_token": os.environ.get("VERIFY_TOKEN", "fb_chatbot_secret_verify_token"),
        "fb_app_secret": os.environ.get("APP_SECRET", ""),
        "default_public_reply": "Сайн байна уу! Танд дэлгэрэнгүй мэдээллийг чатаар илгээлээ. Та чатаа шалгаарай 😊",
        "default_private_reply": "Сайн байна уу! Манай хуудсыг сонирхсонд баярлалаа. Танд ямар чиглэлээр туслах вэ?"
    }

    for k, v in default_settings.items():
        cursor.execute("INSERT OR IGNORE INTO system_settings (key, value) VALUES (?, ?)", (k, v))

    # Add default post rule if empty
    cursor.execute("SELECT COUNT(*) FROM post_rules")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
        INSERT INTO post_rules (post_id, post_name, keywords, public_reply_template, private_reply_template, use_ai, is_active)
        VALUES ('default_all', 'Бүх нийтийн анхдагч тохиргоо (Бүх постын коммент)', 'үнэ,хэд,хүргэлт,захиалах,хаана', '', '', 1, 1)
        """)

    conn.commit()
    conn.close()

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
        "sentiments": sentiments
    }
