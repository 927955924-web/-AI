import datetime

class User:
    def __init__(self, user_id, username, password, email="", role="user", 
                 vip_status=False, vip_expiry=None, last_login=None, created_at=None):
        self.user_id = user_id
        self.username = username
        self.password = password
        self.email = email
        self.role = role  # admin, user, guest
        self.vip_status = vip_status
        self.vip_expiry = vip_expiry
        self.last_login = last_login or datetime.datetime.now()
        self.created_at = created_at or datetime.datetime.now()
        self.is_active = True

    def register(self):
        self.created_at = datetime.datetime.now()
        self.is_active = True

    def login(self):
        self.last_login = datetime.datetime.now()

    def logout(self):
        pass

    def renew_vip(self, days):
        self.vip_status = True
        if self.vip_expiry and self.vip_expiry > datetime.datetime.now():
            self.vip_expiry += datetime.timedelta(days=days)
        else:
            self.vip_expiry = datetime.datetime.now() + datetime.timedelta(days=days)

    def has_permission(self, permission):
        permissions = {
            "admin": ["manage_users", "manage_shops", "view_stats", "system_config"],
            "user": ["manage_own_shops", "view_own_stats", "use_ai_service"],
            "guest": ["view_public"]
        }
        return permission in permissions.get(self.role, [])

    def to_dict(self):
        return {
            "user_id": self.user_id,
            "username": self.username,
            "email": self.email,
            "role": self.role,
            "vip_status": self.vip_status,
            "vip_expiry": self.vip_expiry.isoformat() if self.vip_expiry else None,
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "is_active": self.is_active
        }

    @classmethod
    def from_dict(cls, data):
        user = cls(
            user_id=data.get("user_id"),
            username=data.get("username"),
            password=data.get("password", ""),
            email=data.get("email", ""),
            role=data.get("role", "user"),
            vip_status=data.get("vip_status", False)
        )
        if "vip_expiry" in data and data["vip_expiry"]:
            user.vip_expiry = datetime.datetime.fromisoformat(data["vip_expiry"])
        if "last_login" in data and data["last_login"]:
            user.last_login = datetime.datetime.fromisoformat(data["last_login"])
        if "created_at" in data and data["created_at"]:
            user.created_at = datetime.datetime.fromisoformat(data["created_at"])
        return user