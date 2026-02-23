import datetime
import uuid

from ...domain.product_item import ProductItem
from ..db import _utc_now


class ProductRepository:
    def __init__(self, conn):
        self.conn = conn

    def list(self, shop_id: str, keyword: str = ""):
        sql = "SELECT * FROM products WHERE shop_id = ?"
        args = [shop_id]
        if keyword:
            sql += " AND (name LIKE ? OR sku LIKE ?)"
            args.extend([f"%{keyword}%", f"%{keyword}%"])
        sql += " ORDER BY updated_at DESC"
        rows = self.conn.execute(sql, tuple(args)).fetchall()
        return [self._from_row(r) for r in rows]

    def get(self, product_id: str):
        row = self.conn.execute("SELECT * FROM products WHERE product_id = ?", (product_id,)).fetchone()
        if not row:
            return None
        return self._from_row(row)

    def create(self, shop_id: str, name: str, price: float = 0.0, stock: int = 0, sku: str = "", status: str = "active"):
        pid = f"p_{uuid.uuid4().hex}"
        now = _utc_now()
        self.conn.execute(
            """
            INSERT INTO products(product_id, shop_id, sku, name, price, stock, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (pid, shop_id, sku, name, float(price or 0), int(stock or 0), status, now, now),
        )
        self.conn.commit()
        return self.get(pid)

    def update(self, product: ProductItem):
        now = _utc_now()
        self.conn.execute(
            """
            UPDATE products SET sku = ?, name = ?, price = ?, stock = ?, status = ?, updated_at = ?
            WHERE product_id = ?
            """,
            (product.sku, product.name, float(product.price or 0), int(product.stock or 0), product.status, now, product.product_id),
        )
        self.conn.commit()

    def delete(self, product_id: str):
        self.conn.execute("DELETE FROM products WHERE product_id = ?", (product_id,))
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
        return ProductItem(
            product_id=row["product_id"],
            shop_id=row["shop_id"],
            sku=row["sku"] or "",
            name=row["name"],
            price=row["price"],
            stock=row["stock"],
            status=row["status"],
            created_at=created_at,
            updated_at=updated_at,
        )

