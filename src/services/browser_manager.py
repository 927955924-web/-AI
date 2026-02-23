from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from .ibrowser_service import IBrowserService
from src.domain.shop import Shop
from src.infrastructure.repositories.settings_repository import SettingsRepository
from src.infrastructure.secret_store import unprotect
from src.infrastructure.logger import get_logger

class BrowserManager(IBrowserService):
    def __init__(self, conn, monitoring_service=None):
        self.conn = conn
        self.settings = SettingsRepository(conn)
        self.drivers = {}
        self.logger = get_logger()
        self.monitoring_service = monitoring_service

    def start(self, shop_id=None):
        chrome_options = Options()
        headless = self.settings.get("selenium_headless", "1")
        if str(headless).strip() not in ("0", "false", "False"):
            chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        driver = webdriver.Chrome(options=chrome_options)
        if shop_id:
            self.drivers[shop_id] = driver
            if self.monitoring_service and self.monitoring_service.enabled:
                self.monitoring_service.record_browser_event(
                    event_type="browser_started",
                    shop_id=shop_id,
                    metadata={"headless": headless}
                )
        self.logger.info(f"浏览器启动: shop_id={shop_id or '无'}")
        return driver

    def set_login_url(self, url):
        self.settings.set("default_login_url", url or "")

    def auto_login(self, shop: Shop):
        if self.monitoring_service and self.monitoring_service.enabled:
            self.monitoring_service.record_browser_event(
                event_type="auto_login_started",
                shop_id=shop.shop_id,
                url=shop.login_url or "",
                metadata={"shop_name": shop.shop_name}
            )
        
        driver = self.drivers.get(shop.shop_id)
        if not driver:
            driver = self.start(shop.shop_id)

        url = shop.login_url or self.settings.get("default_login_url", "")
        if url:
            driver.get(url)
            if self.monitoring_service and self.monitoring_service.enabled:
                self.monitoring_service.record_browser_event(
                    event_type="page_loaded",
                    shop_id=shop.shop_id,
                    url=url
                )

        cfg = shop.config or {}
        selectors = cfg.get("selectors") or {}
        account_sel = selectors.get("account_name") or "account"
        password_sel = selectors.get("password_name") or "password"
        submit_xpath = selectors.get("submit_xpath") or "//button[@type='submit']"

        wait = WebDriverWait(driver, 10)
        account_input = wait.until(EC.presence_of_element_located((By.NAME, account_sel)))
        password_input = driver.find_element(By.NAME, password_sel)
        account_input.clear()
        password_input.clear()
        account_input.send_keys(shop.account or "")
        password_input.send_keys(unprotect(shop.password or ""))
        login_button = driver.find_element(By.XPATH, submit_xpath)
        login_button.click()

    def login(self, account, password):
        try:
            if self.monitoring_service and self.monitoring_service.enabled:
                self.monitoring_service.record_browser_event(
                    event_type="login_started",
                    url=self.settings.get("default_login_url", ""),
                    metadata={"account": account}
                )
            
            driver = self.start()
            url = self.settings.get("default_login_url", "")
            if not url:
                self.logger.warning("未设置默认登录URL")
                return None
            driver.get(url)
            
            if self.monitoring_service and self.monitoring_service.enabled:
                self.monitoring_service.record_browser_event(
                    event_type="login_page_loaded",
                    url=url
                )
            cfg = self.settings.get("default_login_selectors", "{}")
            import json
            selectors = json.loads(cfg) if cfg else {}
            account_sel = selectors.get("account_name") or "account"
            password_sel = selectors.get("password_name") or "password"
            submit_xpath = selectors.get("submit_xpath") or "//button[@type='submit']"
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            wait = WebDriverWait(driver, 10)
            account_input = wait.until(EC.presence_of_element_located((By.NAME, account_sel)))
            password_input = driver.find_element(By.NAME, password_sel)
            account_input.clear()
            password_input.clear()
            account_input.send_keys(account)
            password_input.send_keys(password)
            login_button = driver.find_element(By.XPATH, submit_xpath)
            login_button.click()
            
            if self.monitoring_service and self.monitoring_service.enabled:
                self.monitoring_service.record_browser_event(
                    event_type="login_submitted",
                    metadata={"account": account}
                )
            
            return driver
        except Exception as e:
            self.logger.error(f"登录失败: {e}")
            return None

    def fetch_info(self):
        result = []
        for driver in list(self.drivers.values()):
            try:
                elements = driver.find_elements(By.CLASS_NAME, "buyer-info")
                result.extend([el.text for el in elements])
            except Exception:
                continue
        return result

    def enable_cdp_logging(self, driver=None, shop_id=None):
        if driver is None:
            if shop_id is None:
                self.logger.warning("需要提供driver或shop_id")
                return
            driver = self.drivers.get(shop_id)
            if driver is None:
                self.logger.warning(f"未找到shop_id对应的driver: {shop_id}")
                return
        try:
            driver.execute_cdp_cmd("Network.enable", {})
            driver.execute_cdp_cmd("Performance.enable", {})
            driver.execute_cdp_cmd("Log.enable", {})
            self.logger.info("已启用CDP日志记录")
            
            if self.monitoring_service and self.monitoring_service.enabled:
                self.monitoring_service.record_browser_event(
                    event_type="cdp_logging_enabled",
                    shop_id=shop_id,
                    metadata={"driver_present": driver is not None}
                )
        except Exception as e:
            self.logger.error(f"启用CDP日志失败: {e}")
            if self.monitoring_service and self.monitoring_service.enabled:
                self.monitoring_service.record_error(
                    error_type="cdp_enable_error",
                    error_message=str(e),
                    metadata={"shop_id": shop_id}
                )

    def capture_console_log(self, driver=None, shop_id=None):
        if driver is None:
            if shop_id is None:
                self.logger.warning("需要提供driver或shop_id")
                return []
            driver = self.drivers.get(shop_id)
            if driver is None:
                self.logger.warning(f"未找到shop_id对应的driver: {shop_id}")
                return []
        try:
            logs = driver.get_log("browser")
            
            if self.monitoring_service and self.monitoring_service.enabled:
                self.monitoring_service.record_browser_event(
                    event_type="console_log_captured",
                    shop_id=shop_id,
                    metadata={"log_count": len(logs)}
                )
            
            return logs
        except Exception as e:
            self.logger.error(f"获取控制台日志失败: {e}")
            
            if self.monitoring_service and self.monitoring_service.enabled:
                self.monitoring_service.record_error(
                    error_type="console_log_error",
                    error_message=str(e),
                    metadata={"shop_id": shop_id}
                )
            
            return []

    def take_screenshot(self, driver=None, shop_id=None, path=None):
        if driver is None:
            if shop_id is None:
                self.logger.warning("需要提供driver或shop_id")
                return None
            driver = self.drivers.get(shop_id)
            if driver is None:
                self.logger.warning(f"未找到shop_id对应的driver: {shop_id}")
                return None
        try:
            screenshot = driver.get_screenshot_as_png()
            if path:
                with open(path, "wb") as f:
                    f.write(screenshot)
            return screenshot
        except Exception as e:
            self.logger.error(f"截图失败: {e}")
            return None

    def execute_cdp_command(self, command, params, driver=None, shop_id=None):
        if driver is None:
            if shop_id is None:
                self.logger.warning("需要提供driver或shop_id")
                return None
            driver = self.drivers.get(shop_id)
            if driver is None:
                self.logger.warning(f"未找到shop_id对应的driver: {shop_id}")
                return None
        try:
            result = driver.execute_cdp_cmd(command, params)
            return result
        except Exception as e:
            self.logger.error(f"执行CDP命令失败: {e}")
            return None

    def close(self, shop_id=None):
        if shop_id:
            driver = self.drivers.pop(shop_id, None)
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
            return
        for sid, driver in list(self.drivers.items()):
            try:
                driver.quit()
            except Exception:
                pass
        self.drivers.clear()
