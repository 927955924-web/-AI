import json
import sqlite3
import datetime

from .paths import app_db_path


def _utc_now():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat()


def connect(db_path=None):
    path = db_path or app_db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            email TEXT,
            role TEXT NOT NULL,
            vip_status INTEGER NOT NULL DEFAULT 0,
            vip_expiry TEXT,
            last_login TEXT,
            created_at TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS shops (
            shop_id TEXT PRIMARY KEY,
            shop_name TEXT NOT NULL,
            account TEXT,
            password TEXT,
            login_url TEXT,
            platform_type TEXT,
            owner_id TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_login TEXT,
            config_json TEXT NOT NULL DEFAULT '{}',
            notes TEXT NOT NULL DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_shops_owner ON shops(owner_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_shops_platform ON shops(platform_type)")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            product_id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            sku TEXT,
            name TEXT NOT NULL,
            price REAL NOT NULL DEFAULT 0,
            stock INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(shop_id) REFERENCES shops(shop_id) ON DELETE CASCADE
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_products_shop ON products(shop_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_products_sku ON products(sku)")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_sessions (
            session_id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            platform TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_message TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            message_count INTEGER NOT NULL DEFAULT 0,
            unread_count INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(shop_id) REFERENCES shops(shop_id) ON DELETE CASCADE
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_shop ON chat_sessions(shop_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON chat_sessions(user_id)")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            message_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            sender_type TEXT NOT NULL,
            sender_id TEXT,
            content TEXT NOT NULL,
            message_type TEXT NOT NULL DEFAULT 'text',
            timestamp TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'sent',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_time ON messages(timestamp)")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            entity_id TEXT,
            created_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_events_type_time ON events(event_type, created_at)")
    conn.commit()

    cur.execute("SELECT COUNT(*) AS c FROM users")
    if int(cur.fetchone()["c"]) == 0:
        cur.execute(
            "INSERT INTO users(user_id, username, password, email, role, vip_status, created_at, is_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("u_admin", "admin", "admin", "", "admin", 0, _utc_now(), 1),
        )
        conn.commit()


def json_dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_loads(value):
    if not value:
        return {}
    try:
        return json.loads(value)
    except Exception:
        return {}

