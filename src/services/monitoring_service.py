import datetime
import json
import inspect
from typing import Dict, Any, Optional
from src.infrastructure.repositories.stats_repository import StatsRepository
from src.infrastructure.logger import get_logger


class MonitoringService:
    def __init__(self, stats_repo: StatsRepository):
        self.stats_repo = stats_repo
        self.logger = get_logger()
        self.session_id = self._generate_session_id()
        self.enabled = True
        
    def _generate_session_id(self):
        import uuid
        return f"session_{uuid.uuid4().hex[:8]}"
    
    def record_ui_event(self, event_type: str, widget_name: str, widget_type: str, 
                        value: Any = None, metadata: Optional[Dict] = None):
        if not self.enabled:
            return
            
        metadata = metadata or {}
        metadata.update({
            "widget_name": widget_name,
            "widget_type": widget_type,
            "session_id": self.session_id,
            "value": str(value) if value is not None else None,
            "caller_info": self._get_caller_info()
        })
        
        self.stats_repo.emit(f"ui_{event_type}", "", metadata)
        self.logger.debug(f"UI事件记录: {event_type} - {widget_name}")
    
    def record_state_change(self, entity_type: str, entity_id: str, 
                           old_state: Any, new_state: Any, metadata: Optional[Dict] = None):
        if not self.enabled:
            return
            
        metadata = metadata or {}
        metadata.update({
            "entity_type": entity_type,
            "old_state": str(old_state),
            "new_state": str(new_state),
            "session_id": self.session_id,
            "caller_info": self._get_caller_info()
        })
        
        self.stats_repo.emit(f"state_change_{entity_type}", entity_id, metadata)
        self.logger.debug(f"状态变更记录: {entity_type}:{entity_id}")
    
    def record_method_call(self, method_name: str, module_name: str, 
                          args: Dict[str, Any], result: Any = None, 
                          metadata: Optional[Dict] = None):
        if not self.enabled:
            return
            
        metadata = metadata or {}
        metadata.update({
            "method_name": method_name,
            "module_name": module_name,
            "args": self._sanitize_args(args),
            "result": str(result) if result is not None else None,
            "session_id": self.session_id,
            "caller_info": self._get_caller_info()
        })
        
        self.stats_repo.emit(f"method_call_{method_name}", "", metadata)
        self.logger.debug(f"方法调用记录: {module_name}.{method_name}")
    
    def record_database_operation(self, operation: str, table: str, 
                                 entity_id: str = "", metadata: Optional[Dict] = None):
        if not self.enabled:
            return
            
        metadata = metadata or {}
        metadata.update({
            "table": table,
            "session_id": self.session_id,
            "caller_info": self._get_caller_info()
        })
        
        self.stats_repo.emit(f"db_{operation}_{table}", entity_id, metadata)
        self.logger.debug(f"数据库操作记录: {operation} on {table}")
    
    def record_ai_service_call(self, function_name: str, input_data: Any, 
                              output_data: Any = None, metadata: Optional[Dict] = None):
        if not self.enabled:
            return
            
        metadata = metadata or {}
        metadata.update({
            "function_name": function_name,
            "input": str(input_data)[:500],  # 限制长度
            "output": str(output_data)[:500] if output_data is not None else None,
            "session_id": self.session_id,
            "caller_info": self._get_caller_info()
        })
        
        self.stats_repo.emit(f"ai_call_{function_name}", "", metadata)
        self.logger.debug(f"AI服务调用记录: {function_name}")
    
    def record_browser_event(self, event_type: str, shop_id: str = "", 
                            url: str = "", metadata: Optional[Dict] = None):
        if not self.enabled:
            return
            
        metadata = metadata or {}
        metadata.update({
            "shop_id": shop_id,
            "url": url,
            "session_id": self.session_id,
            "caller_info": self._get_caller_info()
        })
        
        self.stats_repo.emit(f"browser_{event_type}", shop_id, metadata)
        self.logger.debug(f"浏览器事件记录: {event_type} - {url}")
    
    def record_error(self, error_type: str, error_message: str, 
                    traceback: str = "", metadata: Optional[Dict] = None):
        if not self.enabled:
            return
            
        metadata = metadata or {}
        metadata.update({
            "error_message": error_message,
            "traceback": traceback[:1000],  # 限制长度
            "session_id": self.session_id,
            "caller_info": self._get_caller_info()
        })
        
        self.stats_repo.emit(f"error_{error_type}", "", metadata)
        self.logger.error(f"错误记录: {error_type} - {error_message}")
    
    def enable(self):
        self.enabled = True
        self.logger.info("监控服务已启用")
    
    def disable(self):
        self.enabled = False
        self.logger.info("监控服务已禁用")
    
    def export_events(self, event_type_filter: str = "", limit: int = 1000):
        conn = self.stats_repo.conn
        sql = "SELECT * FROM events WHERE 1=1"
        params = []
        
        if event_type_filter:
            sql += " AND event_type LIKE ?"
            params.append(f"%{event_type_filter}%")
        
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        rows = conn.execute(sql, tuple(params)).fetchall()
        events = []
        for row in rows:
            events.append({
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "entity_id": row["entity_id"],
                "created_at": row["created_at"],
                "metadata": json.loads(row["metadata_json"]) if row["metadata_json"] else {}
            })
        
        return events
    
    def export_to_json(self, filepath: str, event_type_filter: str = "", limit: int = 1000):
        events = self.export_events(event_type_filter, limit)
        data = {
            "export_time": datetime.datetime.utcnow().isoformat(),
            "session_id": self.session_id,
            "total_events": len(events),
            "events": events
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        self.logger.info(f"事件数据已导出到: {filepath} (共{len(events)}条记录)")
        return filepath
    
    def _get_caller_info(self):
        try:
            stack = inspect.stack()
            if len(stack) > 3:
                caller_frame = stack[3]
                return {
                    "filename": caller_frame.filename,
                    "function": caller_frame.function,
                    "line": caller_frame.lineno
                }
        except Exception:
            pass
        return {}
    
    def _sanitize_args(self, args: Dict[str, Any]) -> Dict[str, Any]:
        sanitized = {}
        for key, value in args.items():
            if key.lower().find('password') != -1 or key.lower().find('secret') != -1:
                sanitized[key] = "***REDACTED***"
            elif isinstance(value, (str, int, float, bool, type(None))):
                sanitized[key] = str(value)[:200]  # 限制长度
            else:
                sanitized[key] = str(type(value))
        return sanitized


def create_monitoring_decorator(monitoring_service: MonitoringService):
    def monitoring_decorator(event_type: str = "method_call"):
        def decorator(func):
            def wrapper(*args, **kwargs):
                if monitoring_service.enabled:
                    try:
                        # 记录方法调用开始
                        arg_names = func.__code__.co_varnames[:func.__code__.co_argcount]
                        arg_dict = dict(zip(arg_names, args))
                        arg_dict.update(kwargs)
                        
                        monitoring_service.record_method_call(
                            method_name=func.__name__,
                            module_name=func.__module__,
                            args=arg_dict,
                            metadata={"decorated": True}
                        )
                    except Exception as e:
                        monitoring_service.logger.error(f"监控装饰器错误: {e}")
                
                # 执行原函数
                result = func(*args, **kwargs)
                
                if monitoring_service.enabled and event_type == "method_call":
                    try:
                        monitoring_service.record_method_call(
                            method_name=func.__name__,
                            module_name=func.__module__,
                            args={},  # 不重复记录参数
                            result=str(result)[:200],
                            metadata={"decorated": True, "completed": True}
                        )
                    except Exception as e:
                        monitoring_service.logger.error(f"监控装饰器结果记录错误: {e}")
                
                return result
            return wrapper
        return decorator
    return monitoring_decorator