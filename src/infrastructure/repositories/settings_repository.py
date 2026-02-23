import datetime

from ..db import _utc_now
from ..secret_store import protect, unprotect


class SettingsRepository:
    def __init__(self, conn):
        self.conn = conn

    def get(self, key: str, default: str = ""):
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if not row:
            return default
        return row["value"]

    def set(self, key: str, value: str):
        now = _utc_now()
        self.conn.execute(
            "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, value, now),
        )
        self.conn.commit()

    def get_secret(self, key: str, default: str = ""):
        raw = self.get(key, "")
        if not raw:
            return default
        return unprotect(raw)

    def set_secret(self, key: str, value: str):
        self.set(key, protect(value or ""))

