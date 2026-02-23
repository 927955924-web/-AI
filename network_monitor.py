"""
网络监控器
监控智语AI客服的网络连接和活动
"""
import time
import threading
import socket
import psutil
from typing import Optional, Dict, Any, List, Set
from external_monitor import EventType, logger


class NetworkMonitor:
    """网络监控器类"""
    
    def __init__(self, main_monitor):
        self.main_monitor = main_monitor
        self.running = False
        self.monitor_thread: Optional[threading.Thread] = None
        self.check_interval = 5.0  # 检查间隔（秒）
        self.last_connections: Dict[int, Set[tuple]] = {}  # pid -> 连接集合
        self.process_monitor = None  # 引用进程监控器以获取PID
        
        # 已知的API端点模式（用于识别API调用）
        self.api_patterns = [
            r'api\.',
            r'openai\.com',
            r'\.ai\.',
            r'chatgpt',
            r'gpt-',
            r'deepseek',
            r'claude',
            r'\.aliyun\.com',
            r'\.tencent\.com',
            r'\.baidu\.com',
            r'volcengine\.com',  # 火山引擎
            r'\.bytedance\.com',  # 字节跳动
        ]
        
    def start(self):
        """启动网络监控"""
        if self.running:
            logger.warning("网络监控已在运行中")
            return
        
        self.running = True
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="NetworkMonitorLoop"
        )
        self.monitor_thread.start()
        logger.info("网络监控已启动")
    
    def stop(self):
        """停止网络监控"""
        self.running = False
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=2.0)
        logger.info("网络监控已停止")
    
    def _monitor_loop(self):
        """网络监控循环"""
        while self.running:
            try:
                # 获取目标进程
                target_pids = self._get_target_process_pids()
                
                # 监控每个进程的网络连接
                for pid in target_pids:
                    self._monitor_process_network(pid)
                
                # 等待下次检查
                time.sleep(self.check_interval)
                
            except Exception as e:
                logger.error(f"网络监控循环出错: {e}")
                time.sleep(5.0)
    
    def _get_target_process_pids(self) -> List[int]:
        """获取目标进程的PID列表"""
        pids = []
        
        # 首先尝试从进程监控器获取
        if hasattr(self.main_monitor, 'process_monitor') and self.main_monitor.process_monitor:
            try:
                processes = self.main_monitor.process_monitor._find_target_processes()
                pids = list(processes.keys())
            except Exception as e:
                logger.debug(f"从进程监控器获取PID失败: {e}")
        
        # 如果无法从进程监控器获取，则直接查找
        if not pids:
            try:
                for proc in psutil.process_iter(['pid', 'name', 'exe']):
                    try:
                        proc_info = proc.info
                        name = proc_info.get('name', '').lower()
                        exe = proc_info.get('exe', '').lower()
                        
                        if ('智语ai客服' in name or '智语ai客服' in exe or 
                            '智语' in name or '智语' in exe):
                            pids.append(proc_info['pid'])
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            except Exception as e:
                logger.error(f"查找进程PID失败: {e}")
        
        return pids
    
    def _monitor_process_network(self, pid: int):
        """监控单个进程的网络连接"""
        try:
            process = psutil.Process(pid)
            
            # 获取当前网络连接
            current_connections = set()
            try:
                connections = process.connections(kind='inet')
                for conn in connections:
                    # 转换为可哈希的元组
                    conn_tuple = (
                        conn.family.name if hasattr(conn.family, 'name') else str(conn.family),
                        conn.type.name if hasattr(conn.type, 'name') else str(conn.type),
                        conn.laddr if conn.laddr else (),
                        conn.raddr if conn.raddr else (),
                        conn.status if conn.status else '',
                        conn.pid if hasattr(conn, 'pid') else pid
                    )
                    current_connections.add(conn_tuple)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.AccessDenied):
                # 进程可能已经退出或无权限
                pass
            
            # 获取上次的连接集合
            last_connections = self.last_connections.get(pid, set())
            
            # 检测新连接
            new_connections = current_connections - last_connections
            for conn_tuple in new_connections:
                self._handle_new_connection(pid, conn_tuple)
            
            # 检测关闭的连接
            closed_connections = last_connections - current_connections
            for conn_tuple in closed_connections:
                self._handle_closed_connection(pid, conn_tuple)
            
            # 更新连接信息
            if current_connections:
                self.last_connections[pid] = current_connections
            elif pid in self.last_connections:
                del self.last_connections[pid]
            
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            # 进程可能已经退出
            if pid in self.last_connections:
                del self.last_connections[pid]
        except Exception as e:
            logger.error(f"监控进程网络连接时出错 (PID: {pid}): {e}")
    
    def _handle_new_connection(self, pid: int, conn_tuple: tuple):
        """处理新网络连接事件"""
        try:
            family, conn_type, laddr, raddr, status, _ = conn_tuple
            
            # 解析地址信息
            local_ip, local_port = laddr if laddr else ('', 0)
            remote_ip, remote_port = raddr if raddr else ('', 0)
            
            # 判断连接类型
            is_outgoing = bool(remote_ip)
            connection_type = "出站" if is_outgoing else "入站"
            
            # 检查是否为API调用
            is_api = False
            api_type = None
            if remote_ip:
                # 尝试反向DNS查找（简化处理，只检查IP模式）
                for pattern in self.api_patterns:
                    if pattern in remote_ip:
                        is_api = True
                        api_type = pattern
                        break
            
            # 构建连接描述
            description = f"网络连接建立: {connection_type} "
            if remote_ip:
                description += f"{remote_ip}:{remote_port}"
                if is_api:
                    description += f" (API: {api_type})"
            else:
                description += f"本地监听 {local_ip}:{local_port}"
            
            # 记录事件
            event_data = {
                "pid": pid,
                "family": family,
                "type": conn_type,
                "local_ip": local_ip,
                "local_port": local_port,
                "remote_ip": remote_ip,
                "remote_port": remote_port,
                "status": status,
                "is_outgoing": is_outgoing,
                "is_api": is_api,
                "api_type": api_type,
                "description": description
            }
            
            self.main_monitor.record_event(
                EventType.NETWORK_REQUEST,
                event_data
            )
            
            logger.info(f"检测到新网络连接: {description}")
            
        except Exception as e:
            logger.error(f"处理新连接事件时出错: {e}")
    
    def _handle_closed_connection(self, pid: int, conn_tuple: tuple):
        """处理网络连接关闭事件"""
        try:
            family, conn_type, laddr, raddr, status, _ = conn_tuple
            
            # 解析地址信息
            local_ip, local_port = laddr if laddr else ('', 0)
            remote_ip, remote_port = raddr if raddr else ('', 0)
            
            description = f"网络连接关闭: "
            if remote_ip:
                description += f"{remote_ip}:{remote_port}"
            else:
                description += f"本地监听 {local_ip}:{local_port}"
            
            event_data = {
                "pid": pid,
                "family": family,
                "type": conn_type,
                "local_ip": local_ip,
                "local_port": local_port,
                "remote_ip": remote_ip,
                "remote_port": remote_port,
                "status": status,
                "description": description
            }
            
            self.main_monitor.record_event(
                EventType.NETWORK_RESPONSE,
                event_data
            )
            
            logger.info(f"检测到网络连接关闭: {description}")
            
        except Exception as e:
            logger.error(f"处理连接关闭事件时出错: {e}")
    
    def get_process_connections(self, pid: int) -> List[Dict[str, Any]]:
        """获取进程的网络连接信息"""
        connections = []
        
        try:
            process = psutil.Process(pid)
            net_connections = process.connections(kind='inet')
            
            for conn in net_connections:
                conn_info = {
                    "family": conn.family.name if hasattr(conn.family, 'name') else str(conn.family),
                    "type": conn.type.name if hasattr(conn.type, 'name') else str(conn.type),
                    "local_address": f"{conn.laddr[0]}:{conn.laddr[1]}" if conn.laddr else "",
                    "remote_address": f"{conn.raddr[0]}:{conn.raddr[1]}" if conn.raddr else "",
                    "status": conn.status,
                    "pid": conn.pid if hasattr(conn, 'pid') else pid
                }
                connections.append(conn_info)
                
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        except Exception as e:
            logger.error(f"获取进程连接信息失败 (PID: {pid}): {e}")
        
        return connections
    
    def get_all_connections_summary(self) -> Dict[str, Any]:
        """获取所有网络连接的摘要信息"""
        summary = {
            "total_connections": 0,
            "outgoing_connections": 0,
            "incoming_connections": 0,
            "api_connections": 0,
            "connections_by_type": {},
            "active_pids": []
        }
        
        for pid, connections in self.last_connections.items():
            summary["active_pids"].append(pid)
            summary["total_connections"] += len(connections)
            
            for conn_tuple in connections:
                family, conn_type, laddr, raddr, status, _ = conn_tuple
                
                # 统计连接类型
                conn_type_str = str(conn_type)
                summary["connections_by_type"][conn_type_str] = summary["connections_by_type"].get(conn_type_str, 0) + 1
                
                # 统计方向
                if raddr:
                    summary["outgoing_connections"] += 1
                    
                    # 检查是否为API连接
                    remote_ip = raddr[0] if raddr else ''
                    for pattern in self.api_patterns:
                        if pattern in remote_ip:
                            summary["api_connections"] += 1
                            break
                else:
                    summary["incoming_connections"] += 1
        
        return summary


if __name__ == "__main__":
    # 测试代码
    print("网络监控器测试")
    
    # 创建模拟的主监控器
    class MockMonitor:
        def __init__(self):
            self.events = []
        
        def record_event(self, event_type, data):
            print(f"记录事件: {event_type.value} - {data.get('description', '')}")
            self.events.append((event_type, data))
    
    monitor = MockMonitor()
    network_monitor = NetworkMonitor(monitor)
    
    print("启动网络监控...")
    network_monitor.start()
    
    try:
        print("监控运行中，按Ctrl+C停止...")
        
        # 显示当前连接摘要
        for i in range(6):  # 运行30秒（6次检查）
            summary = network_monitor.get_all_connections_summary()
            print(f"\n连接摘要:")
            print(f"  活动PID: {summary['active_pids']}")
            print(f"  总连接数: {summary['total_connections']}")
            print(f"  出站连接: {summary['outgoing_connections']}")
            print(f"  入站连接: {summary['incoming_connections']}")
            print(f"  API连接: {summary['api_connections']}")
            
            time.sleep(5)
            
    except KeyboardInterrupt:
        print("停止监控...")
    
    network_monitor.stop()
    print(f"共记录 {len(monitor.events)} 个事件")