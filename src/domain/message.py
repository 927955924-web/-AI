import datetime

class Message:
    def __init__(self, message_id, session_id, sender_type, sender_id, content, 
                 message_type="text", timestamp=None, status="sent", metadata=None):
        self.message_id = message_id
        self.session_id = session_id
        self.sender_type = sender_type  # "user", "ai", "system"
        self.sender_id = sender_id
        self.content = content
        self.message_type = message_type  # "text", "image", "file", "order"
        self.timestamp = timestamp or datetime.datetime.now()
        self.status = status  # "sent", "delivered", "read", "failed"
        self.metadata = metadata or {}

    def mark_as_read(self):
        self.status = "read"

    def mark_as_delivered(self):
        self.status = "delivered"

    def mark_as_failed(self):
        self.status = "failed"

    def to_dict(self):
        return {
            "message_id": self.message_id,
            "session_id": self.session_id,
            "sender_type": self.sender_type,
            "sender_id": self.sender_id,
            "content": self.content,
            "message_type": self.message_type,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "status": self.status,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data):
        message = cls(
            message_id=data.get("message_id"),
            session_id=data.get("session_id"),
            sender_type=data.get("sender_type"),
            sender_id=data.get("sender_id"),
            content=data.get("content"),
            message_type=data.get("message_type", "text"),
            status=data.get("status", "sent"),
            metadata=data.get("metadata", {})
        )
        if "timestamp" in data and data["timestamp"]:
            message.timestamp = datetime.datetime.fromisoformat(data["timestamp"])
        return message