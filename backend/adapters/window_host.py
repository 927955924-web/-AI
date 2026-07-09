"""
千牛窗口嵌入模块 - 将千牛客户端窗口嵌入指定父窗口（Electron 容器）
使用 win32api SetParent + 样式修改，实现类似 BrowserView 的嵌入效果
"""
import ctypes
from typing import Optional

# Win32 constants
GWL_STYLE = -16
WS_CAPTION       = 0x00C00000
WS_THICKFRAME    = 0x00040000
WS_MAXIMIZEBOX   = 0x00010000
WS_MINIMIZEBOX   = 0x00020000
WS_CHILD         = 0x40000000
WS_VISIBLE       = 0x10000000
WS_CLIPSIBLINGS  = 0x04000000
SWP_NOMOVE       = 0x0002
SWP_NOZORDER     = 0x0004
SWP_FRAMECHANGED = 0x0020
SWP_NOACTIVATE   = 0x0010

user32   = ctypes.WinDLL("user32", use_last_error=True)  # use_last_error 确保 GetLastError 准确
user32.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_long * 4)]
kernel32 = ctypes.windll.kernel32


class QianNiuWindowHost:
    """管理千牛窗口的嵌入、样式修改和尺寸调整"""

    def __init__(self):
        self.qianniu_hwnd: Optional[int] = None   # 千牛主窗口（SetParent 用）
        self.cef_hwnd: Optional[int] = None        # CEF 子窗口（UIAutomation 用）
        self.host_hwnd: Optional[int] = None        # Electron 宿主窗口
        self._embedded = False

    # ── 公开属性 ──────────────────────────────
    @property
    def is_embedded(self) -> bool:
        return self._embedded and bool(self.qianniu_hwnd) and bool(self.host_hwnd)

    # ── 核心：嵌入 ────────────────────────────
    def attach(self, qianniu_hwnd: int, host_hwnd: int, width: int = 900, height: int = 700) -> bool:
        """
        将 qianniu_hwnd 嵌入 host_hwnd：
        1. 如果没有指定窗口，自动查找千牛工作台
        2. 先 SetParent 再改窗口样式（CEF 窗口兼容性更好）
        3. SetWindowPos 调整位置
        """
        if not host_hwnd:
            return False

        # 如果没有指定窗口，自动寻找工作台（Electron 传过来的可能是登录窗口）
        if not qianniu_hwnd:
            qianniu_hwnd = self.find_main_window()

        if not qianniu_hwnd:
            return False

        try:
            self.qianniu_hwnd = int(qianniu_hwnd)
            self.host_hwnd = int(host_hwnd)

            # 1. 先改变父窗口（CEF 窗口先 SetParent 更稳定）
            ctypes.set_last_error(0)
            ret = user32.SetParent(self.qianniu_hwnd, self.host_hwnd)
            err = ctypes.get_last_error()
            if ret == 0 and err != 0:
                self._reset_state()
                return False

            # 2. 再改窗口样式
            style = user32.GetWindowLongPtrW(self.qianniu_hwnd, GWL_STYLE)
            style &= ~WS_CAPTION
            style &= ~WS_THICKFRAME
            style &= ~WS_MAXIMIZEBOX
            style &= ~WS_MINIMIZEBOX
            style |= (WS_CHILD | WS_VISIBLE | WS_CLIPSIBLINGS)
            user32.SetWindowLongPtrW(self.qianniu_hwnd, GWL_STYLE, style)

            # 3. 调整位置
            self.resize(width, height)

            # 4. 自动定位 CEF 子窗口（UIAutomation 绑定用）
            self.cef_hwnd = self.get_cef_child()

            self._embedded = True
            return True
        except Exception:
            self._reset_state()
            return False

    def resize(self, width: int = 900, height: int = 700):
        """用 SetWindowPos 调整大小（CEF 程序用 MoveWindow 容易白屏/黑屏）"""
        if not self.qianniu_hwnd:
            return
        try:
            user32.SetWindowPos(
                self.qianniu_hwnd,
                0, 0, 0,
                width, height,
                SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED | SWP_NOACTIVATE
            )
        except Exception:
            pass

    def sync_size(self, width: int, height: int):
        """窗口尺寸跟随 — Electron 拉伸/最大化/切换布局时调用"""
        if not self.is_embedded:
            return
        self.resize(width, height)

    # ── 焦点控制 ──────────────────────────────
    def focus(self):
        """输入框实际属于 CEF 子窗口，优先 SetFocus 到 cef_hwnd"""
        hwnd = self.cef_hwnd or self.qianniu_hwnd
        if not hwnd:
            return
        try:
            user32.SetActiveWindow(hwnd)
            user32.SetFocus(hwnd)
        except Exception:
            pass

    # ── 窗口存活检测 ───────────────────────────
    def is_alive(self) -> bool:
        """检测千牛窗口是否还存在（可能崩溃/被用户关闭/登录退出）"""
        if not self.qianniu_hwnd:
            return False
        try:
            return bool(user32.IsWindow(self.qianniu_hwnd))
        except Exception:
            return False

    # ── 释放 ──────────────────────────────────
    def detach(self):
        """解除嵌入，恢复千牛为独立窗口"""
        if not self.qianniu_hwnd:
            return
        try:
            user32.SetParent(self.qianniu_hwnd, 0)
            style = user32.GetWindowLongPtrW(self.qianniu_hwnd, GWL_STYLE)
            style |= WS_CAPTION | WS_THICKFRAME | WS_MAXIMIZEBOX | WS_MINIMIZEBOX
            style |= WS_VISIBLE           # 恢复可见性
            style &= ~WS_CLIPSIBLINGS     # 去除嵌入时加的 sibling 裁剪
            style &= ~WS_CHILD            # 恢复为顶层窗口
            user32.SetWindowLongPtrW(self.qianniu_hwnd, GWL_STYLE, style)
            user32.SetWindowPos(self.qianniu_hwnd, 0, 100, 100, 900, 700,
                                SWP_NOZORDER | SWP_FRAMECHANGED)
        except Exception:
            pass
        finally:
            self._reset_state()

    # ── 千牛主窗口查找（登录后重新找工作台 HWND）──
    def find_main_window(self) -> Optional[int]:
        """
        登录成功后重新枚举所有可见顶层窗口，按标题"千牛"定位工作台 HWND。
        登录窗口和工作台是不同的 HWND，不能用登录窗口做 SetParent。

        返回: 标题含"千牛"的最后一个可见顶层窗口 HWND
        """
        result = []

        def enum_top(hwnd, _param):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                buf = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(hwnd, buf, 256)
                title = buf.value
                if any(
                    x in title
                    for x in (
                        "千牛", "工作台", "卖家中心", "消息中心",
                        "AliWorkbench", "淘宝", "阿里",
                    )
                ):
                    result.append(hwnd)
            except Exception:
                pass
            return True

        try:
            _EnumWindows = ctypes.WINFUNCTYPE(
                ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p
            )
            callback = _EnumWindows(enum_top)
            user32.EnumWindows(callback, 0)
        except Exception:
            pass

        # 返回最后一个（通常是最新的千牛工作台窗口）
        return result[-1] if result else None

    # ── CEF 子窗口查找 ─────────────────────────
    def get_cef_child(self) -> Optional[int]:
        """
        千牛是 Chromium/CEF 应用，结构：
            千牛主窗口 → Chromium 子窗口 → Chrome_RenderWidgetHostHWND

        UIAutomation 需要绑定到 CEF 子窗口（Chrome_WidgetWin_*）而非外层主窗口。

        策略：递归遍历所有后代窗口，找类名含 "Chrome" 的窗口，
              返回其中面积最大的（聊天页面通常最大），而非第一个。
        """
        if not self.qianniu_hwnd:
            return None

        candidates = []  # [(hwnd, area), ...]

        def enum_recursive(parent):
            """递归枚举 parent 的所有后代窗口，返回 HWND 列表"""
            children = []

            def cb(hwnd, _param):
                children.append(hwnd)
                # 递归搜索该子窗口的后代
                enum_recursive(hwnd)
                return True

            CALLBACK = ctypes.WINFUNCTYPE(
                ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p
            )
            user32.EnumChildWindows(parent, CALLBACK(cb), 0)
            return children

        try:
            for hwnd in enum_recursive(self.qianniu_hwnd):
                try:
                    buf = ctypes.create_unicode_buffer(256)
                    user32.GetClassNameW(hwnd, buf, 256)
                    cls = buf.value
                    if cls and any(
                        x in cls
                        for x in ("Chrome_WidgetWin", "Chrome_RenderWidgetHostHWND")
                    ):
                        rect = (ctypes.c_long * 4)()
                        if user32.GetClientRect(hwnd, ctypes.byref(rect)):
                            area = rect[2] * rect[3]
                            candidates.append((hwnd, area))
                        else:
                            candidates.append((hwnd, 0))
                except Exception:
                    pass
        except Exception:
            pass

        if not candidates:
            return None

        # 返回面积最大的 Chromium 子窗口
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    def _reset_state(self):
        self._embedded = False
        self.qianniu_hwnd = None
        self.cef_hwnd = None
        self.host_hwnd = None

    def get_qianniu_hwnd(self) -> Optional[int]:
        return self.qianniu_hwnd
