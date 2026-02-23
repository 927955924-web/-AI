import datetime
import uuid

from ...domain.user import User
from ..db import _utc_now
from ..secret_store import protect, unprotect


class UserRepository:
    def __init__(self, conn):
        self.conn = conn

    def get_by_username(self, username: str):
        row = self.conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not row:
            return None
        return self._from_row(row)

    def get(self, user_id: str):
        row = self.conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            return None
        return self._from_row(row)

    def list_all(self):
        rows = self.conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
        return [self._from_row(r) for r in rows]

    def create(self, username: str, password: str, email: str = "", role: str = "user"):
        user_id = f"u_{uuid.uuid4().hex}"
        now = _utc_now()
        self.conn.execute(
            "INSERT INTO users(user_id, username, password, email, role, vip_status, created_at, is_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, username, protect(password), email, role, 0, now, 1),
        )
        self.conn.commit()
        return self.get(user_id)

    def authenticate(self, username: str, password: str):
        user = self.get_by_username(username)
        if not user:
            return None
        stored = user.password
        if unprotect(stored) != password:
            return None
        self.conn.execute("UPDATE users SET last_login = ? WHERE user_id = ?", (_utc_now(), user.user_id))
        self.conn.commit()
        return self.get(user.user_id)

    def update_role(self, user_id: str, role: str):
        self.conn.execute("UPDATE users SET role = ? WHERE user_id = ?", (role, user_id))
        self.conn.commit()

    def set_active(self, user_id: str, is_active: bool):
        self.conn.execute("UPDATE users SET is_active = ? WHERE user_id = ?", (1 if is_active else 0, user_id))
        self.conn.commit()

    def _from_row(self, row):
        vip_expiry = None
        if row["vip_expiry"]:
            try:
                vip_expiry = datetime.datetime.fromisoformat(row["vip_expiry"])
            except Exception:
                vip_expiry = None
        last_login = None
        if row["last_login"]:
            try:
                last_login = datetime.datetime.fromisoformat(row["last_login"])
            except Exception:
                last_login = None
        created_at = None
        if row["created_at"]:
            try:
                created_at = datetime.datetime.fromisoformat(row["created_at"])
            except Exception:
                created_at = None
        user = User(
            user_id=row["user_id"],
            username=row["username"],
            password=row["password"],
            email=row["email"] or "",
            role=row["role"],
            vip_status=bool(row["vip_status"]),
            vip_expiry=vip_expiry,
            last_login=last_login,
            created_at=created_at,
        )
        user.is_active = bool(row["is_active"])
        return user
