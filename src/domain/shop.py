import datetime

class Shop:
    def __init__(self, shop_id, shop_name, account, password, login_url, platform_type, 
                 owner_id="", status="未启动", created_at=None, last_login=None, 
                 config=None, notes=""):
        self.shop_id = shop_id
        self.shop_name = shop_name
        self.account = account
        self.password = password
        self.login_url = login_url
        self.platform_type = platform_type
        self.owner_id = owner_id
        self.status = status
        self.created_at = created_at or datetime.datetime.now()
        self.last_login = last_login
        self.config = config or {}
        self.notes = notes
        self.is_active = True

    def start(self):
        self.status = "运行中"
        self.last_login = datetime.datetime.now()

    def stop(self):
        self.status = "已停止"

    def update_config(self, key, value):
        self.config[key] = value

    def get_config(self, key, default=None):
        return self.config.get(key, default)

    def to_dict(self):
        return {
            "shop_id": self.shop_id,
            "shop_name": self.shop_name,
            "account": self.account,
            "password": self.password,
            "login_url": self.login_url,
            "platform_type": self.platform_type,
            "owner_id": self.owner_id,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "config": self.config,
            "notes": self.notes,
            "is_active": self.is_active
        }

    @classmethod
    def from_dict(cls, data):
        shop = cls(
            shop_id=data.get("shop_id"),
            shop_name=data.get("shop_name"),
            account=data.get("account"),
            password=data.get("password"),
            login_url=data.get("login_url"),
            platform_type=data.get("platform_type"),
            owner_id=data.get("owner_id", ""),
            status=data.get("status", "未启动"),
            notes=data.get("notes", "")
        )
        if "created_at" in data and data["created_at"]:
            shop.created_at = datetime.datetime.fromisoformat(data["created_at"])
        if "last_login" in data and data["last_login"]:
            shop.last_login = datetime.datetime.fromisoformat(data["last_login"])
        if "config" in data:
            shop.config = data["config"]
        if "is_active" in data:
            shop.is_active = data["is_active"]
        return shop