/**
 * WeChat Native Adapter
 * Communicates with the Python WeChat adapter API service
 */
const http = require('http');

const WECHAT_API_URL = 'http://127.0.0.1:8765';

class WeChatNativeAdapter {
  constructor() {
    this.baseUrl = WECHAT_API_URL;
    this.isConnected = false;
    this.isMonitoring = false;
    this.pollInterval = null;
    this.onMessageCallback = null;
    this.processedHashes = new Set();
  }

  /**
   * Make HTTP request to WeChat adapter API
   */
  async request(method, path, data = null) {
    return new Promise((resolve, reject) => {
      const url = new URL(path, this.baseUrl);
      
      const options = {
        hostname: url.hostname,
        port: url.port,
        path: url.pathname + url.search,
        method: method,
        headers: {
          'Content-Type': 'application/json'
        },
        timeout: 10000
      };

      const req = http.request(options, (res) => {
        let body = '';
        res.on('data', chunk => body += chunk);
        res.on('end', () => {
          try {
            const result = JSON.parse(body);
            resolve(result);
          } catch (e) {
            resolve({ success: false, error: 'Invalid JSON response' });
          }
        });
      });

      req.on('error', (e) => {
        resolve({ success: false, error: e.message });
      });

      req.on('timeout', () => {
        req.destroy();
        resolve({ success: false, error: 'Request timeout' });
      });

      if (data) {
        req.write(JSON.stringify(data));
      }
      req.end();
    });
  }

  /**
   * Check if WeChat adapter service is running
   */
  async checkService() {
    const result = await this.request('GET', '/status');
    return result.success;
  }

  /**
   * Connect to WeChat PC client
   */
  async connect() {
    const result = await this.request('GET', '/connect');
    this.isConnected = result.success;
    console.log(`[WeChatNative] Connect result:`, result);
    return result;
  }

  /**
   * Get adapter status
   */
  async getStatus() {
    return await this.request('GET', '/status');
  }

  /**
   * Get chat list
   */
  async getChats() {
    return await this.request('GET', '/chats');
  }

  /**
   * Get unread chats
   */
  async getUnreadChats() {
    return await this.request('GET', '/unread');
  }

  /**
   * Select a chat by contact name
   */
  async selectChat(contactName) {
    return await this.request('POST', '/select-chat', { name: contactName });
  }

  /**
   * Get messages from current chat
   */
  async getMessages(count = 20) {
    return await this.request('GET', `/messages?count=${count}`);
  }

  /**
   * Get last customer message
   */
  async getLastMessage() {
    return await this.request('GET', '/last-message');
  }

  /**
   * Get current chat name
   */
  async getCurrentChat() {
    return await this.request('GET', '/current-chat');
  }

  /**
   * Send a message
   */
  async sendMessage(message, contact = null) {
    const data = { message };
    if (contact) {
      data.contact = contact;
    }
    return await this.request('POST', '/send', data);
  }

  /**
   * Start server-side message monitoring
   */
  async startServerMonitoring() {
    return await this.request('POST', '/start-monitor');
  }

  /**
   * Stop server-side message monitoring
   */
  async stopServerMonitoring() {
    return await this.request('POST', '/stop-monitor');
  }

  /**
   * Get pending messages from server queue
   */
  async getPendingMessages() {
    return await this.request('GET', '/pending-messages');
  }

  /**
   * Bring WeChat window to foreground
   */
  async activateWindow() {
    return await this.request('POST', '/activate');
  }

  /**
   * Set callback for new messages
   */
  setMessageCallback(callback) {
    this.onMessageCallback = callback;
  }

  /**
   * Start polling for new messages
   */
  startPolling(intervalMs = 3000) {
    if (this.pollInterval) return;

    this.isMonitoring = true;
    this.pollInterval = setInterval(async () => {
      if (!this.isMonitoring) return;

      try {
        // Check for pending messages from server
        const result = await this.getPendingMessages();
        
        if (result.success && result.data && result.data.length > 0) {
          for (const msg of result.data) {
            // Create unique hash for this message
            const msgHash = `${msg.contact}_${msg.content}_${Math.floor(msg.timestamp)}`;
            
            if (!this.processedHashes.has(msgHash)) {
              this.processedHashes.add(msgHash);
              
              // Trigger callback
              if (this.onMessageCallback) {
                this.onMessageCallback({
                  platformId: 'wechat',
                  customerId: `wechat_${msg.contact}`,
                  customerName: msg.sender || msg.contact,
                  message: msg.content,
                  timestamp: msg.timestamp * 1000
                });
              }
              
              console.log(`[WeChatNative] New message from ${msg.contact}: ${msg.content.substring(0, 50)}`);
            }
          }
        }

        // Cleanup old hashes
        if (this.processedHashes.size > 500) {
          const arr = Array.from(this.processedHashes);
          this.processedHashes = new Set(arr.slice(-250));
        }

      } catch (e) {
        console.error('[WeChatNative] Poll error:', e.message);
      }
    }, intervalMs);

    console.log('[WeChatNative] Started message polling');
  }

  /**
   * Stop polling for new messages
   */
  stopPolling() {
    this.isMonitoring = false;
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
      this.pollInterval = null;
    }
    console.log('[WeChatNative] Stopped message polling');
  }

  /**
   * Full initialization: connect and start monitoring
   */
  async initialize() {
    // Check if service is running
    const serviceOk = await this.checkService();
    if (!serviceOk) {
      console.log('[WeChatNative] Adapter service not running');
      return { success: false, error: 'WeChat adapter service not running. Please start it first.' };
    }

    // Connect to WeChat window
    const connectResult = await this.connect();
    if (!connectResult.success) {
      return connectResult;
    }

    // Start server-side monitoring
    await this.startServerMonitoring();

    // Start client-side polling
    this.startPolling();

    return { success: true, message: 'Connected to WeChat PC client' };
  }

  /**
   * Cleanup: stop monitoring and disconnect
   */
  async cleanup() {
    this.stopPolling();
    await this.stopServerMonitoring();
    this.isConnected = false;
    console.log('[WeChatNative] Cleaned up');
  }
}

// Singleton instance
let wechatNativeAdapter = null;

function getWeChatNativeAdapter() {
  if (!wechatNativeAdapter) {
    wechatNativeAdapter = new WeChatNativeAdapter();
  }
  return wechatNativeAdapter;
}

module.exports = {
  WeChatNativeAdapter,
  getWeChatNativeAdapter
};
