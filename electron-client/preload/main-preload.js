/**
 * Main Window Preload Script
 * Exposes safe APIs to the renderer process
 */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  // Store operations
  store: {
    get: (key) => ipcRenderer.invoke('store:get', key),
    set: (key, value) => ipcRenderer.invoke('store:set', key, value)
  },

  // Shop operations
  shops: {
    list: () => ipcRenderer.invoke('shops:list'),
    create: (data) => ipcRenderer.invoke('shops:create', data),
    update: (shopId, data) => ipcRenderer.invoke('shops:update', shopId, data),
    delete: (shopId) => ipcRenderer.invoke('shops:delete', shopId),
    start: (shopId) => ipcRenderer.invoke('shops:start', shopId),
    stop: (shopId) => ipcRenderer.invoke('shops:stop', shopId),
    pause: (shopId) => ipcRenderer.invoke('shops:pause', shopId),
    resume: (shopId) => ipcRenderer.invoke('shops:resume', shopId),
    logout: (platformId) => ipcRenderer.invoke('shops:logout', platformId),
    select: (shop) => ipcRenderer.invoke('shops:select', shop),
    hide: () => ipcRenderer.invoke('shops:hide')
  },

  // Platform operations
  platforms: {
    list: () => ipcRenderer.invoke('platforms:list'),
    open: (platformId) => ipcRenderer.invoke('platform:open', platformId),
    close: (platformId) => ipcRenderer.invoke('platform:close', platformId)
  },

  // Authentication
  auth: {
    login: (username, password) => ipcRenderer.invoke('auth:login', username, password),
    logout: () => ipcRenderer.invoke('auth:logout')
  },

  // AI operations
  ai: {
    generateReply: (data) => ipcRenderer.invoke('ai:generate-reply', data)
  },

  // Product operations
  products: {
    list: (shopId) => ipcRenderer.invoke('products:list', shopId),
    detail: (productId) => ipcRenderer.invoke('products:detail', productId),
    knowledge: (productId) => ipcRenderer.invoke('products:knowledge', productId),
    delete: (productId) => ipcRenderer.invoke('products:delete', productId)
  },

  // Knowledge operations
  knowledge: {
    list: (shopId) => ipcRenderer.invoke('knowledge:list', shopId),
    update: (id, data) => ipcRenderer.invoke('knowledge:update', id, data),
    delete: (id) => ipcRenderer.invoke('knowledge:delete', id),
    onSync: (callback) => {
      ipcRenderer.on('knowledge:sync', (event, data) => callback(data));
    }
  },

  // Keyword rules
  keywordRules: {
    list: (shopId) => ipcRenderer.invoke('keyword-rules:list', shopId),
    create: (data) => ipcRenderer.invoke('keyword-rules:create', data),
    update: (ruleId, data) => ipcRenderer.invoke('keyword-rules:update', ruleId, data),
    delete: (ruleId) => ipcRenderer.invoke('keyword-rules:delete', ruleId)
  },

  // Sensitive word rules
  sensitiveWords: {
    list: (shopId) => ipcRenderer.invoke('sensitive-words:list', shopId),
    create: (data) => ipcRenderer.invoke('sensitive-words:create', data),
    update: (ruleId, data) => ipcRenderer.invoke('sensitive-words:update', ruleId, data),
    delete: (ruleId) => ipcRenderer.invoke('sensitive-words:delete', ruleId)
  },

  // Scenario rules
  scenarioRules: {
    list: (shopId) => ipcRenderer.invoke('scenario-rules:list', shopId),
    create: (data) => ipcRenderer.invoke('scenario-rules:create', data),
    update: (ruleId, data) => ipcRenderer.invoke('scenario-rules:update', ruleId, data),
    delete: (ruleId) => ipcRenderer.invoke('scenario-rules:delete', ruleId)
  },

  // API Settings (for configuring LLM providers and API keys)
  api: {
    getApiSettings: () => ipcRenderer.invoke('api:getSettings'),
    saveApiSettings: (data) => ipcRenderer.invoke('api:saveSettings', data)
  },

  // Message events
  messages: {
    onReceived: (callback) => {
      ipcRenderer.on('message:received', (event, data) => callback(data));
    },
    onReplied: (callback) => {
      ipcRenderer.on('message:replied', (event, data) => callback(data));
    },
    onError: (callback) => {
      ipcRenderer.on('message:error', (event, data) => callback(data));
    },
    onLogWarn: (callback) => {
      ipcRenderer.on('log:warn', (event, data) => callback(data));
    },
    onProcessLog: (callback) => {
      ipcRenderer.on('message:process-log', (event, data) => callback(data));
    },
    onLoginSuccess: (callback) => {
      ipcRenderer.on('shop:login-success', (event, data) => callback(data));
    }
  },

  // Settings
  settings: {
    getServerUrl: () => ipcRenderer.invoke('store:get', 'serverUrl'),
    setServerUrl: (url) => ipcRenderer.invoke('store:set', 'serverUrl', url),
    getAutoReply: () => ipcRenderer.invoke('store:get', 'autoReply'),
    setAutoReply: (enabled) => ipcRenderer.invoke('store:set', 'autoReply', enabled)
  },

  // WeChat native adapter operations
  wechat: {
    status: () => ipcRenderer.invoke('wechat:status'),
    connect: () => ipcRenderer.invoke('wechat:connect'),
    disconnect: () => ipcRenderer.invoke('wechat:disconnect'),
    getChats: () => ipcRenderer.invoke('wechat:chats'),
    send: (message, contact) => ipcRenderer.invoke('wechat:send', { message, contact })
  },

  // Learning operations
  learning: {
    start: (platformId, shopId) => ipcRenderer.invoke('learning:start', platformId, shopId),
    extract: (platformId) => ipcRenderer.invoke('learning:extract', platformId),
    stop: (platformId) => ipcRenderer.invoke('learning:stop', platformId),
    status: (taskId) => ipcRenderer.invoke('learning:status', taskId),
    close: (platformId) => ipcRenderer.invoke('learning:close', platformId),
    
    // AI Vision learning
    startVisionAgent: (platformId, shopId) => ipcRenderer.invoke('learning:start-vision-agent', platformId, shopId),
    stopVisionAgent: () => ipcRenderer.invoke('learning:stop-vision-agent'),
    
    // Learning events
    onReady: (callback) => {
      ipcRenderer.on('learning:ready', (event, data) => callback(data));
    },
    onStarted: (callback) => {
      ipcRenderer.on('learning:started', (event, data) => callback(data));
    },
    onProgress: (callback) => {
      ipcRenderer.on('learning:progress', (event, data) => callback(data));
    },
    onProductProcessed: (callback) => {
      ipcRenderer.on('learning:product-processed', (event, data) => callback(data));
    },
    onCompleted: (callback) => {
      ipcRenderer.on('learning:completed', (event, data) => callback(data));
    },
    onError: (callback) => {
      ipcRenderer.on('learning:error', (event, data) => callback(data));
    },
    onLog: (callback) => {
      ipcRenderer.on('learning:log', (event, data) => callback(data));
    },
    onTaskCreated: (callback) => {
      ipcRenderer.on('learning:task-created', (event, data) => callback(data));
    },
    
    // AI Vision learning events
    onVisionStarted: (callback) => {
      ipcRenderer.on('learning:vision-started', (event, data) => callback(data));
    },
    onVisionProgress: (callback) => {
      ipcRenderer.on('learning:vision-progress', (event, data) => callback(data));
    },
    onVisionCompleted: (callback) => {
      ipcRenderer.on('learning:vision-completed', (event, data) => callback(data));
    },
    onVisionError: (callback) => {
      ipcRenderer.on('learning:vision-error', (event, data) => callback(data));
    }
  },

  // Auto-updater operations
  updater: {
    checkUpdate: () => ipcRenderer.invoke('update:check'),
    downloadUpdate: () => ipcRenderer.invoke('update:download'),
    installUpdate: () => ipcRenderer.invoke('update:install'),
    getVersion: () => ipcRenderer.invoke('update:get-version'),
    onUpdateAvailable: (callback) => {
      ipcRenderer.on('update:available', (event, data) => callback(data));
    },
    onUpdateNotAvailable: (callback) => {
      ipcRenderer.on('update:not-available', (event, data) => callback(data));
    },
    onDownloadProgress: (callback) => {
      ipcRenderer.on('update:progress', (event, data) => callback(data));
    },
    onUpdateDownloaded: (callback) => {
      ipcRenderer.on('update:downloaded', (event, data) => callback(data));
    },
    onUpdateError: (callback) => {
      ipcRenderer.on('update:error', (event, data) => callback(data));
    }
  }
});
