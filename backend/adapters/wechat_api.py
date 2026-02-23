"""
WeChat Adapter HTTP API Service
Provides REST API for Electron client to interact with WeChat PC client
"""
import json
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Optional, Dict, Any

from .wechat_adapter import get_wechat_adapter, WeChatAdapter


class WeChatAPIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for WeChat adapter API"""
    
    adapter: WeChatAdapter = None
    message_queue: list = []
    message_callback: callable = None
    
    def log_message(self, format, *args):
        """Override to customize logging"""
        print(f"[WeChatAPI] {args[0]}")
    
    def _set_headers(self, status=200, content_type='application/json'):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def _send_json(self, data: Dict, status=200):
        self._set_headers(status)
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
    
    def do_OPTIONS(self):
        """Handle CORS preflight"""
        self._set_headers(200)
    
    def do_GET(self):
        """Handle GET requests"""
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        
        try:
            if path == '/status':
                # Get adapter status
                status = self.adapter.get_status() if self.adapter else {"connected": False}
                self._send_json({"success": True, "data": status})
                
            elif path == '/connect':
                # Connect to WeChat window
                if not self.adapter:
                    self.adapter = get_wechat_adapter()
                    WeChatAPIHandler.adapter = self.adapter
                    
                found = self.adapter.find_wechat_window()
                self._send_json({
                    "success": found,
                    "message": "Connected to WeChat" if found else "WeChat window not found"
                })
                
            elif path == '/chats':
                # Get chat list
                if not self.adapter:
                    self._send_json({"success": False, "error": "Not connected"}, 400)
                    return
                    
                chats = self.adapter.get_chat_list()
                self._send_json({
                    "success": True,
                    "data": [{"name": c.name, "hasUnread": c.has_unread, "unreadCount": c.unread_count} for c in chats]
                })
                
            elif path == '/unread':
                # Get unread chats
                if not self.adapter:
                    self._send_json({"success": False, "error": "Not connected"}, 400)
                    return
                    
                unread = self.adapter.get_unread_chats()
                self._send_json({
                    "success": True,
                    "data": [{"name": c.name, "unreadCount": c.unread_count} for c in unread]
                })
                
            elif path == '/messages':
                # Get messages from current chat
                if not self.adapter:
                    self._send_json({"success": False, "error": "Not connected"}, 400)
                    return
                    
                count = int(query.get('count', [20])[0])
                messages = self.adapter.get_messages(max_count=count)
                self._send_json({
                    "success": True,
                    "data": [{
                        "sender": m.sender,
                        "content": m.content,
                        "isSelf": m.is_self,
                        "hash": m.msg_hash
                    } for m in messages]
                })
                
            elif path == '/last-message':
                # Get last customer message
                if not self.adapter:
                    self._send_json({"success": False, "error": "Not connected"}, 400)
                    return
                    
                msg = self.adapter.get_last_message()
                if msg:
                    self._send_json({
                        "success": True,
                        "data": {
                            "sender": msg.sender,
                            "content": msg.content,
                            "isSelf": msg.is_self,
                            "hash": msg.msg_hash
                        }
                    })
                else:
                    self._send_json({"success": True, "data": None})
                    
            elif path == '/current-chat':
                # Get current chat name
                if not self.adapter:
                    self._send_json({"success": False, "error": "Not connected"}, 400)
                    return
                    
                name = self.adapter.get_current_chat_name()
                self._send_json({"success": True, "data": {"name": name}})
                
            elif path == '/pending-messages':
                # Get pending messages from queue
                messages = list(WeChatAPIHandler.message_queue)
                WeChatAPIHandler.message_queue.clear()
                self._send_json({"success": True, "data": messages})
                
            else:
                self._send_json({"success": False, "error": "Not found"}, 404)
                
        except Exception as e:
            self._send_json({"success": False, "error": str(e)}, 500)
    
    def do_POST(self):
        """Handle POST requests"""
        parsed = urlparse(self.path)
        path = parsed.path
        
        # Read request body
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else '{}'
        
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._send_json({"success": False, "error": "Invalid JSON"}, 400)
            return
        
        try:
            if path == '/select-chat':
                # Select a chat by name
                if not self.adapter:
                    self._send_json({"success": False, "error": "Not connected"}, 400)
                    return
                    
                contact_name = data.get('name')
                if not contact_name:
                    self._send_json({"success": False, "error": "Missing 'name' parameter"}, 400)
                    return
                    
                success = self.adapter.select_chat(contact_name)
                self._send_json({
                    "success": success,
                    "message": f"Selected chat: {contact_name}" if success else "Chat not found"
                })
                
            elif path == '/send':
                # Send a message
                if not self.adapter:
                    self._send_json({"success": False, "error": "Not connected"}, 400)
                    return
                    
                message = data.get('message')
                contact = data.get('contact')  # Optional: select chat first
                
                if not message:
                    self._send_json({"success": False, "error": "Missing 'message' parameter"}, 400)
                    return
                
                # Select chat if specified
                if contact:
                    if not self.adapter.select_chat(contact):
                        self._send_json({"success": False, "error": f"Chat not found: {contact}"}, 400)
                        return
                    time.sleep(0.3)
                
                success = self.adapter.send_message(message)
                self._send_json({
                    "success": success,
                    "message": "Message sent" if success else "Failed to send message"
                })
                
            elif path == '/start-monitor':
                # Start message monitoring
                if not self.adapter:
                    self.adapter = get_wechat_adapter()
                    WeChatAPIHandler.adapter = self.adapter
                
                # Set up callback to queue messages
                def on_message(contact, sender, content):
                    WeChatAPIHandler.message_queue.append({
                        "contact": contact,
                        "sender": sender,
                        "content": content,
                        "timestamp": time.time()
                    })
                    # Keep queue size limited
                    if len(WeChatAPIHandler.message_queue) > 100:
                        WeChatAPIHandler.message_queue = WeChatAPIHandler.message_queue[-50:]
                
                self.adapter.set_message_callback(on_message)
                self.adapter.start_monitoring()
                self._send_json({"success": True, "message": "Monitoring started"})
                
            elif path == '/stop-monitor':
                # Stop message monitoring
                if self.adapter:
                    self.adapter.stop_monitoring()
                self._send_json({"success": True, "message": "Monitoring stopped"})
                
            elif path == '/activate':
                # Bring WeChat window to foreground
                if not self.adapter:
                    self._send_json({"success": False, "error": "Not connected"}, 400)
                    return
                    
                success = self.adapter.activate_window()
                self._send_json({"success": success})
                
            else:
                self._send_json({"success": False, "error": "Not found"}, 404)
                
        except Exception as e:
            self._send_json({"success": False, "error": str(e)}, 500)


class WeChatAPIServer:
    """HTTP server for WeChat adapter API"""
    
    def __init__(self, host='127.0.0.1', port=8765):
        self.host = host
        self.port = port
        self.server: Optional[HTTPServer] = None
        self.thread: Optional[threading.Thread] = None
    
    def start(self):
        """Start the API server in background thread"""
        if self.server:
            return
            
        self.server = HTTPServer((self.host, self.port), WeChatAPIHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        print(f"[WeChatAPI] Server started at http://{self.host}:{self.port}")
    
    def stop(self):
        """Stop the API server"""
        if self.server:
            self.server.shutdown()
            self.server = None
            print("[WeChatAPI] Server stopped")


# Global server instance
_server_instance: Optional[WeChatAPIServer] = None


def start_wechat_api(host='127.0.0.1', port=8765):
    """Start the WeChat API server"""
    global _server_instance
    if _server_instance is None:
        _server_instance = WeChatAPIServer(host, port)
    _server_instance.start()
    return _server_instance


def stop_wechat_api():
    """Stop the WeChat API server"""
    global _server_instance
    if _server_instance:
        _server_instance.stop()
        _server_instance = None


# Run as standalone service
if __name__ == "__main__":
    print("Starting WeChat API Server...")
    server = start_wechat_api()
    
    try:
        print("Press Ctrl+C to stop")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_wechat_api()
        print("Server stopped")
