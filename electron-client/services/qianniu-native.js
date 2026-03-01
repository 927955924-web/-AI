/**
 * QianNiu (千牛) Native Adapter
 * Communicates with the Python QianNiu adapter API service
 * Uses Windows UI Automation to control the local QianNiu PC client
 */
const http = require('http');
const { spawn, exec } = require('child_process');
const path = require('path');
const fs = require('fs');

const QIANNIU_API_URL = 'http://127.0.0.1:8766';

// 千牛可能的安装路径
const QIANNIU_PATHS = [
  // AliWorkbench 路径
  'C:\\Program Files\\AliWorkbench\\AliWorkbench.exe',
  'C:\\Program Files (x86)\\AliWorkbench\\AliWorkbench.exe',
  'C:\\AliWorkbench\\AliWorkbench.exe',
  path.join(process.env.LOCALAPPDATA || '', 'AliWorkbench', 'AliWorkbench.exe'),
  path.join(process.env.APPDATA || '', 'AliWorkbench', 'AliWorkbench.exe'),
  // 千牛工作台 路径
  'C:\\Program Files\\千牛工作台\\千牛工作台.exe',
  'C:\\Program Files (x86)\\千牛工作台\\千牛工作台.exe',
  path.join(process.env.LOCALAPPDATA || '', '千牛工作台', '千牛工作台.exe'),
  path.join(process.env.APPDATA || '', '千牛工作台', '千牛工作台.exe'),
  // 千牛 路径
  'C:\\Program Files\\千牛\\QianNiu.exe',
  'C:\\Program Files (x86)\\千牛\\QianNiu.exe',
  'C:\\Program Files\\千牛\\千牛.exe',
  'C:\\Program Files (x86)\\千牛\\千牛.exe',
  path.join(process.env.LOCALAPPDATA || '', '千牛', 'QianNiu.exe'),
  path.join(process.env.LOCALAPPDATA || '', '千牛', '千牛.exe'),
  // 淘宝千牛 路径
  'C:\\Program Files\\淘宝\\千牛工作台\\千牛工作台.exe',
  'C:\\Program Files (x86)\\淘宝\\千牛工作台\\千牛工作台.exe',
  path.join(process.env.LOCALAPPDATA || '', 'Alibaba', 'AliWorkbench', 'AliWorkbench.exe'),
  path.join(process.env.LOCALAPPDATA || '', 'Taobao', 'QianNiu', 'QianNiu.exe'),
];

class QianNiuNativeAdapter {
  constructor() {
    this.baseUrl = QIANNIU_API_URL;
    this.isConnected = false;
    this.isMonitoring = false;
    this.pollInterval = null;
    this._pollInFlight = false;
    this.onMessageCallback = null;
    this.processedHashes = new Set();
    this.adapterProcess = null;
    this._adapterLogs = [];
    this.qianniuPath = null;
  }

  /**
   * Find QianNiu installation path
   */
  findQianNiuPath() {
    if (this.qianniuPath && fs.existsSync(this.qianniuPath)) {
      return this.qianniuPath;
    }

    const { execSync } = require('child_process');
    const exeNames = ['千牛工作台.exe', 'AliWorkbench.exe', 'QianNiu.exe', '千牛.exe', 'AliIM.exe', 'WangWang.exe'];

    // Method 1: Check predefined paths
    for (const p of QIANNIU_PATHS) {
      if (fs.existsSync(p)) {
        console.log(`[QianNiuNative] Found QianNiu at predefined path: ${p}`);
        this.qianniuPath = p;
        return p;
      }
    }
    console.log('[QianNiuNative] Method 1 (predefined paths): not found');

    // Method 2: PowerShell - resolve ALL desktop shortcuts and find千牛
    try {
      const psScript = `
$shell = New-Object -ComObject WScript.Shell
$desktops = @("$env:PUBLIC\\Desktop", "$env:USERPROFILE\\Desktop")
foreach ($desktop in $desktops) {
  if (Test-Path $desktop) {
    Get-ChildItem -Path $desktop -Filter '*.lnk' -ErrorAction SilentlyContinue | ForEach-Object {
      $shortcut = $shell.CreateShortcut($_.FullName)
      $name = $_.BaseName
      $target = $shortcut.TargetPath
      if ($name -match '千牛|qianniu|aliworkbench' -or $target -match '千牛|qianniu|aliworkbench|AliIM') {
        Write-Output $target
      }
    }
  }
}`;
      const result = execSync(`powershell -Command "${psScript.replace(/\n/g, ' ')}"`,
        { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'], timeout: 10000 });
      const targets = result.trim().split('\n').filter(t => t.trim());
      for (const target of targets) {
        const t = target.trim();
        if (t && fs.existsSync(t)) {
          this.qianniuPath = t;
          console.log(`[QianNiuNative] Found via desktop shortcut: ${t}`);
          return t;
        }
      }
    } catch (e) {
      console.log('[QianNiuNative] Method 2 (desktop shortcuts):', e.message);
    }

    // Method 3: PowerShell - search Start Menu shortcuts
    try {
      const psScript = `
$shell = New-Object -ComObject WScript.Shell
$menus = @("$env:APPDATA\\Microsoft\\Windows\\Start Menu", "$env:PROGRAMDATA\\Microsoft\\Windows\\Start Menu")
foreach ($menu in $menus) {
  if (Test-Path $menu) {
    Get-ChildItem -Path $menu -Filter '*.lnk' -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
      $name = $_.BaseName
      if ($name -match '千牛|qianniu|aliworkbench') {
        $shortcut = $shell.CreateShortcut($_.FullName)
        Write-Output $shortcut.TargetPath
      }
    }
  }
}`;
      const result = execSync(`powershell -Command "${psScript.replace(/\n/g, ' ')}"`,
        { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'], timeout: 10000 });
      const targets = result.trim().split('\n').filter(t => t.trim());
      for (const target of targets) {
        const t = target.trim();
        if (t && fs.existsSync(t)) {
          this.qianniuPath = t;
          console.log(`[QianNiuNative] Found via Start Menu: ${t}`);
          return t;
        }
      }
    } catch (e) {
      console.log('[QianNiuNative] Method 3 (start menu):', e.message);
    }

    // Method 4: Search Windows Uninstall registry
    try {
      const uninstallPaths = [
        'HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall',
        'HKLM\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall',
        'HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall',
      ];
      
      for (const keyword of ['千牛', 'AliWorkbench', 'QianNiu', 'AliIM']) {
        for (const regBase of uninstallPaths) {
          try {
            const result = execSync(`reg query "${regBase}" /s /f "${keyword}" /d`,
              { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'], timeout: 10000 });
            
            const locationMatch = result.match(/InstallLocation\s+REG_SZ\s+(.+)/i);
            if (locationMatch) {
              const installDir = locationMatch[1].trim();
              const found = this._findExeInDir(installDir, exeNames, 2);
              if (found) {
                this.qianniuPath = found;
                return found;
              }
            }
            
            const iconMatch = result.match(/DisplayIcon\s+REG_SZ\s+(.+\.exe)/i);
            if (iconMatch) {
              const iconPath = iconMatch[1].trim().replace(/"/g, '').split(',')[0];
              if (fs.existsSync(iconPath)) {
                this.qianniuPath = iconPath;
                console.log(`[QianNiuNative] Found via registry DisplayIcon: ${iconPath}`);
                return iconPath;
              }
            }
          } catch (e) {}
        }
      }
    } catch (e) {
      console.log('[QianNiuNative] Method 4 (registry):', e.message);
    }

    // Method 5: Scan common directories
    const searchDirs = [
      'C:\\Program Files', 'C:\\Program Files (x86)',
      process.env.LOCALAPPDATA || '', process.env.APPDATA || '',
      'D:\\Program Files', 'D:\\Program Files (x86)',
    ];
    
    for (const dir of searchDirs) {
      if (!dir || !fs.existsSync(dir)) continue;
      try {
        const items = fs.readdirSync(dir);
        for (const item of items) {
          if (/千牛|qianniu|aliworkbench|taobao|alibaba|aliim|wangwang/i.test(item)) {
            const folderPath = path.join(dir, item);
            const found = this._findExeInDir(folderPath, exeNames, 2);
            if (found) {
              this.qianniuPath = found;
              return found;
            }
          }
        }
      } catch (e) {}
    }
    console.log('[QianNiuNative] Method 5 (directory scan): not found');

    // Method 6: Check if千牛 is currently running
    try {
      const result = execSync('tasklist /FO CSV /NH', 
        { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'], timeout: 5000 });
      const lines = result.split('\n');
      for (const line of lines) {
        if (/千牛|aliworkbench|qianniu|aliim/i.test(line)) {
          console.log(`[QianNiuNative] Found running process: ${line.trim()}`);
          // Extract process name
          const nameMatch = line.match(/"([^"]+\.exe)"/i);
          if (nameMatch) {
            // Use WMIC to get full path
            try {
              const wmicResult = execSync(`wmic process where "name='${nameMatch[1]}'" get ExecutablePath /format:list`,
                { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'], timeout: 5000 });
              const pathMatch = wmicResult.match(/ExecutablePath=(.+)/i);
              if (pathMatch && fs.existsSync(pathMatch[1].trim())) {
                this.qianniuPath = pathMatch[1].trim();
                console.log(`[QianNiuNative] Found via running process: ${this.qianniuPath}`);
                return this.qianniuPath;
              }
            } catch (e) {}
          }
        }
      }
    } catch (e) {
      console.log('[QianNiuNative] Method 6 (process list):', e.message);
    }

    // Method 7: PowerShell broad search - find any exe with千牛 in name on C: and D:
    try {
      const result = execSync(
        'powershell -Command "Get-ChildItem -Path \'C:\\Program Files\',\'C:\\Program Files (x86)\',$env:LOCALAPPDATA,$env:APPDATA -Recurse -Filter \'*.exe\' -Depth 4 -ErrorAction SilentlyContinue | Where-Object { $_.Name -match \'千牛|AliWorkbench|QianNiu\' } | Select-Object -First 1 -ExpandProperty FullName"',
        { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'], timeout: 30000 });
      const found = result.trim();
      if (found && fs.existsSync(found)) {
        this.qianniuPath = found;
        console.log(`[QianNiuNative] Found via PowerShell search: ${found}`);
        return found;
      }
    } catch (e) {
      console.log('[QianNiuNative] Method 7 (PowerShell search):', e.message);
    }

    console.log('[QianNiuNative] All detection methods failed. QianNiu not found.');
    return null;
  }

  /**
   * Search for exe files in a directory (with depth limit)
   */
  _findExeInDir(dir, exeNames, maxDepth, depth = 0) {
    if (depth > maxDepth || !dir) return null;
    try {
      if (!fs.existsSync(dir) || !fs.statSync(dir).isDirectory()) return null;
      
      // Check for exe files directly
      for (const exeName of exeNames) {
        const exePath = path.join(dir, exeName);
        if (fs.existsSync(exePath)) {
          console.log(`[QianNiuNative] Found exe: ${exePath}`);
          return exePath;
        }
      }
      
      // Search subdirectories
      if (depth < maxDepth) {
        const items = fs.readdirSync(dir);
        for (const item of items) {
          try {
            const subPath = path.join(dir, item);
            if (fs.statSync(subPath).isDirectory()) {
              const found = this._findExeInDir(subPath, exeNames, maxDepth, depth + 1);
              if (found) return found;
            }
          } catch (e) {}
        }
      }
    } catch (e) {}
    return null;
  }

  _searchFiles(dir, pattern, ext, maxDepth = 3, depth = 0) {
    const results = [];
    if (depth > maxDepth) return results;
    
    try {
      const items = fs.readdirSync(dir);
      for (const item of items) {
        const fullPath = path.join(dir, item);
        try {
          const stat = fs.statSync(fullPath);
          if (stat.isDirectory()) {
            results.push(...this._searchFiles(fullPath, pattern, ext, maxDepth, depth + 1));
          } else if (pattern.test(item) && item.endsWith(ext)) {
            results.push(fullPath);
          }
        } catch (e) {
          // Skip inaccessible items
        }
      }
    } catch (e) {
      // Skip inaccessible directories
    }
    
    return results;
  }

  /**
   * Check if QianNiu is running
   */
  async isQianNiuRunning() {
    return new Promise((resolve) => {
      const candidates = [
        'AliWorkbench.exe',
        'QianNiu.exe',
        '千牛工作台.exe',
        '千牛.exe',
        'AliIM.exe',
        'WangWang.exe',
      ];
      exec('tasklist /FO CSV /NH', { windowsHide: true }, (error, stdout) => {
        if (error) {
          resolve(false);
          return;
        }
        const out = (stdout || '').toLowerCase();
        resolve(candidates.some((name) => out.includes(name.toLowerCase())));
      });
    });
  }

  /**
   * Launch QianNiu client
   */
  async launchQianNiu() {
    const qianniuPath = this.findQianNiuPath();
    
    if (!qianniuPath) {
      return { 
        success: false, 
        error: '未找到千牛安装路径。请确保千牛已安装，或手动启动千牛后重试。'
      };
    }

    // Check if already running
    const isRunning = await this.isQianNiuRunning();
    if (isRunning) {
      console.log('[QianNiuNative] QianNiu is already running');
      return { success: true, message: '千牛已在运行' };
    }

    // Launch QianNiu
    return new Promise((resolve) => {
      console.log(`[QianNiuNative] Launching QianNiu: ${qianniuPath}`);
      
      const qianniu = spawn(qianniuPath, [], {
        detached: true,
        stdio: 'ignore',
        windowsHide: false
      });
      
      qianniu.unref();
      
      // Wait for QianNiu to start
      let attempts = 0;
      const checkInterval = setInterval(async () => {
        attempts++;
        const running = await this.isQianNiuRunning();
        
        if (running) {
          clearInterval(checkInterval);
          console.log('[QianNiuNative] QianNiu started successfully');
          // Wait a bit more for UI to initialize
          setTimeout(() => {
            resolve({ success: true, message: '千牛已启动' });
          }, 3000);
        } else if (attempts > 15) { // 15 seconds timeout
          clearInterval(checkInterval);
          resolve({ success: false, error: '千牛启动超时，请手动启动' });
        }
      }, 1000);
    });
  }

  /**
   * Check if adapter service is running
   */
  async isAdapterServiceRunning() {
    try {
      const result = await this.request('GET', '/status');
      return result.success;
    } catch (e) {
      return false;
    }
  }

  /**
   * Start the adapter service
   */
  async startAdapterService() {
    const serviceRunning = await this.isAdapterServiceRunning();
    if (serviceRunning) {
      console.log('[QianNiuNative] Adapter service already running');
      return { success: true, message: '适配器服务已在运行' };
    }

    // Find the adapter service script
    const possiblePaths = [
      path.join(__dirname, '..', '..', 'backend', 'adapters', 'run_qianniu_service.py'),
      path.join(process.cwd(), 'backend', 'adapters', 'run_qianniu_service.py'),
      path.join(__dirname, '..', '..', '..', 'backend', 'adapters', 'run_qianniu_service.py'),
    ];

    let servicePath = null;
    for (const p of possiblePaths) {
      if (fs.existsSync(p)) {
        servicePath = p;
        break;
      }
    }

    if (!servicePath) {
      return { 
        success: false, 
        error: '未找到适配器服务脚本。请手动启动: python backend/adapters/run_qianniu_service.py'
      };
    }

    console.log(`[QianNiuNative] Starting adapter service: ${servicePath}`);

    return new Promise((resolve) => {
      this._adapterLogs = [];
      this.adapterProcess = spawn('python', [servicePath], {
        windowsHide: true,
        stdio: ['ignore', 'pipe', 'pipe']
      });

      const pushLog = (chunk, isErr) => {
        const text = (chunk || '').toString('utf8').trim();
        if (!text) return;
        for (const line of text.split(/\r?\n/)) {
          this._adapterLogs.push(`${isErr ? 'ERR' : 'OUT'}: ${line}`);
        }
        if (this._adapterLogs.length > 200) {
          this._adapterLogs = this._adapterLogs.slice(-120);
        }
      };
      this.adapterProcess.stdout?.on('data', (c) => pushLog(c, false));
      this.adapterProcess.stderr?.on('data', (c) => pushLog(c, true));

      // Wait for service to start
      let attempts = 0;
      const checkInterval = setInterval(async () => {
        attempts++;
        const running = await this.isAdapterServiceRunning();
        
        if (running) {
          clearInterval(checkInterval);
          console.log('[QianNiuNative] Adapter service started');
          resolve({ success: true, message: '适配器服务已启动' });
        } else if (attempts > 10) { // 10 seconds timeout
          clearInterval(checkInterval);
          const detail = this._adapterLogs.slice(-30).join('\n');
          resolve({ success: false, error: `适配器服务启动超时${detail ? `\n\n${detail}` : ''}` });
        }
      }, 1000);
    });
  }

  /**
   * Make HTTP request to QianNiu adapter API
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
   * Check if QianNiu adapter service is running
   */
  async checkService() {
    const result = await this.request('GET', '/status');
    return result.success;
  }

  /**
   * Connect to QianNiu PC client
   */
  async connect() {
    const result = await this.request('GET', '/connect');
    this.isConnected = result.success;
    console.log(`[QianNiuNative] Connect result:`, result);
    return result;
  }

  /**
   * Get adapter status
   */
  async getStatus() {
    return await this.request('GET', '/status');
  }

  /**
   * Get chat list from QianNiu
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
   * Select a chat by buyer name
   */
  async selectChat(buyerName) {
    return await this.request('POST', '/select-chat', { name: buyerName });
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
   * Get current chat buyer name
   */
  async getCurrentChat() {
    return await this.request('GET', '/current-chat');
  }

  /**
   * Send a message to current chat
   */
  async sendMessage(message, buyer = null) {
    const data = { message };
    if (buyer) {
      data.buyer = buyer;
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
   * Bring QianNiu window to foreground
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
  startPolling(intervalMs = 2000) {
    if (this.pollInterval) return;

    this.isMonitoring = true;
    this.pollInterval = setInterval(async () => {
      if (!this.isMonitoring) return;
      if (this._pollInFlight) return;
      this._pollInFlight = true;

      try {
        // Check for pending messages from server
        const result = await this.getPendingMessages();
        
        if (result.success && result.data && result.data.length > 0) {
          for (const msg of result.data) {
            // Create unique hash for this message
            const msgHash = `${msg.buyer}_${msg.content}_${Math.floor(msg.timestamp)}`;
            
            if (!this.processedHashes.has(msgHash)) {
              this.processedHashes.add(msgHash);
              
              // Trigger callback
              if (this.onMessageCallback) {
                this.onMessageCallback({
                  platformId: 'qianniu',
                  customerId: `qianniu_${msg.buyer}`,
                  customerName: msg.sender || msg.buyer,
                  message: msg.content,
                  timestamp: msg.timestamp * 1000
                });
              }
              
              console.log(`[QianNiuNative] New message from ${msg.buyer}: ${msg.content.substring(0, 50)}`);
            }
          }
        }

        // Cleanup old hashes
        if (this.processedHashes.size > 500) {
          const arr = Array.from(this.processedHashes);
          this.processedHashes = new Set(arr.slice(-250));
        }

      } catch (e) {
        console.error('[QianNiuNative] Poll error:', e.message);
      } finally {
        this._pollInFlight = false;
      }
    }, intervalMs);

    console.log('[QianNiuNative] Started message polling');
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
    console.log('[QianNiuNative] Stopped message polling');
  }

  /**
   * Full initialization: auto-start QianNiu, adapter service, connect and start monitoring
   */
  async initialize() {
    console.log('[QianNiuNative] Starting initialization...');

    // Step 1: Check/Launch QianNiu client
    const qianniuRunning = await this.isQianNiuRunning();
    if (!qianniuRunning) {
      console.log('[QianNiuNative] QianNiu not running, attempting to launch...');
      const launchResult = await this.launchQianNiu();
      if (!launchResult.success) {
        return {
          success: false,
          error: launchResult.error || '无法启动千牛客户端',
          step: 'launch_qianniu'
        };
      }
      // Wait additional time for QianNiu UI to fully load
      await new Promise(resolve => setTimeout(resolve, 5000));
    }

    // Step 2: Check/Start adapter service
    const serviceRunning = await this.isAdapterServiceRunning();
    if (!serviceRunning) {
      console.log('[QianNiuNative] Adapter service not running, attempting to start...');
      const serviceResult = await this.startAdapterService();
      if (!serviceResult.success) {
        return {
          success: false,
          error: serviceResult.error || '适配器服务启动失败。请手动运行: python backend/adapters/run_qianniu_service.py',
          step: 'start_adapter'
        };
      }
      // Wait for service to be ready
      await new Promise(resolve => setTimeout(resolve, 2000));
    }

    // Step 3: Connect to QianNiu window
    const connectResult = await this.connect();
    if (!connectResult.success) {
      return {
        success: false,
        error: connectResult.error || '无法连接到千牛窗口。请确保已开启「页面讲述人模式」和「气泡模式」，并最大化窗口。',
        step: 'connect'
      };
    }

    // Step 4: Start server-side monitoring
    await this.startServerMonitoring();

    // Step 5: Start client-side polling
    this.startPolling();

    console.log('[QianNiuNative] Initialization complete!');
    return { success: true, message: '已连接到千牛PC客户端' };
  }

  /**
   * Cleanup: stop monitoring and disconnect
   */
  async cleanup() {
    this.stopPolling();
    await this.stopServerMonitoring();
    this.isConnected = false;
    console.log('[QianNiuNative] Cleaned up');
  }

  /**
   * Get installation and service status info
   */
  async getInstallationInfo() {
    const qianniuPath = this.findQianNiuPath();
    const qianniuRunning = await this.isQianNiuRunning();
    const serviceRunning = await this.isAdapterServiceRunning();
    
    let connectionStatus = null;
    if (serviceRunning) {
      const status = await this.getStatus();
      connectionStatus = status.success ? status.data : null;
    }

    return {
      qianniuInstalled: !!qianniuPath,
      qianniuPath: qianniuPath,
      qianniuRunning: qianniuRunning,
      adapterServiceRunning: serviceRunning,
      connected: connectionStatus?.connected || false,
      currentChat: connectionStatus?.current_chat || null
    };
  }
}

// Singleton instance
let qianniuNativeAdapter = null;

function getQianNiuNativeAdapter() {
  if (!qianniuNativeAdapter) {
    qianniuNativeAdapter = new QianNiuNativeAdapter();
  }
  return qianniuNativeAdapter;
}

module.exports = {
  QianNiuNativeAdapter,
  getQianNiuNativeAdapter
};
