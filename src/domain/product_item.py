import datetime


class ProductItem:
    def __init__(self, product_id, shop_id, name, price=0.0, stock=0, sku="", status="active", created_at=None, updated_at=None):
        self.product_id = product_id
        self.shop_id = shop_id
        self.sku = sku
        self.name = name
        self.price = float(price or 0.0)
        self.stock = int(stock or 0)
        self.status = status
        self.created_at = created_at or datetime.datetime.now()
        self.updated_at = updated_at or datetime.datetime.now()

    def to_dict(self):
        return {
            "product_id": self.product_id,
            "shop_id": self.shop_id,
            "sku": self.sku,
            "name": self.name,
            "price": self.price,
            "stock": self.stock,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data):
        created_at = None
        if data.get("created_at"):
            try:
                created_at = datetime.datetime.fromisoformat(data["created_at"])
            except Exception:
                created_at = datetime.datetime.now()
        updated_at = None
        if data.get("updated_at"):
            try:
                updated_at = datetime.datetime.fromisoformat(data["updated_at"])
            except Exception:
                updated_at = datetime.datetime.now()
        return cls(
            product_id=data.get("product_id"),
            shop_id=data.get("shop_id"),
            name=data.get("name"),
            price=data.get("price", 0.0),
            stock=data.get("stock", 0),
            sku=data.get("sku", ""),
            status=data.get("status", "active"),
            created_at=created_at,
            updated_at=updated_at
        )

