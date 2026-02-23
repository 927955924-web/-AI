from .iai_service import IAI服务
from src.domain.order_detail import OrderDetail
from src.infrastructure.knowledge_base import KnowledgeBase
from src.infrastructure.repositories.settings_repository import SettingsRepository


class AI服务(IAI服务):
    def __init__(self, conn, api_type="openai"):
        self.api_type = api_type
        self.settings = SettingsRepository(conn)
        self.kb = KnowledgeBase("knowledge.db")

    def 接入API(self, api_type):
        self.api_type = api_type

    def 识别信息(self, 信息):
        text = (信息 or "").strip()
        keywords = []
        for k in ["商品", "物流", "退款", "退货", "发票", "尺码", "售后", "优惠", "发货", "地址"]:
            if k in text:
                keywords.append(k)
        return {"类型": "买家咨询", "关键词": keywords}

    def 生成回复(self, 问题, 上下文, 订单详情: OrderDetail):
        q = (问题 or "").strip()
        ctx = (上下文 or "").strip()

        hits = self.kb.查询相似问题(q) if q else []
        best = next((h for h in hits if h.get("is_correct") in (True, 1, "1")), None) or (hits[0] if hits else None)

        if best and best.get("answer"):
            return best["answer"]

        api_key = self.settings.get_secret("openai_api_key", "") or ""
        model = self.settings.get("openai_model", "gpt-4o-mini")
        temperature = self.settings.get("openai_temperature", "0.3")
        try:
            temperature = float(temperature)
        except Exception:
            temperature = 0.3

        if api_key:
            try:
                from openai import OpenAI

                client = OpenAI(api_key=api_key)
                messages = [
                    {"role": "system", "content": "你是电商客服助手，回答要简洁、礼貌、可执行。"},
                ]
                if ctx:
                    messages.append({"role": "system", "content": f"上下文信息：{ctx}"})
                if 订单详情 is not None:
                    try:
                        products = ", ".join([p.name for p in getattr(订单详情, "products", [])])
                        messages.append({"role": "system", "content": f"订单号：{getattr(订单详情, 'order_id', '')}，商品：{products}"})
                    except Exception:
                        pass
                messages.append({"role": "user", "content": q})

                resp = client.chat.completions.create(
                    model=model,
                    temperature=temperature,
                    messages=messages,
                )
                content = resp.choices[0].message.content if resp and resp.choices else ""
                content = (content or "").strip()
                if content:
                    return content
            except Exception:
                pass

        if 订单详情 is not None:
            try:
                商品列表 = ", ".join([p.name for p in 订单详情.products])
                return f"尊敬的买家，您好！关于您的问题“{q}”，我们已收到。您的订单{订单详情.order_id}包含：{商品列表}。我们将尽快为您处理。"
            except Exception:
                pass

        return f"尊敬的买家，您好！关于您的问题“{q}”，我们已收到，将尽快为您核实并回复。"
