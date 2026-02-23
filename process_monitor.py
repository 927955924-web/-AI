"""
进程监控器
监控智语AI客服.exe的进程状态和资源使用
"""
import time
import psutil
import threading
from typing import Optional, Dict, Any
from external_monitor import EventType, logger


class ProcessMonitor:
    """进程监控器类"""
    
    def __init__(self, main_monitor):
        self.main_monitor = main_monitor
        self.target_process_name = main_monitor.target_process_name
        self.running = False
        self.monitor_thread: Optional[threading.Thread] = None
        self.last_process_info: Dict[int, psutil.Process] = {}
        self.check_interval = 2.0  # 检查间隔（秒）
        self.resource_check_interval = 10.0  # 资源检查间隔（秒）
        
    def start(self):
        """启动进程监控"""
        if self.running:
            logger.warning("进程监控已在运行中")
            return
        
        self.running = True
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="ProcessMonitorLoop"
        )
        self.monitor_thread.start()
        logger.info(f"进程监控已启动，目标进程: {self.target_process_name}")
    
    def stop(self):
        """停止进程监控"""
        self.running = False
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=2.0)
        logger.info("进程监控已停止")
    
    def _monitor_loop(self):
        """监控循环"""
        last_resource_check = 0
        
        while self.running:
            try:
                current_time = time.time()
                
                # 查找目标进程
                current_processes = self._find_target_processes()
                current_pids = set(current_processes.keys())
                last_pids = set(self.last_process_info.keys())
                
                # 检测新进程
                new_pids = current_pids - last_pids
                for pid in new_pids:
                    self._handle_process_start(pid, current_processes[pid])
                
                # 检测进程退出
                exited_pids = last_pids - current_pids
                for pid in exited_pids:
                    self._handle_process_exit(pid)
                
                # 定期检查资源使用
                if current_time - last_resource_check >= self.resource_check_interval:
                    for pid, process in current_processes.items():
                        self._check_process_resources(pid, process)
                    last_resource_check = current_time
                
                # 更新进程信息
                self.last_process_info = current_processes
                
                # 等待下次检查
                time.sleep(self.check_interval)
                
            except Exception as e:
                logger.error(f"进程监控循环出错: {e}")
                time.sleep(5.0)  # 出错后等待更长时间
    
    def _find_target_processes(self) -> Dict[int, psutil.Process]:
        """查找目标进程"""
        processes = {}
        try:
            for proc in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
                try:
                    # 检查进程名
                    if proc.info['name'] and self.target_process_name.lower() in proc.info['name'].lower():
                        processes[proc.info['pid']] = proc
                    # 检查可执行文件路径
                    elif proc.info['exe'] and '智语AI客服' in proc.info['exe']:
                        processes[proc.info['pid']] = proc
                    # 检查命令行参数
                    elif proc.info['cmdline']:
                        cmdline = ' '.join(proc.info['cmdline'])
                        if '智语AI客服' in cmdline:
                            processes[proc.info['pid']] = proc
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            logger.error(f"查找进程时出错: {e}")
        
        return processes
    
    def _handle_process_start(self, pid: int, process: psutil.Process):
        """处理进程启动事件"""
        try:
            proc_info = process.as_dict(attrs=[
                'pid', 'name', 'exe', 'cmdline', 'create_time', 
                'username', 'status'
            ])
            
            # 获取更详细的进程信息
            try:
                proc_info['memory_info'] = process.memory_info()._asdict()
                proc_info['cpu_percent'] = process.cpu_percent(interval=0.1)
                proc_info['num_threads'] = process.num_threads()
                proc_info['connections'] = len(process.connections())
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            
            self.main_monitor.record_event(
                EventType.PROCESS_START,
                {
                    "pid": pid,
                    "process_name": proc_info.get('name', '未知'),
                    "exe_path": proc_info.get('exe', '未知'),
                    "cmdline": proc_info.get('cmdline', []),
                    "create_time": proc_info.get('create_time', 0),
                    "username": proc_info.get('username', '未知'),
                    "description": f"进程启动: {proc_info.get('name', '未知')} (PID: {pid})"
                }
            )
            
            logger.info(f"检测到进程启动: {proc_info.get('name', '未知')} (PID: {pid})")
            
        except Exception as e:
            logger.error(f"处理进程启动事件时出错: {e}")
    
    def _handle_process_exit(self, pid: int):
        """处理进程退出事件"""
        try:
            self.main_monitor.record_event(
                EventType.PROCESS_EXIT,
                {
                    "pid": pid,
                    "description": f"进程退出: PID {pid}"
                }
            )
            
            logger.info(f"检测到进程退出: PID {pid}")
            
        except Exception as e:
            logger.error(f"处理进程退出事件时出错: {e}")
    
    def _check_process_resources(self, pid: int, process: psutil.Process):
        """检查进程资源使用"""
        try:
            # 获取CPU使用率
            cpu_percent = process.cpu_percent(interval=0.1)
            
            # 获取内存信息
            memory_info = process.memory_info()
            memory_mb = memory_info.rss / 1024 / 1024  # 转换为MB
            
            # 获取其他资源信息
            num_threads = process.num_threads()
            num_handles = process.num_handles()
            
            # 获取磁盘IO（如果可用）
            io_counters = None
            try:
                io_counters = process.io_counters()
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                pass
            
            # 获取网络连接数
            connections = []
            try:
                connections = process.connections()
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                pass
            
            resource_data = {
                "pid": pid,
                "cpu_percent": cpu_percent,
                "memory_mb": round(memory_mb, 2),
                "num_threads": num_threads,
                "num_handles": num_handles,
                "num_connections": len(connections),
                "description": f"进程资源: CPU {cpu_percent:.1f}%, 内存 {memory_mb:.1f}MB"
            }
            
            if io_counters:
                resource_data.update({
                    "read_bytes": io_counters.read_bytes,
                    "write_bytes": io_counters.write_bytes,
                    "read_count": io_counters.read_count,
                    "write_count": io_counters.write_count
                })
            
            self.main_monitor.record_event(
                EventType.PROCESS_RESOURCE,
                resource_data
            )
            
            logger.debug(f"进程资源监控: PID {pid}, CPU: {cpu_percent:.1f}%, 内存: {memory_mb:.1f}MB")
            
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            # 进程可能已经退出
            pass
        except Exception as e:
            logger.error(f"检查进程资源时出错: {e}")
    
    def get_process_count(self) -> int:
        """获取当前运行的进程数量"""
        return len(self._find_target_processes())
    
    def get_active_processes_info(self) -> list:
        """获取活动进程的详细信息"""
        processes = self._find_target_processes()
        process_info_list = []
        
        for pid, process in processes.items():
            try:
                info = {
                    "pid": pid,
                    "name": process.name(),
                    "exe": process.exe(),
                    "status": process.status(),
                    "create_time": process.create_time(),
                    "cpu_percent": process.cpu_percent(interval=0.1),
                    "memory_mb": process.memory_info().rss / 1024 / 1024,
                    "num_threads": process.num_threads()
                }
                process_info_list.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        return process_info_list


if __name__ == "__main__":
    # 测试代码
    print("进程监控器测试")
    
    # 创建模拟的主监控器
    class MockMonitor:
        def __init__(self):
            self.events = []
        
        def record_event(self, event_type, data):
            print(f"记录事件: {event_type.value} - {data.get('description', '')}")
            self.events.append((event_type, data))
    
    monitor = MockMonitor()
    process_monitor = ProcessMonitor(monitor)
    
    print("启动进程监控...")
    process_monitor.start()
    
    try:
        print("监控运行中，按Ctrl+C停止...")
        time.sleep(30)
    except KeyboardInterrupt:
        print("停止监控...")
    
    process_monitor.stop()
    print(f"共记录 {len(monitor.events)} 个事件")