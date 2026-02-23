"""
WeChat PC Client Adapter
Uses Windows UI Automation to control WeChat desktop application
"""
import time
import threading
import json
import hashlib
from typing import Optional, List, Dict, Callable
from dataclasses import dataclass, field
from datetime import datetime

try:
    import uiautomation as auto
    HAS_UIAUTOMATION = True
except ImportError:
    HAS_UIAUTOMATION = False
    print("[WeChatAdapter] uiautomation not installed. Run: pip install uiautomation")


@dataclass
class WeChatMessage:
    """Represents a WeChat message"""
    sender: str
    content: str
    timestamp: datetime
    is_self: bool = False
    msg_hash: str = ""
    
    def __post_init__(self):
        if not self.msg_hash:
            self.msg_hash = hashlib.md5(
                f"{self.sender}:{self.content}:{self.timestamp.isoformat()}".encode()
            ).hexdigest()[:16]


@dataclass  
class WeChatContact:
    """Represents a WeChat contact/chat"""
    name: str
    has_unread: bool = False
    unread_count: int = 0


class WeChatAdapter:
    """
    Adapter for WeChat PC client using Windows UI Automation
    
    WeChat PC window structure (typical):
    - Main Window (微信)
      - Navigation (left sidebar with contacts/chats)
      - Chat List (conversation list)
      - Chat Window (right side)
        - Chat Title (contact name)
        - Message List
        - Input Box
        - Send Button
    """
    
    def __init__(self):
        if not HAS_UIAUTOMATION:
            raise RuntimeError("uiautomation library not installed")
        
        self.wechat_window: Optional[auto.WindowControl] = None
        self.is_running = False
        self.monitor_thread: Optional[threading.Thread] = None
        self.processed_messages: set = set()
        self.on_message_callback: Optional[Callable] = None
        self.current_chat: Optional[str] = None
        self.poll_interval = 2.0  # seconds
        
    def find_wechat_window(self) -> bool:
        """Find and attach to WeChat main window"""
        try:
            # Try to find WeChat window by class name or title
            self.wechat_window = auto.WindowControl(
                searchDepth=1,
                ClassName='WeChatMainWndForPC'
            )
            
            if not self.wechat_window.Exists(maxSearchSeconds=3):
                # Try by window name
                self.wechat_window = auto.WindowControl(
                    searchDepth=1,
                    Name='微信'
                )
                
            if self.wechat_window.Exists(maxSearchSeconds=3):
                print(f"[WeChatAdapter] Found WeChat window: {self.wechat_window.Name}")
                return True
            else:
                print("[WeChatAdapter] WeChat window not found")
                return False
                
        except Exception as e:
            print(f"[WeChatAdapter] Error finding WeChat window: {e}")
            return False
    
    def activate_window(self) -> bool:
        """Bring WeChat window to foreground"""
        if not self.wechat_window or not self.wechat_window.Exists():
            return False
        try:
            self.wechat_window.SetActive()
            self.wechat_window.SetFocus()
            time.sleep(0.3)
            return True
        except Exception as e:
            print(f"[WeChatAdapter] Error activating window: {e}")
            return False
    
    def get_chat_list(self) -> List[WeChatContact]:
        """Get list of recent chats with unread indicators"""
        contacts = []
        if not self.wechat_window or not self.wechat_window.Exists():
            return contacts
            
        try:
            # Find chat list control - typically a ListControl
            chat_list = self.wechat_window.ListControl(
                searchDepth=10,
                Name='会话'
            )
            
            if not chat_list.Exists(maxSearchSeconds=2):
                # Try alternative search
                chat_list = self.wechat_window.ListControl(searchDepth=5)
            
            if chat_list.Exists():
                items = chat_list.GetChildren()
                for item in items:
                    name = item.Name
                    if name:
                        # Check for unread indicator (red dot/badge)
                        has_unread = False
                        unread_count = 0
                        
                        # Look for badge text
                        badge = item.TextControl(searchDepth=3)
                        if badge.Exists(maxSearchSeconds=0.1):
                            badge_text = badge.Name
                            if badge_text and badge_text.isdigit():
                                has_unread = True
                                unread_count = int(badge_text)
                        
                        contacts.append(WeChatContact(
                            name=name,
                            has_unread=has_unread,
                            unread_count=unread_count
                        ))
                        
        except Exception as e:
            print(f"[WeChatAdapter] Error getting chat list: {e}")
            
        return contacts
    
    def select_chat(self, contact_name: str) -> bool:
        """Select a chat by contact name"""
        if not self.wechat_window or not self.wechat_window.Exists():
            return False
            
        try:
            # Find and click on the contact in chat list
            chat_item = self.wechat_window.ListItemControl(
                searchDepth=10,
                Name=contact_name
            )
            
            if chat_item.Exists(maxSearchSeconds=2):
                chat_item.Click()
                self.current_chat = contact_name
                time.sleep(0.5)
                print(f"[WeChatAdapter] Selected chat: {contact_name}")
                return True
            else:
                print(f"[WeChatAdapter] Chat not found: {contact_name}")
                return False
                
        except Exception as e:
            print(f"[WeChatAdapter] Error selecting chat: {e}")
            return False
    
    def get_current_chat_name(self) -> Optional[str]:
        """Get the name of currently open chat"""
        if not self.wechat_window or not self.wechat_window.Exists():
            return None
            
        try:
            # Chat title is usually at the top of chat area
            # Try to find by common patterns
            title = self.wechat_window.TextControl(
                searchDepth=5,
                foundIndex=1  # Usually first text in chat area
            )
            
            if title.Exists(maxSearchSeconds=1):
                return title.Name
                
        except Exception as e:
            print(f"[WeChatAdapter] Error getting chat name: {e}")
            
        return self.current_chat
    
    def get_messages(self, max_count: int = 20) -> List[WeChatMessage]:
        """Get recent messages from current chat"""
        messages = []
        if not self.wechat_window or not self.wechat_window.Exists():
            return messages
            
        try:
            # Find message list - typically a ListControl with messages
            msg_list = self.wechat_window.ListControl(
                searchDepth=10,
                Name='消息'
            )
            
            if not msg_list.Exists(maxSearchSeconds=2):
                # Try to find by class or other attributes
                msg_list = self.wechat_window.ListControl(
                    searchDepth=8,
                    AutomationId='MsgList'
                )
            
            if msg_list.Exists():
                items = msg_list.GetChildren()
                
                # Process last N items
                for item in items[-max_count:]:
                    try:
                        # Each message item contains sender info and content
                        item_text = item.Name or ""
                        
                        # Try to extract structured message info
                        sender = "未知"
                        content = item_text
                        is_self = False
                        
                        # Check for self-message indicators
                        # WeChat typically shows "我" or positions differently
                        if "我:" in item_text or item_text.startswith("我 "):
                            is_self = True
                            sender = "我"
                            content = item_text.replace("我:", "").replace("我 ", "").strip()
                        else:
                            # Try to extract sender name
                            parts = item_text.split(":", 1)
                            if len(parts) == 2:
                                sender = parts[0].strip()
                                content = parts[1].strip()
                        
                        if content:
                            msg = WeChatMessage(
                                sender=sender,
                                content=content,
                                timestamp=datetime.now(),
                                is_self=is_self
                            )
                            messages.append(msg)
                            
                    except Exception as e:
                        continue
                        
        except Exception as e:
            print(f"[WeChatAdapter] Error getting messages: {e}")
            
        return messages
    
    def get_last_message(self) -> Optional[WeChatMessage]:
        """Get the last message in current chat"""
        messages = self.get_messages(max_count=5)
        
        # Find last non-self message
        for msg in reversed(messages):
            if not msg.is_self:
                return msg
                
        return None
    
    def send_message(self, text: str) -> bool:
        """Send a message in current chat"""
        if not self.wechat_window or not self.wechat_window.Exists():
            return False
            
        try:
            # Find input box
            input_box = self.wechat_window.EditControl(
                searchDepth=10,
                Name='输入'
            )
            
            if not input_box.Exists(maxSearchSeconds=2):
                # Try alternative search
                input_box = self.wechat_window.EditControl(searchDepth=8)
            
            if not input_box.Exists(maxSearchSeconds=2):
                print("[WeChatAdapter] Input box not found")
                return False
            
            # Click and focus input
            input_box.Click()
            time.sleep(0.2)
            
            # Clear existing text
            input_box.SendKeys('{Ctrl}a')
            time.sleep(0.1)
            
            # Type message using SendKeys (handles Chinese)
            # Use clipboard for better Chinese support
            self._set_clipboard(text)
            input_box.SendKeys('{Ctrl}v')
            time.sleep(0.3)
            
            # Find and click send button or press Enter
            send_btn = self.wechat_window.ButtonControl(
                searchDepth=10,
                Name='发送(S)'
            )
            
            if send_btn.Exists(maxSearchSeconds=1):
                send_btn.Click()
            else:
                # Press Enter to send
                input_box.SendKeys('{Enter}')
            
            print(f"[WeChatAdapter] Sent message: {text[:50]}...")
            return True
            
        except Exception as e:
            print(f"[WeChatAdapter] Error sending message: {e}")
            return False
    
    def _set_clipboard(self, text: str):
        """Set text to clipboard for pasting"""
        try:
            import win32clipboard
            import win32con
            
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
            win32clipboard.CloseClipboard()
        except Exception as e:
            print(f"[WeChatAdapter] Clipboard error: {e}")
            # Fallback: use auto's clipboard
            auto.SetClipboardText(text)
    
    def has_unread_messages(self) -> bool:
        """Check if there are any unread messages"""
        contacts = self.get_chat_list()
        return any(c.has_unread for c in contacts)
    
    def get_unread_chats(self) -> List[WeChatContact]:
        """Get list of chats with unread messages"""
        contacts = self.get_chat_list()
        return [c for c in contacts if c.has_unread]
    
    def set_message_callback(self, callback: Callable[[str, str, str], None]):
        """
        Set callback for new messages
        Callback signature: callback(contact_name, sender, message)
        """
        self.on_message_callback = callback
    
    def start_monitoring(self):
        """Start background monitoring for new messages"""
        if self.is_running:
            return
            
        if not self.find_wechat_window():
            print("[WeChatAdapter] Cannot start monitoring - WeChat not found")
            return
            
        self.is_running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        print("[WeChatAdapter] Started message monitoring")
    
    def stop_monitoring(self):
        """Stop background monitoring"""
        self.is_running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        print("[WeChatAdapter] Stopped message monitoring")
    
    def _monitor_loop(self):
        """Background loop to monitor for new messages"""
        while self.is_running:
            try:
                # Check for unread chats
                unread_chats = self.get_unread_chats()
                
                for chat in unread_chats:
                    # Select the chat
                    if self.select_chat(chat.name):
                        time.sleep(0.5)
                        
                        # Get last message
                        last_msg = self.get_last_message()
                        
                        if last_msg and last_msg.msg_hash not in self.processed_messages:
                            self.processed_messages.add(last_msg.msg_hash)
                            
                            # Trigger callback
                            if self.on_message_callback:
                                self.on_message_callback(
                                    chat.name,
                                    last_msg.sender,
                                    last_msg.content
                                )
                            
                            print(f"[WeChatAdapter] New message from {chat.name}: {last_msg.content[:50]}")
                
                # Cleanup old processed messages
                if len(self.processed_messages) > 1000:
                    self.processed_messages = set(list(self.processed_messages)[-500:])
                    
            except Exception as e:
                print(f"[WeChatAdapter] Monitor error: {e}")
                
            time.sleep(self.poll_interval)
    
    def get_status(self) -> Dict:
        """Get adapter status"""
        window_found = self.wechat_window and self.wechat_window.Exists()
        return {
            "connected": window_found,
            "monitoring": self.is_running,
            "current_chat": self.current_chat,
            "window_title": self.wechat_window.Name if window_found else None
        }


# Singleton instance
_adapter_instance: Optional[WeChatAdapter] = None


def get_wechat_adapter() -> WeChatAdapter:
    """Get singleton WeChat adapter instance"""
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = WeChatAdapter()
    return _adapter_instance


# Simple test
if __name__ == "__main__":
    print("Testing WeChat Adapter...")
    
    adapter = get_wechat_adapter()
    
    if adapter.find_wechat_window():
        print("WeChat window found!")
        
        # Get chat list
        chats = adapter.get_chat_list()
        print(f"Found {len(chats)} chats:")
        for chat in chats[:5]:
            print(f"  - {chat.name} (unread: {chat.has_unread})")
        
        # Get status
        status = adapter.get_status()
        print(f"Status: {status}")
    else:
        print("WeChat window not found. Please open WeChat.")
