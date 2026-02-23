"""
智语AI客服外部监控工具
用于监控已打包的智语AI客服.exe应用程序的运行情况
"""
import os
import sys
import time
import json
import datetime
import threading
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from enum import Enum
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('monitor.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class EventType(Enum):
    PROCESS_START = "process_start"
    PROCESS_EXIT = "process_exit"
    PROCESS_RESOURCE = "process_resource"
    WINDOW_CREATE = "window_create"
    WINDOW_DESTROY = "window_destroy"
    WINDOW_TITLE_CHANGE = "window_title_change"
    WINDOW_FOCUS = "window_focus"
    UI_BUTTON_CLICK = "ui_button_click"
    UI_TEXT_CHANGE = "ui_text_change"
    UI_SELECTION_CHANGE = "ui_selection_change"
    NETWORK_REQUEST = "network_request"
    NETWORK_RESPONSE = "network_response"
    FILE_CREATE = "file_create"
    FILE_MODIFY = "file_modify"
    FILE_DELETE = "file_delete"
    ERROR = "error"


@dataclass
class MonitorEvent:
    event_id: str
    event_type: str
    timestamp: str
    data: Dict[str, Any]
    
    def to_dict(self):
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "data": self.data
        }


class ExternalMonitor:
    """外部监控器主类"""
    
    def __init__(self, target_exe_path: str = None):
        self.target_exe_path = target_exe_path or r"E:\智语AI客服\智语AI客服.exe"
        self.target_process_name = "智语AI客服.exe"
        self.events: List[MonitorEvent] = []
        self.running = False
        self.monitor_threads: List[threading.Thread] = []
        self.session_id = self._generate_session_id()
        
        # 监控器实例
        self.process_monitor = None
        self.window_monitor = None
        self.network_monitor = None
        self.file_monitor = None
        
    def _generate_session_id(self):
        import uuid
        return f"monitor_session_{uuid.uuid4().hex[:8]}"
    
    def start(self):
        """启动所有监控器"""
        if self.running:
            logger.warning("监控器已在运行中")
            return
        
        logger.info(f"启动外部监控器，目标应用: {self.target_exe_path}")
        self.running = True
        
        # 启动进程监控
        try:
            from process_monitor import ProcessMonitor
            self.process_monitor = ProcessMonitor(self)
            process_thread = threading.Thread(
                target=self.process_monitor.start,
                daemon=True,
                name="ProcessMonitor"
            )
            process_thread.start()
            self.monitor_threads.append(process_thread)
            logger.info("进程监控已启动")
        except ImportError as e:
            logger.warning(f"进程监控不可用: {e}")
        
        # 启动窗口监控
        try:
            from window_monitor import WindowMonitor
            self.window_monitor = WindowMonitor(self)
            window_thread = threading.Thread(
                target=self.window_monitor.start,
                daemon=True,
                name="WindowMonitor"
            )
            window_thread.start()
            self.monitor_threads.append(window_thread)
            logger.info("窗口监控已启动")
        except ImportError as e:
            logger.warning(f"窗口监控不可用: {e}")
        
        # 启动网络监控
        try:
            from network_monitor import NetworkMonitor
            self.network_monitor = NetworkMonitor(self)
            network_thread = threading.Thread(
                target=self.network_monitor.start,
                daemon=True,
                name="NetworkMonitor"
            )
            network_thread.start()
            self.monitor_threads.append(network_thread)
            logger.info("网络监控已启动")
        except ImportError as e:
            logger.warning(f"网络监控不可用: {e}")
        
        # 启动文件监控
        try:
            from file_monitor import FileMonitor
            # 监控可能的用户数据目录
            user_data_dirs = self._get_potential_data_dirs()
            self.file_monitor = FileMonitor(self, user_data_dirs)
            file_thread = threading.Thread(
                target=self.file_monitor.start,
                daemon=True,
                name="FileMonitor"
            )
            file_thread.start()
            self.monitor_threads.append(file_thread)
            logger.info(f"文件监控已启动，监控目录: {user_data_dirs}")
        except ImportError as e:
            logger.warning(f"文件监控不可用: {e}")
        
        logger.info("所有监控器已启动")
    
    def stop(self):
        """停止所有监控器"""
        logger.info("正在停止监控器...")
        self.running = False
        
        # 停止各个监控器
        for monitor in [self.process_monitor, self.window_monitor, 
                       self.network_monitor, self.file_monitor]:
            if monitor:
                try:
                    monitor.stop()
                except Exception as e:
                    logger.error(f"停止监控器时出错: {e}")
        
        # 等待线程结束
        for thread in self.monitor_threads:
            if thread.is_alive():
                thread.join(timeout=2.0)
        
        logger.info(f"监控器已停止，共记录 {len(self.events)} 个事件")
    
    def record_event(self, event_type: EventType, data: Dict[str, Any]):
        """记录监控事件"""
        import uuid
        event = MonitorEvent(
            event_id=str(uuid.uuid4()),
            event_type=event_type.value,
            timestamp=datetime.datetime.utcnow().isoformat(),
            data=data
        )
        
        self.events.append(event)
        logger.debug(f"记录事件: {event_type.value} - {data.get('description', '')}")
        
        # 定期保存事件到文件（每100个事件）
        if len(self.events) % 100 == 0:
            self._auto_save_events()
    
    def _auto_save_events(self):
        """自动保存事件到文件"""
        try:
            filename = f"monitor_events_{self.session_id}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                events_data = [event.to_dict() for event in self.events]
                json.dump({
                    "session_id": self.session_id,
                    "export_time": datetime.datetime.utcnow().isoformat(),
                    "total_events": len(events_data),
                    "events": events_data
                }, f, ensure_ascii=False, indent=2)
            logger.debug(f"事件已自动保存到 {filename}")
        except Exception as e:
            logger.error(f"自动保存事件失败: {e}")
    
    def export_events(self, filename: str = None):
        """导出所有监控事件到文件"""
        if not filename:
            filename = f"monitor_export_{self.session_id}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        try:
            events_data = [event.to_dict() for event in self.events]
            export_data = {
                "session_id": self.session_id,
                "export_time": datetime.datetime.utcnow().isoformat(),
                "target_application": self.target_exe_path,
                "total_events": len(events_data),
                "events": events_data
            }
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"监控事件已导出到 {filename}，共 {len(events_data)} 个事件")
            return filename
        except Exception as e:
            logger.error(f"导出事件失败: {e}")
            return None
    
    def get_event_summary(self):
        """获取事件统计摘要"""
        summary = {
            "total_events": len(self.events),
            "event_types": {},
            "time_range": None
        }
        
        if self.events:
            # 按事件类型统计
            for event in self.events:
                event_type = event.event_type
                summary["event_types"][event_type] = summary["event_types"].get(event_type, 0) + 1
            
            # 时间范围
            first_time = datetime.datetime.fromisoformat(self.events[0].timestamp)
            last_time = datetime.datetime.fromisoformat(self.events[-1].timestamp)
            summary["time_range"] = {
                "start": first_time.isoformat(),
                "end": last_time.isoformat(),
                "duration_seconds": (last_time - first_time).total_seconds()
            }
        
        return summary
    
    def _get_potential_data_dirs(self):
        """获取可能的用户数据目录"""
        import os
        potential_dirs = []
        
        # 1. 应用程序所在目录
        app_dir = os.path.dirname(self.target_exe_path)
        potential_dirs.append(app_dir)
        
        # 2. AppData 目录（Windows）
        appdata_dir = os.path.join(os.environ.get('APPDATA', ''), '智语AI客服')
        if os.path.exists(appdata_dir):
            potential_dirs.append(appdata_dir)
        
        # 3. LocalAppData 目录
        local_appdata = os.path.join(os.environ.get('LOCALAPPDATA', ''), '智语AI客服')
        if os.path.exists(local_appdata):
            potential_dirs.append(local_appdata)
        
        # 4. 用户文档目录
        documents_dir = os.path.join(os.path.expanduser('~'), 'Documents', '智语AI客服')
        if os.path.exists(documents_dir):
            potential_dirs.append(documents_dir)
        
        return potential_dirs
    
    def run_interactive(self):
        """运行交互式监控界面"""
        print("=" * 60)
        print("智语AI客服外部监控工具")
        print("=" * 60)
        print(f"目标应用: {self.target_exe_path}")
        print(f"会话ID: {self.session_id}")
        print()
        
        self.start()
        
        try:
            while True:
                print("\n监控选项:")
                print("1. 查看事件统计")
                print("2. 导出监控数据")
                print("3. 查看最近事件")
                print("4. 停止监控")
                print("5. 退出")
                
                choice = input("\n请选择操作 (1-5): ").strip()
                
                if choice == "1":
                    summary = self.get_event_summary()
                    print(f"\n事件统计:")
                    print(f"  总事件数: {summary['total_events']}")
                    if summary['time_range']:
                        print(f"  时间范围: {summary['time_range']['start']} 到 {summary['time_range']['end']}")
                        print(f"  持续时间: {summary['time_range']['duration_seconds']:.1f} 秒")
                    print("\n事件类型分布:")
                    for event_type, count in summary['event_types'].items():
                        print(f"  {event_type}: {count} 个")
                
                elif choice == "2":
                    filename = input("输入导出文件名 (留空使用默认): ").strip()
                    if not filename:
                        filename = None
                    export_file = self.export_events(filename)
                    if export_file:
                        print(f"✓ 数据已导出到: {export_file}")
                    else:
                        print("✗ 导出失败")
                
                elif choice == "3":
                    limit = input("显示最近多少条事件? (默认10): ").strip()
                    limit = int(limit) if limit.isdigit() else 10
                    recent_events = self.events[-limit:] if self.events else []
                    print(f"\n最近 {len(recent_events)} 条事件:")
                    for i, event in enumerate(recent_events, 1):
                        print(f"{i}. [{event.timestamp}] {event.event_type}: {event.data.get('description', '无描述')}")
                
                elif choice == "4":
                    self.stop()
                    print("监控已停止")
                    # 重新启动
                    restart = input("是否重新启动监控? (y/n): ").strip().lower()
                    if restart == 'y':
                        self.start()
                        print("监控已重新启动")
                
                elif choice == "5":
                    print("正在停止监控并退出...")
                    self.stop()
                    break
                
                else:
                    print("无效选择，请重试")
        
        except KeyboardInterrupt:
            print("\n检测到Ctrl+C，正在停止监控...")
            self.stop()
        except Exception as e:
            logger.error(f"交互模式出错: {e}")
            self.stop()


if __name__ == "__main__":
    monitor = ExternalMonitor()
    monitor.run_interactive()