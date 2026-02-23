"""
WeChat Adapter Service Startup Script
Run this to start the WeChat PC client adapter API server
"""
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters.wechat_api import start_wechat_api, stop_wechat_api


def main():
    print("=" * 50)
    print("  微信 PC 客户端适配器服务")
    print("=" * 50)
    print()
    print("使用前请确保:")
    print("1. 微信 PC 客户端已启动并登录")
    print("2. 已安装 uiautomation: pip install uiautomation")
    print("3. 已安装 pywin32: pip install pywin32")
    print()
    
    try:
        server = start_wechat_api(host='127.0.0.1', port=8765)
        print()
        print("API 端点:")
        print("  GET  /status         - 获取连接状态")
        print("  GET  /connect        - 连接到微信窗口")
        print("  GET  /chats          - 获取聊天列表")
        print("  GET  /unread         - 获取未读消息的聊天")
        print("  GET  /messages       - 获取当前聊天的消息")
        print("  GET  /last-message   - 获取最后一条消息")
        print("  POST /select-chat    - 选择聊天 {name: '联系人名'}")
        print("  POST /send           - 发送消息 {message: '内容', contact?: '联系人'}")
        print("  POST /start-monitor  - 开始监控新消息")
        print("  POST /stop-monitor   - 停止监控")
        print()
        print("按 Ctrl+C 停止服务")
        print()
        
        # Keep running
        import time
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n正在停止服务...")
        stop_wechat_api()
        print("服务已停止")
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
