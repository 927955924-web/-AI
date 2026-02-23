import datetime
import uuid

from ...domain.message import Message
from ..db import _utc_now, json_dumps, json_loads


class MessageRepository:
    def __init__(self, conn):
        self.conn = conn

    def list(self, session_id: str, limit: int = 200):
        rows = self.conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY timestamp ASC LIMIT ?",
            (session_id, int(limit)),
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def create(self, session_id: str, sender_type: str, sender_id: str, content: str, message_type: str = "text", status: str = "sent", metadata=None):
        mid = f"m_{uuid.uuid4().hex}"
        ts = _utc_now()
        self.conn.execute(
            """
            INSERT INTO messages(message_id, session_id, sender_type, sender_id, content, message_type, timestamp, status, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (mid, session_id, sender_type, sender_id, content, message_type, ts, status, json_dumps(metadata or {})),
        )
        self.conn.commit()
        return self.get(mid)

    def get(self, message_id: str):
        row = self.conn.execute("SELECT * FROM messages WHERE message_id = ?", (message_id,)).fetchone()
        if not row:
            return None
        return self._from_row(row)

    def _from_row(self, row):
        timestamp = None
        if row["timestamp"]:
            try:
                timestamp = datetime.datetime.fromisoformat(row["timestamp"])
            except Exception:
                timestamp = None
        return Message(
            message_id=row["message_id"],
            session_id=row["session_id"],
            sender_type=row["sender_type"],
            sender_id=row["sender_id"] or "",
            content=row["content"],
            message_type=row["message_type"] or "text",
            timestamp=timestamp,
            status=row["status"] or "sent",
            metadata=json_loads(row["metadata_json"]),
        )

