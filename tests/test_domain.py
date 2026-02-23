import sys
sys.path.insert(0, 'src')

from domain.user import User
from domain.shop import Shop
from domain.order_detail import OrderDetail, Product
import datetime

def test_user():
    user = User("1", "testuser", "password")
    assert user.user_id == "1"
    assert user.username == "testuser"
    assert not user.vip_status
    user.renew_vip(30)
    assert user.vip_status
    assert user.vip_expiry > datetime.datetime.now()

def test_shop():
    shop = Shop("shop1", "测试店铺", "account", "pass", "http://example.com", "淘宝")
    assert shop.shop_id == "shop1"
    assert shop.status == "未启动"
    shop.start()
    assert shop.status == "运行中"
    shop.stop()
    assert shop.status == "已停止"

def test_order_detail():
    p1 = Product("p1", "商品1", 100, 2)
    p2 = Product("p2", "商品2", 200, 1)
    order = OrderDetail("order1", [p1, p2], "买家信息")
    assert order.order_id == "order1"
    assert len(order.products) == 2
    assert order.products[0].name == "商品1"
    assert order.get_order_detail("order1") == order