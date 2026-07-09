"""
QianNiu (千牛) PC Client Adapter v2
使用 Windows UI Automation (UIA) 精确定位千牛界面元素
不依赖截图、不依赖视觉模型、毫秒级响应

核心改进:
1. 搜索深度从 15→15~20 → 分层精准搜索 (从窗口→面板→控件)
2. UIA 事件(StructureChanged)驱动 vs 纯轮询
3. 元素名缓存 + 智能重试 vs 每次都暴力遍历
4. 原生 SendKeys Unicode 输入 vs 剪贴板粘贴
5. 自动重连 vs 断开就死

uiautomation 库版本兼容:
  WindowControl(Name="title") → Exists() → GetChildren()
  EditControl(Name="输入") → Click() → SendKeys()
  ButtonControl(Name="发送") → Click()
"""
import time
import threading
import json
import hashlib
import re
import os
import random
import ctypes
import tkinter as tk
import urllib.request
import uuid
from typing import Optional, List, Dict, Callable, Set
from dataclasses import dataclass, field
from datetime import datetime
from ctypes import wintypes

_HAS_WIN32CLIPBOARD = False
try:
    import win32clipboard
    import win32con
    _HAS_WIN32CLIPBOARD = True
except Exception as e:
    print(f"[QianNiuAdapter] win32clipboard 导入失败: {e}")

_HAS_UIA = False
try:
    import uiautomation as auto
    _HAS_UIA = True
except Exception as e:
    print(f"[QianNiuAdapter] uiautomation 导入失败: {e}")

_HAS_PYAUTOGUI = False
_HAS_PIL = False
try:
    import pyautogui
    _HAS_PYAUTOGUI = True
except Exception as e:
    print(f"[QianNiuAdapter] pyautogui 导入失败: {e}")

try:
    from PIL import Image
    import io
    _HAS_PIL = True
except Exception as e:
    print(f"[QianNiuAdapter] PIL 导入失败: {e}")

_HAS_PSUTIL = False
try:
    import psutil
    _HAS_PSUTIL = True
except Exception as e:
    print(f"[QianNiuAdapter] psutil 导入失败: {e}")


@dataclass
class QianNiuMessage:
    """千牛聊天消息"""
    sender: str          # 'buyer' | 'seller'
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    is_self: bool = False
    msg_hash: str = ""
    
    def __post_init__(self):
        if not self.msg_hash:
            raw = f"{self.sender}:{self.content}:{self.timestamp.isoformat()}"
            self.msg_hash = hashlib.md5(raw.encode()).hexdigest()[:16]


@dataclass
class QianNiuCustomer:
    """千牛会话客户"""
    name: str
    has_unread: bool = False
    unread_count: int = 0
    last_message: str = ""
    has_priority: bool = False


# ============================================================
# 千牛窗口定义
# ============================================================
# 千牛可能的窗口类名 (CEF版/原生版)
_QIANNIU_CLASSES = [
    "Chrome_WidgetWin_0",     # CEF版(新版)
    "AliWorkbenchMainWnd",     # 原生版(旧版)
    "QianNiuMainWnd",          # 备用
]

# 千牛可能的窗口标题
_QIANNIU_TITLES = [
    "千牛工作台",
    "千牛",
    "AliWorkbench",
]


# ============================================================
# 千牛适配器
# ============================================================
class QianNiuAdapter:
    """
    千牛PC客户端UIA适配器 v2
    
    使用分层搜索策略:
    1. 定位主窗口 (WindowControl)
    2. 定位子面板 (PaneControl/CustomControl)
    3. 定位具体控件 (ListControl/EditControl/ButtonControl)
    
    每一层都缓存结果, 减少遍历次数。
    """
    
    # 缓存有效期(秒)
    CACHE_TTL = 15
    # 监控周期(秒)
    POLL_INTERVAL = 0.8  # 嵌入 Electron 后扫描成本更高，降低轮询频率
    # 全量扫描间隔(秒)
    FULL_SCAN_INTERVAL = 10
    # 重连间隔(秒)
    RECONNECT_INTERVAL = 5
    
    def __init__(self):
        if not _HAS_UIA:
            raise RuntimeError("uiautomation 未安装")
        
        self._window: Optional[auto.WindowControl] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._processed_hashes: Set[str] = set()
        self._pending_messages: List[Dict] = []
        self._on_message: Optional[Callable] = None
        self._on_unread: Optional[Callable] = None
        self._current_chat: Optional[str] = None
        self._debug_trace_id: Optional[str] = None
        self._last_login_fail_reason: str = ""
        self._login_log_path: str = ""
        self._login_lock = threading.Lock()
        
        # 元素缓存 { key: (element, timestamp) }
        self._cache: Dict[str, tuple] = {}
        
        # 嵌入模式标志（True 时不调用 SetActive，由外部 window_host 管理）
        self.embedded = False

    def _reset_window_ref(self):
        self._window = None
        self._cache_clear()

    def _safe_exists(self, ctrl, max_search_seconds: float = 0.2) -> bool:
        if not ctrl:
            return False
        try:
            return bool(ctrl.Exists(maxSearchSeconds=max_search_seconds))
        except Exception:
            return False

    def _bind_window_from_hwnd(self, hwnd: int) -> bool:
        if not hwnd or not _HAS_UIA:
            return False
        try:
            ctrl = auto.ControlFromHandle(hwnd)
            if ctrl and self._safe_exists(ctrl, max_search_seconds=0.3):
                self._window = ctrl
                return True
        except Exception:
            pass
        try:
            ctrl = auto.WindowControl(searchDepth=1, NativeWindowHandle=hwnd)
            if ctrl and self._safe_exists(ctrl, max_search_seconds=0.3):
                self._window = ctrl
                return True
        except Exception:
            pass
        return False

    def _current_window_hwnd(self) -> int:
        if not self._window:
            return 0
        try:
            hwnd = int(getattr(self._window, "NativeWindowHandle", 0) or 0)
            return hwnd if hwnd > 0 else 0
        except Exception:
            return 0

    def bind_hwnd(self, hwnd: int) -> bool:
        """嵌入后用 ControlFromHandle 绑定千牛 HWND，不从桌面根节点搜索"""
        ok = self._bind_window_from_hwnd(int(hwnd))
        if ok:
            self.embedded = True
            self._cache_clear()  # 新 HWND 下旧控件缓存已失效
        return ok

    def _find_process_bound_window(self) -> bool:
        if not _HAS_PSUTIL:
            return False
        names = {"aliworkbench.exe", "qianniu.exe", "aliim.exe", "wangwang.exe"}
        user32 = ctypes.windll.user32
        foreground_hwnd = int(user32.GetForegroundWindow() or 0)
        candidates = []

        enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        get_window_text = user32.GetWindowTextW
        get_window_text.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        get_class_name = user32.GetClassNameW
        get_class_name.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        get_window_thread_pid = user32.GetWindowThreadProcessId
        get_window_thread_pid.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

        def _enum_window(hwnd, _lparam):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                if user32.GetParent(hwnd):
                    return True
                pid = wintypes.DWORD()
                get_window_thread_pid(hwnd, ctypes.byref(pid))
                if not pid.value:
                    return True
                try:
                    proc_name = psutil.Process(pid.value).name().lower()
                except Exception:
                    return True
                if proc_name not in names:
                    return True
                title_buf = ctypes.create_unicode_buffer(256)
                class_buf = ctypes.create_unicode_buffer(128)
                get_window_text(hwnd, title_buf, len(title_buf))
                get_class_name(hwnd, class_buf, len(class_buf))
                title = str(title_buf.value or "").strip()
                class_name = str(class_buf.value or "").strip()
                score = 0
                if int(hwnd) == foreground_hwnd:
                    score += 500
                if "工作台" in title:
                    score += 240
                if "千牛" in title or "AliWorkbench" in title:
                    score += 160
                if "登录" in title:
                    score -= 180
                if "悬浮条" in title or "floattoolbar" in class_name.lower():
                    score -= 320
                if class_name in _QIANNIU_CLASSES:
                    score += 80
                if title:
                    score += 20
                candidates.append((score, int(hwnd), proc_name, title, class_name))
            except Exception:
                pass
            return True

        try:
            user32.EnumWindows(enum_proc(_enum_window), 0)
        except Exception:
            return False

        candidates.sort(key=lambda item: item[0], reverse=True)
        for score, hwnd, proc_name, title, class_name in candidates:
            if self._bind_window_from_hwnd(hwnd):
                self._login_log("window.bind", "已按进程句柄绑定千牛窗口", {
                    "hwnd": hwnd,
                    "process": proc_name,
                    "title": title[:80],
                    "class_name": class_name,
                    "score": score,
                })
                return True
        return False

    def _get_login_log_path(self) -> str:
        if self._login_log_path:
            return self._login_log_path
        candidates = []
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            candidates.append(os.path.join(appdata, "ecommerce-cs-client", "logs", "qianniu-login-flow.ndjson"))
        try:
            repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            candidates.append(os.path.join(repo_root, ".dbg", "qianniu-login-flow.ndjson"))
        except Exception:
            pass
        candidates.append(os.path.join(os.getcwd(), ".dbg", "qianniu-login-flow.ndjson"))
        for path in candidates:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                self._login_log_path = path
                return path
            except Exception:
                continue
        self._login_log_path = candidates[0] if candidates else "qianniu-login-flow.ndjson"
        return self._login_log_path

    def _login_log(self, step: str, message: str, data: Optional[Dict] = None, level: str = "info"):
        """写入千牛登录流程日志（NDJSON），便于事后排查"""
        safe_step = str(step)
        safe_message = str(message)
        entry = {
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "level": level,
            "step": safe_step,
            "message": safe_message,
            "traceId": self._debug_trace_id,
            "data": data or {},
        }
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        try:
            with open(self._get_login_log_path(), "a", encoding="utf-8") as log_file:
                log_file.write(line)
        except Exception as e:
            print(f"[QianNiuAdapter] 登录日志写入失败: {e}")
        try:
            print(f"[QianNiuLogin][{safe_step}] {safe_message}")
        except UnicodeEncodeError:
            fallback_step = safe_step.encode("ascii", errors="backslashreplace").decode("ascii")
            fallback_message = safe_message.encode("ascii", errors="backslashreplace").decode("ascii")
            print(f"[QianNiuLogin][{fallback_step}] {fallback_message}")

    def get_login_log_recent(self, max_lines: int = 120) -> List[str]:
        path = self._get_login_log_path()
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as log_file:
                lines = log_file.readlines()
            return [line.rstrip("\n") for line in lines[-max_lines:] if line.strip()]
        except Exception:
            return []

    # #region debug-point A:helpers
    def _debug_probe_enabled(self) -> bool:
        flag = str(os.environ.get("QIANNIU_DEBUG_PROBES", "") or "").strip().lower()
        if flag in ("1", "true", "yes", "on"):
            return True
        if flag in ("0", "false", "no", "off"):
            return False
        try:
            return os.path.exists(os.path.join(os.getcwd(), ".dbg", "enable_qianniu_debug.flag"))
        except Exception:
            return False

    def _debug_emit(self, hypothesis_id: str, msg: str, data: Optional[Dict] = None, run_id: str = "pre-fix", location: str = "qianniu_adapter"):
        if not self._debug_probe_enabled():
            return
        self._login_log(location.split(":")[-1] if ":" in location else "debug", msg, {
            "hypothesisId": hypothesis_id,
            "location": location,
            **(data or {}),
        })
        try:
            debug_server_url = "http://127.0.0.1:7777/event"
            debug_session_id = "qianniu-login-fill"
            env_candidates = [
                os.path.join(os.getcwd(), ".dbg", "qianniu-login-fill.env"),
                os.path.join(os.getcwd(), ".dbg", "qianniu-auto-login.env"),
            ]
            for env_path in env_candidates:
                if not os.path.exists(env_path):
                    continue
                with open(env_path, "r", encoding="utf-8") as env_file:
                    for raw_line in env_file:
                        line = raw_line.strip()
                        if line.startswith("DEBUG_SERVER_URL="):
                            debug_server_url = line.split("=", 1)[1].strip() or debug_server_url
                        elif line.startswith("DEBUG_SESSION_ID="):
                            debug_session_id = line.split("=", 1)[1].strip() or debug_session_id
                break
            payload = {
                "sessionId": debug_session_id,
                "runId": run_id,
                "hypothesisId": hypothesis_id,
                "location": location,
                "msg": f"[DEBUG] {msg}",
                "data": data or {},
                "traceId": self._debug_trace_id,
                "ts": int(time.time() * 1000),
            }
            urllib.request.urlopen(
                urllib.request.Request(
                    debug_server_url,
                    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                ),
                timeout=0.8,
            ).read()
        except:
            pass

    def _debug_get_focused_control(self):
        try:
            focused = auto.GetFocusedControl()
            return focused
        except Exception:
            return None

    def _debug_emit_account_probe(self, hypothesis_id: str, stage: str, account_ctrl=None, password_ctrl=None, run_id: str = "pre-fix"):
        if not self._debug_probe_enabled():
            return
        focused = self._debug_get_focused_control()
        probe_ctrl = account_ctrl
        password_probe = password_ctrl
        account_value = ""
        password_value = ""
        try:
            account_value = self._read_edit_text(probe_ctrl)
        except Exception:
            pass
        try:
            password_value = self._read_edit_text(password_probe)
        except Exception:
            pass
        # #region debug-point A:account-probe
        self._debug_emit(
            hypothesis_id,
            f"account probe: {stage}",
            {
                "stage": stage,
                "account_ctrl": self._describe_control(probe_ctrl),
                "account_rect": self._get_control_rect(probe_ctrl),
                "account_name": (str(self._safe_attr(probe_ctrl, "Name", "") or ""))[:80],
                "account_value": (account_value or "")[:80],
                "password_ctrl": self._describe_control(password_probe),
                "password_rect": self._get_control_rect(password_probe),
                "password_value_length": len(password_value or ""),
                "focused_ctrl": self._describe_control(focused),
                "focused_rect": self._get_control_rect(focused),
            },
            run_id=run_id,
            location="qianniu_adapter:_debug_emit_account_probe",
        )
        # #endregion

    def _describe_control(self, ctrl):
        if not ctrl:
            return None
        try:
            return {
                "type": str(self._safe_attr(ctrl, "ControlTypeName", "") or ""),
                "name": str(self._safe_attr(ctrl, "Name", "") or "")[:80],
                "class_name": str(self._safe_attr(ctrl, "ClassName", "") or "")[:80],
                "automation_id": str(self._safe_attr(ctrl, "AutomationId", "") or "")[:80],
            }
        except:
            return {"type": "unknown"}

    def _chat_ready_snapshot(self) -> Dict:
        snapshot = {
            "window": self._describe_control(self._window),
            "window_title": str(self._safe_attr(self._window, "Name", "") or "")[:120] if self._window else "",
        }
        try:
            session_panel = self._get_session_panel()
            chat_panel = self._get_chat_panel()
            input_box = self._get_input_control()
            send_btn = self._get_send_control()
            order_panel = self._get_order_panel()
            snapshot.update({
                "session_panel": self._describe_control(session_panel),
                "chat_panel": self._describe_control(chat_panel),
                "input_box": self._describe_control(input_box),
                "send_btn": self._describe_control(send_btn),
                "order_panel": self._describe_control(order_panel),
                "session_panel_child_count": len(session_panel.GetChildren()) if session_panel else 0,
                "chat_panel_child_count": len(chat_panel.GetChildren()) if chat_panel else 0,
                "chat_ready": bool(session_panel and chat_panel and input_box),
            })
            missing = []
            if not session_panel:
                missing.append("session_panel")
            if not chat_panel:
                missing.append("chat_panel")
            if not input_box:
                missing.append("input_box")
            snapshot["missing"] = missing
            if chat_panel:
                snapshot["chat_panel_texts"] = self._collect_control_texts(chat_panel, max_depth=2)[:12]
            if order_panel:
                snapshot["order_panel_texts"] = self._collect_control_texts(order_panel, max_depth=2)[:12]
        except Exception as e:
            snapshot["probe_error"] = str(e)[:200]
        return snapshot

    def _account_field_snapshot(self, account_ctrl=None, password_ctrl=None) -> Dict:
        snapshot = {
            "account_ctrl": self._describe_control(account_ctrl),
            "account_rect": self._get_control_rect(account_ctrl),
            "password_ctrl": self._describe_control(password_ctrl),
            "password_rect": self._get_control_rect(password_ctrl),
            "focused_ctrl": self._describe_control(self._debug_get_focused_control()),
        }
        try:
            active_target = self._resolve_active_edit_target(account_ctrl)
            snapshot["active_target"] = self._describe_control(active_target)
            snapshot["active_target_rect"] = self._get_control_rect(active_target)
            snapshot["account_read_text"] = (self._read_edit_text(account_ctrl) or "")[:80]
            snapshot["account_read_text_strict"] = (self._read_edit_text_strict(account_ctrl) or "")[:80]
            snapshot["active_target_read_text"] = (self._read_edit_text(active_target) or "")[:80]
            snapshot["active_target_read_text_strict"] = (self._read_edit_text_strict(active_target) or "")[:80]
            snapshot["account_display_local"] = (self._read_account_display(account_ctrl, include_fresh_controls=False) or "")[:80]
            snapshot["account_display_fresh"] = (self._read_account_display(account_ctrl, include_fresh_controls=True) or "")[:80]
            children = []
            if account_ctrl:
                for child in account_ctrl.GetChildren()[:6]:
                    children.append({
                        "ctrl": self._describe_control(child),
                        "rect": self._get_control_rect(child),
                        "text": (self._read_edit_text(child) or "")[:80],
                    })
            snapshot["account_children"] = children
        except Exception as e:
            snapshot["probe_error"] = str(e)[:200]
        return snapshot

    def _get_control_rect(self, ctrl):
        if not ctrl:
            return None
        try:
            rect = ctrl.BoundingRectangle
            if not rect:
                return None
            return {
                "left": int(rect.left),
                "top": int(rect.top),
                "right": int(rect.right),
                "bottom": int(rect.bottom),
            }
        except:
            return None

    def _get_control_top(self, ctrl, default: int = 10**9) -> int:
        rect = self._get_control_rect(ctrl)
        return rect["top"] if rect else default

    def _get_control_left(self, ctrl, default: int = 10**9) -> int:
        rect = self._get_control_rect(ctrl)
        return rect["left"] if rect else default

    def _is_rect_inside(self, inner_rect, outer_rect, padding: int = 10) -> bool:
        if not inner_rect or not outer_rect:
            return False
        return (
            inner_rect["left"] >= outer_rect["left"] - padding
            and inner_rect["top"] >= outer_rect["top"] - padding
            and inner_rect["right"] <= outer_rect["right"] + padding
            and inner_rect["bottom"] <= outer_rect["bottom"] + padding
        )

    def _resolve_active_edit_target(self, ctrl):
        if not ctrl:
            return None
        ctrl_type = str(self._safe_attr(ctrl, "ControlTypeName", "") or "")
        if ctrl_type not in ("EditControl", "DocumentControl"):
            return ctrl

        reference_rect = self._get_control_rect(ctrl)
        candidates = []
        seen = set()

        def add_candidate(candidate, focused: bool = False):
            if not candidate:
                return
            marker = id(candidate)
            if marker in seen:
                return
            seen.add(marker)
            candidate_type = str(self._safe_attr(candidate, "ControlTypeName", "") or "")
            if candidate_type not in ("EditControl", "DocumentControl"):
                return
            candidate_rect = self._get_control_rect(candidate)
            if reference_rect and candidate_rect and not self._is_rect_inside(candidate_rect, reference_rect, padding=14):
                return
            class_name = str(self._safe_attr(candidate, "ClassName", "") or "")
            area = 10**9
            if candidate_rect:
                area = max(1, candidate_rect["right"] - candidate_rect["left"]) * max(1, candidate_rect["bottom"] - candidate_rect["top"])
            score = 0
            if focused:
                score += 1000
            if class_name.lower() == "editwnd":
                score += 300
            if candidate_rect and reference_rect:
                score -= abs(candidate_rect["top"] - reference_rect["top"]) * 2
                score -= abs(candidate_rect["left"] - reference_rect["left"])
            score -= min(area // 100, 500)
            candidates.append((score, candidate))

        add_candidate(ctrl)
        add_candidate(self._debug_get_focused_control(), focused=True)

        if self._window and self._window.Exists():
            for candidate in self._walk_controls(self._window, max_depth=8):
                add_candidate(candidate)

        if not candidates:
            return ctrl
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _is_combo_or_account_selector(self, ctrl) -> bool:
        """检测是否是 ComboBox 类型的账号选择器，这类控件不应该被 Ctrl+A 清空"""
        if not ctrl:
            return False
        ctrl_type = str(self._safe_attr(ctrl, "ControlTypeName", "") or "")
        if ctrl_type == "ComboBoxControl":
            return True
        name = str(self._safe_attr(ctrl, "Name", "") or "")
        class_name = str(self._safe_attr(ctrl, "ClassName", "") or "")
        automation_id = str(self._safe_attr(ctrl, "AutomationId", "") or "")
        haystack = f"{name} {class_name} {automation_id}".lower()
        # ComboBox 类名和下拉选择器关键词
        if any(k in haystack for k in ["combobox", "dropdown", "选择", "selector", "accountlist", "账号列表"]):
            return True
        # 只读的 EditControl/DocumentControl 也视为账号选择器（千牛登录页常见）
        if ctrl_type in ("EditControl", "DocumentControl") and self._is_readonly_control(ctrl):
            return True
        return False

    def _is_readonly_control(self, ctrl) -> bool:
        """检测控件是否为只读（常用于账号选择器而非可编辑输入框）"""
        if not ctrl:
            return False
        # 方式1: 通过 Value 模式检查 IsReadOnly
        try:
            value_pattern = ctrl.GetValuePattern()
            if value_pattern and hasattr(value_pattern, 'IsReadOnly'):
                if value_pattern.IsReadOnly:
                    return True
        except:
            pass
        # 方式2: 通过 LIA 模式检查 state 是否包含 read-only
        try:
            lia = ctrl.GetLegacyIAccessiblePattern()
            if lia:
                state = getattr(lia, 'State', 0) or 0
                # STATE_SYSTEM_READONLY = 0x40 = 64
                if state & 0x40:
                    return True
        except:
            pass
        return False
    # #endregion
    
    # --------------------------------------------------
    # 窗口管理
    # --------------------------------------------------
    def find_window(self) -> bool:
        """遍历可能的窗口标识查找千牛主窗口"""
        if self._window:
            if self._safe_exists(self._window):
                return True
            self._reset_window_ref()

        # 方式-1: 优先按真实进程窗口句柄绑定
        if self._find_process_bound_window():
            return True

        # 嵌入模式下窗口已由 Manager 管理，不再从桌面根节点枚举（GetRootControl）
        if self.embedded:
            return False

        # 方式0: 枚举所有顶层窗口，匹配进程名或标题
        try:
            for w in auto.GetRootControl().GetChildren():
                try:
                    if not self._safe_exists(w, max_search_seconds=0.2):
                        continue
                    name = w.Name or ""
                    cls = w.ClassName or ""
                    if any(k in name for k in ("千牛", "AliWorkbench", "QianNiu")):
                        self._window = w
                        print(f"[QianNiuAdapter] 找到千牛(枚举): name={name} class={cls}")
                        return True
                except Exception:
                    pass
        except Exception:
            pass

        # 方式1: 按 (class, title) 组合查找
        for class_name in _QIANNIU_CLASSES:
            for title in _QIANNIU_TITLES:
                try:
                    w = auto.WindowControl(
                        searchDepth=1,
                        ClassName=class_name,
                        Name=title
                    )
                    if w.Exists(maxSearchSeconds=0.5):
                        self._window = w
                        print(f"[QianNiuAdapter] 找到千牛: class={class_name}")
                        return True
                except:
                    pass

        # 方式2: 非Chrome_WidgetWin_0类名直接搜索
        for class_name in ["AliWorkbenchMainWnd", "QianNiuMainWnd"]:
            try:
                w = auto.WindowControl(searchDepth=1, ClassName=class_name)
                if w.Exists(maxSearchSeconds=0.3):
                    self._window = w
                    print(f"[QianNiuAdapter] 找到千牛(类名): {class_name}")
                    return True
            except:
                pass

        # 方式3: 按标题模糊搜索（SubName匹配标题含"千牛"的窗口）
        for sub in ("千牛工作台", "千牛", "AliWorkbench"):
            try:
                w = auto.WindowControl(searchDepth=1, SubName=sub)
                if w.Exists(maxSearchSeconds=0.5):
                    # 排除Electron自身窗口
                    name = w.Name or ""
                    if "AI客服" not in name:
                        self._window = w
                        print(f"[QianNiuAdapter] 找到千牛(SubName={sub}): {name}")
                        return True
            except:
                pass

        return False
    
    def activate(self) -> bool:
        """激活千牛窗口到前台（嵌入模式下跳过）"""
        if not self._window or not self._safe_exists(self._window):
            return False
        if self.embedded:
            return True  # 嵌入模式不需要激活
        try:
            self._window.SetActive()
            self._window.SetFocus()
            time.sleep(0.1)
            return True
        except Exception:
            return False
    
    def is_alive(self) -> bool:
        """检查千牛窗口是否存活"""
        return self._window is not None and self._safe_exists(self._window)

    def _safe_attr(self, ctrl, attr: str, default=""):
        try:
            value = getattr(ctrl, attr)
            return value if value is not None else default
        except:
            return default

    def _walk_controls(self, ctrl, max_depth: int = 8, depth: int = 0):
        if not ctrl or depth > max_depth:
            return
        yield ctrl
        try:
            children = ctrl.GetChildren()
        except:
            children = []
        for child in children:
            yield from self._walk_controls(child, max_depth=max_depth, depth=depth + 1)

    def _dump_uia_tree(self, max_depth: int = 6) -> str:
        """将千牛窗口的 UIA 控件树 dump 到文件，用于诊断控件识别问题"""
        if not self._window or not self._window.Exists():
            return "窗口不存在"
        lines = []
        window_rect = self._get_control_rect(self._window)
        lines.append(f"=== UIA Tree Dump for 千牛窗口 ===")
        lines.append(f"窗口标题: {self._safe_attr(self._window, 'Name', '')}")
        lines.append(f"窗口类名: {self._safe_attr(self._window, 'ClassName', '')}")
        lines.append(f"窗口位置: {window_rect}")
        lines.append("")

        def _dump_ctrl(ctrl, depth: int, prefix: str = ""):
            if depth > max_depth:
                return
            try:
                ctrl_type = self._safe_attr(ctrl, "ControlTypeName", "") or "?"
                name = (self._safe_attr(ctrl, "Name", "") or "")[:60]
                class_name = (self._safe_attr(ctrl, "ClassName", "") or "")[:60]
                auto_id = (self._safe_attr(ctrl, "AutomationId", "") or "")[:60]
                rect = self._get_control_rect(ctrl)
                is_enabled = self._safe_attr(ctrl, "IsEnabled", "")
                is_off_screen = self._safe_attr(ctrl, "IsOffscreen", "")
                indent = "  " * depth
                rect_str = f" rect=({rect['left']},{rect['top']},{rect['right']},{rect['bottom']})" if rect else ""
                enabled_str = " OFFSCREEN" if is_off_screen else (" DISABLED" if is_enabled is False else "")
                lines.append(
                    f"{indent}[{ctrl_type}]{enabled_str} name='{name}' class='{class_name}' "
                    f"autoId='{auto_id}'{rect_str}"
                )
            except:
                lines.append(f"{'  ' * depth}[ERROR]")
                return
            try:
                children = ctrl.GetChildren()
            except:
                children = []
            for child in children:
                _dump_ctrl(child, depth + 1, prefix)

        _dump_ctrl(self._window, 0)
        dump_text = "\n".join(lines)
        # 写入文件
        dump_dir = os.path.join(os.getcwd(), ".dbg")
        os.makedirs(dump_dir, exist_ok=True)
        dump_path = os.path.join(dump_dir, "qianniu_uia_tree.txt")
        try:
            with open(dump_path, "w", encoding="utf-8") as f:
                f.write(dump_text)
            print(f"[QianNiuAdapter] UIA 树已 dump 到: {dump_path}")
        except Exception as e:
            print(f"[QianNiuAdapter] UIA 树 dump 写入失败: {e}")
        return dump_text

    def _find_named_control(self, control_types: List[str], keywords: List[str], max_depth: int = 8):
        if not self._window or not self._safe_exists(self._window):
            return None
        lowered = [k.lower() for k in keywords]
        login_noise = ("logo", "adwidget", "advert", "widget", "banner")
        for ctrl in self._walk_controls(self._window, max_depth=max_depth):
            ctrl_type = self._safe_attr(ctrl, "ControlTypeName", "")
            if ctrl_type not in control_types:
                continue
            name = str(self._safe_attr(ctrl, "Name", "") or "")
            class_name = str(self._safe_attr(ctrl, "ClassName", "") or "")
            automation_id = str(self._safe_attr(ctrl, "AutomationId", "") or "")
            haystack = f"{name} {class_name} {automation_id}".lower()
            if any(noise in haystack for noise in login_noise):
                continue
            # 英文关键词只匹配 Name，避免 automationId 中 login 子串误命中
            if any(k in name.lower() for k in lowered if k.isascii()):
                return ctrl
            if any(k in haystack for k in lowered if not k.isascii()):
                return ctrl
        return None

    def _find_controls_in_window_region(self, control_types: List[str], max_depth: int = 10,
                                        x_range: tuple = (0.0, 1.0), y_range: tuple = (0.0, 1.0)) -> List:
        if not self._window or not self._safe_exists(self._window):
            return []
        win_rect = self._get_control_rect(self._window)
        if not win_rect:
            return []
        width = max(1, win_rect["right"] - win_rect["left"])
        height = max(1, win_rect["bottom"] - win_rect["top"])
        matched = []
        for ctrl in self._walk_controls(self._window, max_depth=max_depth):
            try:
                ctrl_type = str(self._safe_attr(ctrl, "ControlTypeName", "") or "")
                if ctrl_type not in control_types:
                    continue
                rect = self._get_control_rect(ctrl)
                if not rect:
                    continue
                cx = (rect["left"] + rect["right"]) / 2
                cy = (rect["top"] + rect["bottom"]) / 2
                rx = (cx - win_rect["left"]) / width
                ry = (cy - win_rect["top"]) / height
                if x_range[0] <= rx <= x_range[1] and y_range[0] <= ry <= y_range[1]:
                    matched.append(ctrl)
            except Exception:
                continue
        return matched

    def _dismiss_workbench_popup(self) -> bool:
        if not self._window or not self._safe_exists(self._window):
            return False
        candidates = self._find_controls_in_window_region(
            ["ButtonControl", "TextControl", "HyperlinkControl", "CustomControl"],
            max_depth=12,
            x_range=(0.58, 0.78),
            y_range=(0.10, 0.35),
        )
        scored = []
        for ctrl in candidates:
            name = str(self._safe_attr(ctrl, "Name", "") or "").strip()
            class_name = str(self._safe_attr(ctrl, "ClassName", "") or "").strip()
            rect = self._get_control_rect(ctrl)
            if not rect:
                continue
            width = max(1, rect["right"] - rect["left"])
            height = max(1, rect["bottom"] - rect["top"])
            area = width * height
            score = 0
            if name in ("×", "X", "x", "关闭"):
                score += 300
            if "close" in class_name.lower():
                score += 120
            if width <= 80 and height <= 60:
                score += 80
            score -= min(area // 50, 120)
            scored.append((score, ctrl, name, rect))
        scored.sort(key=lambda item: item[0], reverse=True)
        for _, ctrl, name, rect in scored[:3]:
            try:
                ctrl.Click()
                self._cache_clear()
                self._login_log("chat.prepare", "已尝试关闭工作台弹层", {
                    "name": (name or "(空)")[:30],
                    "rect": rect,
                })
                time.sleep(0.6)
                return True
            except Exception:
                continue

        try:
            win_rect = self._window.BoundingRectangle
            if win_rect:
                scale = self._get_dpi_scale()
                lx = int((win_rect.left + (win_rect.right - win_rect.left) * 0.705) / scale)
                ly = int((win_rect.top + (win_rect.bottom - win_rect.top) * 0.27) / scale)
                self._human_click_logical(lx, ly, "关闭工作台弹层")
                self._cache_clear()
                time.sleep(0.6)
                return True
        except Exception:
            pass
        return False

    def _click_workbench_wangwang_entry(self) -> bool:
        if not self._window or not self._safe_exists(self._window):
            return False
        candidates = self._find_controls_in_window_region(
            ["ButtonControl", "HyperlinkControl", "TextControl", "CustomControl", "PaneControl"],
            max_depth=12,
            x_range=(0.90, 0.985),
            y_range=(0.015, 0.11),
        )
        win_rect = self._get_control_rect(self._window)
        if not win_rect:
            return False
        win_width = max(1, win_rect["right"] - win_rect["left"])
        win_height = max(1, win_rect["bottom"] - win_rect["top"])
        scored = []
        for ctrl in candidates:
            name = str(self._safe_attr(ctrl, "Name", "") or "").strip()
            class_name = str(self._safe_attr(ctrl, "ClassName", "") or "").strip()
            automation_id = str(self._safe_attr(ctrl, "AutomationId", "") or "").strip()
            rect = self._get_control_rect(ctrl)
            if not rect:
                continue
            width = max(1, rect["right"] - rect["left"])
            height = max(1, rect["bottom"] - rect["top"])
            area = width * height
            haystack = f"{name} {class_name} {automation_id}".lower()
            if any(k in haystack for k in [
                "反馈", "feed", "home", "首页", "设置", "menu", "通知", "notice",
                "消息中心", "msgcenter", "msg_center", "messagecenter", "pushbutton_msgcenter"
            ]):
                continue
            cx = (rect["left"] + rect["right"]) / 2
            cy = (rect["top"] + rect["bottom"]) / 2
            rx = (cx - win_rect["left"]) / win_width
            ry = (cy - win_rect["top"]) / win_height
            score = 0
            if any(k in haystack for k in ["旺旺", "wangwang", "aliim", "会话", "聊天", "客服", "kefu", "im", "chat"]):
                score += 320
            if not name:
                score += 120
            if automation_id:
                if any(k in automation_id.lower() for k in ["wangwang", "aliim", "kefu", "chat", "im"]):
                    score += 220
                if any(k in automation_id.lower() for k in ["msgcenter", "message", "notice", "feedback"]):
                    score -= 260
            if 16 <= width <= 42 and 16 <= height <= 42:
                score += 140
            elif 18 <= width <= 60 and 18 <= height <= 60:
                score += 70
            score += int(rx * 220)
            score += int(max(0, 0.12 - ry) * 600)
            score -= min(area // 40, 150)
            scored.append((score, ctrl, name, rect, {"rx": round(rx, 3), "ry": round(ry, 3), "class_name": class_name, "automation_id": automation_id}))
        scored.sort(key=lambda item: item[0], reverse=True)
        for _, ctrl, name, rect, meta in scored[:3]:
            try:
                ctrl.Click()
                self._cache_clear()
                self._login_log("chat.prepare", "已点击工作台右上旺旺入口", {
                    "name": (name or "(空)")[:30],
                    "rect": rect,
                    "meta": meta,
                })
                time.sleep(1.2)
                return True
            except Exception:
                continue

        try:
            raw_rect = self._window.BoundingRectangle
            if raw_rect:
                scale = self._get_dpi_scale()
                lx = int((raw_rect.left + (raw_rect.right - raw_rect.left) * 0.962) / scale)
                ly = int((raw_rect.top + (raw_rect.bottom - raw_rect.top) * 0.058) / scale)
                self._human_click_logical(lx, ly, "点击工作台右上旺旺图标")
                self._cache_clear()
                time.sleep(1.2)
                return True
        except Exception:
            pass
        return False

    def _is_submit_login_button(self, name: str) -> bool:
        name = (name or "").strip()
        if not name:
            return False
        blocked = ("多账号", "注册", "忘记", "扫码", "切换", "验证", "帮助", "返回", "其他")
        if any(b in name for b in blocked):
            return False
        return name in ("登录", "登 录", "立即登录")

    def _ctrl_to_logical_center(self, ctrl) -> tuple:
        rect = ctrl.BoundingRectangle
        scale = self._get_dpi_scale()
        return (
            int((rect.left + rect.right) / 2 / scale),
            int((rect.top + rect.bottom) / 2 / scale),
        )

    def _human_click_logical(self, lx: int, ly: int, label: str = ""):
        self.activate()
        time.sleep(0.15)
        if _HAS_PYAUTOGUI:
            pyautogui.click(lx, ly)
        else:
            scale = self._get_dpi_scale()
            auto.Click(int(lx * scale), int(ly * scale), waitTime=0.1)
        self._login_log("human.click", label or "点击", {"x": lx, "y": ly})

    def _human_clear_field(self):
        if _HAS_PYAUTOGUI:
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.08)
            pyautogui.press("delete")
        else:
            auto.SendKeys("{Ctrl}a", waitTime=0.05)
            auto.SendKeys("{Delete}", waitTime=0.05)
        time.sleep(0.12)

    def _human_type_text(self, text: str, mask: bool = False):
        if not text:
            return True
        if any(ord(c) > 127 for c in text):
            self._set_clipboard_text(text)
            if _HAS_PYAUTOGUI:
                pyautogui.hotkey("ctrl", "v")
            else:
                auto.SendKeys("{Ctrl}v", waitTime=0.15)
            time.sleep(0.2)
            return True
        if _HAS_PYAUTOGUI:
            pyautogui.write(text, interval=0.05)
            time.sleep(0.15)
            return True
        return self._type_like_human(text)

    def _click_blank_between_fields(self, username_ctrl, password_ctrl) -> bool:
        try:
            scale = self._get_dpi_scale()
            if username_ctrl and password_ctrl:
                un = username_ctrl.BoundingRectangle
                pw = password_ctrl.BoundingRectangle
                if un and pw:
                    lx = int((un.left + un.right) / 2 / scale)
                    ly = int((un.bottom / scale + pw.top / scale) / 2)
                    self._human_click_logical(lx, ly, "点击账号与密码之间的空白区域")
                    return True
            return self._click_blank_area()
        except Exception:
            return self._click_blank_area()

    def _read_account_display(self, ctrl, include_fresh_controls: bool = True) -> str:
        candidates = []
        seen = set()

        def push(candidate):
            if not candidate:
                return
            marker = id(candidate)
            if marker in seen:
                return
            seen.add(marker)
            candidates.append(candidate)

        push(ctrl)
        push(self._resolve_active_edit_target(ctrl))
        if include_fresh_controls:
            try:
                username_ctrl, _, _, account_display_ctrl = self._find_login_controls()
                push(account_display_ctrl)
                push(username_ctrl)
                push(self._resolve_active_edit_target(account_display_ctrl))
                push(self._resolve_active_edit_target(username_ctrl))
            except Exception:
                pass

        for candidate in candidates:
            value = self._read_edit_text(candidate)
            name = str(self._safe_attr(candidate, "Name", "") or "").strip()
            current = (value or name or "").strip()
            if current:
                return current
        return ""

    def _is_account_history_field(self, ctrl, password_ctrl=None) -> bool:
        if not ctrl:
            return False
        if self._is_combo_or_account_selector(ctrl):
            return True
        name = str(self._safe_attr(ctrl, "Name", "") or "").strip()
        placeholder_hints = ("请输入账号", "账号", "手机", "用户名")
        if name in placeholder_hints or not name:
            if password_ctrl:
                try:
                    return self._get_control_top(ctrl) < self._get_control_top(password_ctrl)
                except Exception:
                    pass
            return True
        ctrl_type = str(self._safe_attr(ctrl, "ControlTypeName", "") or "")
        if ctrl_type == "EditControl":
            if ":" in name or "公司" in name or "@" in name or len(name) > 8:
                return True
        return False

    def _account_fill_verified(self, ctrl, username: str, password_ctrl=None) -> bool:
        invalid = ("请输入账号", "请输入密码", "")
        for probe in [ctrl]:
            current = self._read_account_display(probe)
            if not current or current in invalid:
                continue
            normalized = (username or "").strip()
            if normalized and (normalized in current or current in normalized):
                return True
            if len(current) >= 3:
                return True
        try:
            fresh_user, _, _, _ = self._find_login_controls()
            probe = fresh_user or ctrl
            current = self._read_account_display(probe)
            if current and current not in invalid:
                normalized = (username or "").strip()
                if not normalized or normalized in current or current in normalized or len(current) >= 3:
                    return True
        except Exception:
            pass
        return False

    def _send_keys_on_control(self, ctrl, keys: str, wait: float = 0.08) -> bool:
        try:
            ctrl.SetFocus()
            time.sleep(0.1)
        except Exception:
            pass
        try:
            ctrl.SendKeys(keys, waitTime=wait)
            return True
        except Exception:
            try:
                auto.SendKeys(keys, waitTime=wait)
                return True
            except Exception:
                return False

    def _resolve_login_edits(self):
        try:
            username_ctrl, password_ctrl, _, account_display_ctrl = self._find_login_controls()
            if username_ctrl or password_ctrl or account_display_ctrl:
                return username_ctrl or account_display_ctrl, password_ctrl
        except Exception:
            pass

        edits = []
        for ctrl in self._walk_controls(self._window, max_depth=10):
            if self._safe_attr(ctrl, "ControlTypeName", "") == "EditControl":
                edits.append(ctrl)
        edits.sort(key=lambda item: (self._get_control_top(item), self._get_control_left(item)))
        if len(edits) >= 2:
            return edits[0], edits[1]
        if len(edits) == 1:
            return edits[0], None
        return None, None

    def _account_field_has_value(self, account_ctrl=None) -> bool:
        account_ctrl = account_ctrl or self._resolve_login_edits()[0]
        if not account_ctrl:
            return False
        value = self._read_account_display(account_ctrl)
        return bool(value and value not in ("请输入账号", "请输入密码", ""))

    def _account_display_matches(self, display: str, expected: str) -> bool:
        display = (display or "").strip()
        expected = (expected or "").strip()
        if not display or display in ("请输入账号", ""):
            return False
        if not expected:
            return len(display) >= 3
        if display == expected:
            return True
        # 配置主账号时，历史项「公司:子账号」不算正确匹配
        if ":" in display and ":" not in expected:
            company_part = display.split(":", 1)[0].strip()
            if company_part == expected:
                return False
        return False

    def _pick_login_dropdown_item(self, expected: str) -> bool:
        """在下拉列表中点击与配置账号完全一致的项（优先无「:子账号」后缀）。"""
        expected = (expected or "").strip()
        if not expected:
            return False
        exact_items = []
        plain_items = []
        for ctrl in self._walk_controls(self._window, max_depth=9):
            ctrl_type = self._safe_attr(ctrl, "ControlTypeName", "")
            if ctrl_type not in ("ListItemControl", "DataItemControl", "TreeItemControl"):
                continue
            name = str(self._safe_attr(ctrl, "Name", "") or "").strip()
            if not name:
                continue
            if name == expected:
                exact_items.append(ctrl)
            elif name.startswith(expected) and ":" not in name:
                plain_items.append(ctrl)
        for ctrl in exact_items + plain_items:
            try:
                self._click_control_center(ctrl)
                time.sleep(0.35)
                self._login_log("human.account", "已点击下拉匹配项", {
                    "name": str(self._safe_attr(ctrl, "Name", "") or "")[:50],
                })
                return True
            except Exception:
                continue
        return False

    def _account_fill_via_uia(self, account_ctrl, account_name: str, should_try_expand_first: bool = True) -> bool:
        """聚焦账号框：全选后直接替换为公司名，再选下拉主账号。"""
        if not account_ctrl:
            return False
        self.activate()
        time.sleep(0.3)
        text_lx, text_ly, arrow_lx, arrow_ly = self._account_ctrl_logical_points(account_ctrl)
        active_account_ctrl = self._resolve_active_edit_target(account_ctrl) or account_ctrl
        # #region debug-point B:uia-fill-before
        self._debug_emit_account_probe("B", "account_fill_via_uia:before_expand", account_ctrl)
        # #endregion

        if should_try_expand_first and self._account_expand_and_pick(account_ctrl, account_name):
            current = self._read_account_display(active_account_ctrl, include_fresh_controls=False)
            if self._account_display_matches(current, account_name):
                self._login_log("human.account", "下拉已选中主账号", {"value": (current or "")[:50]})
                return True

        self._human_click_logical(text_lx, text_ly, "点击账号框")
        target_ctrl = self._resolve_active_edit_target(account_ctrl) or active_account_ctrl
        try:
            (target_ctrl or account_ctrl).SetFocus()
        except Exception:
            pass
        time.sleep(0.25)

        if not self._set_clipboard_text(account_name):
            self._login_log("human.account", "设置账号剪贴板失败", level="warn")
            return False

        if not self._send_keys_on_control(target_ctrl or account_ctrl, "{Ctrl}a", wait=0.05):
            self._win32_send_hotkey("ctrl", "a")
        time.sleep(0.15)
        if not self._send_keys_on_control(target_ctrl or account_ctrl, "{Ctrl}v", wait=0.12):
            self._win32_send_hotkey("ctrl", "v")
        self._login_log("human.account", "Win32 已全选并粘贴公司名", {"length": len(account_name or "")})
        time.sleep(0.9)
        # #region debug-point B:uia-fill-after-paste
        self._debug_emit_account_probe("B", "account_fill_via_uia:after_paste", account_ctrl)
        # #endregion

        current_after_paste = self._read_account_display(target_ctrl or account_ctrl, include_fresh_controls=False)
        if not self._account_display_matches(current_after_paste, account_name):
            refreshed_account_ctrl, _ = self._resolve_login_edits()
            refreshed_account_ctrl = refreshed_account_ctrl or account_ctrl
            refreshed_target_ctrl = self._resolve_active_edit_target(refreshed_account_ctrl) or refreshed_account_ctrl
            refreshed_after_paste = self._read_account_display(refreshed_target_ctrl, include_fresh_controls=False)
            if refreshed_after_paste:
                account_ctrl = refreshed_account_ctrl
                target_ctrl = refreshed_target_ctrl
                current_after_paste = refreshed_after_paste
        self._login_log("human.account", "粘贴后账号框状态", {
            "current": (current_after_paste or "")[:50],
        })
        if current_after_paste and self._account_display_matches(current_after_paste, account_name):
            self._login_log("human.account", "Win32 鐩村～鍚庡凡鍛戒腑鐩爣涓昏处鍙凤紝璺宠繃浜屾涓嬫媺纭", {
                "current": current_after_paste[:50],
            })
            return True
        if current_after_paste and ":" in current_after_paste and current_after_paste.split(":", 1)[0].strip() == account_name:
            self._login_log("human.account", "粘贴未替换历史子账号，改用 Unicode 逐字输入", level="warn")
            self._human_click_logical(text_lx, text_ly, "重新点击账号文本区")
            time.sleep(0.2)
            self._win32_send_hotkey("ctrl", "a")
            time.sleep(0.12)
            self._win32_type_unicode(account_name, interval=0.08)
            time.sleep(0.8)

        if self._pick_login_dropdown_item(account_name):
            return True

        target_ctrl = self._resolve_active_edit_target(account_ctrl) or target_ctrl or account_ctrl
        for _ in range(4):
            current = self._read_account_display(target_ctrl, include_fresh_controls=False)
            if self._account_display_matches(current, account_name):
                self._login_log("human.account", "方向键选中主账号", {"value": current[:50]})
                self._win32_send_hotkey("enter")
                time.sleep(0.3)
                return True
            self._win32_send_hotkey("down")
            time.sleep(0.12)

        current = self._read_account_display(target_ctrl, include_fresh_controls=False)
        self._login_log("human.account", "未识别到主账号下拉项，按 Enter 确认当前账号", {
            "current": (current or "")[:50],
        }, level="warn")
        self._win32_send_hotkey("enter")
        time.sleep(0.35)
        return True

    def _fill_password_via_uia(self, password_ctrl, password: str) -> bool:
        if not password_ctrl:
            return False
        password_target = self._resolve_active_edit_target(password_ctrl)
        self._click_control_center(password_target or password_ctrl)
        try:
            (password_target or password_ctrl).SetFocus()
        except Exception:
            pass
        time.sleep(0.2)

        def send_keys(keys: str, wait: float = 0.06):
            try:
                (password_target or password_ctrl).SendKeys(keys, waitTime=wait)
            except Exception:
                auto.SendKeys(keys, waitTime=wait)

        send_keys("{Ctrl}a", 0.05)
        send_keys("{Delete}", 0.05)
        time.sleep(0.1)
        try:
            (password_target or password_ctrl).SendKeys(password or "", waitTime=0.05)
        except Exception:
            if self._set_clipboard_text(password):
                send_keys("{Ctrl}v", 0.12)
            else:
                return False
        time.sleep(0.25)
        return True

    def _account_fill_exact_name_at(self, lx: int, ly: int, account_name: str):
        """全选后粘贴公司名，并从下拉选中无子账号后缀的项。"""
        self._human_click_logical(lx, ly, "点击账号框")
        time.sleep(0.35)
        # 账号框是历史选择器，不使用 Delete，避免清空后输入丢失。
        if _HAS_PYAUTOGUI:
            pyautogui.hotkey("ctrl", "a")
        else:
            auto.SendKeys("{Ctrl}a", waitTime=0.08)
        time.sleep(0.15)
        if not self._set_clipboard_text(account_name):
            if _HAS_PYAUTOGUI:
                pyautogui.write(account_name, interval=0.06)
            else:
                auto.SendKeys(account_name, waitTime=0.05)
        elif _HAS_PYAUTOGUI:
            pyautogui.hotkey("ctrl", "v")
        else:
            auto.SendKeys("{Ctrl}v", waitTime=0.12)
        time.sleep(0.65)
        if self._pick_login_dropdown_item(account_name):
            return
        # 未识别到下拉项时：用方向键跳过带冒号的子账号
        for _ in range(6):
            if _HAS_PYAUTOGUI:
                pyautogui.press("down")
            else:
                auto.SendKeys("{Down}", waitTime=0.08)
            time.sleep(0.12)
            account_ctrl, _ = self._resolve_login_edits()
            current = self._read_account_display(account_ctrl)
            if self._account_display_matches(current, account_name):
                if _HAS_PYAUTOGUI:
                    pyautogui.press("enter")
                else:
                    auto.SendKeys("{Enter}", waitTime=0.12)
                time.sleep(0.35)
                return
        if _HAS_PYAUTOGUI:
            pyautogui.press("enter")
        else:
            auto.SendKeys("{Enter}", waitTime=0.12)
        time.sleep(0.45)

    def _account_type_enter_at(self, lx: int, ly: int, text: str, clear_first: bool = False):
        self._human_click_logical(lx, ly, "点击账号框")
        time.sleep(0.35)
        if clear_first:
            self._human_clear_field()
            time.sleep(0.15)
        if _HAS_PYAUTOGUI:
            pyautogui.write(text or "", interval=0.06)
        else:
            auto.SendKeys(text or "", waitTime=0.05)
        time.sleep(0.2)
        if _HAS_PYAUTOGUI:
            pyautogui.press("enter")
        else:
            auto.SendKeys("{Enter}", waitTime=0.12)
        time.sleep(0.18)

    def _account_paste_enter_at(self, lx: int, ly: int, text: str, clear_first: bool = False):
        if not self._set_clipboard_text(text):
            return False
        self._human_click_logical(lx, ly, "点击账号框")
        time.sleep(0.35)
        if clear_first:
            self._human_clear_field()
            time.sleep(0.15)
        if _HAS_PYAUTOGUI:
            pyautogui.hotkey("ctrl", "v")
        else:
            auto.SendKeys("{Ctrl}v", waitTime=0.12)
        time.sleep(0.55)
        if _HAS_PYAUTOGUI:
            pyautogui.press("enter")
        else:
            auto.SendKeys("{Enter}", waitTime=0.12)
        time.sleep(0.45)
        return True

    def _account_dropdown_first_at(self, lx: int, ly: int):
        self._human_click_logical(lx, ly, "点击账号框展开下拉")
        time.sleep(0.45)
        if _HAS_PYAUTOGUI:
            pyautogui.press("down")
            time.sleep(0.35)
            pyautogui.press("enter")
        else:
            auto.SendKeys("{Down}", waitTime=0.12)
            time.sleep(0.35)
            auto.SendKeys("{Enter}", waitTime=0.12)
        time.sleep(0.45)

    def _account_search_hint_at(self, lx: int, ly: int, search_key: str):
        self._human_click_logical(lx, ly, "点击账号框")
        time.sleep(0.35)
        if search_key and not search_key.isascii():
            if self._set_clipboard_text(search_key):
                if _HAS_PYAUTOGUI:
                    pyautogui.hotkey("ctrl", "v")
                else:
                    auto.SendKeys("{Ctrl}v", waitTime=0.12)
            else:
                auto.SendKeys(search_key, waitTime=0.05)
        elif _HAS_PYAUTOGUI:
            pyautogui.write(search_key, interval=0.06)
        else:
            auto.SendKeys(search_key, waitTime=0.05)
        time.sleep(0.5)
        if _HAS_PYAUTOGUI:
            pyautogui.press("enter")
        else:
            auto.SendKeys("{Enter}", waitTime=0.12)
        time.sleep(0.45)

    def _human_fill_account(self, username_ctrl, username: str, password_ctrl=None) -> bool:
        account_ctrl = username_ctrl
        pwd_edit = None
        if not account_ctrl or not password_ctrl:
            resolved_account_ctrl, resolved_password_ctrl = self._resolve_login_edits()
            account_ctrl = account_ctrl or resolved_account_ctrl
            pwd_edit = resolved_password_ctrl
        password_ctrl = pwd_edit or password_ctrl
        expected = (username or "").strip()
        # #region debug-point A:account-start
        self._debug_emit_account_probe("A", "human_fill_account:start", account_ctrl, password_ctrl)
        # #endregion
        active_target = self._resolve_active_edit_target(account_ctrl) if account_ctrl else None
        strict_hint = (
            self._read_edit_text_strict(active_target)
            or self._read_edit_text_strict(account_ctrl)
            or ""
        ).strip()
        initial_hint = self._read_account_display(account_ctrl, include_fresh_controls=False)
        self._login_log("human.account", "账号框初始状态", {
            "hint": (initial_hint or "(空)")[:50],
            "strict_hint": (strict_hint or "(空)")[:50],
            "expected": expected[:50],
        })
        self._login_log("human.account.probe", "账号阶段初始快照", self._account_field_snapshot(account_ctrl, password_ctrl), level="info")

        if self._account_display_matches(strict_hint, expected):
            self._login_log("human.account.probe", "账号当前值命中目标，但仍执行账号确认策略", self._account_field_snapshot(account_ctrl, password_ctrl), level="warn")
            self._login_log("human.account", "账号控件值看似正确，继续执行账号确认策略", {"value": strict_hint[:50]})
        if self._account_display_matches(initial_hint, expected):
            self._login_log("human.account", "外层显示值命中目标账号，但严格读值为空或不匹配，继续重填", {
                "hint": initial_hint[:50],
                "strict_hint": strict_hint[:50],
                "expected": expected[:50],
            }, level="warn")

        if initial_hint and ":" in initial_hint and expected and ":" not in expected:
            company_part = initial_hint.split(":", 1)[0].strip()
            if company_part == expected:
                self._login_log("human.account", "历史为子账号，需重选主账号", {
                    "history": initial_hint[:50],
                    "expected": expected[:50],
                })

        fill_executed = False
        account_ctrl = account_ctrl or username_ctrl

        account_strategies = []
        should_try_dropdown_first = bool((initial_hint or "").strip())
        should_try_expand_inside_uia = bool((initial_hint or "").strip())
        if should_try_dropdown_first:
            account_strategies.append(("灞曞紑涓嬫媺閫変富璐﹀彿", lambda: self._account_expand_and_pick(account_ctrl, expected)))
        account_strategies.append(("Win32濞撳懐鈹栭獮鎯扮翻閸忋儱鍙曢崣绋挎倳", lambda: self._account_fill_via_uia(account_ctrl, expected, should_try_expand_first=should_try_expand_inside_uia)))
        if not should_try_dropdown_first:
            account_strategies.append(("灞曞紑涓嬫媺閫変富璐﹀彿", lambda: self._account_expand_and_pick(account_ctrl, expected)))

        for label, strategy in account_strategies:
            try:
                self._login_log("human.account.probe", "准备执行账号策略", {
                    "strategy": label,
                    "expected": expected[:50],
                    **self._account_field_snapshot(account_ctrl, password_ctrl),
                }, level="info")
                # #region debug-point A:before-strategy
                self._debug_emit_account_probe("A", f"before_strategy:{label}", account_ctrl, password_ctrl)
                # #endregion
                strategy_succeeded = bool(strategy())
            except Exception as e:
                self._login_log("human.account", f"策略异常: {e}", level="warn")
                continue

            if not strategy_succeeded:
                self._login_log("human.account", "策略执行完成但未选中目标账号", {
                    "strategy": label,
                    "expected": expected[:50],
                }, level="warn")
                continue

            fill_executed = True

            current = self._read_account_display(account_ctrl, include_fresh_controls=False)
            if not self._account_display_matches(current, expected):
                refreshed_account_ctrl, _ = self._resolve_login_edits()
                if refreshed_account_ctrl:
                    account_ctrl = refreshed_account_ctrl
                    current = self._read_account_display(account_ctrl, include_fresh_controls=False)
            # #region debug-point A:after-strategy
            self._debug_emit_account_probe("A", f"after_strategy:{label}", account_ctrl, password_ctrl)
            # #endregion
            if self._account_display_matches(current, expected):
                self._login_log("human.account", "账号已填入", {
                    "strategy": label,
                    "value": current[:50],
                })
                return True
            if current and expected and current.startswith(expected) and ":" not in current:
                self._login_log("human.account", "账号近似匹配", {"value": current[:50]})
                return True

        if fill_executed:
            final_current = self._read_account_display(account_ctrl, include_fresh_controls=False)
            if not self._account_display_matches(final_current, expected):
                refreshed_account_ctrl, _ = self._resolve_login_edits()
                if refreshed_account_ctrl:
                    account_ctrl = refreshed_account_ctrl
                    final_current = self._read_account_display(account_ctrl, include_fresh_controls=False)
            # #region debug-point A:final-account-check
            self._debug_emit_account_probe("A", "human_fill_account:final_check", account_ctrl, password_ctrl)
            # #endregion
            if self._account_display_matches(final_current, expected):
                self._login_log("human.account", "最终复核通过，继续填密码", {
                    "value": final_current[:50],
                })
                return True
            self._login_log("human.account", "账号策略已执行，但最终未确认到目标账号", {
                "expected": expected[:50],
                "current": (final_current or "")[:50],
            }, level="error")
            return False

        self._login_log("human.account", "账号填写失败", {
            "expected": expected[:50],
        }, level="error")
        return False

    def _human_click_blank_safe(self, username_ctrl, password_ctrl) -> bool:
        """点击窗体右侧空白，避免点在账号/密码之间导致账号被清空"""
        try:
            scale = self._get_dpi_scale()
            win_rect = self._window.BoundingRectangle
            if win_rect:
                lx = int((win_rect.left + (win_rect.right - win_rect.left) * 0.88) / scale)
                ly = int((win_rect.top + (win_rect.bottom - win_rect.top) * 0.22) / scale)
                self._human_click_logical(lx, ly, "点击窗体右侧空白区域")
                return True
        except Exception:
            pass
        return self._click_blank_area()

    def _simulate_human_login_sequence(
        self, username_ctrl, password_ctrl, username: str, password: str
    ) -> bool:
        """模拟人工：点账号→(必要时输入)→Tab到密码→输入密码"""
        self._login_log("human.start", "开始模拟人工登录")
        try:
            self.activate()
            time.sleep(0.4)

            account_ctrl = username_ctrl
            pwd_ctrl = password_ctrl
            if not account_ctrl or not pwd_ctrl:
                resolved_account_ctrl, resolved_password_ctrl = self._resolve_login_edits()
                account_ctrl = account_ctrl or resolved_account_ctrl
                pwd_ctrl = pwd_ctrl or resolved_password_ctrl
            password_ctrl = pwd_ctrl or password_ctrl

            if not self._human_fill_account(account_ctrl, username, password_ctrl):
                return False
            time.sleep(0.25)

            # 用 Tab 切换焦点到密码框，避免点空白导致账号被清空
            self._login_log("human.click", "按 Tab 从账号切换到密码框")
            auto.SendKeys("{Tab}", waitTime=0.12)
            time.sleep(0.35)

            refreshed_username_ctrl, refreshed_password_ctrl, _, _ = self._find_login_controls()
            password_ctrl = refreshed_password_ctrl or password_ctrl
            if refreshed_password_ctrl:
                self._login_log("human.password", "Tab 后重新识别密码控件", {
                    "password_ctrl": self._describe_control(refreshed_password_ctrl),
                })

            pwd_filled = False
            if password_ctrl:
                px, py = self._ctrl_to_logical_center(password_ctrl)
                self._human_click_logical(px, py, "点击密码输入框")
                time.sleep(0.3)

                pwd_filled = self._fill_login_edit(password_ctrl, password, "密码", mask_value=True)
                if not pwd_filled:
                    pwd_filled = self._fill_password_via_uia(password_ctrl, password)
                if not pwd_filled:
                    pwd_filled = self._fill_password_via_tab(
                        refreshed_username_ctrl or account_ctrl,
                        password_ctrl,
                        password,
                    )

            if not pwd_filled:
                self._login_log("human.password", "密码控件填写未确认，回退到当前焦点直接输入", level="warn")
                self._human_type_text(password, mask=True)
            self._login_log("human.type", "已输入密码", {
                "length": len(password or ""),
                "method": "multi_strategy" if pwd_filled else "focused_type",
            })
            time.sleep(0.35)
            return True
        except Exception as e:
            self._login_log("human.fail", f"模拟人工登录失败: {e}", level="error")
            return False

    def _find_login_button_control(self, password_ctrl=None):
        candidates = []
        for ctrl in self._walk_controls(self._window, max_depth=12):
            ctrl_type = self._safe_attr(ctrl, "ControlTypeName", "")
            if ctrl_type not in ("ButtonControl", "TextControl", "HyperlinkControl", "CustomControl", "PaneControl"):
                continue
            name = str(self._safe_attr(ctrl, "Name", "") or "").strip()
            if not self._is_submit_login_button(name):
                continue
            try:
                rect = ctrl.BoundingRectangle
                width = int(rect.right - rect.left) if rect else 0
                height = int(rect.bottom - rect.top) if rect else 0
                top = int(rect.top) if rect else 0
            except Exception:
                continue
            score = 0
            if name in ("登录", "登 录"):
                score += 200
            if ctrl_type == "ButtonControl":
                score += 50
            if width >= 100:
                score += 30
            if password_ctrl:
                try:
                    pw_bottom = int(password_ctrl.BoundingRectangle.bottom)
                    if top >= pw_bottom - 5:
                        score += 80
                except Exception:
                    pass
            candidates.append((score, ctrl, name))

        if candidates:
            candidates.sort(key=lambda item: item[0], reverse=True)
            return candidates[0][1]

        if password_ctrl:
            try:
                pw_rect = password_ctrl.BoundingRectangle
                if pw_rect:
                    geom_candidates = []
                    for ctrl in self._walk_controls(self._window, max_depth=10):
                        ctrl_type = self._safe_attr(ctrl, "ControlTypeName", "")
                        if ctrl_type not in ("ButtonControl", "TextControl", "HyperlinkControl", "CustomControl", "PaneControl"):
                            continue
                        name = str(self._safe_attr(ctrl, "Name", "") or "").strip()
                        if name and not self._is_submit_login_button(name):
                            continue
                        rect = ctrl.BoundingRectangle
                        if not rect:
                            continue
                        top = int(rect.top)
                        if top < int(pw_rect.bottom):
                            continue
                        width = int(rect.right - rect.left)
                        height = int(rect.bottom - rect.top)
                        if width < 100 or height < 24 or height > 80:
                            continue
                        score = width - abs(top - int(pw_rect.bottom) - 55) * 2
                        geom_candidates.append((score, ctrl))
                    if geom_candidates:
                        geom_candidates.sort(key=lambda item: item[0], reverse=True)
                        return geom_candidates[0][1]
            except Exception:
                pass
        return None

    def _find_clickable_control_by_keywords(
        self,
        keywords: List[str],
        exclude_keywords: Optional[List[str]] = None,
        max_depth: int = 10
    ):
        if not self._window or not self._window.Exists():
            return None
        lowered = [k.lower() for k in keywords if k]
        excluded = [k.lower() for k in (exclude_keywords or []) if k]
        preferred_types = {
            "ButtonControl",
            "HyperlinkControl",
            "TextControl",
            "PaneControl",
            "CustomControl",
            "ListItemControl",
        }

        candidates = []
        for ctrl in self._walk_controls(self._window, max_depth=max_depth):
            ctrl_type = self._safe_attr(ctrl, "ControlTypeName", "")
            if ctrl_type not in preferred_types:
                continue
            name = str(self._safe_attr(ctrl, "Name", "") or "")
            class_name = str(self._safe_attr(ctrl, "ClassName", "") or "")
            automation_id = str(self._safe_attr(ctrl, "AutomationId", "") or "")
            haystack = f"{name} {class_name} {automation_id}".lower().strip()
            if not haystack:
                continue
            if excluded and any(k in haystack for k in excluded):
                continue
            if not any(k in haystack for k in lowered):
                continue
            try:
                rect = ctrl.BoundingRectangle
                width = max(0, int(rect.right - rect.left)) if rect else 0
                height = max(0, int(rect.bottom - rect.top)) if rect else 0
            except:
                width = 0
                height = 0
            score = 0
            if ctrl_type == "ButtonControl":
                score += 50
            if any(k in name.lower() for k in lowered):
                score += 30
            if width > 20 and height > 12:
                score += 10
            candidates.append((score, ctrl, name))

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _get_dpi_scale(self) -> float:
        """获取当前屏幕 DPI 缩放比例（物理像素/逻辑像素）"""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            dc = user32.GetDC(0)
            dpi_x = ctypes.windll.gdi32.GetDeviceCaps(dc, 88)  # LOGPIXELSX
            user32.ReleaseDC(0, dc)
            scale = dpi_x / 96.0
            print(f"[QianNiuAdapter] DPI缩放: {scale:.2f}x (dpi={dpi_x})")
            return scale
        except Exception as e:
            print(f"[QianNiuAdapter] 获取DPI失败: {e}, 默认1.0x")
            return 1.0

    def _win32_click(self, phys_x: int, phys_y: int) -> bool:
        """用 win32api 移动鼠标并发送 WM_LBUTTONDOWN/UP，绕过前台焦点限制。
        phys_x/phys_y 为物理像素（与 UIA BoundingRectangle 同坐标系）。
        """
        try:
            import ctypes
            scale = self._get_dpi_scale()
            # 转为逻辑像素给 SetCursorPos / mouse_event
            lx = int(phys_x / scale)
            ly = int(phys_y / scale)
            # 方式1：移动鼠标再点击（最可靠）
            ctypes.windll.user32.SetCursorPos(lx, ly)
            time.sleep(0.05)
            ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
            time.sleep(0.05)
            ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP
            time.sleep(0.05)
            print(f"[QianNiuAdapter] win32 mouse_event 点击 物理({phys_x},{phys_y}) 逻辑({lx},{ly})")
            return True
        except Exception as e:
            print(f"[QianNiuAdapter] win32_click 失败: {e}")
            return False

    def _win32_send_hotkey(self, *keys: str) -> bool:
        """用 SendInput 发送组合键，比 pyautogui 更易落到千牛原生控件。"""
        vk_map = {
            "ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10,
            "a": 0x41, "v": 0x56, "c": 0x43, "enter": 0x0D, "return": 0x0D,
            "down": 0x28, "up": 0x26, "tab": 0x09, "delete": 0x2E, "backspace": 0x08,
        }
        try:
            import ctypes
            from ctypes import wintypes

            INPUT_KEYBOARD = 1
            KEYEVENTF_KEYUP = 0x0002

            class KEYBDINPUT(ctypes.Structure):
                _fields_ = [
                    ("wVk", wintypes.WORD),
                    ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
                ]

            class INPUT_UNION(ctypes.Union):
                _fields_ = [("ki", KEYBDINPUT)]

            class INPUT(ctypes.Structure):
                _fields_ = [("type", wintypes.DWORD), ("u", INPUT_UNION)]

            extra = ctypes.c_ulong(0)
            extra_ptr = ctypes.pointer(extra)
            send = ctypes.windll.user32.SendInput

            def key_event(vk: int, key_up: bool = False):
                flags = KEYEVENTF_KEYUP if key_up else 0
                inp = INPUT(
                    type=INPUT_KEYBOARD,
                    u=INPUT_UNION(ki=KEYBDINPUT(vk, 0, flags, 0, extra_ptr)),
                )
                send(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

            modifiers = []
            normal = []
            for key in keys:
                lowered = (key or "").lower()
                if lowered in ("ctrl", "control", "alt", "shift"):
                    modifiers.append(vk_map[lowered])
                else:
                    vk = vk_map.get(lowered)
                    if vk is not None:
                        normal.append(vk)

            for vk in modifiers:
                key_event(vk, False)
                time.sleep(0.02)
            for vk in normal:
                key_event(vk, False)
                time.sleep(0.02)
                key_event(vk, True)
                time.sleep(0.02)
            for vk in reversed(modifiers):
                key_event(vk, True)
                time.sleep(0.02)
            return True
        except Exception as e:
            print(f"[QianNiuAdapter] win32_send_hotkey 失败: {e}")
            return False

    def _win32_type_unicode(self, text: str, interval: float = 0.06) -> bool:
        """逐字符 Unicode 输入，用于千牛账号框过滤下拉。"""
        if not text:
            return True
        try:
            import ctypes
            from ctypes import wintypes

            INPUT_KEYBOARD = 1
            KEYEVENTF_KEYUP = 0x0002
            KEYEVENTF_UNICODE = 0x0004

            class KEYBDINPUT(ctypes.Structure):
                _fields_ = [
                    ("wVk", wintypes.WORD),
                    ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
                ]

            class INPUT_UNION(ctypes.Union):
                _fields_ = [("ki", KEYBDINPUT)]

            class INPUT(ctypes.Structure):
                _fields_ = [("type", wintypes.DWORD), ("u", INPUT_UNION)]

            extra = ctypes.c_ulong(0)
            extra_ptr = ctypes.pointer(extra)
            send = ctypes.windll.user32.SendInput
            inputs = (INPUT * 2)()

            for ch in text:
                code = ord(ch)
                inputs[0] = INPUT(
                    type=INPUT_KEYBOARD,
                    u=INPUT_UNION(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE, 0, extra_ptr)),
                )
                inputs[1] = INPUT(
                    type=INPUT_KEYBOARD,
                    u=INPUT_UNION(
                        ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, extra_ptr)
                    ),
                )
                send(2, ctypes.byref(inputs), ctypes.sizeof(INPUT))
                time.sleep(interval)
            return True
        except Exception as e:
            print(f"[QianNiuAdapter] win32_type_unicode 失败: {e}")
            return False

    def _account_ctrl_logical_points(self, account_ctrl) -> tuple:
        """返回账号框文本区与下拉箭头的逻辑坐标。"""
        rect = account_ctrl.BoundingRectangle
        scale = self._get_dpi_scale()
        text_lx = int((rect.left + (rect.right - rect.left) * 0.32) / scale)
        text_ly = int((rect.top + rect.bottom) / 2 / scale)
        arrow_lx = int((rect.left + (rect.right - rect.left) * 0.88) / scale)
        arrow_ly = text_ly
        return text_lx, text_ly, arrow_lx, arrow_ly

    def _account_expand_and_pick(self, account_ctrl, account_name: str) -> bool:
        """展开账号下拉并点击与配置完全一致的主账号项。"""
        if not account_ctrl:
            return False
        text_lx, text_ly, arrow_lx, arrow_ly = self._account_ctrl_logical_points(account_ctrl)
        target_ctrl = self._resolve_active_edit_target(account_ctrl) or account_ctrl
        # #region debug-point C:expand-before-click
        self._debug_emit_account_probe("C", "account_expand_and_pick:before_arrow_click", account_ctrl)
        # #endregion
        self._human_click_logical(arrow_lx, arrow_ly, "点击账号下拉箭头")
        time.sleep(0.55)
        # #region debug-point C:expand-after-arrow
        self._debug_emit_account_probe("C", "account_expand_and_pick:after_arrow_click", account_ctrl)
        # #endregion
        if self._pick_login_dropdown_item(account_name):
            return True
        self._human_click_logical(text_lx, text_ly, "点击账号文本区展开下拉")
        time.sleep(0.45)
        # #region debug-point C:expand-after-text
        self._debug_emit_account_probe("C", "account_expand_and_pick:after_text_click", account_ctrl)
        # #endregion
        if self._pick_login_dropdown_item(account_name):
            return True
        for _ in range(4):
            current = self._read_account_display(target_ctrl, include_fresh_controls=False)
            if self._account_display_matches(current, account_name):
                self._login_log("human.account", "下拉方向键命中主账号", {"value": (current or "")[:50]})
                self._win32_send_hotkey("enter")
                time.sleep(0.3)
                return True
            self._win32_send_hotkey("down")
            time.sleep(0.12)
        return False

    def _click_blank_area(self) -> bool:
        if not self._window or not self._window.Exists():
            return False
        try:
            rect = self._window.BoundingRectangle
            if not rect:
                return False
            x = int(rect.left + (rect.right - rect.left) * 0.92)
            y = int(rect.top + (rect.bottom - rect.top) * 0.18)
            auto.Click(x, y, waitTime=0.1)
            time.sleep(0.2)
            return True
        except:
            return False

    def _type_like_human(self, text: str) -> bool:
        """模拟人工打字：逐字符发送，每字符间隔 80-200ms 随机"""
        if not text:
            return True
        print(f"[QianNiuAdapter] 模拟人工输入 {len(text)} 个字符...")
        for i, ch in enumerate(text):
            try:
                auto.SendKeys(ch, waitTime=0.02)
            except:
                # 特殊字符处理
                try:
                    auto.SendKeys(ch)
                except:
                    pass
            # 随机间隔：80-200ms（模拟不同打字速度）
            delay = random.uniform(0.08, 0.20)
            time.sleep(delay)
            # 偶尔有更长的停顿（模拟思考/看键盘）
            if random.random() < 0.08:
                time.sleep(random.uniform(0.2, 0.4))
            # 每 5 个字符打印进度（不刷屏）
            if (i + 1) % 5 == 0 or i == len(text) - 1:
                print(f"  输入进度: {i+1}/{len(text)}")
        return True

    def _find_login_button_by_vision(self, password_ctrl) -> tuple:
        """使用视觉识别（截屏+色彩检测）定位千牛登录按钮
        
        优先用密码框位置缩小搜索范围；若密码框不可用，则对整个千牛窗口扫描。
        Returns:
            (x, y) 登录按钮中心坐标（UIA物理像素），失败返回 (None, None)
        """
        if not _HAS_PYAUTOGUI or not _HAS_PIL:
            print("[QianNiuAdapter] 视觉识别不可用（缺少 pyautogui/Pillow）")
            return None, None

        if not self._window or not self._window.Exists():
            return None, None

        # 截图前先强制将千牛窗口置于最前，避免截到黑屏或遮挡
        try:
            import ctypes
            hwnd = self._window.NativeWindowHandle
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 9)   # SW_RESTORE
                ctypes.windll.user32.SetForegroundWindow(hwnd)
                time.sleep(0.35)
        except:
            pass

        # DPI缩放转换：UIA坐标是物理像素，pyautogui用逻辑像素
        scale = self._get_dpi_scale()

        # 确定截图区域
        # 优先：密码框下方 180px 精准区域
        # 兜底：整个千牛窗口下半部分（登录按钮肯定在中下区域）
        search_left_v = search_top_v = search_w = search_h = None
        try:
            if password_ctrl:
                pw_rect = password_ctrl.BoundingRectangle
                if pw_rect:
                    search_left_v = max(0, int(pw_rect.left / scale) - 20)
                    search_top_v  = int(pw_rect.bottom / scale)
                    search_w      = int((pw_rect.right - pw_rect.left) / scale) + 40
                    search_h      = 180
                    print(f"[QianNiuAdapter] 视觉搜索区域(密码框下方): ({search_left_v},{search_top_v}) {search_w}x{search_h}")
        except:
            pass

        if search_left_v is None:
            # 兜底：窗口右侧 55%（左侧是装饰图，右侧才是登录表单）的下半部分
            try:
                win_rect = self._window.BoundingRectangle
                if win_rect:
                    wl = int(win_rect.left / scale)
                    wt = int(win_rect.top / scale)
                    ww = int((win_rect.right - win_rect.left) / scale)
                    wh = int((win_rect.bottom - win_rect.top) / scale)
                    # 只取右侧 55%，避免扫到左侧装饰图的蓝色
                    search_left_v = wl + int(ww * 0.45)
                    search_top_v  = wt + int(wh * 0.50)   # 下半部分
                    search_w      = int(ww * 0.55)
                    search_h      = int(wh * 0.40)
                    print(f"[QianNiuAdapter] 视觉搜索区域(窗口右下): ({search_left_v},{search_top_v}) {search_w}x{search_h}")
            except:
                pass

        if search_left_v is None:
            print("[QianNiuAdapter] 无法确定截图区域")
            return None, None

        try:
            screenshot = pyautogui.screenshot(region=(search_left_v, search_top_v, search_w, search_h))
        except Exception as e:
            print(f"[QianNiuAdapter] 截屏失败: {e}")
            return None, None

        # 保存截图用于调试
        try:
            dump_dir = os.path.join(os.getcwd(), ".dbg")
            os.makedirs(dump_dir, exist_ok=True)
            screenshot.save(os.path.join(dump_dir, "qianniu_login_search_area.png"))
            print(f"[QianNiuAdapter] 搜索区域截图已保存: .dbg/qianniu_login_search_area.png")
        except:
            pass

        img = screenshot.convert("RGB")
        pixels = img.load()
        w, h = img.size

        # 千牛登录按钮主色调
        # 蓝色: #1677FF → (22, 119, 255)  深蓝
        # 蓝色: #4C9EFF → (76, 158, 255)   亮蓝（渐变高光）
        # 橙色: #FF6B00 → (255, 107, 0)
        # 放宽蓝色 R 通道上限至 130，覆盖渐变高光色
        button_pixels = set()

        for py in range(h):
            for px in range(w):
                r, g, b = pixels[px, py]
                # 蓝色系按钮（含深浅变化及渐变高光）
                if b >= 180 and b > r + 80 and b > g + 20 and r <= 130:
                    button_pixels.add((px, py))
                # 橙色系按钮（含深浅变化）
                elif 220 <= r <= 255 and 40 <= g <= 170 and b <= 50:
                    button_pixels.add((px, py))

        if not button_pixels:
            print(f"[QianNiuAdapter] 视觉搜索未找到登录按钮色彩（蓝色/橙色）")
            return None, None

        # 计算按钮边界
        min_x = min(p[0] for p in button_pixels)
        max_x = max(p[0] for p in button_pixels)
        min_y = min(p[1] for p in button_pixels)
        max_y = max(p[1] for p in button_pixels)

        btn_w = max_x - min_x
        btn_h = max_y - min_y
        print(f"[QianNiuAdapter] 视觉识别到按钮区域(逻辑): ({min_x},{min_y})-({max_x},{max_y}) 尺寸={btn_w}x{btn_h}")

        # 过滤太小的噪点
        if btn_w < 30 or btn_h < 10:
            print(f"[QianNiuAdapter] 检测区域太小({btn_w}x{btn_h})，忽略")
            return None, None

        # 过滤非宽扁形：登录按钮宽高比 >= 3（宽远大于高）
        # 左侧装饰图蓝色区域近似正方形，宽高比 < 2，可排除
        if btn_h > 0 and (btn_w / btn_h) < 2.5:
            print(f"[QianNiuAdapter] 宽高比={btn_w/btn_h:.1f} < 2.5，非宽扁按钮，忽略（可能是左侧装饰图）")
            return None, None

        # 逻辑像素 → 物理像素
        abs_x = int((search_left_v + min_x + btn_w // 2) * scale)
        abs_y = int((search_top_v  + min_y + btn_h // 2) * scale)
        print(f"[QianNiuAdapter] 登录按钮物理坐标: ({abs_x}, {abs_y})")

        return abs_x, abs_y

    def _click_control_center(self, ctrl) -> bool:
        if not ctrl:
            return False
        try:
            rect = ctrl.BoundingRectangle
            if not rect:
                return False
            x = int((rect.left + rect.right) / 2)
            y = int((rect.top + rect.bottom) / 2)
            auto.Click(x, y, waitTime=0.1)
            time.sleep(0.2)
            return True
        except:
            try:
                ctrl.Click()
                time.sleep(0.2)
                return True
            except:
                return False

    def _set_clipboard_text(self, text: str) -> bool:
        if _HAS_WIN32CLIPBOARD:
            try:
                win32clipboard.OpenClipboard()
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text or "")
                win32clipboard.CloseClipboard()
                return True
            except Exception as e:
                try:
                    win32clipboard.CloseClipboard()
                except Exception:
                    pass
                print(f"[QianNiuAdapter] win32 设置剪贴板失败: {e}")
        try:
            root = tk.Tk()
            root.withdraw()
            root.clipboard_clear()
            root.clipboard_append(text or "")
            root.update()
            root.destroy()
            return True
        except Exception as e:
            print(f"[QianNiuAdapter] 设置剪贴板失败: {e}")
            return False

    def _paste_edit_text(self, edit_ctrl, text: str) -> bool:
        if not edit_ctrl:
            return False
        try:
            if not self._click_control_center(edit_ctrl):
                return False
            try:
                edit_ctrl.SetFocus()
                time.sleep(0.1)
            except:
                pass
            # ① ValuePattern.SetValue（嵌入后首选，不走剪贴板）
            try:
                edit_ctrl.GetValuePattern().SetValue(text or "")
                time.sleep(0.15)
                return True
            except Exception:
                pass
            # ② ComboBox 类型的账号选择器
            if self._is_combo_or_account_selector(edit_ctrl):
                current_value = self._read_edit_text(edit_ctrl)
                if current_value:
                    print(f"[QianNiuAdapter] 账号选择器已有值 {current_value[:20]}，跳过粘贴，尝试直接输入")
                    return self._set_edit_text(edit_ctrl, text)
                auto.SendKeys(text or "", waitTime=0.12)
                time.sleep(0.25)
                return True
            # ③ 剪贴板粘贴（兜底）
            auto.SendKeys("{Ctrl}a", waitTime=0.05)
            auto.SendKeys("{Delete}", waitTime=0.05)
            if not self._set_clipboard_text(text):
                return False
            auto.SendKeys("{Ctrl}v", waitTime=0.15)
            time.sleep(0.25)
            return True
        except Exception as e:
            print(f"[QianNiuAdapter] 粘贴输入失败: {e}")
            return False

    def _read_edit_text(self, edit_ctrl) -> str:
        if not edit_ctrl:
            return ""
        getters = [
            lambda: getattr(edit_ctrl, "GetValuePattern")().Value,
            lambda: getattr(edit_ctrl, "GetLegacyIAccessiblePattern")().Value,
            lambda: self._safe_attr(edit_ctrl, "Value", ""),
            lambda: self._safe_attr(edit_ctrl, "Name", ""),
        ]
        for getter in getters:
            try:
                value = getter()
                if value is None:
                    continue
                value = str(value).strip()
                if value:
                    return value
            except:
                pass
        return ""

    def _read_edit_text_strict(self, edit_ctrl) -> str:
        if not edit_ctrl:
            return ""
        getters = [
            lambda: getattr(edit_ctrl, "GetValuePattern")().Value,
            lambda: getattr(edit_ctrl, "GetLegacyIAccessiblePattern")().Value,
            lambda: self._safe_attr(edit_ctrl, "Value", ""),
        ]
        for getter in getters:
            try:
                value = getter()
                if value is None:
                    continue
                value = str(value).strip()
                if value:
                    return value
            except:
                pass
        return ""

    def _set_edit_text(self, edit_ctrl, text: str) -> bool:
        if not edit_ctrl:
            return False
        try:
            edit_ctrl.Click()
            time.sleep(0.15)
            # ComboBox 不清空已有内容，直接追加输入
            if self._is_combo_or_account_selector(edit_ctrl):
                edit_ctrl.SendKeys(text or "", waitTime=0.25)
                return True
            edit_ctrl.SendKeys("{Ctrl}a", waitTime=0.05)
            edit_ctrl.SendKeys("{Delete}", waitTime=0.05)
            edit_ctrl.SendKeys(text or "", waitTime=0.25)
            return True
        except Exception as e:
            print(f"[QianNiuAdapter] 输入失败: {e}")
            return False

    def _type_edit_text(self, edit_ctrl, text: str) -> bool:
        if not edit_ctrl:
            return False
        try:
            if not self._click_control_center(edit_ctrl):
                return False
            try:
                edit_ctrl.SetFocus()
                time.sleep(0.1)
            except:
                pass
            # ComboBox 不清空已有内容，直接模拟键盘输入
            if self._is_combo_or_account_selector(edit_ctrl):
                auto.SendKeys(text or "", waitTime=0.12)
                time.sleep(0.25)
                return True
            auto.SendKeys("{Ctrl}a", waitTime=0.05)
            auto.SendKeys("{Delete}", waitTime=0.05)
            auto.SendKeys(text or "", waitTime=0.12)
            time.sleep(0.25)
            return True
        except Exception as e:
            print(f"[QianNiuAdapter] 模拟键盘输入失败: {e}")
            return False

    def _fill_password_pyautogui(self, edit_ctrl, text: str) -> bool:
        if not _HAS_PYAUTOGUI or not edit_ctrl:
            return False
        try:
            rect = edit_ctrl.BoundingRectangle
            if not rect:
                return False
            scale = self._get_dpi_scale()
            x = int((rect.left + rect.right) / 2 / scale)
            y = int((rect.top + rect.bottom) / 2 / scale)
            self.activate()
            time.sleep(0.15)
            pyautogui.click(x, y)
            time.sleep(0.2)
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.05)
            pyautogui.press("delete")
            time.sleep(0.05)
            pyautogui.write(text or "", interval=0.04)
            time.sleep(0.2)
            return True
        except Exception as e:
            print(f"[QianNiuAdapter] pyautogui 填密码失败: {e}")
            return False

    def _fill_password_via_tab(self, username_ctrl, password_ctrl, text: str) -> bool:
        try:
            probe = username_ctrl or password_ctrl
            if not probe:
                return False
            self.activate()
            self._click_control_center(probe)
            time.sleep(0.2)
            auto.SendKeys("{Tab}", waitTime=0.1)
            time.sleep(0.2)
            auto.SendKeys(text or "", waitTime=0.05)
            time.sleep(0.2)
            return True
        except Exception as e:
            print(f"[QianNiuAdapter] Tab 填密码失败: {e}")
            return False

    def _fill_login_edit(self, edit_ctrl, text: str, field_name: str, mask_value: bool = False) -> bool:
        if not edit_ctrl:
            print(f"[QianNiuAdapter] {field_name} 输入框不存在")
            # #region debug-point C:fill-login-edit-missing
            self._debug_emit(
                "C",
                "login edit missing",
                {"field_name": field_name},
                location="qianniu_adapter:_fill_login_edit:missing",
            )
            # #endregion
            return False
        display_text = "***" if mask_value else (text or "")
        target_ctrl = self._resolve_active_edit_target(edit_ctrl)
        self._login_log("fill.edit.start", f"开始填写{field_name}", {
            "field_name": field_name,
            "control": self._describe_control(target_ctrl or edit_ctrl),
            "text_length": len(text or ""),
            "mask_value": mask_value,
        })
        print(f"[QianNiuAdapter] 正在填写{field_name}: {display_text[:60]}")

        is_selector = self._is_combo_or_account_selector(edit_ctrl)

        # 账号选择器专用：展开下拉 + 搜索 + Enter 选择
        if is_selector and not mask_value:
            # #region debug-point C:fill-login-edit-attempt
            self._debug_emit(
                "C",
                "fill login edit attempt",
                {
                    "field_name": field_name,
                    "method": "combo_search",
                    "control": self._describe_control(target_ctrl or edit_ctrl),
                    "text_length": len(text or ""),
                    "mask_value": mask_value,
                },
                location="qianniu_adapter:_fill_login_edit:attempt",
            )
            # #endregion
            if self._fill_combo_account(target_ctrl or edit_ctrl, text):
                # #region debug-point C:fill-login-edit-result
                self._debug_emit(
                    "C",
                    "fill login edit result (combo_search)",
                    {"field_name": field_name, "method": "combo_search", "success": True},
                    location="qianniu_adapter:_fill_login_edit:result",
                )
                # #endregion
                print(f"[QianNiuAdapter] {field_name} 已通过 combo_search 填入")
                return True
            print(f"[QianNiuAdapter] {field_name} combo_search 失败，尝试标准方式")

        attempts = [
            ("paste", self._paste_edit_text),
            ("set_text", self._set_edit_text),
            ("type_keys", self._type_edit_text),
        ]
        if mask_value:
            attempts = [
                ("type_keys", self._type_edit_text),
                ("pyautogui", lambda ctrl, value: self._fill_password_pyautogui(ctrl, value)),
            ]
        for method_name, method in attempts:
            # #region debug-point C:fill-login-edit-attempt
            self._debug_emit(
                "C",
                "fill login edit attempt",
                {
                    "field_name": field_name,
                    "method": method_name,
                        "control": self._describe_control(target_ctrl or edit_ctrl),
                    "text_length": len(text or ""),
                    "mask_value": mask_value,
                },
                location="qianniu_adapter:_fill_login_edit:attempt",
            )
            # #endregion
            if not method(target_ctrl or edit_ctrl, text):
                continue
            current_value = self._read_edit_text(target_ctrl or edit_ctrl)
            # #region debug-point C:fill-login-edit-result
            self._debug_emit(
                "C",
                "fill login edit result",
                {
                    "field_name": field_name,
                    "method": method_name,
                    "current_value_length": len(current_value or ""),
                    "matches_expected": False if mask_value else (current_value == text),
                    "mask_value": mask_value,
                },
                location="qianniu_adapter:_fill_login_edit:result",
            )
            # #endregion
            if mask_value:
                if current_value:
                    print(f"[QianNiuAdapter] {field_name} 已通过 {method_name} 填入")
                    return True
                # PasswordControl value is unreadable via accessibility API - that's expected.
                # But if paste was used, it may be blocked by the password field.
                # Only accept as success on the last attempt (type_keys), otherwise try next method.
                if method_name in ("type_keys", "pyautogui"):
                    print(f"[QianNiuAdapter] {field_name} 通过 {method_name} 填入后无法读取值（密码框安全限制），按成功继续")
                    return True
                print(f"[QianNiuAdapter] {field_name} 通过 {method_name} 无法验证，尝试下一种方式")
            if current_value == text:
                print(f"[QianNiuAdapter] {field_name} 已通过 {method_name} 填入")
                return True
            if current_value:
                print(f"[QianNiuAdapter] {field_name} 当前值与预期不一致: {current_value[:60]}")
            else:
                print(f"[QianNiuAdapter] {field_name} 通过 {method_name} 填入后仍为空")
        self._login_log("fill.edit.fail", f"{field_name} 所有填写方式均失败", {
            "field_name": field_name,
            "mask_value": mask_value,
        }, level="error")
        return False

    def _fill_combo_account(self, edit_ctrl, text: str) -> bool:
        """专门处理 ComboBox/账号选择器的填写：点击展开下拉 → 输入搜索 → Enter 确认"""
        if not edit_ctrl:
            return False
        try:
            # 1. 点击控件展开下拉列表
            self._click_control_center(edit_ctrl)
            time.sleep(0.35)
            # 2. SetFocus
            try:
                edit_ctrl.SetFocus()
                time.sleep(0.15)
            except:
                pass
            # 3. 发送账号文本（让下拉列表自动筛选匹配项）
            auto.SendKeys(text or "", waitTime=0.15)
            time.sleep(0.35)
            # 4. 按 Enter 确认选择第一个匹配项
            auto.SendKeys("{Enter}", waitTime=0.1)
            time.sleep(0.3)
            return True
        except Exception as e:
            print(f"[QianNiuAdapter] 账号选择器填写失败: {e}")
            return False

    def _find_login_controls(self):
        if not self._window or not self._window.Exists():
            return None, None, None, None

        edits = []
        password_ctrls_direct = []  # PasswordControl type controls
        account_displays = []
        combo_boxes = []  # 账号选择器（ComboBox类型）
        for ctrl in self._walk_controls(self._window, max_depth=8):
            ctrl_type = self._safe_attr(ctrl, "ControlTypeName", "")
            name = str(self._safe_attr(ctrl, "Name", "") or "")
            class_name = str(self._safe_attr(ctrl, "ClassName", "") or "")
            automation_id = str(self._safe_attr(ctrl, "AutomationId", "") or "")
            haystack = f"{name} {class_name} {automation_id}".lower()
            if ctrl_type == "PasswordControl":
                # Dedicated password control type - highest priority for password field
                password_ctrls_direct.append((ctrl, haystack))
            if ctrl_type in ("EditControl", "DocumentControl"):
                edits.append((ctrl, haystack))
            if ctrl_type == "ComboBoxControl":
                combo_boxes.append((ctrl, haystack))
            if ctrl_type in ("ComboBoxControl", "TextControl", "CustomControl", "PaneControl", "EditControl", "DocumentControl"):
                if any(k in haystack for k in ["账号", "账户", "用户名", "account", "user", "手机", "手机号", "email"]):
                    account_displays.append((ctrl, haystack))

        # #region debug-point B:login-control-candidates
        self._debug_emit(
            "B",
            "login control candidates scanned",
            {
                "candidate_count": len(edits),
                "password_ctrl_direct_count": len(password_ctrls_direct),
                "account_display_count": len(account_displays),
                "candidates": [
                    {
                        "type": str(self._safe_attr(ctrl, "ControlTypeName", "") or ""),
                        "name": str(self._safe_attr(ctrl, "Name", "") or "")[:80],
                        "class_name": str(self._safe_attr(ctrl, "ClassName", "") or "")[:80],
                        "automation_id": str(self._safe_attr(ctrl, "AutomationId", "") or "")[:80],
                    }
                    for ctrl, _ in (edits + password_ctrls_direct)[:8]
                ],
            },
            location="qianniu_adapter:_find_login_controls:candidates",
        )
        # #endregion

        username_ctrl = None
        password_ctrl = None
        combo_box_account = None  # ComboBox类型的账号选择器
        
        # PasswordControl type takes highest priority for password field
        if password_ctrls_direct:
            password_ctrl = password_ctrls_direct[0][0]
        
        # 优先查找ComboBox类型的账号选择器
        for ctrl, haystack in combo_boxes:
            if any(k in haystack for k in ["账号", "账户", "用户名", "account", "user", "手机", "手机号", "email"]):
                combo_box_account = ctrl
                break
        # 如果没找到带关键词的ComboBox，取第一个ComboBox作为账号选择器候选
        if not combo_box_account and combo_boxes:
            combo_box_account = combo_boxes[0][0]
        
        # 在所有EditControl中匹配
        for ctrl, haystack in edits:
            if not username_ctrl and any(k in haystack for k in ["账号", "用户名", "account", "user", "手机", "手机号", "email"]):
                username_ctrl = ctrl
            if not password_ctrl and any(k in haystack for k in ["密码", "password", "pwd"]):
                password_ctrl = ctrl

        edits.sort(key=lambda item: self._get_control_top(item[0]))
        account_displays.sort(key=lambda item: self._get_control_top(item[0]))
        
        # 如果没有找到明确的账号输入框，使用ComboBox作为账号选择器
        if not username_ctrl and combo_box_account:
            username_ctrl = combo_box_account
        
        # 回退：按位置推断
        if not username_ctrl and len(edits) >= 2:
            username_ctrl = edits[0][0]
        if not password_ctrl:
            if len(edits) >= 2:
                password_ctrl = edits[-1][0]
            elif len(edits) == 1:
                password_ctrl = edits[0][0]
        
        # 账号显示控件优先级：ComboBox > account_displays
        account_display_ctrl = combo_box_account
        if not account_display_ctrl:
            for ctrl, _ in account_displays:
                if self._read_edit_text(ctrl):
                    account_display_ctrl = ctrl
                    break
        if not account_display_ctrl and account_displays:
            account_display_ctrl = account_displays[0][0]

        login_btn = self._find_login_button_control(password_ctrl)
        # #region debug-point B:login-control-match
        self._debug_emit(
            "B",
            "login controls matched",
            {
                "username_ctrl": self._describe_control(username_ctrl),
                "password_ctrl": self._describe_control(password_ctrl),
                "account_display_ctrl": self._describe_control(account_display_ctrl),
                "login_btn": self._describe_control(login_btn),
            },
            location="qianniu_adapter:_find_login_controls:matched",
        )
        # #endregion
        return username_ctrl, password_ctrl, login_btn, account_display_ctrl

    def _should_fill_username(self, username_ctrl, password_ctrl, account_display_ctrl, expected_username: str) -> bool:
        username_ctrl_type = str(self._safe_attr(username_ctrl, "ControlTypeName", "") or "")
        display_value = self._read_edit_text(account_display_ctrl or username_ctrl)
        normalized_display = (display_value or "").strip()
        normalized_expected = (expected_username or "").strip()
        reason = ""

        if self._is_combo_or_account_selector(username_ctrl):
            if password_ctrl and self._get_control_top(username_ctrl) < self._get_control_top(password_ctrl):
                if normalized_display and normalized_expected:
                    if normalized_display == normalized_expected:
                        reason = "combo_selector:已有正确账号"
                        self._login_log("fill.username.reason", reason, {
                            "display": normalized_display[:40],
                        })
                        return False
                    if ":" in normalized_display and ":" not in normalized_expected:
                        company_part = normalized_display.split(":", 1)[0].strip()
                        if company_part == normalized_expected:
                            reason = "combo_selector:历史子账号需重选主账号"
                            self._login_log("fill.username.reason", reason, {
                                "display": normalized_display[:40],
                                "expected": normalized_expected[:40],
                            })
                            return True
                    if normalized_expected in normalized_display or normalized_display in normalized_expected:
                        reason = "combo_selector:账号部分匹配"
                        self._login_log("fill.username.reason", reason)
                        return False
                reason = "combo_selector:需要填入账号"
                self._login_log("fill.username.reason", reason, {
                    "display": (normalized_display or "(无法读取)")[:40],
                })
                return True
            if normalized_display:
                reason = "combo_selector:边缘情况已有值"
                self._login_log("fill.username.reason", reason)
                return False
            reason = "combo_selector:空值需填入"
            self._login_log("fill.username.reason", reason)
            return True

        if username_ctrl_type in ("EditControl", "DocumentControl"):
            if account_display_ctrl and display_value:
                if self._get_control_top(account_display_ctrl) < self._get_control_top(password_ctrl):
                    reason = "edit:账号选择器已有值"
                    self._login_log("fill.username.reason", reason, {"display": display_value[:40]})
                    return False
            if self._is_readonly_control(username_ctrl):
                if password_ctrl and self._get_control_top(username_ctrl) < self._get_control_top(password_ctrl):
                    if normalized_display and normalized_expected:
                        if normalized_display == normalized_expected:
                            reason = "readonly:已有正确账号"
                            self._login_log("fill.username.reason", reason)
                            return False
                    reason = "readonly:需要 combo 填入"
                    self._login_log("fill.username.reason", reason)
                    return True
                if display_value:
                    reason = "readonly:已有值"
                    self._login_log("fill.username.reason", reason)
                    return False
            if normalized_display and normalized_expected:
                if normalized_display == normalized_expected:
                    reason = "edit:账号已匹配"
                    self._login_log("fill.username.reason", reason)
                    return False
                if normalized_expected in normalized_display or normalized_display in normalized_expected:
                    reason = "edit:账号部分匹配"
                    self._login_log("fill.username.reason", reason)
                    return False
            reason = "edit:需要填入账号"
            self._login_log("fill.username.reason", reason)
            return True

        if normalized_display:
            if not normalized_expected:
                reason = "other:已有显示值无期望账号"
                self._login_log("fill.username.reason", reason)
                return False
            if normalized_display == normalized_expected:
                reason = "other:账号已匹配"
                self._login_log("fill.username.reason", reason)
                return False
            if normalized_expected in normalized_display or normalized_display in normalized_expected:
                reason = "other:账号部分匹配"
                self._login_log("fill.username.reason", reason)
                return False
        reason = "other:默认需要填入"
        self._login_log("fill.username.reason", reason)
        return True

    def _chat_candidates_snapshot(self, limit: int = 8) -> Dict:
        snapshot = {
            "window": self._describe_control(self._window),
            "edit_candidates": [],
            "button_candidates": [],
        }
        if not self._window or not self._safe_exists(self._window):
            return snapshot
        edit_candidates = []
        button_candidates = []
        for ctrl in self._walk_controls(self._window, max_depth=12):
            try:
                ctrl_type = str(self._safe_attr(ctrl, "ControlTypeName", "") or "")
                if ctrl_type not in ("EditControl", "DocumentControl", "ButtonControl"):
                    continue
                item = {
                    "type": ctrl_type,
                    "name": str(self._safe_attr(ctrl, "Name", "") or "")[:80],
                    "class_name": str(self._safe_attr(ctrl, "ClassName", "") or "")[:80],
                    "automation_id": str(self._safe_attr(ctrl, "AutomationId", "") or "")[:120],
                    "rect": self._get_control_rect(ctrl),
                }
                if ctrl_type in ("EditControl", "DocumentControl"):
                    edit_candidates.append(item)
                else:
                    button_candidates.append(item)
            except Exception:
                continue
        snapshot["edit_candidates"] = edit_candidates[:limit]
        snapshot["button_candidates"] = button_candidates[:limit]
        return snapshot

    def is_chat_ready(self) -> bool:
        if not self.find_window():
            return False
        try:
            self._cache.pop("chat_panel", None)
            self._cache.pop("session_panel", None)
            self._cache.pop("input_box", None)
            self._cache.pop("chat_items", None)
            session_panel = self._get_session_panel()
            chat_panel = self._get_chat_panel()
            input_box = self._get_input_control()
            if session_panel and chat_panel and input_box:
                return True
            title = str(self._safe_attr(self._window, "Name", "") or "")
            if "接待中心" in title or "ChatView" in str(self._safe_attr(self._window, "ClassName", "") or ""):
                self._login_log("chat.ready.candidates", "聊天窗口候选控件快照", {
                    "title": title[:80],
                    "session_panel": self._describe_control(session_panel),
                    "chat_panel": self._describe_control(chat_panel),
                    "input_box": self._describe_control(input_box),
                    **self._chat_candidates_snapshot(),
                }, level="info")
        except:
            pass
        return False

    def ensure_chat_ready(self, timeout: float = 20.0) -> bool:
        if self.is_chat_ready():
            return True
        candidates = [
            ["聊天"],
            ["消息"],
            ["接待中心"],
            ["客服"],
            ["工作台"],
        ]
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_chat_ready():
                return True
            title = str(self._safe_attr(self._window, "Name", "") or "") if self._window else ""
            if "工作台" in title or "千牛" in title:
                popup_closed = self._dismiss_workbench_popup()
                if popup_closed:
                    self._login_log("chat.prepare", "工作台弹层关闭后重新检查聊天窗口")
                    if self.is_chat_ready():
                        return True
                entry_clicked = self._click_workbench_wangwang_entry()
                if entry_clicked:
                    self._reset_window_ref()
                    self.find_window()
                    self._cache_clear()
                    if self.is_chat_ready():
                        return True
            for keywords in candidates:
                ctrl = self._find_named_control(
                    ["ButtonControl", "TabItemControl", "TextControl", "MenuItemControl", "CustomControl"],
                    keywords,
                    max_depth=8
                )
                if ctrl:
                    try:
                        ctrl.Click()
                        time.sleep(1.2)
                        self._cache_clear()
                        if self.is_chat_ready():
                            print(f"[QianNiuAdapter] 已打开聊天界面: {'/'.join(keywords)}")
                            return True
                    except:
                        pass
            time.sleep(0.8)
        return self.is_chat_ready()

    def login(self, username: str, password: str, timeout: float = 45.0) -> bool:
        if not self._login_lock.acquire(blocking=False):
            self._last_login_fail_reason = "登录流程正在进行中，请稍候再试"
            self._login_log("login.fail", self._last_login_fail_reason, level="warn")
            return False
        try:
            return self._login_impl(username, password, timeout)
        finally:
            self._login_lock.release()

    def _login_impl(self, username: str, password: str, timeout: float = 90.0) -> bool:
        self._debug_trace_id = f"qn-login-{uuid.uuid4().hex[:8]}"
        log_path = self._get_login_log_path()
        self._login_log("login.start", "开始千牛自动登录流程", {
            "log_path": log_path,
            "username": (username or "")[:50],
            "username_length": len(username or ""),
            "password_length": len(password or ""),
            "timeout": timeout,
            "chat_ready_before": self.is_chat_ready(),
            "has_window_before": bool(self._window),
        })
        if self.is_chat_ready():
            self._login_log("login.skip", "聊天界面已就绪，跳过登录", level="info")
            return True
        if not username or not password:
            self._last_login_fail_reason = f"缺少登录凭据：账号长度={len(username or '')}，密码长度={len(password or '')}"
            self._login_log("login.fail", self._last_login_fail_reason, level="error")
            return False

        found_window = self.find_window()
        activated = found_window and self.activate()
        self._login_log("login.window", "查找并激活千牛窗口", {
            "found_window": found_window,
            "activated": activated,
            "window": self._describe_control(self._window),
        })
        if not found_window or not activated:
            self._last_login_fail_reason = "未找到千牛窗口，请确认千牛已启动"
            self._login_log("login.fail", self._last_login_fail_reason, level="error")
            return False

        username_ctrl, password_ctrl, login_btn, account_display_ctrl = self._find_login_controls()
        self._login_log("login.controls", "识别登录表单控件", {
            "username_ctrl": self._describe_control(username_ctrl),
            "password_ctrl": self._describe_control(password_ctrl),
            "login_btn": self._describe_control(login_btn),
            "account_display_ctrl": self._describe_control(account_display_ctrl),
        })
        if (not username_ctrl and not account_display_ctrl) or not password_ctrl:
            missing = []
            if not username_ctrl and not account_display_ctrl:
                missing.append("账号框")
            if not password_ctrl:
                missing.append("密码框")
            self._last_login_fail_reason = f"未识别到千牛登录表单，缺少: {', '.join(missing)}"
            self._login_log("login.fail", self._last_login_fail_reason, level="error")
            return False

        if not login_btn:
            self._login_log("login.controls", "UIA 未识别到「登录」按钮，将尝试视觉/坐标方案", level="warn")

        if not self._simulate_human_login_sequence(
            username_ctrl or account_display_ctrl, password_ctrl, username, password
        ):
            self._last_login_fail_reason = "模拟人工填写账号密码失败（账号未能选中或密码未填入）"
            self._login_log("login.fail", self._last_login_fail_reason, level="error")
            return False

        login_clicked = False
        login_method = ""

        self._login_log("login.submit", "开始点击登录按钮")
        try:
            import ctypes
            hwnd = self._window.NativeWindowHandle
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 9)
                ctypes.windll.user32.SetForegroundWindow(hwnd)
                time.sleep(0.3)
            self._window.SetActive()
            time.sleep(0.2)
        except Exception:
            pass

        vision_x, vision_y = self._find_login_button_by_vision(password_ctrl)
        self._login_log("login.submit.vision", "视觉识别蓝色登录按钮", {
            "found": vision_x is not None and vision_y is not None,
            "x": vision_x,
            "y": vision_y,
        })
        if vision_x is not None and vision_y is not None:
            self._win32_click(vision_x, vision_y)
            time.sleep(0.1)
            auto.Click(vision_x, vision_y, waitTime=0.1)
            if _HAS_PYAUTOGUI:
                scale = self._get_dpi_scale()
                pyautogui.click(int(vision_x / scale), int(vision_y / scale))
            time.sleep(0.4)
            login_clicked = True
            login_method = "vision_click"

        submit_btn = self._find_login_button_control(password_ctrl) or login_btn
        if not login_clicked and submit_btn:
            try:
                rect = submit_btn.BoundingRectangle
                if rect:
                    x = int((rect.left + rect.right) / 2)
                    y = int((rect.top + rect.bottom) / 2)
                    self._login_log("login.submit.uia", "点击「登录」按钮", {
                        "btn": self._describe_control(submit_btn),
                        "x": x,
                        "y": y,
                    })
                    self._win32_click(x, y)
                    time.sleep(0.1)
                    auto.Click(x, y, waitTime=0.1)
                    time.sleep(0.3)
                    login_clicked = True
                    login_method = "login_button_click"
            except Exception as e:
                self._login_log("login.submit.uia", f"登录按钮点击失败: {e}", level="warn")

        vision_x, vision_y = None, None
        if not login_clicked:
            fresh_btn = self._find_login_button_control(password_ctrl)
            btn_to_click = fresh_btn or submit_btn or login_btn
            self._login_log("login.submit.uia", "尝试 UIA 点击登录按钮", {
                "btn": self._describe_control(btn_to_click),
            })

            if btn_to_click:
                try:
                    rect = btn_to_click.BoundingRectangle
                    if rect:
                        x = int((rect.left + rect.right) / 2)
                        y = int((rect.top + rect.bottom) / 2)
                        self._login_log("login.submit.uia", "UIA 坐标点击", {"x": x, "y": y})
                        self._win32_click(x, y)
                        time.sleep(0.05)
                        auto.Click(x, y, waitTime=0.1)
                        time.sleep(0.2)
                        login_clicked = True
                        login_method = "uia_coord_click"
                except Exception as e:
                    self._login_log("login.submit.uia", f"UIA 坐标点击失败: {e}", level="warn")

                if not login_clicked:
                    try:
                        btn_to_click.Click()
                        time.sleep(0.25)
                        login_clicked = True
                        login_method = "uia_click"
                        self._login_log("login.submit.uia", "已通过 Click() 点击登录")
                    except Exception as e:
                        self._login_log("login.submit.uia", f"Click() 失败: {e}", level="warn")

                if not login_clicked:
                    try:
                        invoke = btn_to_click.GetInvokePattern()
                        if invoke:
                            invoke.Invoke()
                            time.sleep(0.25)
                            login_clicked = True
                            login_method = "uia_invoke"
                            self._login_log("login.submit.uia", "已通过 InvokePattern 点击登录")
                    except Exception as e:
                        self._login_log("login.submit.uia", f"InvokePattern 失败: {e}", level="warn")

        if not login_clicked:
            self._login_log("login.submit.fallback", "视觉和 UIA 均失败，使用坐标推算兜底", level="warn")
            try:
                pw_rect = password_ctrl.BoundingRectangle
                if pw_rect:
                    base_x = int((pw_rect.left + pw_rect.right) / 2)
                    pw_width = int(pw_rect.right - pw_rect.left)
                    tried = []
                    for offset_y in [50, 65, 80, 95, 35]:
                        for offset_x in [0, int(pw_width * 0.3), int(-pw_width * 0.3)]:
                            btn_x = base_x + offset_x
                            btn_y = int(pw_rect.bottom + offset_y)
                            tried.append({"x": btn_x, "y": btn_y, "offset_x": offset_x, "offset_y": offset_y})
                            self._win32_click(btn_x, btn_y)
                            time.sleep(0.05)
                            auto.Click(btn_x, btn_y, waitTime=0.05)
                            time.sleep(0.05)
                    login_clicked = True
                    login_method = "coord_fallback"
                    self._login_log("login.submit.fallback", "已通过多位置坐标推算点击", {"tried": tried[:12]})
            except Exception as e:
                self._login_log("login.submit.fallback", f"坐标推算失败: {e}", level="warn")

            if not login_clicked:
                try:
                    win_rect = self._window.BoundingRectangle
                    if win_rect:
                        wx = int(win_rect.left + (win_rect.right - win_rect.left) * 0.5)
                        wy = int(win_rect.top + (win_rect.bottom - win_rect.top) * 0.72)
                        self._login_log("login.submit.fallback", "窗口相对位置推算点击", {"x": wx, "y": wy})
                        self._win32_click(wx, wy)
                        time.sleep(0.05)
                        auto.Click(wx, wy, waitTime=0.1)
                        time.sleep(0.05)
                        if _HAS_PYAUTOGUI:
                            scale = self._get_dpi_scale()
                            pyautogui.click(int(wx / scale), int(wy / scale))
                        login_clicked = True
                        login_method = "window_coord_fallback"
                except Exception as e:
                    self._login_log("login.submit.fallback", f"窗口推算失败: {e}", level="warn")

        if not login_clicked:
            try:
                import ctypes
                hwnd = self._window.NativeWindowHandle
                if hwnd:
                    ctypes.windll.user32.SetForegroundWindow(hwnd)
                    time.sleep(0.2)
                auto.SendKeys("{Enter}", waitTime=0.1)
                login_clicked = True
                login_method = "enter_fallback"
                self._login_log("login.submit", "兜底使用 Enter 触发登录")
            except Exception as e:
                self._login_log("login.submit", f"Enter 兜底失败: {e}", level="warn")

        if not login_clicked:
            self._last_login_fail_reason = "所有方式(视觉+UIA+坐标推算)均无法点击登录按钮"
            self._login_log("login.fail", self._last_login_fail_reason, level="error")
            return False

        self._login_log("login.wait", "已提交登录，等待进入聊天界面", {
            "login_method": login_method,
            "timeout": timeout,
        })
        deadline = time.time() + timeout
        poll_count = 0
        while time.time() < deadline:
            poll_count += 1
            self._cache_clear()
            if self.is_chat_ready():
                self._login_log("login.success", "千牛登录成功，聊天界面已就绪", {
                    "login_method": login_method,
                    "poll_count": poll_count,
                    "remaining_seconds": round(deadline - time.time(), 2),
                })
                return True
            self._reset_window_ref()
            if self.find_window():
                title = str(self._safe_attr(self._window, "Name", "") or "")
                if title and "登录" not in title and ("千牛" in title or "工作台" in title or "接待" in title):
                    self._login_log("login.wait", "登录窗口已切换，尝试打开聊天界面", {"title": title[:60]})
                    time.sleep(2)
                    if self.ensure_chat_ready(timeout=20.0):
                        self._login_log("login.success", "千牛登录成功，已进入工作台", {
                            "login_method": login_method,
                            "title": title[:60],
                        })
                        return True
                    self._login_log("login.wait.probe", "已进入工作台，但聊天界面仍未就绪", self._chat_ready_snapshot(), level="warn")
            if self.ensure_chat_ready(timeout=2.0):
                self._login_log("login.success", "千牛登录成功，已打开聊天界面", {
                    "login_method": login_method,
                    "poll_count": poll_count,
                    "via": "ensure_chat_ready",
                })
                return True
            if poll_count % 5 == 0:
                self._login_log("login.wait", "仍在等待聊天界面", {
                    "poll_count": poll_count,
                    "remaining_seconds": round(deadline - time.time(), 2),
                    "chat_ready": False,
                })
                self._login_log("login.wait.probe", "等待聊天界面时的控件快照", self._chat_ready_snapshot(), level="info")
            time.sleep(1)
        self._last_login_fail_reason = f"已填写账号密码并点击登录，但等待 {timeout}s 后未进入聊天界面（可能密码错误或触发了验证码）"
        self._login_log("login.fail.probe", "登录失败前的聊天界面快照", self._chat_ready_snapshot(), level="error")
        self._login_log("login.fail", self._last_login_fail_reason, {
            "login_method": login_method,
            "poll_count": poll_count,
            "timeout": timeout,
        }, level="error")
        return False

    def pop_pending_messages(self) -> List[Dict]:
        items = list(self._pending_messages)
        self._pending_messages.clear()
        return items
    
    # --------------------------------------------------
    # 缓存管理
    # --------------------------------------------------
    def _cache_get(self, key: str):
        """获取缓存"""
        entry = self._cache.get(key)
        if entry and (time.time() - entry[1]) < self.CACHE_TTL:
            return entry[0]
        return None
    
    def _cache_set(self, key: str, value):
        """设置缓存"""
        self._cache[key] = (value, time.time())
    
    def _cache_clear(self):
        """清除缓存"""
        self._cache.clear()
    
    # --------------------------------------------------
    # 元素定位 (分层搜索)
    # --------------------------------------------------
    def _get_session_panel(self) -> Optional:
        """
        获取千牛左侧"会话列表"面板
        
        千牛布局:
          ┌──────────────┬──────────────────┐
          │ 会话列表区域  │  聊天区域         │
          │ (左侧面板)    │  消息列表         │
          │              │  输入框           │
          │              │  发送按钮         │
          └──────────────┴──────────────────┘
        """
        if not self._window or not self._window.Exists():
            return None
        
        cached = self._cache_get("session_panel")
        if cached:
            return cached
        
        # 方式1: 查找左侧第一个Custom/Pane面板
        children = self._window.GetChildren()
        for child in children:
            if child.ControlTypeName in ("CustomControl", "PaneControl"):
                sub = child.GetChildren()
                if len(sub) >= 3:  # 有多个子元素, 可能是会话列表
                    self._cache_set("session_panel", child)
                    return child
        
        # 方式2: 直接取第一个子控件(千牛通常左面板是第一个)
        if children:
            first = children[0]
            self._cache_set("session_panel", first)
            return first
        
        return None

    def _get_order_panel(self) -> Optional:
        """获取千牛右侧订单/买家信息面板（通常为第3个主面板）"""
        if not self._window or not self._window.Exists():
            return None

        cached = self._cache_get("order_panel")
        if cached:
            return cached

        panels = []
        for child in self._window.GetChildren():
            if child.ControlTypeName in ("CustomControl", "PaneControl"):
                panels.append(child)

        if len(panels) >= 3:
            panel = panels[2]
            self._cache_set("order_panel", panel)
            return panel
        if panels:
            panel = panels[-1]
            self._cache_set("order_panel", panel)
            return panel
        return None

    def _ensure_order_panel_visible(self) -> bool:
        """尝试点击订单/物流相关标签，确保右侧订单信息可见"""
        keywords = ["订单", "买家订单", "商品订单", "物流", "交易"]
        for kw in keywords:
            btn = self._find_named_control(
                ["TabItemControl", "ButtonControl", "TextControl", "HyperlinkControl"],
                [kw],
                max_depth=10
            )
            if not btn:
                continue
            try:
                btn.Click()
                time.sleep(0.6)
                self._cache_clear()
                return True
            except:
                pass
        return False

    def _snapshot_shipping_status(self, snapshot: Dict) -> str:
        if not isinstance(snapshot, dict):
            return ""
        return str(snapshot.get("shippingStatus") or snapshot.get("shipping_status") or "")
    
    def _get_chat_panel(self) -> Optional:
        """
        获取千牛右侧"聊天区"面板
        """
        if not self._window or not self._window.Exists():
            return None
        
        cached = self._cache_get("chat_panel")
        if cached:
            return cached

        title = str(self._safe_attr(self._window, "Name", "") or "")
        class_name = str(self._safe_attr(self._window, "ClassName", "") or "")
        if "接待中心" in title or "ChatView" in class_name:
            self._cache_set("chat_panel", self._window)
            return self._window
        
        children = self._window.GetChildren()
        # 聊天区通常是右侧第二个主要面板
        panel_count = 0
        for child in children:
            if child.ControlTypeName in ("CustomControl", "PaneControl"):
                panel_count += 1
                if panel_count == 2:
                    self._cache_set("chat_panel", child)
                    return child
        
        return None
    
    def _get_chat_list_items(self) -> List:
        """
        获取会话列表中的所有会话项
        """
        panel = self._get_session_panel()
        if not panel:
            return []
        
        cached = self._cache_get("chat_items")
        if cached:
            return cached
        
        items = []
        # 千牛会话列表通常由 ListItemControl 组成
        children = panel.GetChildren()
        
        for child in children:
            # 查找包含 ListItemControl 的子控件
            if child.ControlTypeName == "ListControl":
                items = child.GetChildren()
                break
            # 部分版本直接是 ListItemControl 的容器
            elif child.ControlTypeName == "ListItemControl":
                items.append(child)
            # 也有可能是 CustomControl 嵌套
            elif child.ControlTypeName == "CustomControl":
                sub_items = child.GetChildren()
                if sub_items:
                    items.extend(sub_items)
        
        if items:
            self._cache_set("chat_items", items)
        return items
    
    def _get_message_controls(self) -> List:
        """
        获取当前会话的消息控件
        """
        panel = self._get_chat_panel()
        if not panel:
            return []
        
        cached = self._cache_get("msg_controls")
        if cached:
            return cached
        
        # 在聊天面板中查找消息列表
        # 千牛消息在 ListControl 或 CustomControl 中
        msgs = []
        children = panel.GetChildren()
        
        for child in children:
            ctype = child.ControlTypeName
            # 新版千牛(ListControl 或 PaneControl)
            if ctype in ("ListControl", "CustomControl", "PaneControl"):
                sub = child.GetChildren()
                if sub and len(sub) >= 2:  # 有多个子项 -> 消息列表
                    msgs = sub
                    break
        
        if msgs:
            self._cache_set("msg_controls", msgs)
        return msgs
    
    def _get_input_control(self) -> Optional:
        """
        获取输入框
        """
        if not self._window or not self._window.Exists():
            return None
        
        cached = self._cache_get("input_box")
        if cached:
            return cached
        
        # 方式1: 按 Name 查找
        try:
            edit = self._window.EditControl(searchDepth=15, Name="输入")
            if edit.Exists(maxSearchSeconds=0.5):
                self._cache_set("input_box", edit)
                return edit
        except:
            pass
        
        # 方式2: 搜索任意可编辑控件
        try:
            edit = self._window.EditControl(searchDepth=15)
            if edit.Exists(maxSearchSeconds=0.5):
                title = str(self._safe_attr(self._window, "Name", "") or "")
                class_name = str(self._safe_attr(self._window, "ClassName", "") or "")
                if "接待中心" in title or "ChatView" in class_name:
                    candidates = []
                    for ctrl in self._walk_controls(self._window, max_depth=12):
                        try:
                            ctrl_type = str(self._safe_attr(ctrl, "ControlTypeName", "") or "")
                            if ctrl_type not in ("EditControl", "DocumentControl"):
                                continue
                            name = str(self._safe_attr(ctrl, "Name", "") or "").strip()
                            ctrl_class = str(self._safe_attr(ctrl, "ClassName", "") or "").strip()
                            automation_id = str(self._safe_attr(ctrl, "AutomationId", "") or "").strip()
                            haystack = f"{name} {ctrl_class} {automation_id}".lower()
                            if any(k in haystack for k in ["搜索", "search", "chatsearchview"]):
                                continue
                            rect = self._get_control_rect(ctrl) or {}
                            top = int(rect.get("top", 0) or 0)
                            width = int((rect.get("right", 0) or 0) - (rect.get("left", 0) or 0))
                            score = top + min(width, 1000)
                            if any(k in haystack for k in ["input", "editor", "chatcontentview", "message"]):
                                score += 300
                            candidates.append((score, ctrl))
                        except Exception:
                            continue
                    if candidates:
                        candidates.sort(key=lambda item: item[0], reverse=True)
                        picked = candidates[0][1]
                        self._cache_set("input_box", picked)
                        return picked
                self._cache_set("input_box", edit)
                return edit
        except:
            pass
        
        return None
    
    def _get_send_control(self) -> Optional:
        """
        获取发送按钮。
        策略：Name="发送" → ButtonControl 遍历 → 回退到所有按钮按面积/位置打分
        """
        if not self._window or not self._window.Exists():
            return None
        
        cached = self._cache_get("send_btn")
        if cached:
            return cached
        
        # 方式1: 按名称"发送"查找
        try:
            btn = self._window.ButtonControl(searchDepth=15, Name="发送")
            if btn.Exists(maxSearchSeconds=0.5):
                self._cache_set("send_btn", btn)
                return btn
        except:
            pass
        
        # 方式2: 遍历所有 ButtonControl，按文本匹配
        try:
            buttons = self._window.ButtonControl(searchDepth=15)
            if buttons.Exists(maxSearchSeconds=0.3):
                children = buttons.GetChildren() if hasattr(buttons, 'GetChildren') else []
                if not children:
                    # 本身可能就是单个按钮
                    name = str(getattr(buttons, 'Name', '') or '')
                    if '发送' in name or 'Send' in name.lower():
                        self._cache_set("send_btn", buttons)
                        return buttons
                for btn in children:
                    name = str(getattr(btn, 'Name', '') or '')
                    if '发送' in name or 'Send' in name.lower():
                        self._cache_set("send_btn", btn)
                        return btn
        except:
            pass
        
        # 方式3: 按位置 + 类名打分（通常发送按钮在右下角）
        try:
            best_btn = None
            best_score = -1
            for ctrl in self._walk_controls(self._window, max_depth=12):
                try:
                    ctrl_type = str(self._safe_attr(ctrl, "ControlTypeName", "") or "")
                    if "Button" not in ctrl_type:
                        continue
                    rect = self._get_control_rect(ctrl) or {}
                    top = int(rect.get("top", 0) or 0)
                    right = int(rect.get("right", 0) or 0)
                    name = str(self._safe_attr(ctrl, "Name", "") or "").strip()
                    # 右下角 + 有"发送"/"Send"关键词
                    score = top + right
                    if any(k in name for k in ("发送", "Send", "send")):
                        score += 5000
                    if score > best_score:
                        best_score = score
                        best_btn = ctrl
                except Exception:
                    continue
            if best_btn:
                self._cache_set("send_btn", best_btn)
                return best_btn
        except:
            pass
        
        return None

    def _collect_control_texts(self, ctrl, depth: int = 0, max_depth: int = 4) -> List[str]:
        texts = []
        if not ctrl or depth > max_depth:
            return texts
        try:
            name = (ctrl.Name or "").strip()
            if name:
                texts.append(name)
        except:
            pass
        try:
            for child in ctrl.GetChildren():
                texts.extend(self._collect_control_texts(child, depth + 1, max_depth))
        except:
            pass
        deduped = []
        for item in texts:
            normalized = str(item or '').strip()
            if normalized and normalized not in deduped:
                deduped.append(normalized)
        return deduped

    def _extract_order_snapshot_from_texts(self, texts: List[str]) -> Dict:
        merged = "\n".join([t for t in texts if t])
        normalized = merged.replace("：", ":")

        order_id = ""
        order_match = re.search(r'(订单号|订单编号|订单编码|商家订单号)\s*:?\s*([A-Za-z0-9\-]{6,})', normalized)
        if order_match:
            order_id = order_match.group(2).strip()

        tracking_number = ""
        tracking_match = re.search(r'(快递单号|运单号|物流单号|包裹单号|物流编号)\s*:?\s*([A-Za-z0-9\-]{6,})', normalized)
        if tracking_match:
            tracking_number = tracking_match.group(2).strip()
        if not tracking_number:
            bare_tracking = re.search(r'(?:^|\s)([A-Z]{2}\d{10,}|[0-9]{12,18})(?:\s|$)', normalized)
            if bare_tracking:
                tracking_number = bare_tracking.group(1).strip()

        shipping_status = ""
        for keyword in ['待发货', '已发货', '运输中', '派送中', '已签收', '待揽收', '已揽收', '退款中', '售后中', '未发货', '部分发货']:
            if keyword in merged:
                shipping_status = keyword
                break

        courier_name = ""
        for keyword in ['顺丰', '中通', '圆通', '韵达', '申通', '极兔', '京东', '邮政', 'EMS', '德邦', '菜鸟', '丹鸟']:
            if keyword in merged:
                courier_name = keyword
                break

        product_names = []
        for text in texts:
            cleaned = str(text or '').strip()
            if not cleaned:
                continue
            if any(tag in cleaned for tag in ['订单号', '物流', '快递', '发货', '收货', '地址', '运单号', '退款']):
                continue
            if 2 <= len(cleaned) <= 40 and not re.fullmatch(r'[A-Za-z0-9\-]+', cleaned):
                product_names.append(cleaned)
        deduped_products = []
        for name in product_names:
            if name not in deduped_products:
                deduped_products.append(name)

        logistics_trajectory = ""
        logistics_lines = []
        for text in texts:
            line = str(text or '').strip()
            if any(keyword in line for keyword in ['已签收', '运输中', '派送中', '待揽收', '已揽收', '离开', '到达', '收件']):
                logistics_lines.append(line)
        if logistics_lines:
            logistics_trajectory = "；".join(logistics_lines[:3])

        return {
            "orderId": order_id,
            "shippingStatus": shipping_status,
            "trackingNumber": tracking_number,
            "courierName": courier_name,
            "logisticsTrajectory": logistics_trajectory,
            "products": [{"name": name} for name in deduped_products[:3]],
            "rawTexts": texts[:50],
        }

    def get_order_snapshot(self) -> Dict:
        """读取当前会话右侧可见的订单/物流信息快照"""
        try:
            self.activate()
        except:
            pass

        self._ensure_order_panel_visible()

        texts = []
        order_panel = self._get_order_panel()
        if order_panel:
            texts.extend(self._collect_control_texts(order_panel, max_depth=6))

        panel = self._get_chat_panel()
        if panel:
            texts.extend(self._collect_control_texts(panel, max_depth=4))

        if not texts and self._window:
            texts.extend(self._collect_control_texts(self._window, max_depth=4))

        if not texts:
            return {"success": False, "error": "no_visible_texts"}

        snapshot = self._extract_order_snapshot_from_texts(texts)
        return {"success": True, "data": snapshot}

    def approve_address_change_request(self) -> Dict:
        """在千牛原生窗口中自动同意买家提交的改地址申请"""
        if not self.activate():
            return {"success": False, "executed": False, "error": "window_not_active"}

        snapshot_result = self.get_order_snapshot()
        snapshot = snapshot_result.get("data") if snapshot_result.get("success") else {}
        shipping_status = self._snapshot_shipping_status(snapshot)
        if any(keyword in shipping_status for keyword in ["已发货", "运输中", "派送中", "已签收", "已揽收", "待签收"]):
            return {
                "success": True,
                "executed": False,
                "skipped": True,
                "reason": f"当前订单状态为{shipping_status}，不应自动同意改地址"
            }

        approve_keywords = ["同意修改", "确认修改", "确认改址", "审核通过", "同意", "通过", "确认"]
        reject_keywords = ["不同意", "拒绝", "驳回", "取消", "关闭"]

        btn = self._find_clickable_control_by_keywords(approve_keywords, exclude_keywords=reject_keywords, max_depth=12)
        if not btn:
            return {
                "success": False,
                "executed": False,
                "skipped": True,
                "reason": "未找到改址申请同意入口"
            }

        first_name = str(self._safe_attr(btn, "Name", "") or "")
        if not self._click_control_center(btn):
            return {
                "success": False,
                "executed": False,
                "error": "click_first_approve_failed"
            }

        time.sleep(0.5)

        second_btn = self._find_clickable_control_by_keywords(approve_keywords, exclude_keywords=reject_keywords, max_depth=12)
        second_name = str(self._safe_attr(second_btn, "Name", "") or "") if second_btn else ""
        if second_btn and second_btn != btn and second_name and second_name != first_name:
            self._click_control_center(second_btn)
            time.sleep(0.6)

        return {
            "success": True,
            "executed": True,
            "reason": "已自动同意买家改址申请",
            "button_text": first_name or second_name or "确认"
        }

    def approve_refund_request(self) -> Dict:
        """在千牛原生窗口中自动同意未发货仅退款申请"""
        if not self.activate():
            return {"success": False, "executed": False, "error": "window_not_active"}

        snapshot_result = self.get_order_snapshot()
        snapshot = snapshot_result.get("data") if snapshot_result.get("success") else {}
        shipping_status = self._snapshot_shipping_status(snapshot)
        if any(keyword in shipping_status for keyword in ["已发货", "运输中", "派送中", "已签收", "已揽收", "待签收", "已收货"]):
            return {
                "success": True,
                "executed": False,
                "skipped": True,
                "reason": f"当前订单状态为{shipping_status}，不应自动同意仅退款"
            }

        approve_keywords = ["同意退款", "确认退款", "同意售后", "审核通过", "同意", "通过", "确认"]
        reject_keywords = ["不同意", "拒绝", "驳回", "取消", "关闭", "地址"]

        btn = self._find_clickable_control_by_keywords(approve_keywords, exclude_keywords=reject_keywords, max_depth=12)
        if not btn:
            return {
                "success": False,
                "executed": False,
                "skipped": True,
                "reason": "未找到退款申请同意入口"
            }

        first_name = str(self._safe_attr(btn, "Name", "") or "")
        if not self._click_control_center(btn):
            return {
                "success": False,
                "executed": False,
                "error": "click_first_refund_approve_failed"
            }

        time.sleep(0.5)

        second_btn = self._find_clickable_control_by_keywords(approve_keywords, exclude_keywords=reject_keywords, max_depth=12)
        second_name = str(self._safe_attr(second_btn, "Name", "") or "") if second_btn else ""
        if second_btn and second_btn != btn and second_name and second_name != first_name:
            self._click_control_center(second_btn)
            time.sleep(0.6)

        return {
            "success": True,
            "executed": True,
            "reason": "已自动同意未发货仅退款申请",
            "button_text": first_name or second_name or "确认"
        }

    def reject_refund_request(self) -> Dict:
        """在千牛原生窗口中自动驳回已收货后的仅退款申请"""
        if not self.activate():
            return {"success": False, "executed": False, "error": "window_not_active"}

        snapshot_result = self.get_order_snapshot()
        snapshot = snapshot_result.get("data") if snapshot_result.get("success") else {}
        shipping_status = self._snapshot_shipping_status(snapshot)
        if not any(keyword in shipping_status for keyword in ["已签收", "待签收", "已收货", "签收"]):
            return {
                "success": True,
                "executed": False,
                "skipped": True,
                "reason": f"当前订单状态为{shipping_status or '未知'}，不满足自动驳回仅退款条件"
            }

        reject_keywords = ["拒绝退款", "驳回申请", "不同意", "拒绝", "驳回"]
        exclude_keywords = ["地址", "关闭", "取消"]
        btn = self._find_clickable_control_by_keywords(reject_keywords, exclude_keywords=exclude_keywords, max_depth=12)
        if not btn:
            return {
                "success": False,
                "executed": False,
                "skipped": True,
                "reason": "未找到仅退款驳回入口"
            }

        first_name = str(self._safe_attr(btn, "Name", "") or "")
        if not self._click_control_center(btn):
            return {
                "success": False,
                "executed": False,
                "error": "click_first_refund_reject_failed"
            }

        time.sleep(0.5)

        second_btn = self._find_clickable_control_by_keywords(reject_keywords, exclude_keywords=exclude_keywords, max_depth=12)
        second_name = str(self._safe_attr(second_btn, "Name", "") or "") if second_btn else ""
        if second_btn and second_btn != btn and second_name and second_name != first_name:
            self._click_control_center(second_btn)
            time.sleep(0.6)

        return {
            "success": True,
            "executed": True,
            "reason": "已自动驳回已收货仅退款申请",
            "button_text": first_name or second_name or "驳回"
        }

    def approve_return_refund_request(self) -> Dict:
        """在千牛原生窗口中自动同意退货退款申请"""
        if not self.activate():
            return {"success": False, "executed": False, "error": "window_not_active"}

        approve_keywords = ["同意退货", "确认退货", "同意退货退款", "审核通过", "同意", "通过", "确认"]
        reject_keywords = ["不同意", "拒绝", "驳回", "取消", "关闭", "地址"]
        btn = self._find_clickable_control_by_keywords(approve_keywords, exclude_keywords=reject_keywords, max_depth=12)
        if not btn:
            return {
                "success": False,
                "executed": False,
                "skipped": True,
                "reason": "未找到退货退款同意入口"
            }

        first_name = str(self._safe_attr(btn, "Name", "") or "")
        if not self._click_control_center(btn):
            return {
                "success": False,
                "executed": False,
                "error": "click_first_return_approve_failed"
            }

        time.sleep(0.5)

        second_btn = self._find_clickable_control_by_keywords(approve_keywords, exclude_keywords=reject_keywords, max_depth=12)
        second_name = str(self._safe_attr(second_btn, "Name", "") or "") if second_btn else ""
        if second_btn and second_btn != btn and second_name and second_name != first_name:
            self._click_control_center(second_btn)
            time.sleep(0.6)

        return {
            "success": True,
            "executed": True,
            "reason": "已自动同意退货退款申请",
            "button_text": first_name or second_name or "确认"
        }
    
    # --------------------------------------------------
    # 会话列表读取
    # --------------------------------------------------
    def get_customers(self) -> List[QianNiuCustomer]:
        """读取千牛左侧会话列表"""
        customers = []
        items = self._get_chat_list_items()
        
        for item in items:
            try:
                name = item.Name or ""
            except:
                continue
            
            if not name or len(name) < 1:
                continue
            
            c = QianNiuCustomer(name="")
            
            # 提取未读标记 (\d+条未读)
            um = re.search(r'(\d+)\s*条?未读', name)
            if um:
                c.unread_count = int(um.group(1))
                c.has_unread = True
            
            # 紧急标记
            c.has_priority = bool(re.search(r'(超时|倒计时)', name))
            if c.has_priority:
                c.has_unread = True
            
            # 提取客户名: 去除状态文字
            clean = re.sub(r'[\(（].*?[\)）]|\d+\s*条?未读|超时|倒计时|即将', '', name)
            clean = clean.strip()
            if clean:
                c.name = clean
                customers.append(c)
        
        return customers
    
    def select_chat(self, customer_name: str) -> bool:
        """选择指定客户的对话"""
        if not self.activate():
            return False
        
        items = self._get_chat_list_items()
        
        # 先精确匹配
        for item in items:
            try:
                if item.Name and item.Name.strip() == customer_name:
                    item.Click()
                    self._current_chat = customer_name
                    self._cache.pop("msg_controls", None)  # 清消息缓存
                    time.sleep(0.3)
                    return True
            except:
                pass
        
        # 再模糊匹配
        for item in items:
            try:
                if item.Name and customer_name in item.Name:
                    item.Click()
                    self._current_chat = customer_name
                    self._cache.pop("msg_controls", None)
                    time.sleep(0.3)
                    return True
            except:
                pass
        
        return False
    
    # --------------------------------------------------
    # 消息读取
    # --------------------------------------------------
    def get_messages(self, max_count: int = 20) -> List[QianNiuMessage]:
        """读取当前会话的消息"""
        messages = []
        controls = self._get_message_controls()
        
        for ctrl in controls[-max_count:]:
            msg = self._parse_message(ctrl)
            if msg:
                messages.append(msg)
        
        return messages
    
    def _parse_message(self, ctrl) -> Optional[QianNiuMessage]:
        """从UIA控件解析消息"""
        try:
            text = ctrl.Name
            if not text or len(text) < 1:
                return None
        except:
            return None
        
        # 判断发送方
        is_self = False
        sender = "buyer"
        
        # 方法1: 通过控件位置判断(千牛卖家消息靠右)
        try:
            rect = ctrl.BoundingRectangle
            if rect and self._window:
                w_rect = self._window.BoundingRectangle
                if w_rect:
                    cx = rect.left + (rect.right - rect.left) / 2
                    wc = w_rect.left + (w_rect.right - w_rect.left) / 2
                    is_self = cx > wc
                    sender = "seller" if is_self else "buyer"
        except:
            pass
        
        # 方法2: 通过文本前缀
        for prefix, self_msg in [
            ("我：", True), ("我:", True),
            ("客服：", True), ("客服:", True),
            ("卖家：", True), ("卖家:", True),
            ("买家：", False), ("买家:", False),
            ("对方：", False), ("对方:", False),
        ]:
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
                is_self = self_msg
                sender = "seller" if self_msg else "buyer"
                break
        
        if text and len(text) > 1:
            return QianNiuMessage(sender=sender, content=text, is_self=is_self)
        return None
    
    def get_last_buyer_message(self) -> Optional[QianNiuMessage]:
        """获取买家最后一条消息"""
        msgs = self.get_messages(max_count=10)
        for m in reversed(msgs):
            if not m.is_self:
                return m
        return None
    
    # --------------------------------------------------
    # 发送消息
    # --------------------------------------------------
    def send_message(self, text: str) -> bool:
        """发送消息 (模拟人工鼠标点击 + 粘贴 + 点击发送)"""
        if not text:
            return False
        if not self.activate():
            return False
        
        inp = self._get_input_control()
        if not inp:
            print("[QianNiuAdapter] 找不到输入框")
            return False
        
        try:
            if not self._click_control_center(inp):
                return False
            if not self._paste_edit_text(inp, text):
                return False

            btn = self._get_send_control()
            if btn:
                if not self._click_control_center(btn):
                    btn.Click()
            else:
                auto.SendKeys("{Enter}", waitTime=0.1)
            
            # 清空消息缓存, 下次读取能看到新消息
            self._cache.pop("msg_controls", None)
            print(f"[QianNiuAdapter] 已发送: {text[:40]}...")
            return True
        except Exception as e:
            print(f"[QianNiuAdapter] 发送失败: {e}")
            return False
    
    # --------------------------------------------------
    # 实时监控
    # --------------------------------------------------
    def set_on_message(self, cb: Callable[[str, str, str], None]):
        """设置新消息回调 (customer, sender, content)"""
        self._on_message = cb
    
    def set_on_unread(self, cb: Callable[[List[QianNiuCustomer]], None]):
        """设置未读会话回调"""
        self._on_unread = cb
    
    def start(self):
        """启动实时监控 (事件驱动 + 辅助轮询)"""
        if self._running:
            return
        if not self.find_window():
            print("[QianNiuAdapter] 千牛未启动, 无法启动监控")
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("[QianNiuAdapter] 监控已启动")
    
    def stop(self):
        """停止监控"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        print("[QianNiuAdapter] 监控已停止")
    
    def _loop(self):
        """监控主循环"""
        last_full = 0
        fail_count = 0
        
        while self._running:
            try:
                if not self.is_alive():
                    fail_count += 1
                    if fail_count >= 6:
                        print("[QianNiuAdapter] 千牛窗口持续丢失, 停止监控")
                        break
                    time.sleep(self.RECONNECT_INTERVAL)
                    self.find_window()
                    self._cache_clear()
                    continue
                
                fail_count = 0
                now = time.time()
                
                # 全量扫描(会话列表)
                if now - last_full >= self.FULL_SCAN_INTERVAL:
                    self._scan_full()
                    last_full = now
                
                # 高频检查(当前会话新消息)
                if self._current_chat:
                    self._scan_new_messages()
                
                time.sleep(self.POLL_INTERVAL)
            except Exception as e:
                print(f"[QianNiuAdapter] 循环异常: {e}")
                time.sleep(1)
    
    def _scan_full(self):
        """全量扫描: 检查未读会话"""
        try:
            self._cache.pop("chat_items", None)
            customers = self.get_customers()
            unread = [c for c in customers if c.has_unread]
            
            if unread and self._on_unread:
                self._on_unread(unread)
            
            # 无当前会话时自动选第一个未读
            if unread and not self._current_chat:
                self.select_chat(unread[0].name)
        except:
            pass
    
    def _scan_new_messages(self):
        """高频检查: 当前会话新消息"""
        try:
            self._cache.pop("msg_controls", None)
            latest = self.get_last_buyer_message()
            if latest and latest.msg_hash not in self._processed_hashes:
                self._processed_hashes.add(latest.msg_hash)
                self._pending_messages.append({
                    "buyer": self._current_chat or "",
                    "sender": self._current_chat or "",
                    "content": latest.content,
                    "timestamp": latest.timestamp.timestamp(),
                })
                if len(self._pending_messages) > 200:
                    self._pending_messages = self._pending_messages[-100:]
                if self._on_message:
                    self._on_message(self._current_chat, latest.sender, latest.content)
                
                if len(self._processed_hashes) > 2000:
                    self._processed_hashes = set(list(self._processed_hashes)[-1000:])
        except:
            pass
    
    # --------------------------------------------------
    # 状态查询
    # --------------------------------------------------
    def get_status(self) -> dict:
        """适配器状态"""
        alive = self.is_alive()
        return {
            "connected": alive,
            "monitoring": self._running,
            "window_title": self._window.Name if alive else None,
            "current_chat": self._current_chat,
            "processed_count": len(self._processed_hashes),
            "pending_count": len(self._pending_messages),
            "cache_size": len(self._cache),
            "platform": "qianniu",
            "chat_ready": self.is_chat_ready() if alive else False,
        }


# ============================================================
# Flask API
# ============================================================
def create_app():
    """创建 Flask web 服务"""
    from flask import Flask, request, jsonify
    from flask_cors import CORS
    
    app = Flask(__name__)
    CORS(app)
    
    # 全局错误处理：确保所有异常都返回 JSON
    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"success": False, "error": "Not found"}), 404
    
    @app.errorhandler(500)
    def server_error(e):
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": "Internal server error"}), 500
    
    @app.errorhandler(Exception)
    def handle_exception(e):
        return jsonify({"success": False, "error": str(e)}), 500
    
    adapter = get_qianniu_adapter()
    
    # 统一管理层（协调 window_host + adapter）
    from manager import QianNiuManager
    manager_wrapper = QianNiuManager()
    manager_wrapper.set_adapter(adapter)
    
    # 启动心跳日志
    startup_log = os.path.join(os.getcwd(), ".dbg", "service_startup.log")
    try:
        os.makedirs(os.path.dirname(startup_log), exist_ok=True)
        with open(startup_log, "w") as f:
            f.write(f"Flask app created at {datetime.datetime.now()}\n")
    except:
        pass
    
    @app.route("/ping")
    def api_ping():
        return jsonify({"ok": True})
    
    @app.route("/status")
    def api_status():
        try:
            status = adapter.get_status()
            return jsonify({
                "success": True,
                "data": status,
                **status,
            })
        except Exception as e:
            return jsonify({"success": True, "connected": False, "error": str(e)})
    
    @app.route("/connect")
    def api_connect():
        import time as _time
        last_error = ""
        for attempt in range(3):
            try:
                ok = adapter.find_window()
                return jsonify({"success": ok})
            except Exception as e:
                last_error = str(e)
                adapter._reset_window_ref()
                if attempt < 2:
                    _time.sleep(0.6)
        return jsonify({"success": False, "error": last_error or "connect failed"})
    
    @app.route("/customers")
    def api_customers():
        customers = [
            {"name": c.name, "unread": c.unread_count,
             "has_unread": c.has_unread, "priority": c.has_priority}
            for c in adapter.get_customers()
        ]
        return jsonify({
            "success": True,
            "customers": customers,
            "data": customers,
        })

    @app.route("/chats")
    def api_chats():
        customers = [
            {"name": c.name, "unread": c.unread_count,
             "hasUnread": c.has_unread, "unreadCount": c.unread_count, "priority": c.has_priority}
            for c in adapter.get_customers()
        ]
        return jsonify({"success": True, "data": customers})

    @app.route("/unread")
    def api_unread():
        customers = [
            {"name": c.name, "unread": c.unread_count,
             "hasUnread": c.has_unread, "unreadCount": c.unread_count, "priority": c.has_priority}
            for c in adapter.get_customers() if c.has_unread
        ]
        return jsonify({"success": True, "data": customers})
    
    @app.route("/messages")
    def api_messages():
        count = request.args.get("count", 20, type=int)
        return jsonify({
            "success": True,
            "messages": [
                {"sender": m.sender, "content": m.content,
                 "is_self": m.is_self, "time": m.timestamp.isoformat()}
                for m in adapter.get_messages(count)
            ]
        })
    
    @app.route("/select", methods=["POST"])
    def api_select():
        name = (request.get_json() or {}).get("name", "")
        ok = adapter.select_chat(name)
        return jsonify({"success": ok})

    @app.route("/select-chat", methods=["POST"])
    def api_select_chat():
        name = (request.get_json() or {}).get("name", "")
        ok = adapter.select_chat(name)
        return jsonify({"success": ok})
    
    @app.route("/send", methods=["POST"])
    def api_send():
        payload = request.get_json() or {}
        text = payload.get("text", "") or payload.get("message", "")
        if not text:
            return jsonify({"success": False, "error": "text required"})
        return jsonify({"success": adapter.send_message(text)})
    
    @app.route("/start-monitor", methods=["POST"])
    def api_start():
        adapter.start()
        return jsonify({"success": True, "status": adapter.get_status()})
    
    @app.route("/stop-monitor", methods=["POST"])
    def api_stop():
        adapter.stop()
        return jsonify({"success": True})
    
    @app.route("/last-message")
    def api_last():
        m = adapter.get_last_buyer_message()
        if m:
            return jsonify({
                "success": True,
                "sender": m.sender,
                "content": m.content,
                "time": m.timestamp.isoformat()
            })
        return jsonify({"success": False})
    
    @app.route("/current-chat")
    def api_current_chat():
        return jsonify({"success": True, "current_chat": adapter._current_chat, "data": adapter._current_chat})

    @app.route("/pending-messages")
    def api_pending_messages():
        return jsonify({"success": True, "data": adapter.pop_pending_messages()})

    @app.route("/order-snapshot")
    def api_order_snapshot():
        snapshot = adapter.get_order_snapshot()
        return jsonify(snapshot)

    @app.route("/approve-address-change", methods=["POST"])
    def api_approve_address_change():
        return jsonify(adapter.approve_address_change_request())

    @app.route("/approve-refund", methods=["POST"])
    def api_approve_refund():
        return jsonify(adapter.approve_refund_request())

    @app.route("/reject-refund", methods=["POST"])
    def api_reject_refund():
        return jsonify(adapter.reject_refund_request())

    @app.route("/approve-return-refund", methods=["POST"])
    def api_approve_return_refund():
        return jsonify(adapter.approve_return_refund_request())

    @app.route("/login", methods=["POST"])
    def api_login():
        payload = request.get_json() or {}
        adapter._last_login_fail_reason = ""
        try:
            ok = adapter.login((payload.get("username") or "").strip(), payload.get("password") or "")
        except Exception as e:
            adapter._login_log("login.exception", f"登录异常: {e}", level="error")
            ok = False
            adapter._last_login_fail_reason = str(e)
        # 登录成功后重新枚举窗口获取工作台 HWND（而非登录窗口 HWND）
        workbench_hwnd = 0
        if ok:
            try:
                workbench_hwnd = manager_wrapper.host.find_main_window() or 0
            except Exception:
                pass
        result = {
            "success": ok,
            "chat_ready": adapter.is_chat_ready() if ok else False,
            "hwnd": workbench_hwnd,
            "log_path": adapter._get_login_log_path(),
            "log_recent": adapter.get_login_log_recent(80),
        }
        if not ok and adapter._last_login_fail_reason:
            result["detail"] = adapter._last_login_fail_reason
            print(f"[QianNiuAdapter] 登录失败详情: {adapter._last_login_fail_reason}")
        return jsonify(result)

    @app.route("/login-log", methods=["GET"])
    def api_login_log():
        max_lines = request.args.get("max", default=120, type=int)
        return jsonify({
            "success": True,
            "log_path": adapter._get_login_log_path(),
            "lines": adapter.get_login_log_recent(max_lines),
        })

    @app.route("/login-log", methods=["POST"])
    def api_login_log_append():
        payload = request.get_json() or {}
        adapter._login_log(
            str(payload.get("step") or "client"),
            str(payload.get("message") or ""),
            payload.get("data") if isinstance(payload.get("data"), dict) else {},
            str(payload.get("level") or "info"),
        )
        return jsonify({"success": True, "log_path": adapter._get_login_log_path()})

    @app.route("/open-chat", methods=["POST"])
    def api_open_chat():
        ok = adapter.ensure_chat_ready()
        if not ok:
            adapter._login_log("open_chat.fail.probe", "打开聊天工作台失败", adapter._chat_ready_snapshot(), level="error")
        workbench_hwnd = 0
        if ok:
            try:
                workbench_hwnd = manager_wrapper.host.find_main_window() or 0
            except Exception:
                pass
        return jsonify({
            "success": ok,
            "chat_ready": adapter.is_chat_ready() if ok else False,
            "hwnd": workbench_hwnd,
        })

    @app.route("/attach", methods=["POST"])
    def api_attach():
        """将千牛窗口嵌入 Electron，并通过 ControlFromHandle 重新绑定 UIA"""
        payload = request.get_json() or {}
        host_hwnd = int(payload.get("host_hwnd") or 0)
        result = manager_wrapper.attach(host_hwnd)
        return jsonify(result)

    @app.route("/activate", methods=["GET", "POST"])
    def api_activate():
        return jsonify({"success": adapter.activate()})
    
    return app


# Singleton
_adapter: Optional[QianNiuAdapter] = None


def get_qianniu_adapter() -> QianNiuAdapter:
    global _adapter
    if _adapter is None:
        _adapter = QianNiuAdapter()
    return _adapter


# --------------------------------------------------
# 测试 / 服务
# --------------------------------------------------
if __name__ == "__main__":
    import sys
    
    if "--service" in sys.argv:
        port = 8766
        a = get_qianniu_adapter()
        if a.find_window():
            print(f"[QianNiuAdapter] 千牛已连接, 启动自动监控")
            a.start()
        else:
            print(f"[QianNiuAdapter] 千牛未运行, 启动后可通过 /connect 连接")
        
        app = create_app()
        print(f"[QianNiuAdapter] API: http://127.0.0.1:{port}")
        print(f"  GET  /status     - 状态")
        print(f"  GET  /connect    - 连接千牛")
        print(f"  GET  /customers  - 会话列表")
        print(f"  GET  /messages   - 消息列表")
        print(f"  POST /select     - 选择会话")
        print(f"  POST /send       - 发送消息")
        print(f"  POST /start-mon,-stop  - 监控开关")
        print(f"  GET  /last-msg   - 买家最后消息")
        app.run(host="127.0.0.1", port=port, debug=False)
    else:
        # 测试
        print("=" * 50)
        print("千牛适配器 v2 测试")
        print("=" * 50)
        a = get_qianniu_adapter()
        if a.find_window():
            print("\n千牛已找到")
            cs = a.get_customers()
            print(f"会话({len(cs)}):")
            for c in cs[:10]:
                f = []
                if c.has_unread: f.append(f"未读:{c.unread_count}")
                if c.has_priority: f.append("紧急")
                print(f"  - {c.name}" + (f" ({', '.join(f)})" if f else ""))
            print(f"\n📊 状态: {a.get_status()}")
        else:
            print("\n千牛未运行")
