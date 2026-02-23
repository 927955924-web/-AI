import json
import datetime

from ..db import _utc_now


class StatsRepository:
    def __init__(self, conn):
        self.conn = conn

    def emit(self, event_type: str, entity_id: str = "", metadata=None):
        self.conn.execute(
            "INSERT INTO events(event_type, entity_id, created_at, metadata_json) VALUES (?, ?, ?, ?)",
            (event_type, entity_id or "", _utc_now(), json.dumps(metadata or {}, ensure_ascii=False, separators=(",", ":"))),
        )
        self.conn.commit()

    def totals(self):
        cur = self.conn.cursor()
        shops = cur.execute("SELECT COUNT(*) AS c FROM shops WHERE is_active = 1").fetchone()["c"]
        products = cur.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]
        sessions = cur.execute("SELECT COUNT(*) AS c FROM chat_sessions").fetchone()["c"]
        messages = cur.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"]
        return {
            "shops": int(shops or 0),
            "products": int(products or 0),
            "sessions": int(sessions or 0),
            "messages": int(messages or 0),
        }

    def daily_messages(self, days: int = 14):
        since = (datetime.datetime.utcnow().date() - datetime.timedelta(days=int(days) - 1)).isoformat()
        rows = self.conn.execute(
            """
            SELECT substr(timestamp, 1, 10) AS day, COUNT(*) AS c
            FROM messages
            WHERE substr(timestamp, 1, 10) >= ?
            GROUP BY substr(timestamp, 1, 10)
            ORDER BY day ASC
            """,
            (since,),
        ).fetchall()
        return [{"day": r["day"], "count": int(r["c"] or 0)} for r in rows]

    def top_events(self, limit: int = 20):
        rows = self.conn.execute(
            """
            SELECT event_type, COUNT(*) AS c
            FROM events
            GROUP BY event_type
            ORDER BY c DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [{"event_type": r["event_type"], "count": int(r["c"] or 0)} for r in rows]

