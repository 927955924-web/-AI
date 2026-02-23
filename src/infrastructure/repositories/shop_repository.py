import datetime
import uuid

from ...domain.shop import Shop
from ..db import _utc_now, json_dumps, json_loads
from ..secret_store import protect, unprotect


class ShopRepository:
    def __init__(self, conn):
        self.conn = conn

    def list(self, owner_id: str = "", platform_type: str = "", keyword: str = ""):
        sql = "SELECT * FROM shops WHERE is_active = 1"
        args = []
        if owner_id:
            sql += " AND owner_id = ?"
            args.append(owner_id)
        if platform_type:
            sql += " AND platform_type = ?"
            args.append(platform_type)
        if keyword:
            sql += " AND (shop_name LIKE ? OR account LIKE ?)"
            args.extend([f"%{keyword}%", f"%{keyword}%"])
        sql += " ORDER BY created_at DESC"
        rows = self.conn.execute(sql, tuple(args)).fetchall()
        return [self._from_row(r) for r in rows]

    def get(self, shop_id: str):
        row = self.conn.execute("SELECT * FROM shops WHERE shop_id = ?", (shop_id,)).fetchone()
        if not row:
            return None
        return self._from_row(row)

    def create(self, shop_name: str, platform_type: str, account: str = "", password: str = "", login_url: str = "", owner_id: str = "", notes: str = ""):
        shop_id = f"s_{uuid.uuid4().hex}"
        now = _utc_now()
        self.conn.execute(
            """
            INSERT INTO shops(shop_id, shop_name, account, password, login_url, platform_type, owner_id, status, created_at, config_json, notes, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (shop_id, shop_name, account, protect(password), login_url, platform_type, owner_id, "未启动", now, json_dumps({}), notes),
        )
        self.conn.commit()
        return self.get(shop_id)

    def update(self, shop: Shop):
        self.conn.execute(
            """
            UPDATE shops SET shop_name = ?, account = ?, password = ?, login_url = ?, platform_type = ?, owner_id = ?, status = ?, last_login = ?, config_json = ?, notes = ?, is_active = ?
            WHERE shop_id = ?
            """,
            (
                shop.shop_name,
                shop.account,
                protect(unprotect(shop.password)),
                shop.login_url,
                shop.platform_type,
                shop.owner_id,
                shop.status,
                shop.last_login.isoformat() if shop.last_login else None,
                json_dumps(shop.config or {}),
                shop.notes or "",
                1 if getattr(shop, "is_active", True) else 0,
                shop.shop_id,
            ),
        )
        self.conn.commit()

    def set_status(self, shop_id: str, status: str, last_login: str = None):
        self.conn.execute("UPDATE shops SET status = ?, last_login = ? WHERE shop_id = ?", (status, last_login, shop_id))
        self.conn.commit()

    def delete(self, shop_id: str):
        self.conn.execute("UPDATE shops SET is_active = 0 WHERE shop_id = ?", (shop_id,))
        self.conn.commit()

    def _from_row(self, row):
        created_at = None
        if row["created_at"]:
            try:
                created_at = datetime.datetime.fromisoformat(row["created_at"])
            except Exception:
                created_at = None
        last_login = None
        if row["last_login"]:
            try:
                last_login = datetime.datetime.fromisoformat(row["last_login"])
            except Exception:
                last_login = None
        shop = Shop(
            shop_id=row["shop_id"],
            shop_name=row["shop_name"],
            account=row["account"] or "",
            password=row["password"] or "",
            login_url=row["login_url"] or "",
            platform_type=row["platform_type"] or "",
            owner_id=row["owner_id"] or "",
            status=row["status"] or "未启动",
            created_at=created_at,
            last_login=last_login,
            config=json_loads(row["config_json"]),
            notes=row["notes"] or "",
        )
        shop.is_active = bool(row["is_active"])
        return shop

