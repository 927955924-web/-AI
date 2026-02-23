import datetime
from typing import List

class ChatSession:
    def __init__(self, session_id, shop_id, user_id, platform, 
                 status="active", created_at=None, updated_at=None, 
                 last_message=None, metadata=None):
        self.session_id = session_id
        self.shop_id = shop_id
        self.user_id = user_id
        self.platform = platform
        self.status = status  # "active", "closed", "archived"
        self.created_at = created_at or datetime.datetime.now()
        self.updated_at = updated_at or datetime.datetime.now()
        self.last_message = last_message
        self.metadata = metadata or {}
        self.message_count = 0
        self.unread_count = 0

    def update_last_message(self, message_content, message_time):
        self.last_message = message_content
        self.updated_at = message_time
        self.message_count += 1

    def increment_unread(self):
        self.unread_count += 1

    def reset_unread(self):
        self.unread_count = 0

    def close(self):
        self.status = "closed"
        self.updated_at = datetime.datetime.now()

    def archive(self):
        self.status = "archived"
        self.updated_at = datetime.datetime.now()

    def reopen(self):
        self.status = "active"
        self.updated_at = datetime.datetime.now()

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "shop_id": self.shop_id,
            "user_id": self.user_id,
            "platform": self.platform,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_message": self.last_message,
            "metadata": self.metadata,
            "message_count": self.message_count,
            "unread_count": self.unread_count
        }

    @classmethod
    def from_dict(cls, data):
        session = cls(
            session_id=data.get("session_id"),
            shop_id=data.get("shop_id"),
            user_id=data.get("user_id"),
            platform=data.get("platform"),
            status=data.get("status", "active"),
            last_message=data.get("last_message"),
            metadata=data.get("metadata", {})
        )
        if "created_at" in data and data["created_at"]:
            session.created_at = datetime.datetime.fromisoformat(data["created_at"])
        if "updated_at" in data and data["updated_at"]:
            session.updated_at = datetime.datetime.fromisoformat(data["updated_at"])
        if "message_count" in data:
            session.message_count = data["message_count"]
        if "unread_count" in data:
            session.unread_count = data["unread_count"]
        return session