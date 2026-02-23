from abc import ABC, abstractmethod

class IAI服务(ABC):
    @abstractmethod
    def 识别信息(self, 信息):
        pass

    @abstractmethod
    def 生成回复(self, 问题, 上下文, 订单详情):
        pass