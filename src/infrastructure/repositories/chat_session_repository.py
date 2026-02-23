import datetime
import uuid

from ...domain.chat_session import ChatSession
from ..db import _utc_now, json_dumps, json_loads


class ChatSessionRepository:
    def __init__(self, conn):
        self.conn = conn

    def list(self, shop_id: str, status: str = ""):
        sql = "SELECT * FROM chat_sessions WHERE shop_id = ?"
        args = [shop_id]
        if status:
            sql += " AND status = ?"
            args.append(status)
        sql += " ORDER BY updated_at DESC"
        rows = self.conn.execute(sql, tuple(args)).fetchall()
        return [self._from_row(r) for r in rows]

    def get(self, session_id: str):
        row = self.conn.execute("SELECT * FROM chat_sessions WHERE session_id = ?", (session_id,)).fetchone()
        if not row:
            return None
        return self._from_row(row)

    def create(self, shop_id: str, user_id: str, platform: str = ""):
        sid = f"cs_{uuid.uuid4().hex}"
        now = _utc_now()
        self.conn.execute(
            """
            INSERT INTO chat_sessions(session_id, shop_id, user_id, platform, status, created_at, updated_at, last_message, metadata_json, message_count, unread_count)
            VALUES (?, ?, ?, ?, 'active', ?, ?, NULL, ?, 0, 0)
            """,
            (sid, shop_id, user_id, platform, now, now, json_dumps({})),
        )
        self.conn.commit()
        return self.get(sid)

    def touch(self, session_id: str, last_message: str = None, inc_message: bool = False):
        now = _utc_now()
        if inc_message:
            self.conn.execute(
                "UPDATE chat_sessions SET updated_at = ?, last_message = COALESCE(?, last_message), message_count = message_count + 1 WHERE session_id = ?",
                (now, last_message, session_id),
            )
        else:
            self.conn.execute(
                "UPDATE chat_sessions SET updated_at = ?, last_message = COALESCE(?, last_message) WHERE session_id = ?",
                (now, last_message, session_id),
            )
        self.conn.commit()

    def set_status(self, session_id: str, status: str):
        self.conn.execute("UPDATE chat_sessions SET status = ?, updated_at = ? WHERE session_id = ?", (status, _utc_now(), session_id))
        self.conn.commit()

    def reset_unread(self, session_id: str):
        self.conn.execute("UPDATE chat_sessions SET unread_count = 0 WHERE session_id = ?", (session_id,))
        self.conn.commit()

    def increment_unread(self, session_id: str, n: int = 1):
        self.conn.execute("UPDATE chat_sessions SET unread_count = unread_count + ? WHERE session_id = ?", (n, session_id))
        self.conn.commit()

    def _from_row(self, row):
        created_at = None
        if row["created_at"]:
            try:
                created_at = datetime.datetime.fromisoformat(row["created_at"])
            except Exception:
                created_at = None
        updated_at = None
        if row["updated_at"]:
            try:
                updated_at = datetime.datetime.fromisoformat(row["updated_at"])
            except Exception:
                updated_at = None
        session = ChatSession(
            session_id=row["session_id"],
            shop_id=row["shop_id"],
            user_id=row["user_id"],
            platform=row["platform"] or "",
            status=row["status"] or "active",
            created_at=created_at,
            updated_at=updated_at,
            last_message=row["last_message"],
            metadata=json_loads(row["metadata_json"]),
        )
        session.message_count = int(row["message_count"] or 0)
        session.unread_count = int(row["unread_count"] or 0)
        return session

