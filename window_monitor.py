"""
窗口监控器
监控智语AI客服的窗口状态和UI事件
"""
import time
import threading
import re
from typing import Optional, Dict, Any, List, Tuple
from external_monitor import EventType, logger

try:
    import win32gui
    import win32con
    import win32api
    WIN32_AVAILABLE = True
except ImportError:
    logger.warning("win32gui模块不可用，窗口监控功能受限")
    WIN32_AVAILABLE = False

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    logger.warning("pyautogui模块不可用，UI操作监控功能受限")
    PYAUTOGUI_AVAILABLE = False


class WindowMonitor:
    """窗口监控器类"""
    
    def __init__(self, main_monitor):
        self.main_monitor = main_monitor
        self.target_window_titles = ["智语AI客服", "智语", "AI客服"]  # 可能的窗口标题关键词
        self.running = False
        self.monitor_thread: Optional[threading.Thread] = None
        self.last_windows: Dict[int, Dict[str, Any]] = {}  # hwnd -> 窗口信息
        self.check_interval = 1.0  # 检查间隔（秒）
        self.focus_check_interval = 0.5  # 焦点检查间隔
        self.screenshot_interval = 30.0  # 截图间隔（秒）
        self.last_screenshot_time = 0
        
        # UI事件检测
        self.last_mouse_position = None
        self.last_click_time = 0
        self.click_threshold = 0.5  # 点击检测阈值（秒）
        
    def start(self):
        """启动窗口监控"""
        if self.running:
            logger.warning("窗口监控已在运行中")
            return
        
        if not WIN32_AVAILABLE:
            logger.error("win32gui不可用，窗口监控无法启动")
            return
        
        self.running = True
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="WindowMonitorLoop"
        )
        self.monitor_thread.start()
        logger.info("窗口监控已启动")
    
    def stop(self):
        """停止窗口监控"""
        self.running = False
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=2.0)
        logger.info("窗口监控已停止")
    
    def _monitor_loop(self):
        """窗口监控循环"""
        last_focus_check = 0
        last_window_check = 0
        
        while self.running:
            try:
                current_time = time.time()
                
                # 定期检查窗口变化
                if current_time - last_window_check >= self.check_interval:
                    self._check_window_changes()
                    last_window_check = current_time
                
                # 更频繁地检查焦点变化
                if current_time - last_focus_check >= self.focus_check_interval:
                    self._check_focus_changes()
                    last_focus_check = current_time
                
                # 定期截图（如果启用）
                if PYAUTOGUI_AVAILABLE and current_time - self.last_screenshot_time >= self.screenshot_interval:
                    self._capture_screenshot_if_target()
                    self.last_screenshot_time = current_time
                
                # 监控UI事件（鼠标点击等）
                if PYAUTOGUI_AVAILABLE:
                    self._monitor_ui_events()
                
                # 等待下次检查
                time.sleep(0.1)  # 短时间等待以提高响应性
                
            except Exception as e:
                logger.error(f"窗口监控循环出错: {e}")
                time.sleep(2.0)
    
    def _check_window_changes(self):
        """检查窗口变化"""
        try:
            current_windows = self._find_target_windows()
            current_hwnds = set(current_windows.keys())
            last_hwnds = set(self.last_windows.keys())
            
            # 检测新窗口
            new_hwnds = current_hwnds - last_hwnds
            for hwnd in new_hwnds:
                self._handle_window_create(hwnd, current_windows[hwnd])
            
            # 检测窗口关闭
            closed_hwnds = last_hwnds - current_hwnds
            for hwnd in closed_hwnds:
                self._handle_window_destroy(hwnd)
            
            # 检测窗口标题变化
            for hwnd in current_hwnds.intersection(last_hwnds):
                old_title = self.last_windows.get(hwnd, {}).get('title', '')
                new_title = current_windows[hwnd].get('title', '')
                if old_title != new_title:
                    self._handle_window_title_change(hwnd, old_title, new_title)
            
            # 更新窗口信息
            self.last_windows = current_windows
            
        except Exception as e:
            logger.error(f"检查窗口变化时出错: {e}")
    
    def _find_target_windows(self) -> Dict[int, Dict[str, Any]]:
        """查找目标窗口"""
        windows = {}
        
        def enum_windows_callback(hwnd, extra):
            try:
                # 获取窗口标题
                title = win32gui.GetWindowText(hwnd)
                
                # 检查是否为目标窗口
                if self._is_target_window(hwnd, title):
                    # 获取窗口信息
                    window_info = self._get_window_info(hwnd, title)
                    windows[hwnd] = window_info
            except Exception as e:
                logger.debug(f"枚举窗口时出错 (hwnd={hwnd}): {e}")
            return True
        
        try:
            win32gui.EnumWindows(enum_windows_callback, None)
        except Exception as e:
            logger.error(f"枚举窗口失败: {e}")
        
        return windows
    
    def _is_target_window(self, hwnd: int, title: str) -> bool:
        """判断是否为目标窗口"""
        if not title:
            return False
        
        # 检查标题是否包含关键词
        title_lower = title.lower()
        for keyword in self.target_window_titles:
            if keyword.lower() in title_lower:
                return True
        
        # 检查窗口类名（Tkinter应用通常使用'TkTopLevel'或'TkFrame'）
        try:
            class_name = win32gui.GetClassName(hwnd)
            if class_name in ['TkTopLevel', 'TkFrame', 'Tk']:
                return True
        except:
            pass
        
        # 检查窗口是否可见
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return False
        except:
            return False
        
        return False
    
    def _get_window_info(self, hwnd: int, title: str) -> Dict[str, Any]:
        """获取窗口详细信息"""
        info = {
            'hwnd': hwnd,
            'title': title,
            'class_name': '',
            'rect': None,
            'is_visible': False,
            'is_enabled': False,
            'process_id': None
        }
        
        try:
            info['class_name'] = win32gui.GetClassName(hwnd)
            info['rect'] = win32gui.GetWindowRect(hwnd)
            info['is_visible'] = win32gui.IsWindowVisible(hwnd)
            info['is_enabled'] = win32gui.IsWindowEnabled(hwnd)
            
            # 获取进程ID
            _, pid = win32gui.GetWindowThreadProcessId(hwnd)
            info['process_id'] = pid
            
            # 获取窗口样式
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
            info['style'] = style
            
            # 获取扩展样式
            ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            info['ex_style'] = ex_style
            
        except Exception as e:
            logger.debug(f"获取窗口信息失败 (hwnd={hwnd}): {e}")
        
        return info
    
    def _handle_window_create(self, hwnd: int, window_info: Dict[str, Any]):
        """处理窗口创建事件"""
        try:
            self.main_monitor.record_event(
                EventType.WINDOW_CREATE,
                {
                    "hwnd": hwnd,
                    "title": window_info.get('title', '未知'),
                    "class_name": window_info.get('class_name', '未知'),
                    "rect": window_info.get('rect'),
                    "process_id": window_info.get('process_id'),
                    "description": f"窗口创建: {window_info.get('title', '未知')} (句柄: {hwnd})"
                }
            )
            
            logger.info(f"检测到窗口创建: {window_info.get('title', '未知')} (句柄: {hwnd})")
            
        except Exception as e:
            logger.error(f"处理窗口创建事件时出错: {e}")
    
    def _handle_window_destroy(self, hwnd: int):
        """处理窗口销毁事件"""
        try:
            old_info = self.last_windows.get(hwnd, {})
            self.main_monitor.record_event(
                EventType.WINDOW_DESTROY,
                {
                    "hwnd": hwnd,
                    "title": old_info.get('title', '未知'),
                    "description": f"窗口销毁: {old_info.get('title', '未知')} (句柄: {hwnd})"
                }
            )
            
            logger.info(f"检测到窗口销毁: {old_info.get('title', '未知')} (句柄: {hwnd})")
            
        except Exception as e:
            logger.error(f"处理窗口销毁事件时出错: {e}")
    
    def _handle_window_title_change(self, hwnd: int, old_title: str, new_title: str):
        """处理窗口标题变化事件"""
        try:
            self.main_monitor.record_event(
                EventType.WINDOW_TITLE_CHANGE,
                {
                    "hwnd": hwnd,
                    "old_title": old_title,
                    "new_title": new_title,
                    "description": f"窗口标题变化: '{old_title}' -> '{new_title}' (句柄: {hwnd})"
                }
            )
            
            logger.info(f"检测到窗口标题变化: '{old_title}' -> '{new_title}' (句柄: {hwnd})")
            
        except Exception as e:
            logger.error(f"处理窗口标题变化事件时出错: {e}")
    
    def _check_focus_changes(self):
        """检查焦点窗口变化"""
        try:
            # 获取当前焦点窗口
            focus_hwnd = win32gui.GetForegroundWindow()
            
            # 检查是否是目标窗口
            focus_title = win32gui.GetWindowText(focus_hwnd)
            if self._is_target_window(focus_hwnd, focus_title):
                # 检查焦点是否变化
                if hasattr(self, '_last_focus_hwnd') and self._last_focus_hwnd != focus_hwnd:
                    old_info = self.last_windows.get(self._last_focus_hwnd, {})
                    new_info = self.last_windows.get(focus_hwnd, {})
                    
                    self.main_monitor.record_event(
                        EventType.WINDOW_FOCUS,
                        {
                            "old_hwnd": self._last_focus_hwnd,
                            "old_title": old_info.get('title', '未知'),
                            "new_hwnd": focus_hwnd,
                            "new_title": new_info.get('title', focus_title),
                            "description": f"窗口焦点变化: {old_info.get('title', '未知')} -> {new_info.get('title', focus_title)}"
                        }
                    )
                    
                    logger.debug(f"窗口焦点变化: {old_info.get('title', '未知')} -> {new_info.get('title', focus_title)}")
                
                # 更新最后焦点窗口
                self._last_focus_hwnd = focus_hwnd
            else:
                # 焦点不在目标窗口上
                self._last_focus_hwnd = None
                
        except Exception as e:
            logger.debug(f"检查焦点变化时出错: {e}")
    
    def _capture_screenshot_if_target(self):
        """如果焦点在目标窗口上，则捕获截图"""
        try:
            if not hasattr(self, '_last_focus_hwnd') or not self._last_focus_hwnd:
                return
            
            # 检查焦点窗口是否仍然是目标窗口
            focus_title = win32gui.GetWindowText(self._last_focus_hwnd)
            if not self._is_target_window(self._last_focus_hwnd, focus_title):
                return
            
            # 获取窗口位置
            try:
                left, top, right, bottom = win32gui.GetWindowRect(self._last_focus_hwnd)
                width = right - left
                height = bottom - top
                
                # 截图（仅窗口区域）
                screenshot = pyautogui.screenshot(region=(left, top, width, height))
                
                # 保存截图
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                filename = f"screenshot_{timestamp}_hwnd{self._last_focus_hwnd}.png"
                screenshot.save(filename)
                
                logger.debug(f"已保存窗口截图: {filename}")
                
            except Exception as e:
                logger.debug(f"截图失败: {e}")
                
        except Exception as e:
            logger.debug(f"捕获截图时出错: {e}")
    
    def _monitor_ui_events(self):
        """监控UI事件（鼠标点击等）"""
        try:
            current_time = time.time()
            
            # 获取当前鼠标位置
            current_pos = pyautogui.position()
            
            # 检查鼠标点击
            # 注意：这只能检测鼠标位置变化，不能直接检测点击事件
            # 更高级的检测需要钩子（hook），这里简化处理
            
            # 如果鼠标位置突然变化，可能表示点击
            if self.last_mouse_position and self.last_mouse_position != current_pos:
                # 检查是否在目标窗口内点击
                if self._is_position_in_target_window(current_pos):
                    # 简单点击检测：位置变化且距离上次点击时间超过阈值
                    if current_time - self.last_click_time > self.click_threshold:
                        # 记录可能的点击事件
                        self._record_ui_click(current_pos)
                        self.last_click_time = current_time
            
            # 更新鼠标位置
            self.last_mouse_position = current_pos
            
        except Exception as e:
            logger.debug(f"监控UI事件时出错: {e}")
    
    def _is_position_in_target_window(self, position: Tuple[int, int]) -> bool:
        """检查位置是否在目标窗口内"""
        x, y = position
        
        for hwnd, window_info in self.last_windows.items():
            try:
                rect = window_info.get('rect')
                if not rect:
                    continue
                
                left, top, right, bottom = rect
                if left <= x <= right and top <= y <= bottom:
                    return True
            except:
                continue
        
        return False
    
    def _record_ui_click(self, position: Tuple[int, int]):
        """记录UI点击事件"""
        x, y = position
        
        # 查找点击的窗口
        clicked_window = None
        for hwnd, window_info in self.last_windows.items():
            try:
                rect = window_info.get('rect')
                if not rect:
                    continue
                
                left, top, right, bottom = rect
                if left <= x <= right and top <= y <= bottom:
                    clicked_window = window_info
                    break
            except:
                continue
        
        if clicked_window:
            # 计算相对坐标
            left, top, right, bottom = clicked_window['rect']
            rel_x = x - left
            rel_y = y - top
            
            self.main_monitor.record_event(
                EventType.UI_BUTTON_CLICK,
                {
                    "hwnd": clicked_window['hwnd'],
                    "title": clicked_window.get('title', '未知'),
                    "absolute_x": x,
                    "absolute_y": y,
                    "relative_x": rel_x,
                    "relative_y": rel_y,
                    "description": f"UI点击: {clicked_window.get('title', '未知')} 在 ({rel_x}, {rel_y})"
                }
            )
            
            logger.debug(f"检测到UI点击: {clicked_window.get('title', '未知')} 在 ({rel_x}, {rel_y})")
    
    def get_active_windows(self) -> List[Dict[str, Any]]:
        """获取活动窗口列表"""
        windows = self._find_target_windows()
        return list(windows.values())
    
    def get_focused_window(self) -> Optional[Dict[str, Any]]:
        """获取当前焦点窗口"""
        try:
            focus_hwnd = win32gui.GetForegroundWindow()
            focus_title = win32gui.GetWindowText(focus_hwnd)
            
            if self._is_target_window(focus_hwnd, focus_title):
                return self._get_window_info(focus_hwnd, focus_title)
        except:
            pass
        
        return None


if __name__ == "__main__":
    # 测试代码
    print("窗口监控器测试")
    
    # 创建模拟的主监控器
    class MockMonitor:
        def __init__(self):
            self.events = []
        
        def record_event(self, event_type, data):
            print(f"记录事件: {event_type.value} - {data.get('description', '')}")
            self.events.append((event_type, data))
    
    monitor = MockMonitor()
    
    if WIN32_AVAILABLE:
        window_monitor = WindowMonitor(monitor)
        
        print("启动窗口监控...")
        window_monitor.start()
        
        try:
            print("监控运行中，按Ctrl+C停止...")
            print("当前活动窗口:")
            windows = window_monitor.get_active_windows()
            for i, win in enumerate(windows, 1):
                print(f"{i}. {win.get('title', '未知')} (句柄: {win.get('hwnd')})")
            
            time.sleep(30)
        except KeyboardInterrupt:
            print("停止监控...")
        
        window_monitor.stop()
        print(f"共记录 {len(monitor.events)} 个事件")
    else:
        print("win32gui不可用，无法测试窗口监控")