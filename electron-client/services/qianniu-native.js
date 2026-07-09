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
  'D:\\千牛\\AliWorkbench.exe',
  'D:\\千牛\\new\\new_AliWorkbench.exe',
  'D:\\AliWorkbench\\AliWorkbench.exe',
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
    this._loginTraceId = `qn-client-${Date.now().toString(36)}`;
    this._initInFlight = null;
    this._uiLogCallback = null;
    this._preferredEmbedHwnd = null;
  }

  setUiLogCallback(callback) {
    this._uiLogCallback = typeof callback === 'function' ? callback : null;
  }

  _getLoginLogPath() {
    const appData = process.env.APPDATA || '';
    if (appData) {
      return path.join(appData, 'ecommerce-cs-client', 'logs', 'qianniu-login-flow.ndjson');
    }
    return path.join(process.cwd(), '.dbg', 'qianniu-login-flow.ndjson');
  }

  _loginFlowLog(step, message, data = {}, level = 'info') {
    const entry = {
      ts: new Date().toISOString(),
      level,
      step: `client.${step}`,
      message,
      traceId: this._loginTraceId,
      data,
    };
    const line = `${JSON.stringify(entry)}\n`;
    try {
      const logPath = this._getLoginLogPath();
      fs.mkdirSync(path.dirname(logPath), { recursive: true });
      fs.appendFileSync(logPath, line, 'utf8');
    } catch (e) {
      console.warn('[QianNiuNative] 登录日志写入失败:', e.message);
    }
    console.log(`[QianNiuLogin][client.${step}] ${message}`);
    if (this._uiLogCallback) {
      this._uiLogCallback(`[千牛登录] ${message}`);
    }
    this.request('POST', '/login-log', { step: `client.${step}`, message, data, level }).catch(() => {});
  }

  _sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  setQianNiuPath(qianniuPath) {
    if (qianniuPath && typeof qianniuPath === 'string' && fs.existsSync(qianniuPath)) {
      this.qianniuPath = qianniuPath;
      return { success: true };
    }
    this.qianniuPath = null;
    return { success: false };
  }

  _normalizeExecutablePath(rawPath) {
    if (!rawPath || typeof rawPath !== 'string') return null;
    let value = rawPath.replace(/\u0000/g, '').trim();
    if (!value) return null;
    value = value.replace(/^"+|"+$/g, '').trim();
    const exeMatch = value.match(/[A-Za-z]:\\[^"\r\n]*?\.exe/i);
    if (exeMatch && exeMatch[0]) {
      value = exeMatch[0].trim();
    }
    value = value.replace(/%([^%]+)%/g, (_, name) => process.env[name] || `%${name}%`);
    value = value.replace(/^"+|"+$/g, '').trim();
    if (fs.existsSync(value)) return value;
    return null;
  }

  _resolveDetectedPath(rawPath, source) {
    const resolved = this._normalizeExecutablePath(rawPath);
    if (!resolved) return null;
    this.qianniuPath = resolved;
    console.log(`[QianNiuNative] Found via ${source}: ${resolved}`);
    return resolved;
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
        const found = this._resolveDetectedPath(target, 'desktop shortcut');
        if (found) return found;
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
        const found = this._resolveDetectedPath(target, 'start menu');
        if (found) return found;
      }
    } catch (e) {
      console.log('[QianNiuNative] Method 3 (start menu):', e.message);
    }

    // Method 4: Search Windows App Paths registry
    try {
      const appPathBases = [
        'HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths',
        'HKLM\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\App Paths',
        'HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths',
      ];
      for (const regBase of appPathBases) {
        for (const exeName of exeNames) {
          try {
            const result = execSync(`reg query "${regBase}\\${exeName}" /ve`,
              { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'], timeout: 5000 });
            const pathMatch = result.match(/REG_SZ\s+(.+)/i);
            if (pathMatch) {
              const found = this._resolveDetectedPath(pathMatch[1], 'registry app paths');
              if (found) return found;
            }
          } catch (e) {}
        }
      }
    } catch (e) {
      console.log('[QianNiuNative] Method 4 (app paths):', e.message);
    }

    // Method 5: Search Windows Uninstall registry
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
              const found = this._resolveDetectedPath(iconMatch[1], 'registry display icon');
              if (found) return found;
            }
          } catch (e) {}
        }
      }
    } catch (e) {
      console.log('[QianNiuNative] Method 5 (registry):', e.message);
    }

    // Method 5B: PowerShell registry lookup for InstallLocation / DisplayIcon
    try {
      const psScript = `
$paths = @(
  'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall',
  'HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall',
  'HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall'
)
$results = @()
foreach ($base in $paths) {
  if (Test-Path $base) {
    Get-ChildItem $base -ErrorAction SilentlyContinue | ForEach-Object {
      $p = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
      if (($p.DisplayName -match '千牛|AliWorkbench|QianNiu|AliIM') -or ($p.InstallLocation -match '千牛|AliWorkbench|QianNiu|AliIM') -or ($p.DisplayIcon -match '千牛|AliWorkbench|QianNiu|AliIM')) {
        if ($p.InstallLocation) { Write-Output ('LOC=' + $p.InstallLocation) }
        if ($p.DisplayIcon) { Write-Output ('ICO=' + $p.DisplayIcon) }
      }
    }
  }
}`;
      const result = execSync(`powershell -Command "${psScript.replace(/\n/g, ' ')}"`,
        { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'], timeout: 10000 });
      const lines = result.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
      for (const line of lines) {
        if (line.startsWith('LOC=')) {
          const installDir = line.slice(4).trim();
          const found = this._findExeInDir(installDir, exeNames, 4) ||
            this._findMatchedExeInDir(installDir, /(AliWorkbench|QianNiu|千牛|AliIM|WangWang)/i, 4);
          if (found) {
            this.qianniuPath = found;
            return found;
          }
        }
        if (line.startsWith('ICO=')) {
          const found = this._resolveDetectedPath(line.slice(4), 'powershell registry display icon');
          if (found) return found;
        }
      }
    } catch (e) {
      console.log('[QianNiuNative] Method 5B (powershell registry):', e.message);
    }

    // Method 6: Scan common directories
    const searchDirs = [
      'C:\\Program Files', 'C:\\Program Files (x86)',
      process.env.LOCALAPPDATA || '', process.env.APPDATA || '',
      'D:\\Program Files', 'D:\\Program Files (x86)',
      'D:\\千牛', 'D:\\AliWorkbench',
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
            const fuzzyFound = this._findMatchedExeInDir(folderPath, /(AliWorkbench|QianNiu|千牛|AliIM|WangWang)/i, 3);
            if (fuzzyFound) {
              this.qianniuPath = fuzzyFound;
              return fuzzyFound;
            }
          }
        }
      } catch (e) {}
    }
    console.log('[QianNiuNative] Method 6 (directory scan): not found');

    // Method 7: Check if千牛 is currently running
    try {
      const result = execSync('tasklist /FO CSV /NH', 
        { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'], timeout: 5000 });
      const lines = result.split(/\r?\n/);
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
              if (pathMatch) {
                const found = this._resolveDetectedPath(pathMatch[1], 'running process');
                if (found) return found;
              }
            } catch (e) {}
          }
        }
      }
    } catch (e) {
      console.log('[QianNiuNative] Method 7 (process list):', e.message);
    }

    // Method 8: PowerShell broad search - find any exe with千牛 in name on C: and D:
    try {
      const result = execSync(
        'powershell -Command "Get-ChildItem -Path \'C:\\Program Files\',\'C:\\Program Files (x86)\',$env:LOCALAPPDATA,$env:APPDATA -Recurse -Filter \'*.exe\' -Depth 4 -ErrorAction SilentlyContinue | Where-Object { $_.Name -match \'千牛|AliWorkbench|QianNiu\' } | Select-Object -First 1 -ExpandProperty FullName"',
        { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'], timeout: 30000 });
      const found = this._resolveDetectedPath(result, 'powershell search');
      if (found) return found;
    } catch (e) {
      console.log('[QianNiuNative] Method 8 (PowerShell search):', e.message);
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

  _findMatchedExeInDir(dir, namePattern, maxDepth = 3, depth = 0) {
    if (depth > maxDepth || !dir) return null;
    try {
      if (!fs.existsSync(dir) || !fs.statSync(dir).isDirectory()) return null;

      const items = fs.readdirSync(dir);
      for (const item of items) {
        const fullPath = path.join(dir, item);
        let stat = null;
        try {
          stat = fs.statSync(fullPath);
        } catch (e) {
          continue;
        }
        if (stat.isFile() && /\.exe$/i.test(item) && namePattern.test(item)) {
          console.log(`[QianNiuNative] Found matched exe: ${fullPath}`);
          return fullPath;
        }
      }

      if (depth < maxDepth) {
        for (const item of items) {
          const subPath = path.join(dir, item);
          try {
            if (fs.statSync(subPath).isDirectory()) {
              const found = this._findMatchedExeInDir(subPath, namePattern, maxDepth, depth + 1);
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
        error: '未找到千牛安装路径。请确认千牛已安装，或手动启动后重试。',
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

      let qianniu;
      try {
        qianniu = spawn(qianniuPath, [], {
          cwd: path.dirname(qianniuPath),
          detached: true,
          stdio: 'ignore',
          windowsHide: false
        });
      } catch (e) {
        resolve({ success: false, error: `千牛启动失败: ${e.message}` });
        return;
      }

      qianniu.on('error', (e) => {
        resolve({ success: false, error: `千牛启动失败: ${e.message}` });
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
          resolve({ success: true, message: '千牛已启动' });
        } else if (attempts > 60) {
          clearInterval(checkInterval);
          resolve({ success: false, error: `千牛启动超时（已等待 ${attempts} 次），请手动启动后重试。路径: ${qianniuPath}` });
        }
      }, 300);
    });
  }

  /**
   * Check if adapter service is running
   */
  async isAdapterServiceRunning() {
    try {
      // 鍏堢敤 /ping 蹇€熸娴?
      const pingResult = await this.request('GET', '/ping');
      if (pingResult?.ok === true) return true;
      // 鍏滃簳鐢?/status
      const result = await this.request('GET', '/status');
      return result?.success === true || typeof result?.connected === 'boolean';
    } catch (e) {
      return false;
    }
  }

  getAdapterServiceEntry() {
    const exeCandidates = [
      path.join(process.resourcesPath || '', 'backend', 'qianniu_service.exe'),
      path.join(process.resourcesPath || '', 'backend', 'qianniu_service_fixed.exe'),
      path.join(process.cwd(), 'dist', 'qianniu_service.exe'),
      path.join(process.cwd(), 'dist', 'qianniu_service_fixed.exe'),
      path.join(__dirname, '..', '..', 'dist', 'qianniu_service.exe'),
      path.join(__dirname, '..', '..', 'dist', 'qianniu_service_fixed.exe'),
    ].filter(Boolean);

    for (const p of exeCandidates) {
      if (fs.existsSync(p)) {
        return { path: p, kind: 'exe' };
      }
    }

    const pyCandidates = [
      path.join(__dirname, '..', '..', 'backend', 'adapters', 'run_qianniu_service.py'),
      path.join(process.cwd(), 'backend', 'adapters', 'run_qianniu_service.py'),
      path.join(__dirname, '..', '..', '..', 'backend', 'adapters', 'run_qianniu_service.py'),
    ];

    for (const p of pyCandidates) {
      if (fs.existsSync(p)) {
        return { path: p, kind: 'python' };
      }
    }

    return null;
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

    const serviceEntry = this.getAdapterServiceEntry();
    if (!serviceEntry?.path) {
      return {
        success: false,
        error: '未找到千牛适配器服务文件。安装版请确认已包含 qianniu_service.exe，开发环境请确认 backend/adapters/run_qianniu_service.py 存在。',
      };
    }

    console.log(`[QianNiuNative] Starting adapter service: ${serviceEntry.path}`);
    this._loginFlowLog('service.spawn', '准备启动适配器服务', {
      path: serviceEntry.path,
      kind: serviceEntry.kind,
      exists: fs.existsSync(serviceEntry.path),
    });

    return new Promise((resolve) => {
      this._adapterLogs = [];
      const spawnCwd = path.dirname(serviceEntry.path);
      let settled = false;
      let checkInterval = null;
      const finish = (result) => {
        if (settled) return;
        settled = true;
        if (checkInterval) clearInterval(checkInterval);
        resolve(result);
      };

      // 中文路径下 cmd /c 会乱码导致"不是内部或外部命令"，exe 必须直接 spawn
      try {
        if (serviceEntry.kind === 'exe') {
          this.adapterProcess = spawn(serviceEntry.path, [], {
            cwd: spawnCwd,
            windowsHide: false,   // 开发阶段不隐藏，可看到控制台错误
            stdio: ['ignore', 'pipe', 'pipe'],
          });
        } else {
          this.adapterProcess = spawn('python', [serviceEntry.path], {
            cwd: spawnCwd,
            windowsHide: true,
            stdio: ['ignore', 'pipe', 'pipe'],
          });
        }
      } catch (e) {
        this._loginFlowLog('service.spawn_fail', 'spawn 调用失败', { error: e.message }, 'error');
        finish({ success: false, error: `无法启动适配器服务: ${e.message}` });
        return;
      }

      const pushLog = (chunk, isErr) => {
        let text = '';
        try {
          const iconv = require('iconv-lite');
          text = iconv.decode(Buffer.from(chunk), 'gbk').trim();
        } catch (_) {
          text = (chunk || '').toString('utf8').trim();
        }
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
      this.adapterProcess.on('error', (e) => {
        this._loginFlowLog('service.process_error', '适配器进程触发 error 事件', { error: e.message }, 'error');
        const detail = this._adapterLogs.slice(-20).join('\n');
        finish({
          success: false,
          error: `适配器服务进程启动失败: ${e.message}${detail ? `\n\n${detail}` : ''}`,
        });
      });
      this.adapterProcess.on('exit', (code, signal) => {
        if (settled) return;
        if (code === 0 || signal) return;
        const detail = this._adapterLogs.slice(-20).join('\n');
        this._loginFlowLog('service.process_exit', '适配器进程异常退出', { code, signal }, 'error');
        finish({
          success: false,
          error: `适配器服务进程退出: code=${code}${detail ? `\n\n${detail}` : ''}`,
        });
      });

      let attempts = 0;
      checkInterval = setInterval(async () => {
        attempts++;
        const running = await this.isAdapterServiceRunning();

        if (running) {
          this._loginFlowLog('service.ready', '适配器服务已就绪', { attempts });
          finish({ success: true, message: '适配器服务已启动' });
        } else if (attempts > 60) {
          const detail = this._adapterLogs.slice(-30).join('\n');
          console.log('[QianNiuNative] 适配器启动日志:\n' + this._adapterLogs.join('\n'));
          this._loginFlowLog('service.timeout', '适配器服务启动超时', { attempts, detail: detail.slice(0, 500) }, 'error');
          finish({ success: false, error: `适配器服务启动超时${detail ? `\n\n${detail}` : ''}` });
        }
      }, 250);
    });
  }

  /**
   * Make HTTP request to QianNiu adapter API
   */
  async request(method, path, data = null, options = {}) {
    return new Promise((resolve, reject) => {
      const url = new URL(path, this.baseUrl);
      const defaultTimeout = path === '/login' ? 120000 : 15000;
      const timeout = options.timeout ?? defaultTimeout;
      
      const reqOptions = {
        hostname: url.hostname,
        port: url.port,
        path: url.pathname + url.search,
        method: method,
        headers: {
          'Content-Type': 'application/json'
        },
        timeout
      };

      const req = http.request(reqOptions, (res) => {
        let body = '';
        res.on('data', chunk => body += chunk);
        res.on('end', () => {
          try {
            const result = JSON.parse(body);
            resolve(result);
          } catch (e) {
            console.error(`[QianNiuNative] Invalid JSON from ${method} ${path}:`, body.substring(0, 500));
            resolve({ success: false, error: 'Invalid JSON response', raw: body.substring(0, 200) });
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
    // 鍏堣瘯 /ping锛堟渶杞婚噺锛夛紝澶辫触鍐嶈瘯 /status
    const pingResult = await this.request('GET', '/ping');
    if (pingResult?.ok === true) return true;
    console.log('[QianNiuNative] /ping failed:', JSON.stringify(pingResult).substring(0, 200));
    const statusResult = await this.request('GET', '/status');
    if (statusResult.success) return true;
    console.log('[QianNiuNative] /status also failed:', JSON.stringify(statusResult).substring(0, 200));
    return false;
  }

  /**
   * Connect to QianNiu PC client
   */
  async connect() {
    const result = await this.request('GET', '/connect', null, { timeout: 30000 });
    this.isConnected = result.success;
    if (!result.success && result.error) {
      result.error = result.error;
    }
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
   * Get visible order/logistics snapshot from QianNiu native window
   */
  async getOrderSnapshot() {
    return await this.request('GET', '/order-snapshot');
  }

  async approveAddressChange() {
    return await this.request('POST', '/approve-address-change');
  }

  async approveRefund() {
    return await this.request('POST', '/approve-refund');
  }

  async rejectRefund() {
    return await this.request('POST', '/reject-refund');
  }

  async approveReturnRefund() {
    return await this.request('POST', '/approve-return-refund');
  }

  async login(username, password) {
    this._loginFlowLog('login.request', 'Electron 发起登录请求', {
      username_length: (username || '').length,
      password_length: (password || '').length,
    });
    let lastLineCount = 0;
    const poll = setInterval(async () => {
      try {
        const logResult = await this.request('GET', '/login-log?max=40', null, { timeout: 8000 });
        const lines = logResult.lines || logResult.data?.lines || [];
        for (let i = lastLineCount; i < lines.length; i++) {
          try {
            const entry = JSON.parse(lines[i]);
            if (this._uiLogCallback && entry.message) {
              const prefix = entry.step ? `[${entry.step}] ` : '';
              this._uiLogCallback(`[千牛登录] ${prefix}${entry.message}`);
            }
          } catch (e) {
            // ignore malformed lines
          }
        }
        lastLineCount = lines.length;
      } catch (e) {
        // ignore poll errors
      }
    }, 1200);
    let result;
    try {
      result = await this.request('POST', '/login', { username, password }, { timeout: 150000 });
    } finally {
      clearInterval(poll);
    }
    const logPath = result.data?.log_path || result.log_path || this._getLoginLogPath();
    this._loginFlowLog('login.response', result.success ? '登录 API 返回成功' : '登录 API 返回失败', {
      success: result.success,
      detail: result.data?.detail || result.detail || '',
      log_path: logPath,
    }, result.success ? 'info' : 'error');
    if (logPath) {
      result.log_path = logPath;
      if (result.data) result.data.log_path = logPath;
    }
    const loginHwnd = Number(result?.hwnd || result?.data?.hwnd || 0) || 0;
    if (loginHwnd > 0) {
      this._preferredEmbedHwnd = String(loginHwnd);
    }
    return result;
  }

  async openChat() {
    const result = await this.request('POST', '/open-chat');
    const chatHwnd = Number(result?.hwnd || result?.data?.hwnd || 0) || 0;
    if (chatHwnd > 0) {
      this._preferredEmbedHwnd = String(chatHwnd);
    }
    return result;
  }

  /**
   * 将千牛窗口嵌入到 Electron 主窗口中
   * @param {number} hostHwnd - Electron 主窗口的 HWND
   */
  async attach(hostHwnd) {
    this._loginFlowLog('embed.attach', '请求嵌入千牛窗口', { hostHwnd });
    const result = await this.request('POST', '/attach', { host_hwnd: hostHwnd });
    if (result?.success) {
      this._preferredEmbedHwnd = null;
      this._loginFlowLog('embed.attach', '千牛窗口已嵌入', { qianniu_main_hwnd: result?.qianniu_main_hwnd, qianniu_cef_hwnd: result?.qianniu_cef_hwnd });
    } else {
      this._loginFlowLog('embed.attach', '嵌入失败', { error: result?.error || 'unknown' });
    }
    return result?.success || false;
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
  async initialize(options = {}) {
    if (this._initInFlight) {
      return await this._initInFlight;
    }
    this._initInFlight = this._initializeImpl(options);
    try {
      return await this._initInFlight;
    } finally {
      this._initInFlight = null;
    }
  }

  async _initializeImpl(options = {}) {
    this._loginTraceId = `qn-client-${Date.now().toString(36)}`;
    const logPath = this._getLoginLogPath();
    console.log('[QianNiuNative] Starting initialization...');
    const username = `${options.username || ''}`.trim();
    const password = `${options.password || ''}`;
    const shopId = options.shopId || '';
    const shopName = options.shopName || '';
    const credentialSource = options.credentialSource || 'unknown';
    this._loginFlowLog('init.start', 'Electron 千牛初始化开始', {
      log_path: logPath,
      shop_id: shopId,
      shop_name: shopName,
      credential_source: credentialSource,
      account_preview: username ? `${username.slice(0, 6)}...` : '',
      has_username: !!username,
      has_password: !!password,
    });

    if (!username || !password) {
      const missingMsg = shopName
        ? `店铺“${shopName}”未配置登录凭据，请在店铺管理中填写登录账号和密码`
        : '未配置登录凭据，请在店铺管理中填写登录账号和密码';
      this._loginFlowLog('init.credentials_missing', missingMsg, {}, 'error');
      return {
        success: false,
        error: missingMsg,
        step: 'shop_credentials',
        log_path: logPath,
      };
    }

    const qianniuRunning = await this.isQianNiuRunning();
    this._loginFlowLog('init.launch_check', '检查千牛是否运行', { running: qianniuRunning });
    if (!qianniuRunning) {
      console.log('[QianNiuNative] QianNiu not running, attempting to launch...');
      const launchResult = await this.launchQianNiu();
      this._loginFlowLog('init.launch', '尝试启动千牛', {
        success: launchResult.success,
        error: launchResult.error || '',
      }, launchResult.success ? 'info' : 'error');
      if (!launchResult.success) {
        return {
          success: false,
          error: launchResult.error || '无法启动千牛客户端',
          step: 'launch_qianniu',
          log_path: logPath,
        };
      }
      await this._sleep(250);
    }

    const serviceRunning = await this.isAdapterServiceRunning();
    this._loginFlowLog('init.service_check', '检查适配器服务', { running: serviceRunning });
    if (!serviceRunning) {
      console.log('[QianNiuNative] Adapter service not running, attempting to start...');
      const serviceResult = await this.startAdapterService();
      this._loginFlowLog('init.service_start', '尝试启动适配器服务', {
        success: serviceResult.success,
        error: serviceResult.error || '',
      }, serviceResult.success ? 'info' : 'error');
      if (!serviceResult.success) {
        return {
          success: false,
          error: serviceResult.error || '适配器服务启动失败。请手动运行: python backend/adapters/run_qianniu_service.py',
          step: 'start_adapter',
          log_path: logPath,
        };
      }
      await this._sleep(120);
    }

    const connectResult = await this.connect();
    this._loginFlowLog('init.connect', '连接千牛窗口', {
      success: connectResult.success,
      error: connectResult.error || '',
    }, connectResult.success ? 'info' : 'error');
    if (!connectResult.success) {
      return {
        success: false,
        error: connectResult.error || '无法连接到千牛窗口。请确认已开启页面讲述人模式和气泡模式，并最大化窗口。',
        step: 'connect',
        log_path: logPath,
      };
    }

    if (username && password) {
      this._loginFlowLog('init.login_start', '使用店铺管理中的账号密码登录千牛', {
        shop_id: shopId,
        shop_name: shopName,
        credential_source: credentialSource,
        account: username,
        account_length: username.length,
      });
      const loginResult = await this.login(username, password);
      if (!loginResult.success) {
        const detail = loginResult.data?.detail || loginResult.detail || '';
        const resolvedLogPath = loginResult.log_path || loginResult.data?.log_path || logPath;
        this._loginFlowLog('init.login_fail', '初始化登录失败', { detail }, 'error');
        return {
          success: false,
          error: `千牛登录失败，请检查账号密码或当前登录页状态${detail ? `，${detail}` : ''}`,
          step: 'login',
          log_path: resolvedLogPath,
        };
      }
    } else {
      this._loginFlowLog('init.login_skip', '未提供账号密码，跳过登录');
    }

    const chatResult = await this.openChat();
    this._loginFlowLog('init.open_chat', '打开聊天工作台', {
      success: chatResult.success,
      hwnd: Number(chatResult?.hwnd || chatResult?.data?.hwnd || 0) || 0,
    }, chatResult.success ? 'info' : 'error');
    if (!chatResult.success) {
      return {
        success: false,
        error: '千牛登录成功后未能打开聊天对话框',
        step: 'open_chat',
        log_path: logPath,
      };
    }

    await this.startServerMonitoring();
    this.startPolling();
    this._loginFlowLog('init.success', '千牛初始化完成');
    console.log('[QianNiuNative] Initialization complete!');
    return {
      success: true,
      message: '已连接到千牛 PC 客户端',
      log_path: logPath,
      hwnd: Number(chatResult?.hwnd || chatResult?.data?.hwnd || this._preferredEmbedHwnd || 0) || 0,
    };
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
      connectionStatus = status?.data || (status?.success ? status : null);
    }

    return {
      qianniuInstalled: !!qianniuPath,
      qianniuPath: qianniuPath,
      qianniuRunning: qianniuRunning,
      adapterServiceRunning: serviceRunning,
      connected: connectionStatus?.connected || false,
      currentChat: connectionStatus?.current_chat || connectionStatus?.currentChat || null
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
