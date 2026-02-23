import datetime

class Product:
    def __init__(self, product_id, name, price, quantity):
        self.product_id = product_id
        self.name = name
        self.price = price
        self.quantity = quantity

    def total_price(self):
        return self.price * self.quantity

    def to_dict(self):
        return {
            "product_id": self.product_id,
            "name": self.name,
            "price": self.price,
            "quantity": self.quantity
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            product_id=data.get("product_id"),
            name=data.get("name"),
            price=data.get("price", 0.0),
            quantity=data.get("quantity", 1)
        )

class OrderDetail:
    def __init__(self, order_id, products, buyer_info):
        self.order_id = order_id
        self.products = products
        self.buyer_info = buyer_info

    def get_order_detail(self, order_id):
        return self

    def total_amount(self):
        total = 0.0
        for product in self.products:
            total += product.price * product.quantity
        return total

    def to_dict(self):
        return {
            "order_id": self.order_id,
            "products": [p.to_dict() for p in self.products],
            "buyer_info": self.buyer_info
        }

    @classmethod
    def from_dict(cls, data):
        products = [Product.from_dict(p) for p in data.get("products", [])]
        return cls(
            order_id=data.get("order_id"),
            products=products,
            buyer_info=data.get("buyer_info", {})
        )