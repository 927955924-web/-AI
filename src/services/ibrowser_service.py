from abc import ABC, abstractmethod

class IBrowserService(ABC):
    @abstractmethod
    def start(self):
        pass

    @abstractmethod
    def login(self, account, password):
        pass

    @abstractmethod
    def fetch_info(self):
        pass