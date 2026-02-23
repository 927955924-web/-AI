"""
文件监控器
监控智语AI客服相关的文件变化
"""
import os
import time
import threading
import hashlib
from typing import Optional, Dict, Any, List, Set
from pathlib import Path
from external_monitor import EventType, logger

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    logger.warning("watchdog模块不可用，文件监控功能受限")
    WATCHDOG_AVAILABLE = False


class FileMonitor:
    """文件监控器类"""
    
    def __init__(self, main_monitor, watch_dirs: List[str] = None):
        self.main_monitor = main_monitor
        self.watch_dirs = watch_dirs or []
        self.running = False
        self.monitor_thread: Optional[threading.Thread] = None
        
        # 文件监控相关
        self.observer = None
        self.event_handler = None
        
        # 定期检查相关（备用方案）
        self.check_interval = 10.0  # 检查间隔（秒）
        self.last_file_states: Dict[str, Dict[str, Any]] = {}  # 文件路径 -> 文件状态
        self.watch_patterns = [
            '*.db', '*.sqlite', '*.sqlite3', '*.db3',
            '*.json', '*.ini', '*.cfg', '*.conf', '*.config',
            '*.yaml', '*.yml', '*.xml',
            '*.log', '*.txt', '*.csv',
            'knowledge.db', 'settings.db'  # 已知的文件名
        ]
        
        # 重要文件路径模式（用于识别关键文件）
        self.important_patterns = [
            'knowledge.db',
            'settings',
            'config',
            'user',
            'shop',
            'product',
            'session',
            'order',
            'chat',
            'database',
            'db\\.'
        ]
        
    def start(self):
        """启动文件监控"""
        if self.running:
            logger.warning("文件监控已在运行中")
            return
        
        # 清理无效目录
        valid_dirs = []
        for dir_path in self.watch_dirs:
            if os.path.exists(dir_path) and os.path.isdir(dir_path):
                valid_dirs.append(dir_path)
            else:
                logger.debug(f"目录不存在或不是目录: {dir_path}")
        
        if not valid_dirs:
            logger.warning("没有有效的监控目录，文件监控将无法工作")
            return
        
        self.watch_dirs = valid_dirs
        self.running = True
        
        # 尝试使用watchdog
        if WATCHDOG_AVAILABLE:
            try:
                self._start_watchdog()
                logger.info(f"使用watchdog启动文件监控，监控目录: {valid_dirs}")
                return
            except Exception as e:
                logger.warning(f"watchdog启动失败，使用定期检查: {e}")
        
        # 使用定期检查
        self.monitor_thread = threading.Thread(
            target=self._periodic_check_loop,
            daemon=True,
            name="FileMonitorLoop"
        )
        self.monitor_thread.start()
        logger.info(f"使用定期检查启动文件监控，监控目录: {valid_dirs}")
    
    def stop(self):
        """停止文件监控"""
        self.running = False
        
        # 停止watchdog观察者
        if self.observer:
            try:
                self.observer.stop()
                self.observer.join()
            except Exception as e:
                logger.error(f"停止watchdog观察者时出错: {e}")
        
        # 停止监控线程
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=2.0)
        
        logger.info("文件监控已停止")
    
    def _start_watchdog(self):
        """使用watchdog启动文件监控"""
        self.observer = Observer()
        self.event_handler = FileEventHandler(self)
        
        for dir_path in self.watch_dirs:
            try:
                self.observer.schedule(self.event_handler, dir_path, recursive=True)
                logger.debug(f"添加监控目录: {dir_path}")
            except Exception as e:
                logger.error(f"添加监控目录失败 {dir_path}: {e}")
        
        self.observer.start()
    
    def _periodic_check_loop(self):
        """定期检查文件变化循环"""
        # 初始扫描
        self._scan_files()
        
        while self.running:
            try:
                # 扫描文件变化
                self._check_file_changes()
                
                # 等待下次检查
                time.sleep(self.check_interval)
                
            except Exception as e:
                logger.error(f"文件监控循环出错: {e}")
                time.sleep(5.0)
    
    def _scan_files(self):
        """扫描所有监控目录的文件"""
        for dir_path in self.watch_dirs:
            try:
                for root, dirs, files in os.walk(dir_path):
                    for file in files:
                        if self._is_watched_file(file):
                            file_path = os.path.join(root, file)
                            self._update_file_state(file_path)
            except Exception as e:
                logger.error(f"扫描目录失败 {dir_path}: {e}")
    
    def _check_file_changes(self):
        """检查文件变化"""
        current_files = set()
        
        # 收集当前文件
        for dir_path in self.watch_dirs:
            try:
                for root, dirs, files in os.walk(dir_path):
                    for file in files:
                        if self._is_watched_file(file):
                            file_path = os.path.join(root, file)
                            current_files.add(file_path)
                            
                            # 检查文件状态
                            if file_path in self.last_file_states:
                                # 文件已存在，检查是否修改
                                old_state = self.last_file_states[file_path]
                                new_state = self._get_file_state(file_path)
                                
                                if old_state['mtime'] != new_state['mtime'] or old_state['size'] != new_state['size']:
                                    self._handle_file_modify(file_path, old_state, new_state)
                                    self.last_file_states[file_path] = new_state
                            else:
                                # 新文件
                                new_state = self._get_file_state(file_path)
                                self._handle_file_create(file_path, new_state)
                                self.last_file_states[file_path] = new_state
            except Exception as e:
                logger.error(f"检查目录失败 {dir_path}: {e}")
        
        # 检查已删除的文件
        deleted_files = set(self.last_file_states.keys()) - current_files
        for file_path in deleted_files:
            old_state = self.last_file_states[file_path]
            self._handle_file_delete(file_path, old_state)
            del self.last_file_states[file_path]
    
    def _is_watched_file(self, filename: str) -> bool:
        """判断是否监控此文件"""
        filename_lower = filename.lower()
        
        # 检查文件扩展名
        for pattern in self.watch_patterns:
            if pattern.startswith('*.'):
                # 通配符扩展名
                ext = pattern[2:]
                if filename_lower.endswith('.' + ext):
                    return True
            elif pattern in filename_lower:
                # 完全匹配
                return True
        
        # 检查重要文件模式
        for pattern in self.important_patterns:
            if pattern in filename_lower:
                return True
        
        return False
    
    def _get_file_state(self, file_path: str) -> Dict[str, Any]:
        """获取文件状态信息"""
        try:
            stat = os.stat(file_path)
            file_size = stat.st_size
            mtime = stat.st_mtime
            ctime = stat.st_ctime
            
            # 计算文件哈希（仅对小文件）
            file_hash = None
            if file_size < 10 * 1024 * 1024:  # 10MB以下
                try:
                    with open(file_path, 'rb') as f:
                        file_hash = hashlib.md5(f.read()).hexdigest()
                except Exception:
                    pass
            
            return {
                'path': file_path,
                'size': file_size,
                'mtime': mtime,
                'ctime': ctime,
                'hash': file_hash,
                'is_important': self._is_important_file(file_path)
            }
        except Exception as e:
            logger.error(f"获取文件状态失败 {file_path}: {e}")
            return {}
    
    def _update_file_state(self, file_path: str):
        """更新文件状态（用于初始扫描）"""
        state = self._get_file_state(file_path)
        if state:
            self.last_file_states[file_path] = state
    
    def _is_important_file(self, file_path: str) -> bool:
        """判断是否为重要文件"""
        filename = os.path.basename(file_path).lower()
        
        for pattern in self.important_patterns:
            if pattern in filename:
                return True
        
        # 检查扩展名
        if any(filename.endswith(ext) for ext in ['.db', '.sqlite', '.sqlite3']):
            return True
        
        return False
    
    def _handle_file_create(self, file_path: str, file_state: Dict[str, Any]):
        """处理文件创建事件"""
        try:
            description = f"文件创建: {os.path.basename(file_path)}"
            if file_state.get('is_important'):
                description += " (重要文件)"
            
            event_data = {
                "file_path": file_path,
                "file_name": os.path.basename(file_path),
                "file_size": file_state.get('size', 0),
                "mtime": file_state.get('mtime', 0),
                "is_important": file_state.get('is_important', False),
                "description": description
            }
            
            self.main_monitor.record_event(
                EventType.FILE_CREATE,
                event_data
            )
            
            logger.info(f"检测到文件创建: {file_path}")
            
        except Exception as e:
            logger.error(f"处理文件创建事件时出错: {e}")
    
    def _handle_file_modify(self, file_path: str, old_state: Dict[str, Any], new_state: Dict[str, Any]):
        """处理文件修改事件"""
        try:
            description = f"文件修改: {os.path.basename(file_path)}"
            if new_state.get('is_important'):
                description += " (重要文件)"
            
            # 计算变化
            size_change = new_state.get('size', 0) - old_state.get('size', 0)
            if size_change != 0:
                description += f"，大小变化: {size_change} 字节"
            
            event_data = {
                "file_path": file_path,
                "file_name": os.path.basename(file_path),
                "old_size": old_state.get('size', 0),
                "new_size": new_state.get('size', 0),
                "size_change": size_change,
                "old_mtime": old_state.get('mtime', 0),
                "new_mtime": new_state.get('mtime', 0),
                "is_important": new_state.get('is_important', False),
                "description": description
            }
            
            # 如果是数据库文件，记录额外信息
            if file_path.lower().endswith(('.db', '.sqlite', '.sqlite3')):
                event_data['file_type'] = 'database'
            
            self.main_monitor.record_event(
                EventType.FILE_MODIFY,
                event_data
            )
            
            logger.info(f"检测到文件修改: {file_path}，大小变化: {size_change} 字节")
            
        except Exception as e:
            logger.error(f"处理文件修改事件时出错: {e}")
    
    def _handle_file_delete(self, file_path: str, old_state: Dict[str, Any]):
        """处理文件删除事件"""
        try:
            description = f"文件删除: {os.path.basename(file_path)}"
            if old_state.get('is_important'):
                description += " (重要文件)"
            
            event_data = {
                "file_path": file_path,
                "file_name": os.path.basename(file_path),
                "file_size": old_state.get('size', 0),
                "is_important": old_state.get('is_important', False),
                "description": description
            }
            
            self.main_monitor.record_event(
                EventType.FILE_DELETE,
                event_data
            )
            
            logger.info(f"检测到文件删除: {file_path}")
            
        except Exception as e:
            logger.error(f"处理文件删除事件时出错: {e}")
    
    def handle_watchdog_event(self, event_type: str, file_path: str, is_directory: bool = False):
        """处理watchdog事件（由FileEventHandler调用）"""
        if is_directory or not self._is_watched_file(os.path.basename(file_path)):
            return
        
        if event_type == 'created':
            new_state = self._get_file_state(file_path)
            if new_state:
                self._handle_file_create(file_path, new_state)
                self.last_file_states[file_path] = new_state
        
        elif event_type == 'modified':
            if file_path in self.last_file_states:
                old_state = self.last_file_states[file_path]
                new_state = self._get_file_state(file_path)
                if new_state and (old_state['mtime'] != new_state['mtime'] or old_state['size'] != new_state['size']):
                    self._handle_file_modify(file_path, old_state, new_state)
                    self.last_file_states[file_path] = new_state
        
        elif event_type == 'deleted':
            if file_path in self.last_file_states:
                old_state = self.last_file_states[file_path]
                self._handle_file_delete(file_path, old_state)
                del self.last_file_states[file_path]
    
    def get_watched_files(self) -> List[Dict[str, Any]]:
        """获取监控的文件列表"""
        files = []
        
        for file_path, state in self.last_file_states.items():
            file_info = {
                "path": file_path,
                "name": os.path.basename(file_path),
                "size": state.get('size', 0),
                "mtime": state.get('mtime', 0),
                "is_important": state.get('is_important', False),
                "last_check": time.time()
            }
            files.append(file_info)
        
        return files
    
    def get_important_files(self) -> List[Dict[str, Any]]:
        """获取重要文件列表"""
        important_files = []
        
        for file_path, state in self.last_file_states.items():
            if state.get('is_important'):
                file_info = {
                    "path": file_path,
                    "name": os.path.basename(file_path),
                    "size": state.get('size', 0),
                    "mtime": state.get('mtime', 0),
                    "last_check": time.time()
                }
                important_files.append(file_info)
        
        return important_files


if WATCHDOG_AVAILABLE:
    class FileEventHandler(FileSystemEventHandler):
        """watchdog文件事件处理器"""
        
        def __init__(self, file_monitor):
            super().__init__()
            self.file_monitor = file_monitor
        
        def on_created(self, event):
            self.file_monitor.handle_watchdog_event('created', event.src_path, event.is_directory)
        
        def on_modified(self, event):
            self.file_monitor.handle_watchdog_event('modified', event.src_path, event.is_directory)
        
        def on_deleted(self, event):
            self.file_monitor.handle_watchdog_event('deleted', event.src_path, event.is_directory)


if __name__ == "__main__":
    # 测试代码
    print("文件监控器测试")
    
    # 创建模拟的主监控器
    class MockMonitor:
        def __init__(self):
            self.events = []
        
        def record_event(self, event_type, data):
            print(f"记录事件: {event_type.value} - {data.get('description', '')}")
            self.events.append((event_type, data))
    
    monitor = MockMonitor()
    
    # 测试监控当前目录
    test_dirs = [os.getcwd()]
    file_monitor = FileMonitor(monitor, test_dirs)
    
    print("启动文件监控...")
    file_monitor.start()
    
    try:
        print("监控运行中，按Ctrl+C停止...")
        print(f"监控目录: {test_dirs}")
        
        # 显示当前监控的文件
        for i in range(6):  # 运行30秒
            files = file_monitor.get_watched_files()
            important_files = file_monitor.get_important_files()
            
            print(f"\n监控文件统计 (第{i+1}次检查):")
            print(f"  总监控文件数: {len(files)}")
            print(f"  重要文件数: {len(important_files)}")
            
            if important_files:
                print("  重要文件列表:")
                for j, file_info in enumerate(important_files[:3], 1):
                    print(f"    {j}. {file_info['name']} ({file_info['size']} 字节)")
                if len(important_files) > 3:
                    print(f"    ... 和 {len(important_files) - 3} 个其他文件")
            
            time.sleep(5)
            
    except KeyboardInterrupt:
        print("停止监控...")
    
    file_monitor.stop()
    print(f"共记录 {len(monitor.events)} 个事件")