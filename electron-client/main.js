/**
 * Electron Main Process
 * E-commerce Customer Service Automation Client
 */
const { app, BrowserWindow, BrowserView, ipcMain, session, Menu } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const { autoUpdater } = require('electron-updater');
const Store = require('./services/store');
const { ApiService } = require('./services/api');
const { getWeChatNativeAdapter } = require('./services/wechat-native');
const mqtt = require('mqtt');

// MQTT client for real-time knowledge sync
let mqttClient = null;
let currentMqttTopic = null;

// Backend process reference
let backendProcess = null;

// WeChat native adapter instance
let wechatAdapter = null;

// Initialize store
const store = new Store({
  defaults: {
    serverUrl: 'http://120.26.199.225:8080',
    useLocalBackend: false,  // Set to true to start local backend server
    autoReply: true,
    shops: [],
    tokens: null
  }
});

// Platform configurations
const PLATFORMS = {
  qianniu: {
    name: '千牛工作台',
    url: 'https://qn.taobao.com/',
    loginUrl: 'https://login.taobao.com/',
    preload: 'qianniu.js'
  },
  pinduoduo: {
    name: '拼多多商家',
    url: 'https://mms.pinduoduo.com/chat-merchant',
    loginUrl: 'https://mms.pinduoduo.com/chat-merchant',
    preload: 'pinduoduo.js'
  },
  douyin: {
    name: '抖音商家',
    url: 'https://fxg.jinritemai.com/',
    loginUrl: 'https://fxg.jinritemai.com/login',
    preload: 'douyin.js'
  },
  wechat: {
    name: '微信PC客户端',
    native: true,  // Uses native Windows UI Automation instead of BrowserView
    adapterUrl: 'http://127.0.0.1:8765'  // WeChat adapter API endpoint
  }
};

// Backend platform_type -> Electron platform key mapping
const PLATFORM_TYPE_MAP = {
  'taobao': 'qianniu',
  'pdd': 'pinduoduo',
  'douyin': 'douyin',
  'wechat': 'wechat'
};

function mapBackendPlatformToElectron(backendPlatform) {
  return PLATFORM_TYPE_MAP[backendPlatform] || null;
}

// Learning mode platform configurations (product management pages)
const LEARNING_PLATFORMS = {
  pinduoduo: {
    name: '拼多多商品管理',
    loginUrl: 'https://mms.pinduoduo.com/login/',
    goodsUrl: 'https://mms.pinduoduo.com/home',
    preload: 'learning-pinduoduo.js'
  },
  qianniu: {
    name: '淘宝商品管理',
    loginUrl: 'https://login.taobao.com/',
    goodsUrl: 'https://sell.taobao.com/auction/goods/goods_on_sale.htm',
    preload: 'learning-qianniu.js'
  },
  douyin: {
    name: '抖音商品管理',
    loginUrl: 'https://fxg.jinritemai.com/login/common',
    goodsUrl: 'https://fxg.jinritemai.com/ffa/g/list',
    preload: 'learning-douyin.js'
  }
};

// Global references
let mainWindow = null;
let platformViews = {};
let learningViews = {};  // Separate views for learning mode
let learningState = {};  // Track learning state per platform: { platformId: { isExtracting, pendingProducts, currentIndex, listPageUrl } }
let apiService = null;
let currentLearningTask = null;  // Track current learning task
let preLearningWindowState = null;  // Store window state before learning (for restore after)

// Track pending auto-login timers so they can be cancelled on logout/stop
let autoLoginTimers = {};  // platformId -> timeoutId

// Track customers currently being processed to prevent duplicate replies
const processingCustomers = new Set();

// Debug mode variables
let debugWindow = null;
let debugCountdownTimer = null;
let pendingDebugMessage = null;
let debugCountdownPaused = false;
let debugCountdownSeconds = 10; // Default countdown time

// Shop rotation variables
let shopRotationInterval = null;
let shopRefreshInterval = null;
let lastShopRefreshTime = {};  // Track last refresh time per shop
const SHOP_ROTATION_INTERVAL = 10000;  // Check every 10 seconds
const SHOP_REFRESH_INTERVAL = 30 * 60 * 1000;  // Refresh every 30 minutes

/**
 * Create the main application window
 */
function createMainWindow() {
  // Hide menu bar
  Menu.setApplicationMenu(null);

  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1200,
    minHeight: 700,
    title: '电商客服助手',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload', 'main-preload.js')
    }
  });

  // Load control panel
  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));

  // Open DevTools (detached window)
  mainWindow.webContents.openDevTools({ mode: 'detach' });
  
  // F12 to toggle DevTools
  mainWindow.webContents.on('before-input-event', (event, input) => {
    if (input.key === 'F12') {
      mainWindow.webContents.toggleDevTools();
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
    // Clean up all platform views
    Object.values(platformViews).forEach(view => {
      if (view && !view.webContents.isDestroyed()) {
        view.webContents.close();
      }
    });
    platformViews = {};
  });

  // Update BrowserView bounds on window resize
  mainWindow.on('resize', () => {
    const currentViews = mainWindow.getBrowserViews();
    if (currentViews.length > 0) {
      const contentBounds = mainWindow.getContentBounds();
      // Detect if the current view is a learning view; if so, use wider offset
      const isLearning = Object.values(learningViews).includes(currentViews[0]);
      const x = isLearning ? 440 : 200;
      currentViews[0].setBounds({
        x: x,
        y: 44,
        width: contentBounds.width - x - 180,
        height: contentBounds.height - 44
      });
    }
  });
}

/**
 * Create the debug training window
 */
function createDebugWindow() {
  if (debugWindow && !debugWindow.isDestroyed()) {
    debugWindow.focus();
    return debugWindow;
  }

  debugWindow = new BrowserWindow({
    width: 500,
    height: 700,
    minWidth: 400,
    minHeight: 500,
    title: '智语AI客服 - 调试训练窗口',
    alwaysOnTop: false,
    resizable: true,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload', 'debug-preload.js')
    }
  });

  debugWindow.loadFile(path.join(__dirname, 'renderer', 'debug-window.html'));

  debugWindow.on('closed', () => {
    debugWindow = null;
    clearDebugState();
  });

  return debugWindow;
}

/**
 * Start debug countdown timer
 */
function startDebugCountdown(seconds = 10) {
  debugCountdownSeconds = seconds;
  debugCountdownPaused = false;
  
  if (debugCountdownTimer) {
    clearInterval(debugCountdownTimer);
  }

  debugCountdownTimer = setInterval(() => {
    if (debugCountdownPaused) return;
    
    debugCountdownSeconds--;
    
    // Update countdown display in debug window
    if (debugWindow && !debugWindow.isDestroyed()) {
      debugWindow.webContents.send('debug:countdown-update', debugCountdownSeconds);
    }
    
    // Auto-send when countdown reaches 0
    if (debugCountdownSeconds <= 0) {
      clearInterval(debugCountdownTimer);
      debugCountdownTimer = null;
      autoSendDebugReply();
    }
  }, 1000);
}

/**
 * Auto-send the pending debug reply
 */
function autoSendDebugReply() {
  if (!pendingDebugMessage) return;
  
  const { sender, customerId, reply } = pendingDebugMessage;
  
  if (reply && sender) {
    sender.send('platform:send-reply', {
      customerId,
      reply,
      source: 'ai_auto'
    });
    
    // Notify main renderer
    if (mainWindow) {
      mainWindow.webContents.send('message:replied', {
        ...pendingDebugMessage.originalData,
        reply,
        source: 'ai_auto'
      });
    }
    
    console.log('[Debug] Auto-sent reply after countdown');
  }
  
  clearDebugState();
}

/**
 * Clear debug state
 */
function clearDebugState() {
  if (debugCountdownTimer) {
    clearInterval(debugCountdownTimer);
    debugCountdownTimer = null;
  }
  pendingDebugMessage = null;
  debugCountdownPaused = false;
  debugCountdownSeconds = 10;
}

/**
 * Create a BrowserView for a platform
 */
function createPlatformView(platformId) {
  const platform = PLATFORMS[platformId];
  if (!platform) return null;

  const view = new BrowserView({
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload', platform.preload),
      partition: `persist:${platformId}`
    }
  });

  // Load platform URL
  view.webContents.loadURL(platform.url);

  // Handle new window requests (for login popups)
  view.webContents.setWindowOpenHandler(({ url }) => {
    view.webContents.loadURL(url);
    return { action: 'deny' };
  });

  platformViews[platformId] = view;
  return view;
}

/**
 * Show a platform view in the main window
 */
function showPlatformView(platformId) {
  // Remove current view
  const currentViews = mainWindow.getBrowserViews();
  currentViews.forEach(v => mainWindow.removeBrowserView(v));

  // Get or create view
  let view = platformViews[platformId];
  if (!view) {
    view = createPlatformView(platformId);
  }

  if (view) {
    mainWindow.addBrowserView(view);
    // Set bounds: left shop panel (200px) + top navbar (44px) + right panel (180px)
    const contentBounds = mainWindow.getContentBounds();
    view.setBounds({
      x: 200,
      y: 44,
      width: contentBounds.width - 200 - 180,
      height: contentBounds.height - 44
    });
    view.setAutoResize({ width: false, height: false });
  }
}

/**
 * Hide all platform views
 */
function hidePlatformViews() {
  const currentViews = mainWindow.getBrowserViews();
  currentViews.forEach(v => mainWindow.removeBrowserView(v));
}

// ============ IPC Handlers ============

// Forward preload logs to main process console (for debugging)
ipcMain.on('platform:log', (event, data) => {
  const { level, message, platformId } = data;
  const prefix = platformId ? `[${platformId}]` : '[preload]';
  if (level === 'error') {
    console.error(prefix, message);
  } else if (level === 'warn') {
    console.warn(prefix, message);
  } else {
    console.log(prefix, message);
  }
});

// Send native Enter key to platform view (trusted event)
ipcMain.on('platform:send-enter', (event, platformId) => {
  const view = platformViews[platformId];
  if (view && !view.webContents.isDestroyed()) {
    view.webContents.sendInputEvent({ type: 'keyDown', keyCode: 'Return' });
    setTimeout(() => {
      view.webContents.sendInputEvent({ type: 'keyUp', keyCode: 'Return' });
    }, 50);
    console.log(`[${platformId}] Sent native Enter key`);
  }
});

// Send Shift+Tab to switch to next pending conversation (PDD feature)
ipcMain.on('platform:send-shift-tab', (event, platformId) => {
  const view = platformViews[platformId];
  if (view && !view.webContents.isDestroyed()) {
    // Press Shift+Tab
    view.webContents.sendInputEvent({ 
      type: 'keyDown', 
      keyCode: 'Tab',
      modifiers: ['shift']
    });
    setTimeout(() => {
      view.webContents.sendInputEvent({ 
        type: 'keyUp', 
        keyCode: 'Tab',
        modifiers: ['shift']
      });
    }, 50);
    console.log(`[${platformId}] Sent Shift+Tab to switch conversation`);
  }
});

// Get store data
ipcMain.handle('store:get', (event, key) => {
  const value = store.get(key);
  console.log('[Store] Getting', key, ':', value !== undefined && value !== null ? JSON.stringify(value).substring(0, 200) : 'undefined');
  return value;
});

// Set store data
ipcMain.handle('store:set', (event, key, value) => {
  console.log('[Store] Setting', key, ':', value !== undefined && value !== null ? JSON.stringify(value).substring(0, 200) : 'undefined');
  store.set(key, value);
  
  // Handle debugMode toggle - open/close debug window immediately
  if (key === 'debugMode') {
    if (value === true) {
      console.log('[Debug] Debug mode enabled, opening debug window...');
      createDebugWindow();
    } else {
      console.log('[Debug] Debug mode disabled, closing debug window...');
      if (debugWindow && !debugWindow.isDestroyed()) {
        debugWindow.close();
      }
      clearDebugState();
    }
  }
  
  return true;
});

// Get platforms list
ipcMain.handle('platforms:list', () => {
  return Object.entries(PLATFORMS).map(([id, config]) => ({
    id,
    name: config.name,
    url: config.url
  }));
});

// Open platform
ipcMain.handle('platform:open', (event, platformId) => {
  showPlatformView(platformId);
  return true;
});

// Close platform view
ipcMain.handle('platform:close', (event, platformId) => {
  const view = platformViews[platformId];
  if (view) {
    mainWindow.removeBrowserView(view);
    view.webContents.close();
    delete platformViews[platformId];
  }
  return true;
});

// ============ Shop IPC Handlers ============

// List shops from backend
ipcMain.handle('shops:list', async () => {
  try {
    if (!apiService) return { success: false, error: 'API service not initialized' };
    return await apiService.getShops();
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// Create a new shop
ipcMain.handle('shops:create', async (event, shopData) => {
  try {
    if (!apiService) return { success: false, error: 'API service not initialized' };
    return await apiService.createShop(shopData);
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// Update shop
ipcMain.handle('shops:update', async (event, shopId, shopData) => {
  try {
    if (!apiService) return { success: false, error: 'API service not initialized' };
    return await apiService.updateShop(shopId, shopData);
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// Delete shop
ipcMain.handle('shops:delete', async (event, shopId) => {
  try {
    if (!apiService) return { success: false, error: 'API service not initialized' };
    // Close associated BrowserView if open
    const currentShop = store.get('currentShop');
    if (currentShop && currentShop.shopId === shopId) {
      hidePlatformViews();
      store.set('currentShop', null);
    }
    return await apiService.deleteShop(shopId);
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// Start shop monitoring
ipcMain.handle('shops:start', async (event, shopId) => {
  try {
    if (!apiService) return { success: false, error: 'API service not initialized' };
    // Clear locally stopped flag when starting
    locallyStoppedShops.delete(shopId);
    
    // Trigger auto-login when shop is started
    const currentShop = store.get('currentShop');
    if (currentShop && currentShop.shopId === shopId) {
      const platformId = currentShop.platformId;
      
      // Show platform view if not already visible
      if (!currentShop.isNative) {
        showPlatformView(platformId);
      }
      
      const view = platformViews[platformId];
      const username = currentShop.username || '';
      const password = currentShop.password || '';
      
      if (view && username && password && !view.webContents.isDestroyed()) {
        // Cancel any previously pending auto-login timer
        if (autoLoginTimers[platformId]) {
          clearTimeout(autoLoginTimers[platformId]);
          autoLoginTimers[platformId] = null;
        }
        autoLoginTimers[platformId] = setTimeout(() => {
          autoLoginTimers[platformId] = null;
          if (view && !view.webContents.isDestroyed()) {
            view.webContents.send('shop:auto-login', {
              username: username,
              password: password
            });
            console.log(`[Shop] Sent auto-login credentials to ${platformId} on start`);
          }
        }, 3000);
      }
    }
    
    return await apiService.startShop(shopId);
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// Stop shop monitoring
ipcMain.handle('shops:stop', async (event, shopId) => {
  try {
    if (!apiService) return { success: false, error: 'API service not initialized' };
    console.log(`[Shop] Stopping shop: ${shopId}`);
    
    // Mark as locally stopped immediately (prevents race condition with shop rotation)
    locallyStoppedShops.add(shopId);
    
    // Clean up tasks for this shop only
    const currentShop = store.get('currentShop');
    const platformId = currentShop && currentShop.shopId === shopId ? currentShop.platformId : null;
    if (platformId) {
      // Cancel any pending auto-login timer for this platform
      if (autoLoginTimers[platformId]) {
        clearTimeout(autoLoginTimers[platformId]);
        autoLoginTimers[platformId] = null;
        console.log(`[Shop] Cancelled pending auto-login timer for ${platformId}`);
      }
      await cleanupShopTasks(shopId, platformId);
    }
    return await apiService.stopShop(shopId);
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// Logout shop - clear session/cookies and close BrowserView
ipcMain.handle('shops:logout', async (event, platformId) => {
  try {
    console.log(`[Shop] Logging out platform: ${platformId}`);
    
    // Cancel any pending auto-login timer for this platform
    if (autoLoginTimers[platformId]) {
      clearTimeout(autoLoginTimers[platformId]);
      autoLoginTimers[platformId] = null;
      console.log(`[Shop] Cancelled pending auto-login timer for ${platformId}`);
    }
    
    // Clean up tasks for this shop only
    const currentShop = store.get('currentShop');
    const shopId = currentShop && currentShop.platformId === platformId ? currentShop.shopId : null;
    if (shopId) {
      await cleanupShopTasks(shopId, platformId);
    }
    
    // Clear session data for this platform
    const partitionName = `persist:${platformId}`;
    const platformSession = session.fromPartition(partitionName);
    
    // Clear all storage data (cookies, localStorage, etc.)
    await platformSession.clearStorageData({
      storages: ['cookies', 'localstorage', 'sessionstorage', 'cachestorage']
    });
    
    // Close and remove the BrowserView
    if (platformViews[platformId]) {
      const view = platformViews[platformId];
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.removeBrowserView(view);
      }
      if (!view.webContents.isDestroyed()) {
        view.webContents.destroy();
      }
      delete platformViews[platformId];
    }
    
    // Clear current shop from store
    store.set('currentShop', null);
    
    console.log(`[Shop] Platform ${platformId} logged out and session cleared`);
    return { success: true };
  } catch (error) {
    console.error(`[Shop] Logout error:`, error);
    return { success: false, error: error.message };
  }
});

// Pause shop auto-reply (shop stays open but doesn't process messages)
const pausedShops = new Set();
// Track shops that have been stopped locally (prevents race condition with backend API)
const locallyStoppedShops = new Set();

ipcMain.handle('shops:pause', async (event, shopId) => {
  try {
    pausedShops.add(shopId);
    console.log(`[Shop] Paused shop: ${shopId}`);
    // Clean up tasks for this shop only
    const currentShop = store.get('currentShop');
    const platformId = currentShop && currentShop.shopId === shopId ? currentShop.platformId : null;
    if (platformId) {
      await cleanupShopTasks(shopId, platformId);
    }
    return { success: true };
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// Resume shop auto-reply
ipcMain.handle('shops:resume', async (event, shopId) => {
  try {
    pausedShops.delete(shopId);
    console.log(`[Shop] Resumed shop: ${shopId}`);
    return { success: true };
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// Check if shop is paused (used by message handler)
function isShopPaused(shopId) {
  return pausedShops.has(shopId);
}

// Select and open a shop's platform view
ipcMain.handle('shops:select', async (event, shop) => {
  try {
    if (!shop) {
      // Deselect - hide BrowserView and cleanup native adapters
      hidePlatformViews();
      if (wechatAdapter) {
        await wechatAdapter.cleanup();
      }
      store.set('currentShop', null);
      // Unsubscribe MQTT topic
      if (mqttClient && currentMqttTopic) {
        mqttClient.unsubscribe(currentMqttTopic);
        currentMqttTopic = null;
      }
      return { success: true };
    }

    const electronPlatform = mapBackendPlatformToElectron(shop.platform_type);
    if (!electronPlatform || !PLATFORMS[electronPlatform]) {
      return { success: false, error: `平台 ${shop.platform_type} 暂不支持` };
    }

    const platformConfig = PLATFORMS[electronPlatform];

    // Handle native adapters (like WeChat) differently
    if (platformConfig.native) {
      // Hide any BrowserViews
      hidePlatformViews();
      
      // For WeChat, initialize the native adapter
      if (electronPlatform === 'wechat') {
        console.log('[Shop] Initializing WeChat native adapter...');
        wechatAdapter = getWeChatNativeAdapter();
        
        // Set up message callback
        wechatAdapter.setMessageCallback(async (msgData) => {
          // Forward to AI service for processing
          if (mainWindow && !mainWindow.isDestroyed()) {
            mainWindow.webContents.send('message:received', msgData);
          }
          
          // Process message through AI
          if (apiService) {
            try {
              const result = await apiService.generateReply({
                shop_id: shop.shop_id,
                customer_id: msgData.customerId,
                customer_name: msgData.customerName,
                message: msgData.message,
                platform: 'wechat'
              });
              
              if (result.success && result.data && result.data.reply) {
                // Send reply via WeChat adapter
                const sendResult = await wechatAdapter.sendMessage(result.data.reply, msgData.customerName);
                
                if (sendResult.success) {
                  // Notify renderer
                  if (mainWindow && !mainWindow.isDestroyed()) {
                    mainWindow.webContents.send('message:replied', {
                      customerId: msgData.customerId,
                      reply: result.data.reply,
                      source: result.data.source
                    });
                  }
                }
              }
            } catch (e) {
              console.error('[WeChat] AI reply error:', e.message);
            }
          }
        });
        
        // Try to initialize (connect to WeChat)
        const initResult = await wechatAdapter.initialize();
        if (!initResult.success) {
          console.log('[Shop] WeChat adapter init:', initResult.message || initResult.error);
          // Don't fail - user can manually start WeChat later
        }
      }
    } else {
      // Standard BrowserView platform
      // If a view already exists (shop is running), show it; otherwise just hide
      if (platformViews[electronPlatform]) {
        showPlatformView(electronPlatform);
      } else {
        hidePlatformViews();
      }
    }

    // Get credentials from local store
    const credentials = store.get('shopCredentials') || {};
    const shopCreds = credentials[shop.shop_id] || {};
    const username = shopCreds.account || shop.account || '';
    const password = shopCreds.password || '';

    // Save current shop context for message handling
    const shopConfigs = store.get('shopConfigs') || {};
    const localConfig = shopConfigs[shop.shop_id] || {};
    
    store.set('currentShop', {
      shopId: shop.shop_id,
      shopName: shop.shop_name,
      platformId: electronPlatform,
      platformType: shop.platform_type,
      isNative: platformConfig.native || false,
      username: username,
      password: password,
      config_json: Object.keys(localConfig).length > 0 ? localConfig : (shop.config_json || {})
    });

    // Send credentials to preload for auto-login ONLY when shop is started (not on select)
    // Auto-login is now triggered by shops:start handler
    // (credentials are stored in currentShop for later use)

    console.log(`[Shop] Selected shop: ${shop.shop_name} (${electronPlatform}${platformConfig.native ? ' - native' : ''})`);

    // Switch MQTT subscription to new shop's knowledge sync topic
    if (mqttClient && mqttClient.connected) {
      if (currentMqttTopic) {
        mqttClient.unsubscribe(currentMqttTopic);
      }
      currentMqttTopic = `knowledge/sync/${shop.shop_id}`;
      mqttClient.subscribe(currentMqttTopic);
      console.log(`[MQTT] Subscribed to ${currentMqttTopic}`);
    }

    return { success: true };
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// Hide BrowserView (used when showing forms or switching tabs)
ipcMain.handle('shops:hide', async () => {
  hidePlatformViews();
  return { success: true };
});

// Handle auto-login request from preload script (when page navigates to login)
ipcMain.handle('shop:request-auto-login', async (event, platformId) => {
  try {
    const currentShop = store.get('currentShop');
    
    if (!currentShop) {
      console.log('[Shop] No current shop for auto-login request');
      return { success: false, error: 'No current shop' };
    }
    
    // Verify platform matches
    if (platformId && currentShop.platformId !== platformId) {
      console.log(`[Shop] Platform mismatch: requested ${platformId}, current ${currentShop.platformId}`);
      return { success: false, error: 'Platform mismatch' };
    }
    
    const username = currentShop.username || '';
    const password = currentShop.password || '';
    
    if (!username || !password) {
      console.log('[Shop] No credentials available for auto-login');
      return { success: false, error: 'No credentials' };
    }
    
    console.log(`[Shop] Providing auto-login credentials for ${currentShop.shopName}`);
    return {
      success: true,
      username: username,
      password: password
    };
  } catch (error) {
    console.error('[Shop] Error handling auto-login request:', error.message);
    return { success: false, error: error.message };
  }
});

// Simulate typing a character (for auto-login)
ipcMain.handle('input:type-char', async (event, platformId, char) => {
  try {
    const view = platformViews[platformId];
    if (view && !view.webContents.isDestroyed()) {
      view.webContents.sendInputEvent({
        type: 'char',
        keyCode: char
      });
      return { success: true };
    }
    return { success: false, error: 'View not found' };
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// Simulate pressing Enter key
ipcMain.handle('input:press-enter', async (event, platformId) => {
  try {
    const view = platformViews[platformId];
    if (view && !view.webContents.isDestroyed()) {
      view.webContents.sendInputEvent({
        type: 'keyDown',
        keyCode: 'Return'
      });
      view.webContents.sendInputEvent({
        type: 'keyUp',
        keyCode: 'Return'
      });
      return { success: true };
    }
    return { success: false, error: 'View not found' };
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// Simulate mouse click at specific coordinates
ipcMain.handle('input:mouse-click', async (event, platformId, x, y) => {
  try {
    const view = platformViews[platformId];
    if (view && !view.webContents.isDestroyed()) {
      // Move mouse to position
      view.webContents.sendInputEvent({
        type: 'mouseMove',
        x: Math.round(x),
        y: Math.round(y)
      });
      
      // Mouse down
      view.webContents.sendInputEvent({
        type: 'mouseDown',
        x: Math.round(x),
        y: Math.round(y),
        button: 'left',
        clickCount: 1
      });
      
      // Mouse up
      view.webContents.sendInputEvent({
        type: 'mouseUp',
        x: Math.round(x),
        y: Math.round(y),
        button: 'left',
        clickCount: 1
      });
      
      console.log(`[Input] Mouse click at (${x}, ${y}) on ${platformId}`);
      return { success: true };
    }
    return { success: false, error: 'View not found' };
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// ============ Auth & AI IPC Handlers ============

// Login to backend
ipcMain.handle('auth:login', async (event, username, password) => {
  try {
    const serverUrl = store.get('serverUrl');
    apiService = new ApiService(serverUrl);
    apiService.onTokenRefreshed((newTokens) => {
      store.set('tokens', newTokens);
    });
    const result = await apiService.login(username, password);
    if (result.success) {
      store.set('tokens', result.data.tokens);
      apiService.setTokens(result.data.tokens);
    }
    return result;
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// Handle platform login success from preload scripts
ipcMain.on('platform:login-success', (event, data) => {
  const { platformId } = data;
  console.log(`[Shop] Platform login success detected: ${platformId}`);
  // Forward to renderer to update shop status display
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('shop:login-success', { platformId });
  }
});

// ============ Products API ============

ipcMain.handle('products:list', async (event, shopId) => {
  try {
    if (!apiService) return { success: false, error: 'API service not initialized' };
    return await apiService.getProducts(shopId);
  } catch (error) {
    return { success: false, error: error.message };
  }
});

ipcMain.handle('products:detail', async (event, productId) => {
  try {
    if (!apiService) return { success: false, error: 'API service not initialized' };
    return await apiService.getProductDetail(productId);
  } catch (error) {
    return { success: false, error: error.message };
  }
});

ipcMain.handle('products:knowledge', async (event, productId) => {
  try {
    if (!apiService) return { success: false, error: 'API service not initialized' };
    return await apiService.getKnowledgeByProduct(productId);
  } catch (error) {
    return { success: false, error: error.message };
  }
});

ipcMain.handle('products:delete', async (event, productId) => {
  try {
    if (!apiService) return { success: false, error: 'API service not initialized' };
    return await apiService.deleteProduct(productId);
  } catch (error) {
    return { success: false, error: error.message };
  }
});

ipcMain.handle('knowledge:list', async (event, shopId) => {
  try {
    if (!apiService) return { success: false, error: 'API service not initialized' };
    return await apiService.getKnowledgeBase(shopId);
  } catch (error) {
    return { success: false, error: error.message };
  }
});

ipcMain.handle('knowledge:update', async (event, id, data) => {
  try {
    if (!apiService) return { success: false, error: 'API service not initialized' };
    return await apiService.updateKnowledge(id, data);
  } catch (error) {
    return { success: false, error: error.message };
  }
});

ipcMain.handle('knowledge:delete', async (event, id) => {
  try {
    if (!apiService) return { success: false, error: 'API service not initialized' };
    return await apiService.deleteKnowledge(id);
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// ============ Keyword Rules IPC ============

ipcMain.handle('keyword-rules:list', async (event, shopId) => {
  try {
    if (!apiService) return { success: false, error: 'API service not initialized' };
    return await apiService.getKeywordRules(shopId);
  } catch (error) {
    return { success: false, error: error.message };
  }
});

ipcMain.handle('keyword-rules:create', async (event, data) => {
  try {
    if (!apiService) return { success: false, error: 'API service not initialized' };
    return await apiService.createKeywordRule(data);
  } catch (error) {
    return { success: false, error: error.message };
  }
});

ipcMain.handle('keyword-rules:update', async (event, ruleId, data) => {
  try {
    if (!apiService) return { success: false, error: 'API service not initialized' };
    return await apiService.updateKeywordRule(ruleId, data);
  } catch (error) {
    return { success: false, error: error.message };
  }
});

ipcMain.handle('keyword-rules:delete', async (event, ruleId) => {
  try {
    if (!apiService) return { success: false, error: 'API service not initialized' };
    return await apiService.deleteKeywordRule(ruleId);
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// ============ Sensitive Word Rules IPC ============

ipcMain.handle('sensitive-words:list', async (event, shopId) => {
  try {
    if (!apiService) return { success: false, error: 'API service not initialized' };
    return await apiService.getSensitiveWordRules(shopId);
  } catch (error) {
    return { success: false, error: error.message };
  }
});

ipcMain.handle('sensitive-words:create', async (event, data) => {
  try {
    if (!apiService) return { success: false, error: 'API service not initialized' };
    return await apiService.createSensitiveWordRule(data);
  } catch (error) {
    return { success: false, error: error.message };
  }
});

ipcMain.handle('sensitive-words:update', async (event, ruleId, data) => {
  try {
    if (!apiService) return { success: false, error: 'API service not initialized' };
    return await apiService.updateSensitiveWordRule(ruleId, data);
  } catch (error) {
    return { success: false, error: error.message };
  }
});

ipcMain.handle('sensitive-words:delete', async (event, ruleId) => {
  try {
    if (!apiService) return { success: false, error: 'API service not initialized' };
    return await apiService.deleteSensitiveWordRule(ruleId);
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// ============ Scenario Rules IPC ============

ipcMain.handle('scenario-rules:list', async (event, shopId) => {
  try {
    if (!apiService) return { success: false, error: 'API service not initialized' };
    return await apiService.getScenarioRules(shopId);
  } catch (error) {
    return { success: false, error: error.message };
  }
});

ipcMain.handle('scenario-rules:create', async (event, data) => {
  try {
    if (!apiService) return { success: false, error: 'API service not initialized' };
    return await apiService.createScenarioRule(data);
  } catch (error) {
    return { success: false, error: error.message };
  }
});

ipcMain.handle('scenario-rules:update', async (event, ruleId, data) => {
  try {
    if (!apiService) return { success: false, error: 'API service not initialized' };
    return await apiService.updateScenarioRule(ruleId, data);
  } catch (error) {
    return { success: false, error: error.message };
  }
});

ipcMain.handle('scenario-rules:delete', async (event, ruleId) => {
  try {
    if (!apiService) return { success: false, error: 'API service not initialized' };
    return await apiService.deleteScenarioRule(ruleId);
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// Generate AI reply
ipcMain.handle('ai:generate-reply', async (event, data) => {
  try {
    if (!apiService) {
      const serverUrl = store.get('serverUrl');
      const tokens = store.get('tokens');
      apiService = new ApiService(serverUrl);
      apiService.onTokenRefreshed((newTokens) => {
        store.set('tokens', newTokens);
      });
      if (tokens) apiService.setTokens(tokens);
    }
    return await apiService.generateReply(data);
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// Sync message to backend
ipcMain.handle('message:sync', async (event, data) => {
  try {
    if (!apiService) return { success: false, error: 'Not connected' };
    return await apiService.syncMessage(data);
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// Handle new message from platform (from preload script)

// Helper: save conversation record for training data (async, fire-and-forget)
function saveConversationRecord({ buyerMessage, customerReply, context, buyerName, shopId, platformId, source, modelUsed, confidence, orderDetail }) {
  if (!apiService) return;
  
  const orderStr = orderDetail ? JSON.stringify(orderDetail) : '';
  
  apiService.saveConversation({
    buyer_message: buyerMessage,
    customer_reply: customerReply,
    conversation_context: context || '',
    buyer_name: buyerName || '',
    image_analysis: '',
    order_info: orderStr,
    shop_id: shopId || '',
    platform: platformId || '',
    source: source || 'ai_auto',
    model_used: modelUsed || '',
    confidence: confidence || 0,
  }).then(res => {
    if (res.success) {
      console.log(`[ConvRecord] Saved record #${res.record_id}`);
    } else {
      console.warn(`[ConvRecord] Failed to save: ${res.error}`);
    }
  }).catch(err => {
    console.warn(`[ConvRecord] Error saving: ${err.message}`);
  });
}

ipcMain.on('platform:new-message', async (event, data) => {
  const { platformId, customerId, customerName, message, context, timestamp, buyerImages } = data;
  
  console.log(`[${platformId}] New message from ${customerName}: ${message}`);
  
  // Check if this customer is already being processed
  if (processingCustomers.has(customerId)) {
    console.log(`[${platformId}] Customer ${customerId} already being processed, skipping duplicate`);
    return;
  }
  
  // Notify renderer
  if (mainWindow) {
    mainWindow.webContents.send('message:received', data);
  }
  
  // Check if auto-reply is enabled
  const autoReply = store.get('autoReply');
  console.log(`[${platformId}] Auto-reply enabled: ${autoReply}`);
  if (!autoReply) return;
  
  // Check if current shop is paused
  const currentShop = store.get('currentShop');
  if (currentShop && isShopPaused(currentShop.shopId)) {
    console.log(`[${platformId}] Shop ${currentShop.shopId} is paused, skipping auto-reply`);
    return;
  }
  
  // Mark customer as being processed
  processingCustomers.add(customerId);
  
  // Ensure apiService is initialized
  if (!apiService) {
    const serverUrl = store.get('serverUrl');
    const tokens = store.get('tokens');
    apiService = new ApiService(serverUrl);
    apiService.onTokenRefreshed((newTokens) => {
      store.set('tokens', newTokens);
    });
    if (tokens) apiService.setTokens(tokens);
    console.log(`[${platformId}] ApiService initialized with serverUrl: ${serverUrl}`);
  }
  
  try {
    console.log(`[${platformId}] Calling AI generate-reply API...`);
    
    // Get AI model from shop config
    const aiModel = currentShop?.config_json?.ai_model || '';
    if (aiModel) {
      console.log(`[${platformId}] 使用AI模型: ${aiModel}`);
    }
    
    // [OrderDetect] Check if order detection is enabled and extract order info
    let orderDetail = null;
    const orderDetect = store.get('orderDetect');
    if (orderDetect) {
      console.log(`[${platformId}] OrderDetect enabled, extracting order info...`);
      try {
        const requestId = `${Date.now()}-${Math.random().toString(36).substr(2, 6)}`;
        orderDetail = await Promise.race([
          new Promise((resolve) => {
            const handler = (e, result) => {
              if (result && result.requestId === requestId) {
                ipcMain.removeListener('platform:order-info-result', handler);
                resolve(result.data);
              }
            };
            ipcMain.on('platform:order-info-result', handler);
            // Send extraction request to the same preload that sent the message
            event.sender.send('platform:get-order-info', { requestId });
          }),
          new Promise((resolve) => setTimeout(() => {
            console.log(`[${platformId}] OrderDetect extraction timeout (2s)`);
            resolve(null);
          }, 2000))
        ]);
        if (orderDetail) {
          console.log(`[${platformId}] Order info extracted:`, JSON.stringify(orderDetail).substring(0, 200));
        } else {
          console.log(`[${platformId}] No order info found on page`);
        }
      } catch (extractErr) {
        console.error(`[${platformId}] OrderDetect extraction error:`, extractErr.message);
        orderDetail = null;
      }
    }
    
    // Generate AI reply with full conversation context
    const result = await apiService.generateReply({
      question: message,
      shop_id: currentShop?.shopId,
      context: context || `买家: ${customerName}`,
      model: aiModel,
      order_detail: orderDetail,
      product_names: data.productNames || [],
      buyer_images: buyerImages || []  // Pass buyer-sent images for vision analysis
    });
    
    console.log(`[${platformId}] API result:`, JSON.stringify(result));
    
    // Check if model was unavailable
    if (result.success && result.data && result.data.model_unavailable) {
      console.warn(`[${platformId}] [模型不可用] ${result.data.model_error}`);
      // Notify renderer about model unavailability
      if (mainWindow) {
        mainWindow.webContents.send('log:warn', `[模型不可用] ${result.data.model_error}`);
      }
    }
    
    if (result.success && result.data && result.data.reply) {
      console.log(`[${platformId}] Sending reply (source: ${result.data.source}, model: ${result.data.model_used || 'default'}): ${result.data.reply}`);
      
      // [DebugMode] Check if debug mode is enabled
      const debugMode = store.get('debugMode');
      if (debugMode) {
        console.log(`[${platformId}] Debug mode enabled, opening debug window...`);
        
        // Clear any previous pending message
        clearDebugState();
        
        // Store pending message for debug window
        pendingDebugMessage = {
          sender: event.sender,
          customerId,
          customerName,
          message,
          reply: result.data.reply,
          source: result.data.source,
          shopId: currentShop?.shopId,
          originalData: data
        };
        
        // Create/show debug window
        createDebugWindow();
        
        // Send message data to debug window
        setTimeout(() => {
          if (debugWindow && !debugWindow.isDestroyed()) {
            debugWindow.webContents.send('debug:new-message', {
              customerMessage: message,
              question: message,
              aiReply: result.data.reply,
              shopId: currentShop?.shopId,
              customerName
            });
            
            // Start countdown
            startDebugCountdown(10);
          }
        }, 500);
        
        // Release lock after debug window opens (debug window handles its own flow)
        setTimeout(() => {
          processingCustomers.delete(customerId);
        }, 3000);
        
        return; // Don't auto-send, wait for debug window action
      }
      
      // Send reply back to platform
      event.reply('platform:send-reply', {
        customerId,
        reply: result.data.reply,
        source: result.data.source
      });
      
      // Notify renderer
      if (mainWindow) {
        mainWindow.webContents.send('message:replied', {
          ...data,
          reply: result.data.reply,
          source: result.data.source
        });
      }
      
      // [ConvRecord] Save conversation record for training data
      saveConversationRecord({
        buyerMessage: message,
        customerReply: result.data.reply,
        context: context || '',
        buyerName: customerName,
        shopId: currentShop?.shopId,
        platformId,
        source: result.data.source === 'knowledge_base' ? 'ai_kb' : 'ai_auto',
        modelUsed: result.data.model_used || aiModel || '',
        confidence: result.data.confidence || 0,
        orderDetail,
      });
    } else {
      console.log(`[${platformId}] API returned no reply:`, result.error || 'unknown error');
    }
  } catch (error) {
    console.error(`[${platformId}] Error generating reply:`, error);
    if (mainWindow) {
      mainWindow.webContents.send('message:error', {
        ...data,
        error: error.message
      });
    }
  } finally {
    // Always remove customer from processing set after completion
    setTimeout(() => {
      processingCustomers.delete(customerId);
      console.log(`[${platformId}] Released lock for customer ${customerId}`);
    }, 3000); // Wait 3 seconds before allowing new requests for same customer
  }
});

// ============ Debug Mode IPC Handlers ============

// Send reply from debug window
ipcMain.on('debug:send-reply', (event, reply) => {
  if (!pendingDebugMessage) {
    console.log('[Debug] No pending message to reply');
    return;
  }
  
  const { sender, customerId, originalData } = pendingDebugMessage;
  
  // Send edited reply to platform
  if (sender) {
    sender.send('platform:send-reply', {
      customerId,
      reply,
      source: 'debug_edited'
    });
  }
  
  // Notify main renderer
  if (mainWindow) {
    mainWindow.webContents.send('message:replied', {
      ...originalData,
      reply,
      source: 'debug_edited'
    });
  }
  
  console.log('[Debug] Sent edited reply from debug window');
  
  // [ConvRecord] Save debug-edited conversation record
  const currentShop = store.get('currentShop');
  saveConversationRecord({
    buyerMessage: pendingDebugMessage.message,
    customerReply: reply,
    context: '',
    buyerName: pendingDebugMessage.customerName || '',
    shopId: pendingDebugMessage.shopId || currentShop?.shopId,
    platformId: originalData?.platformId || '',
    source: reply !== pendingDebugMessage.reply ? 'human_edited' : 'debug_edited',
    modelUsed: '',
    confidence: 0,
    orderDetail: null,
  });
  
  clearDebugState();
  
  // Close debug window
  if (debugWindow && !debugWindow.isDestroyed()) {
    debugWindow.close();
  }
});

// Skip message from debug window
ipcMain.on('debug:skip-message', () => {
  console.log('[Debug] Message skipped');
  clearDebugState();
  
  if (debugWindow && !debugWindow.isDestroyed()) {
    debugWindow.close();
  }
});

// Pause/resume countdown
ipcMain.on('debug:pause-countdown', (event, paused) => {
  debugCountdownPaused = paused;
  console.log(`[Debug] Countdown ${paused ? 'paused' : 'resumed'}`);
});

// Set always on top
ipcMain.on('debug:set-always-on-top', (event, flag) => {
  if (debugWindow && !debugWindow.isDestroyed()) {
    debugWindow.setAlwaysOnTop(flag);
  }
});

// Close debug window
ipcMain.on('debug:close-window', () => {
  clearDebugState();
  if (debugWindow && !debugWindow.isDestroyed()) {
    debugWindow.close();
  }
});

// Get shops for debug window
ipcMain.on('debug:get-shops', async (event, { requestId }) => {
  try {
    if (!apiService) {
      event.reply('debug:get-shops-result', { requestId, success: false, error: 'API service not initialized' });
      return;
    }
    const result = await apiService.getShops();
    if (result.success) {
      event.reply('debug:get-shops-result', { requestId, success: true, data: result.data });
    } else {
      event.reply('debug:get-shops-result', { requestId, success: false, error: result.error });
    }
  } catch (error) {
    event.reply('debug:get-shops-result', { requestId, success: false, error: error.message });
  }
});

// Search knowledge base
ipcMain.on('debug:search-knowledge', async (event, { question, shopId, requestId }) => {
  try {
    if (!apiService) {
      event.reply('debug:search-knowledge-result', { requestId, success: false, error: 'API service not initialized' });
      return;
    }
    const result = await apiService.searchKnowledge(question, shopId);
    if (result.success) {
      event.reply('debug:search-knowledge-result', { requestId, success: true, data: result.data });
    } else {
      event.reply('debug:search-knowledge-result', { requestId, success: false, error: result.error });
    }
  } catch (error) {
    event.reply('debug:search-knowledge-result', { requestId, success: false, error: error.message });
  }
});

// Add to knowledge base
ipcMain.on('debug:add-knowledge', async (event, data) => {
  const { requestId, shop_id, question, answer, category } = data;
  try {
    if (!apiService) {
      event.reply('debug:add-knowledge-result', { requestId, success: false, error: 'API service not initialized' });
      return;
    }
    const result = await apiService.createKnowledge({ shop_id, question, answer, category });
    if (result.success) {
      event.reply('debug:add-knowledge-result', { requestId, success: true, data: result.data });
    } else {
      event.reply('debug:add-knowledge-result', { requestId, success: false, error: result.error });
    }
  } catch (error) {
    event.reply('debug:add-knowledge-result', { requestId, success: false, error: error.message });
  }
});

// ============ Learning Mode IPC Handlers ============

/**
 * Create a BrowserView for learning mode
 * First loads the login page, then polls for login success
 */
function createLearningView(platformId) {
  const platform = LEARNING_PLATFORMS[platformId];
  if (!platform) return null;

  const view = new BrowserView({
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload', platform.preload),
      partition: `persist:learning-${platformId}`
    }
  });

  // Load login page first
  view.webContents.loadURL(platform.loginUrl);

  view.webContents.setWindowOpenHandler(({ url }) => {
    view.webContents.loadURL(url);
    return { action: 'deny' };
  });

  // Poll for login success every 5 seconds
  let loginCheckInterval = null;
  let loginDetected = false;
  const loginCheckStartTime = Date.now();
  const LOGIN_TIMEOUT = 5 * 60 * 1000; // 5 minute timeout

  function startLoginCheck() {
    if (loginCheckInterval) clearInterval(loginCheckInterval);

    // Notify renderer that we're waiting for login
    if (mainWindow) {
      mainWindow.webContents.send('learning:log', { message: '请在弹出的页面中手动登录平台账号...' });
    }

    loginCheckInterval = setInterval(async () => {
      try {
        if (!view || view.webContents.isDestroyed()) {
          clearInterval(loginCheckInterval);
          return;
        }

        // Check if login timeout
        if (Date.now() - loginCheckStartTime > LOGIN_TIMEOUT) {
          clearInterval(loginCheckInterval);
          console.log(`[Learning] Login timeout for ${platformId}`);
          if (mainWindow) {
            mainWindow.webContents.send('learning:error', { error: '登录超时，请重新尝试' });
          }
          return;
        }

        const currentUrl = view.webContents.getURL();
        console.log(`[Learning] Checking login status, current URL: ${currentUrl}`);

        // Check if redirected away from login page (means logged in)
        const isStillOnLogin = currentUrl.includes('/login') || currentUrl.includes('login.taobao');
        
        if (!isStillOnLogin) {
          // Logged in! Clear interval
          clearInterval(loginCheckInterval);
          loginCheckInterval = null;
          loginDetected = true;
          console.log(`[Learning] Login detected for ${platformId}, ready for extraction`);
          
          // Check if learning is already in progress
          const currentState = learningState[platformId];
          if (mainWindow) {
            if (currentState && currentState.isExtracting) {
              // Learning in progress - send progress update
              const current = currentState.currentProductIndex || 0;
              const total = currentState.totalProducts || 0;
              mainWindow.webContents.send('learning:log', { message: `登录成功！继续学习 (${current + 1}/${total})...` });
              mainWindow.webContents.send('learning:progress', { 
                platform: platformId,
                phase: 'detail',
                current: current + 1,
                total: total,
                message: `正在学习第 ${current + 1}/${total} 个商品...`
              });
            } else {
              // Not learning yet - show ready state
              mainWindow.webContents.send('learning:log', { message: '登录成功！请勾选商品后点击开始学习' });
              mainWindow.webContents.send('learning:ready', { platform: platformId });
            }
          }

          // Don't auto-trigger extraction - wait for user to click "开始学习" button
          return;
        }

        // Notify renderer we're still waiting
        if (mainWindow) {
          mainWindow.webContents.send('learning:log', { message: '等待登录中...' });
        }
      } catch (err) {
        console.error('[Learning] Login check error:', err);
      }
    }, 5000);
  }

  // Start login check after page loads
  view.webContents.on('did-finish-load', () => {
    const url = view.webContents.getURL();
    if (url.includes('/login') || url.includes('login.taobao')) {
      if (!loginDetected) {
        startLoginCheck();
      }
    } else if (!loginDetected) {
      // Already logged in (e.g. from persistent session)
      if (loginCheckInterval) clearInterval(loginCheckInterval);
      loginDetected = true;
      console.log(`[Learning] Already logged in for ${platformId}`);
      
      // Check if learning is already in progress (e.g., navigating between pages)
      const currentState = learningState[platformId];
      if (currentState && currentState.isExtracting) {
        // Learning in progress - send progress update instead of ready
        console.log(`[Learning] Learning in progress for ${platformId}, sending progress update`);
        if (mainWindow) {
          const current = currentState.currentProductIndex || 0;
          const total = currentState.totalProducts || 0;
          mainWindow.webContents.send('learning:log', { message: `页面已加载，继续学习 (${current + 1}/${total})...` });
          mainWindow.webContents.send('learning:progress', { 
            platform: platformId,
            phase: 'detail',
            current: current + 1,
            total: total,
            message: `正在学习第 ${current + 1}/${total} 个商品...`
          });
        }
      } else {
        // Not learning yet - show ready state
        if (mainWindow) {
          mainWindow.webContents.send('learning:log', { message: '已登录，请勾选商品后点击开始学习' });
          mainWindow.webContents.send('learning:ready', { platform: platformId });
        }
      }
      // Don't auto-trigger extraction - wait for user to click "开始学习" button
    }
  });

  learningViews[platformId] = view;
  
  // Store cleanup function
  view._cleanupLoginCheck = () => {
    if (loginCheckInterval) {
      clearInterval(loginCheckInterval);
      loginCheckInterval = null;
    }
  };

  return view;
}

/**
 * Show learning view in main window
 */
function showLearningView(platformId) {
  // Save current window state before maximizing (if not already saved)
  if (!preLearningWindowState && mainWindow) {
    preLearningWindowState = {
      bounds: mainWindow.getBounds(),
      isMaximized: mainWindow.isMaximized()
    };
    console.log('[Learning] Saved window state before learning:', preLearningWindowState);
    
    // Maximize window for better learning view
    if (!mainWindow.isMaximized()) {
      mainWindow.maximize();
      console.log('[Learning] Window maximized for learning');
    }
  }
  
  // Remove current views
  const currentViews = mainWindow.getBrowserViews();
  currentViews.forEach(v => mainWindow.removeBrowserView(v));

  // Get or create learning view
  let view = learningViews[platformId];
  if (!view) {
    view = createLearningView(platformId);
  }

  if (view) {
    mainWindow.addBrowserView(view);
    const contentBounds = mainWindow.getContentBounds();
    // Offset BrowserView to the right (x=440) so the learning control panel
    // (position:fixed, left:10px, width:420px => extends to x=430) is not covered.
    // BrowserView always renders on top of renderer content, so we must avoid overlap.
    const learningX = 440;
    view.setBounds({
      x: learningX,
      y: 44,
      width: contentBounds.width - learningX - 180,
      height: contentBounds.height - 44
    });
    view.setAutoResize({ width: false, height: false });
  }
}

// Start learning task
// Map BrowserView platformId back to backend platform type
const PLATFORM_TO_BACKEND = {
  pinduoduo: 'pdd',
  qianniu: 'taobao',
  douyin: 'douyin',
  wechat: 'wechat'
};

// ============ WeChat Native Adapter IPC Handlers ============

// Check WeChat adapter status
ipcMain.handle('wechat:status', async () => {
  try {
    if (!wechatAdapter) {
      return { success: true, data: { connected: false, monitoring: false } };
    }
    const status = await wechatAdapter.getStatus();
    return status;
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// Connect to WeChat PC client
ipcMain.handle('wechat:connect', async () => {
  try {
    if (!wechatAdapter) {
      wechatAdapter = getWeChatNativeAdapter();
    }
    const result = await wechatAdapter.initialize();
    return result;
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// Disconnect WeChat adapter
ipcMain.handle('wechat:disconnect', async () => {
  try {
    if (wechatAdapter) {
      await wechatAdapter.cleanup();
    }
    return { success: true };
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// Get WeChat chat list
ipcMain.handle('wechat:chats', async () => {
  try {
    if (!wechatAdapter) {
      return { success: false, error: 'WeChat adapter not initialized' };
    }
    return await wechatAdapter.getChats();
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// Send message via WeChat
ipcMain.handle('wechat:send', async (event, { message, contact }) => {
  try {
    if (!wechatAdapter) {
      return { success: false, error: 'WeChat adapter not initialized' };
    }
    return await wechatAdapter.sendMessage(message, contact);
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// ============ Learning Handlers ============

ipcMain.handle('learning:start', async (event, platformId, shopId) => {
  try {
    const backendPlatform = PLATFORM_TO_BACKEND[platformId] || platformId;
    console.log(`[Learning] Starting learning task for platform: ${platformId} (backend: ${backendPlatform}), shop: ${shopId}`);
    
    // Clear any previous learning state to ensure fresh start
    delete learningState[platformId];
    console.log(`[Learning] Cleared previous learning state for ${platformId}`);
    
    // Show learning view FIRST (so user sees login page immediately)
    showLearningView(platformId);
    
    // Start task on backend (in background)
    let result;
    try {
      result = await apiService.startLearningTask(shopId, backendPlatform);
      console.log(`[Learning] API result:`, JSON.stringify(result));
    } catch (apiErr) {
      console.error('[Learning] API call failed:', apiErr.message);
      result = { success: false, error: apiErr.message };
    }
    
    // Handle both new task and existing task (TASK_EXISTS)
    const taskData = result?.data;
    if (taskData) {
      currentLearningTask = {
        taskId: taskData.task_id,
        platformId,
        shopId,
        status: taskData.status || 'pending'
      };
      
      // Notify renderer
      if (mainWindow) {
        mainWindow.webContents.send('learning:task-created', taskData);
      }
    } else {
      console.log('[Learning] No task data from API, view still shown for login');
    }
    
    return result || { success: true };
  } catch (error) {
    console.error('[Learning] Error starting task:', error);
    return { success: false, error: error.message };
  }
});

// Trigger extraction in learning view
ipcMain.handle('learning:extract', async (event, platformId) => {
  const view = learningViews[platformId];
  if (view && !view.webContents.isDestroyed()) {
    view.webContents.send('learning:start-extraction');
    return { success: true };
  }
  return { success: false, error: 'Learning view not found' };
});

// Stop learning
ipcMain.handle('learning:stop', async (event, platformId) => {
  const view = learningViews[platformId];
  if (view) {
    // Clean up login check interval
    if (view._cleanupLoginCheck) view._cleanupLoginCheck();
    if (!view.webContents.isDestroyed()) {
      view.webContents.send('learning:stop');
    }
  }
  
  // Clear learning state so next start is fresh
  delete learningState[platformId];
  console.log(`[Learning] Cleared learning state for ${platformId} on stop`);
  
  if (currentLearningTask) {
    await apiService.completeLearningTask(currentLearningTask.taskId);
    currentLearningTask = null;
  }
  
  return { success: true };
});

// Get learning task status
ipcMain.handle('learning:status', async (event, taskId) => {
  return await apiService.getLearningTaskStatus(taskId);
});

// Close learning view and return to normal view
ipcMain.handle('learning:close', async (event, platformId) => {
  const view = learningViews[platformId];
  if (view) {
    if (view._cleanupLoginCheck) view._cleanupLoginCheck();
    mainWindow.removeBrowserView(view);
    view.webContents.close();
    delete learningViews[platformId];
  }
  
  // Clear learning state so next start is fresh
  delete learningState[platformId];
  console.log(`[Learning] Cleared learning state for ${platformId} on close`);
  
  // Restore window state from before learning
  // Keep window maximized after learning (better user experience)
  if (preLearningWindowState && mainWindow) {
    console.log('[Learning] Learning completed, keeping window maximized');
    if (!mainWindow.isMaximized()) {
      mainWindow.maximize();
    }
    preLearningWindowState = null;  // Clear saved state
  }
  
  // Show normal platform view
  showPlatformView(platformId);
  
  return { success: true };
});

// Learning preload script events
ipcMain.on('learning:log', (event, data) => {
  console.log(`[Learning-${data.platform}] ${data.message}`);
  if (mainWindow) {
    mainWindow.webContents.send('learning:log', data);
  }
});

ipcMain.on('learning:ready', (event, data) => {
  console.log(`[Learning] ${data.platform} preload script ready`);
  if (mainWindow) {
    mainWindow.webContents.send('learning:ready', data);
  }
});

ipcMain.on('learning:started', (event, data) => {
  console.log(`[Learning] ${data.platform} extraction started`);
  if (mainWindow) {
    mainWindow.webContents.send('learning:started', data);
  }
});

ipcMain.on('learning:progress', (event, data) => {
  console.log(`[Learning] ${data.platform} progress: ${data.extracted} products extracted`);
  if (mainWindow) {
    mainWindow.webContents.send('learning:progress', data);
  }
});

ipcMain.on('learning:products-extracted', async (event, data) => {
  console.log(`[Learning] ${data.platform} extracted ${data.totalCount} products`);
  
  if (!currentLearningTask) {
    console.error('[Learning] No active learning task');
    return;
  }
  
  try {
    // Update task with total products count
    await apiService.updateLearningTaskProgress(currentLearningTask.taskId, data.totalCount);
    
    // Process each product
    let processedCount = 0;
    let successCount = 0;
    let qaGenerated = 0;
    for (const product of data.products) {
      try {
        const result = await apiService.processProduct(currentLearningTask.taskId, product);
        processedCount++;
        
        const isSuccess = !!(result && result.success);
        const qaCount = (result && (result.qa_count || result.qaCount)) || 0;
        if (isSuccess) {
          successCount++;
          qaGenerated += qaCount;
        }
        
        // Send progress to renderer
        if (mainWindow) {
          mainWindow.webContents.send('learning:product-processed', {
            platform: data.platform,
            productName: product.name,
            result: result,
            success: isSuccess,
            qaCount: qaCount,
            progress: {
              processed: processedCount,
              total: data.totalCount
            }
          });
        }
        
        // Small delay to avoid overwhelming the backend
        await new Promise(resolve => setTimeout(resolve, 200));
        
      } catch (err) {
        console.error(`[Learning] Error processing product ${product.name}:`, err);
        processedCount++;
        // Still send progress update on error so the UI reflects the count
        if (mainWindow) {
          mainWindow.webContents.send('learning:product-processed', {
            platform: data.platform,
            productName: product.name,
            success: false,
            qaCount: 0,
            progress: {
              processed: processedCount,
              total: data.totalCount
            }
          });
        }
      }
    }
    
    // Complete the task
    await apiService.completeLearningTask(currentLearningTask.taskId);
    
    if (mainWindow) {
      mainWindow.webContents.send('learning:completed', {
        platform: data.platform,
        totalProducts: data.totalCount,
        processedCount: processedCount,
        successCount: successCount,
        qaGenerated: qaGenerated
      });
    }
    
    currentLearningTask = null;
    
  } catch (error) {
    console.error('[Learning] Error processing products:', error);
    if (mainWindow) {
      mainWindow.webContents.send('learning:error', {
        platform: data.platform,
        error: error.message
      });
    }
  }
});

ipcMain.on('learning:error', (event, data) => {
  console.error(`[Learning] ${data.platform} error: ${data.error}`);
  if (mainWindow) {
    mainWindow.webContents.send('learning:error', data);
  }
});

// Handle navigate back request from learning preload (after extracting detail page)
ipcMain.on('learning:navigate-back', async (event, data) => {
  console.log(`[Learning] Navigate back request: index ${data.nextIndex}/${data.total}`);
  
  const view = learningViews[data.platform];
  if (view && !view.webContents.isDestroyed()) {
    let continueSent = false;
    
    function sendContinueSignal(reason) {
      if (continueSent) return;
      continueSent = true;
      console.log(`[Learning] Sending continue signal (trigger: ${reason})`);
      setTimeout(() => {
        if (view && !view.webContents.isDestroyed()) {
          view.webContents.send('learning:continue');
        }
      }, 500);
    }
    
    // Listen for multiple navigation completion events
    // did-finish-load: fires on full page load
    view.webContents.once('did-finish-load', () => sendContinueSignal('did-finish-load'));
    // did-navigate: fires when navigation completes (even if page is cached)
    view.webContents.once('did-navigate', () => sendContinueSignal('did-navigate'));
    // dom-ready: fires when DOM is ready (backup)
    view.webContents.once('dom-ready', () => sendContinueSignal('dom-ready'));
    
    // Fallback timeout: if no navigation event fires (e.g., bfcache/SPA),
    // check if we're still on detail page and force navigate to list URL
    setTimeout(() => {
      if (continueSent) return;
      // Check if we're still on the detail page (goBack failed)
      const currentUrl = view.webContents.getURL();
      if (data.listPageUrl && !currentUrl.includes('goods_list') && !currentUrl.includes('/goods/list')) {
        console.log(`[Learning] goBack() failed (still on: ${currentUrl.substring(0, 80)}), forcing navigation to list page`);
        view.webContents.loadURL(data.listPageUrl);
        // Wait for the forced navigation to complete
        view.webContents.once('did-finish-load', () => sendContinueSignal('forced-navigate'));
        // Secondary timeout in case forced navigate also stalls
        setTimeout(() => sendContinueSignal('timeout-fallback-final'), 8000);
      } else {
        sendContinueSignal('timeout-fallback');
      }
    }, 5000);
    
    // Go back to list page
    if (view.webContents.canGoBack()) {
      view.webContents.goBack();
    } else if (data.listPageUrl) {
      // Fallback: navigate to saved list URL
      view.webContents.loadURL(data.listPageUrl);
    }
  }
});

// ============ Learning State Management ============

// Get learning state for a platform
ipcMain.handle('learning:get-state', (event, platformId) => {
  return learningState[platformId] || null;
});

// Set learning state for a platform
ipcMain.handle('learning:set-state', (event, platformId, state) => {
  learningState[platformId] = state;
  console.log(`[Learning] State updated for ${platformId}:`, JSON.stringify(state).substring(0, 200));
  return true;
});

// Clear learning state for a platform
ipcMain.handle('learning:clear-state', (event, platformId) => {
  delete learningState[platformId];
  console.log(`[Learning] State cleared for ${platformId}`);
  return true;
});

// Vision-based page analysis for learning
ipcMain.handle('learning:vision-analyze-page', async (event, platformId) => {
  try {
    const view = learningViews[platformId];
    if (!view || view.webContents.isDestroyed()) {
      return { success: false, error: 'Learning view not found' };
    }
    
    console.log(`[Learning-Vision] Capturing page screenshot for ${platformId}...`);
    
    // Capture the full page screenshot
    const image = await view.webContents.capturePage();
    const imageBase64 = image.toPNG().toString('base64');
    
    console.log(`[Learning-Vision] Screenshot captured, size: ${imageBase64.length} chars, sending to vision API...`);
    
    // Call vision API to analyze the page
    if (!apiService) {
      return { success: false, error: 'API service not initialized' };
    }
    
    const analysisResult = await apiService.visionAnalyzePage({
      image_base64: imageBase64,
      page_type: 'product_detail',
      extract_mode: 'full'
    });
    
    if (!analysisResult.success) {
      console.error(`[Learning-Vision] Vision analysis failed:`, analysisResult.error);
      return { success: false, error: analysisResult.error };
    }
    
    console.log(`[Learning-Vision] Vision analysis completed successfully`);
    
    return {
      success: true,
      description: analysisResult.description || '',
      specs: analysisResult.specs || {},
      images: analysisResult.images || []
    };
    
  } catch (error) {
    console.error(`[Learning-Vision] Error:`, error);
    return { success: false, error: error.message };
  }
});

// Multi-segment vision analysis - captures multiple screenshots at different scroll positions
ipcMain.handle('learning:vision-analyze-multi-segment', async (event, platformId) => {
  try {
    const view = learningViews[platformId];
    if (!view || view.webContents.isDestroyed()) {
      return { success: false, error: 'Learning view not found' };
    }
    
    console.log(`[Learning-Vision] Starting multi-segment analysis for ${platformId}...`);
    
    if (!apiService) {
      return { success: false, error: 'API service not initialized' };
    }
    
    // Get page dimensions
    const pageInfo = await view.webContents.executeJavaScript(`
      ({
        scrollHeight: document.documentElement.scrollHeight,
        viewportHeight: window.innerHeight,
        scrollTop: window.scrollY
      })
    `);
    
    const { scrollHeight, viewportHeight } = pageInfo;
    const numSegments = Math.min(Math.ceil(scrollHeight / viewportHeight), 4); // Max 4 segments
    
    console.log(`[Learning-Vision] Page height: ${scrollHeight}px, viewport: ${viewportHeight}px, segments: ${numSegments}`);
    
    const allDescriptions = [];
    const allSpecs = {};
    const allImages = [];
    
    // Capture and analyze each segment
    for (let i = 0; i < numSegments; i++) {
      const scrollPos = Math.min(i * viewportHeight * 0.8, scrollHeight - viewportHeight);
      
      // Scroll to position
      await view.webContents.executeJavaScript(`
        window.scrollTo({ top: ${scrollPos}, behavior: 'instant' });
      `);
      
      // Wait for scroll and rendering
      await new Promise(r => setTimeout(r, 500));
      
      console.log(`[Learning-Vision] Capturing segment ${i + 1}/${numSegments} at scroll ${scrollPos}px...`);
      
      // Capture screenshot
      const image = await view.webContents.capturePage();
      const imageBase64 = image.toPNG().toString('base64');
      
      // Analyze this segment
      const segmentResult = await apiService.visionAnalyzePage({
        image_base64: imageBase64,
        page_type: 'product_detail',
        extract_mode: 'segment',
        segment_info: `第${i + 1}/${numSegments}段`
      });
      
      if (segmentResult.success) {
        if (segmentResult.description) {
          allDescriptions.push(`【第${i + 1}段内容】\n${segmentResult.description}`);
        }
        if (segmentResult.specs) {
          Object.assign(allSpecs, segmentResult.specs);
        }
        if (segmentResult.images) {
          allImages.push(...segmentResult.images);
        }
        console.log(`[Learning-Vision] Segment ${i + 1} analyzed: ${segmentResult.description?.length || 0} chars`);
      } else {
        console.warn(`[Learning-Vision] Segment ${i + 1} analysis failed: ${segmentResult.error}`);
      }
    }
    
    // Scroll back to top
    await view.webContents.executeJavaScript(`window.scrollTo({ top: 0, behavior: 'instant' });`);
    
    // Combine all results
    const combinedDescription = allDescriptions.join('\n\n');
    
    console.log(`[Learning-Vision] Multi-segment analysis completed: ${combinedDescription.length} chars total`);
    
    return {
      success: true,
      description: combinedDescription,
      specs: allSpecs,
      images: [...new Set(allImages)]
    };
    
  } catch (error) {
    console.error(`[Learning-Vision] Multi-segment error:`, error);
    return { success: false, error: error.message };
  }
});

// ============ AI Vision Learning IPC Handlers ============

// Capture screenshot of learning view
ipcMain.handle('learning:capture-screenshot', async (event, platformId) => {
  try {
    const view = learningViews[platformId];
    if (!view || view.webContents.isDestroyed()) {
      return { success: false, error: 'Learning view not found' };
    }
    
    // Capture the page as PNG
    const image = await view.webContents.capturePage();
    const base64 = image.toPNG().toString('base64');
    
    console.log(`[Learning-Vision] Screenshot captured for ${platformId}, size: ${base64.length} chars`);
    
    return {
      success: true,
      image_base64: base64,
      width: image.getSize().width,
      height: image.getSize().height
    };
  } catch (error) {
    console.error(`[Learning-Vision] Screenshot error:`, error);
    return { success: false, error: error.message };
  }
});

// Execute action in learning view (click, scroll, etc.)
ipcMain.handle('learning:execute-action', async (event, platformId, action, params) => {
  try {
    const view = learningViews[platformId];
    if (!view || view.webContents.isDestroyed()) {
      return { success: false, error: 'Learning view not found' };
    }
    
    console.log(`[Learning-Vision] Executing action: ${action}`, params);
    
    switch (action) {
      case 'click': {
        // Click at specified position or on element matching selector
        if (params.selector) {
          // Click by CSS selector
          const result = await view.webContents.executeJavaScript(`
            (function() {
              const el = document.querySelector('${params.selector.replace(/'/g, "\\'")}');
              if (el) {
                el.click();
                return { success: true, clicked: true };
              }
              return { success: false, error: 'Element not found' };
            })()
          `);
          return result;
        } else if (params.text) {
          // Click element containing text
          const result = await view.webContents.executeJavaScript(`
            (function() {
              const text = '${params.text.replace(/'/g, "\\'")}';
              const elements = document.querySelectorAll('a, button, span, div, td, li');
              for (const el of elements) {
                if (el.textContent && el.textContent.includes(text)) {
                  el.click();
                  return { success: true, clicked: true, element: el.tagName };
                }
              }
              return { success: false, error: 'Element with text not found' };
            })()
          `);
          return result;
        } else if (params.x !== undefined && params.y !== undefined) {
          // Click at coordinates
          view.webContents.sendInputEvent({
            type: 'mouseDown',
            x: Math.round(params.x),
            y: Math.round(params.y),
            button: 'left',
            clickCount: 1
          });
          await new Promise(r => setTimeout(r, 50));
          view.webContents.sendInputEvent({
            type: 'mouseUp',
            x: Math.round(params.x),
            y: Math.round(params.y),
            button: 'left',
            clickCount: 1
          });
          return { success: true, clicked: true };
        }
        return { success: false, error: 'No click target specified' };
      }
      
      case 'scroll': {
        // Scroll the page
        const direction = params.direction || 'down';
        const amount = params.amount || 500;
        
        const scrollY = direction === 'up' ? -amount : amount;
        
        await view.webContents.executeJavaScript(`
          window.scrollBy({ top: ${scrollY}, behavior: 'smooth' });
        `);
        
        // Wait for scroll animation
        await new Promise(r => setTimeout(r, 500));
        
        return { success: true, scrolled: true, direction, amount };
      }
      
      case 'wait': {
        // Wait for specified milliseconds
        const ms = params.ms || 1000;
        await new Promise(r => setTimeout(r, ms));
        return { success: true, waited: ms };
      }
      
      case 'back': {
        // Navigate back
        if (view.webContents.canGoBack()) {
          view.webContents.goBack();
          // Wait for navigation
          await new Promise(resolve => {
            view.webContents.once('did-finish-load', resolve);
            setTimeout(resolve, 5000); // Timeout after 5s
          });
          return { success: true, navigated: 'back' };
        }
        return { success: false, error: 'Cannot go back' };
      }
      
      case 'extract': {
        // Extract page content using JavaScript
        const result = await view.webContents.executeJavaScript(`
          (function() {
            // Try to extract product info from current page
            const title = document.querySelector('h1, .product-title, .goods-title, [class*="title"]');
            const price = document.querySelector('[class*="price"], .price');
            const desc = document.querySelector('[class*="description"], [class*="detail"], .desc');
            
            return {
              title: title ? title.textContent.trim() : '',
              price: price ? price.textContent.trim() : '',
              description: desc ? desc.textContent.trim().substring(0, 500) : '',
              url: window.location.href
            };
          })()
        `);
        return { success: true, extracted: result };
      }
      
      default:
        return { success: false, error: `Unknown action: ${action}` };
    }
  } catch (error) {
    console.error(`[Learning-Vision] Execute action error:`, error);
    return { success: false, error: error.message };
  }
});

// AI Vision analysis via backend API
ipcMain.handle('learning:vision-analyze', async (event, imageBase64, pageType, sessionId) => {
  try {
    if (!apiService) {
      return { success: false, error: 'API service not initialized' };
    }
    
    const result = await apiService.visionAnalyze({
      image_base64: imageBase64,
      page_type: pageType || 'list',
      session_id: sessionId
    });
    
    return result;
  } catch (error) {
    console.error(`[Learning-Vision] Vision analyze error:`, error);
    return { success: false, error: error.message };
  }
});

// Process extracted product data via backend API
ipcMain.handle('learning:vision-extract', async (event, extractionData, sessionId, shopId) => {
  try {
    if (!apiService) {
      return { success: false, error: 'API service not initialized' };
    }
    
    const result = await apiService.visionExtract({
      extraction_data: extractionData,
      session_id: sessionId,
      shop_id: shopId,
      save_to_kb: true
    });
    
    return result;
  } catch (error) {
    console.error(`[Learning-Vision] Vision extract error:`, error);
    return { success: false, error: error.message };
  }
});

// AI Vision Learning Agent Main Loop
let visionAgentRunning = false;
let visionAgentStopRequested = false;

/**
 * Run the AI Vision Learning Agent
 * This function implements the main loop: screenshot -> analyze -> execute -> repeat
 */
async function runVisionLearningAgent(platformId, shopId, sessionId) {
  if (visionAgentRunning) {
    console.log('[Vision-Agent] Agent already running');
    return { success: false, error: 'Agent already running' };
  }
  
  visionAgentRunning = true;
  visionAgentStopRequested = false;
  
  const MAX_ITERATIONS = 100;  // Safety limit
  const MAX_SCROLL_PER_PAGE = 5;
  let iteration = 0;
  let scrollCount = 0;
  let productsProcessed = 0;
  let currentPageType = 'list';
  let extractedProducts = [];
  
  console.log(`[Vision-Agent] Starting for platform: ${platformId}, shop: ${shopId}`);
  
  // Notify renderer
  if (mainWindow) {
    mainWindow.webContents.send('learning:vision-started', {
      platform: platformId,
      sessionId
    });
  }
  
  try {
    while (iteration < MAX_ITERATIONS && !visionAgentStopRequested) {
      iteration++;
      console.log(`[Vision-Agent] Iteration ${iteration}, page type: ${currentPageType}`);
      
      // Step 1: Capture screenshot
      const view = learningViews[platformId];
      if (!view || view.webContents.isDestroyed()) {
        throw new Error('Learning view not available');
      }
      
      const image = await view.webContents.capturePage();
      const imageBase64 = image.toPNG().toString('base64');
      
      // Step 2: Send to vision API for analysis
      const analysisResult = await apiService.visionAnalyze({
        image_base64: imageBase64,
        page_type: currentPageType,
        session_id: sessionId,
        shop_id: shopId
      });
      
      if (!analysisResult.success) {
        console.error(`[Vision-Agent] Analysis failed:`, analysisResult.error);
        // Send progress update with error
        if (mainWindow) {
          mainWindow.webContents.send('learning:vision-error', {
            platform: platformId,
            error: analysisResult.error,
            iteration
          });
        }
        // Try to continue with fallback behavior
        await new Promise(r => setTimeout(r, 2000));
        continue;
      }
      
      const { action, data } = analysisResult;
      console.log(`[Vision-Agent] Action: ${action}`, data);
      
      // Send progress to renderer
      if (mainWindow) {
        mainWindow.webContents.send('learning:vision-progress', {
          platform: platformId,
          iteration,
          action,
          pageType: currentPageType,
          productsProcessed,
          data: data
        });
      }
      
      // Step 3: Execute the action
      switch (action) {
        case 'click': {
          // Click on the target element
          const clickParams = {};
          if (data.target?.product_name) {
            clickParams.text = data.target.product_name;
          } else if (data.target?.description) {
            clickParams.text = data.target.description;
          }
          
          const clickResult = await executeVisionAction(view, 'click', clickParams);
          
          if (clickResult.success) {
            // Wait for page to load
            await new Promise(r => setTimeout(r, 2000));
            // After clicking from list, we should be on detail page
            currentPageType = 'detail';
            scrollCount = 0;
          }
          break;
        }
        
        case 'scroll': {
          if (scrollCount >= MAX_SCROLL_PER_PAGE) {
            console.log('[Vision-Agent] Max scroll reached, moving to next action');
            // If we've scrolled too much on list page, we're done
            if (currentPageType === 'list') {
              visionAgentStopRequested = true;
            }
          } else {
            await executeVisionAction(view, 'scroll', { direction: 'down', amount: 400 });
            scrollCount++;
            await new Promise(r => setTimeout(r, 1000));
          }
          break;
        }
        
        case 'extract': {
          // Extract product information
          if (data.product_info) {
            // Process extracted data through backend
            const extractResult = await apiService.visionExtract({
              extraction_data: data,
              session_id: sessionId,
              shop_id: shopId,
              save_to_kb: true
            });
            
            if (extractResult.success) {
              productsProcessed++;
              extractedProducts.push({
                name: data.product_info.name,
                qaCount: extractResult.saved_count || 0
              });
              
              // Notify renderer
              if (mainWindow) {
                mainWindow.webContents.send('learning:product-processed', {
                  platform: platformId,
                  productName: data.product_info.name,
                  success: true,
                  qaCount: extractResult.saved_count || 0,
                  progress: {
                    processed: productsProcessed,
                    total: data.remaining_count ? productsProcessed + data.remaining_count : productsProcessed
                  }
                });
              }
            }
          }
          
          // If extraction complete, go back to list
          if (data.extraction_complete) {
            currentPageType = 'list';
            scrollCount = 0;
            // Navigate back
            if (view.webContents.canGoBack()) {
              view.webContents.goBack();
              await new Promise(r => setTimeout(r, 2000));
            }
          }
          break;
        }
        
        case 'back': {
          // Navigate back to list page
          if (view.webContents.canGoBack()) {
            view.webContents.goBack();
            await new Promise(r => setTimeout(r, 2000));
          }
          currentPageType = 'list';
          scrollCount = 0;
          break;
        }
        
        case 'done': {
          // All products processed
          console.log('[Vision-Agent] Received done signal, stopping');
          visionAgentStopRequested = true;
          break;
        }
        
        default: {
          console.log(`[Vision-Agent] Unknown action: ${action}, waiting...`);
          await new Promise(r => setTimeout(r, 2000));
        }
      }
      
      // Small delay between iterations
      await new Promise(r => setTimeout(r, 500));
    }
    
    // Complete
    console.log(`[Vision-Agent] Completed. Processed ${productsProcessed} products in ${iteration} iterations`);
    
    // Notify renderer
    if (mainWindow) {
      mainWindow.webContents.send('learning:vision-completed', {
        platform: platformId,
        productsProcessed,
        iterations: iteration,
        extractedProducts
      });
    }
    
    return {
      success: true,
      productsProcessed,
      iterations: iteration
    };
    
  } catch (error) {
    console.error('[Vision-Agent] Error:', error);
    if (mainWindow) {
      mainWindow.webContents.send('learning:vision-error', {
        platform: platformId,
        error: error.message
      });
    }
    return { success: false, error: error.message };
  } finally {
    visionAgentRunning = false;
    visionAgentStopRequested = false;
  }
}

/**
 * Helper function to execute vision-directed actions
 */
async function executeVisionAction(view, action, params) {
  try {
    switch (action) {
      case 'click': {
        if (params.text) {
          // Click element containing text
          const result = await view.webContents.executeJavaScript(`
            (function() {
              const text = '${params.text.replace(/'/g, "\\'")}';
              const elements = document.querySelectorAll('a, button, span, div, td, li, h1, h2, h3, h4, p');
              for (const el of elements) {
                if (el.textContent && el.textContent.includes(text)) {
                  el.click();
                  return { success: true, clicked: true, element: el.tagName };
                }
              }
              return { success: false, error: 'Element with text not found' };
            })()
          `);
          return result;
        }
        return { success: false, error: 'No click target' };
      }
      
      case 'scroll': {
        const direction = params.direction || 'down';
        const amount = params.amount || 400;
        const scrollY = direction === 'up' ? -amount : amount;
        
        await view.webContents.executeJavaScript(`
          window.scrollBy({ top: ${scrollY}, behavior: 'smooth' });
        `);
        return { success: true, scrolled: true };
      }
      
      default:
        return { success: false, error: `Unknown action: ${action}` };
    }
  } catch (error) {
    return { success: false, error: error.message };
  }
}

// IPC handler to start vision learning agent
ipcMain.handle('learning:start-vision-agent', async (event, platformId, shopId) => {
  const sessionId = `vision_${platformId}_${Date.now()}`;
  
  // Run agent in background
  runVisionLearningAgent(platformId, shopId, sessionId).catch(err => {
    console.error('[Vision-Agent] Unhandled error:', err);
  });
  
  return { success: true, sessionId };
});

// IPC handler to stop vision learning agent
ipcMain.handle('learning:stop-vision-agent', async () => {
  visionAgentStopRequested = true;
  return { success: true };
});

// ============ Shop Rotation & Auto-Refresh ============

/**
 * Get list of running shops from backend
 */
async function getRunningShops() {
  if (!apiService) return [];
  try {
    const result = await apiService.getShops();
    if (result.success && Array.isArray(result.data)) {
      return result.data.filter(shop => shop.status === 'running');
    }
  } catch (e) {
    console.error('[ShopRotation] Failed to get shops:', e.message);
  }
  return [];
}

/**
 * Check if current shop has pending messages
 */
async function checkCurrentShopPending() {
  const currentShop = store.get('currentShop');
  if (!currentShop) return false;
  
  const view = platformViews[currentShop.platformId];
  if (!view || view.webContents.isDestroyed()) return false;
  
  return new Promise((resolve) => {
    const requestId = `pending_${Date.now()}`;
    const timeout = setTimeout(() => {
      ipcMain.removeListener('platform:pending-result', handler);
      resolve(false);
    }, 3000);
    
    const handler = (event, result) => {
      if (result.requestId === requestId) {
        clearTimeout(timeout);
        ipcMain.removeListener('platform:pending-result', handler);
        // Log diagnostic info if available
        if (result.diagnostic) {
          console.log('[PDD-Diag]', JSON.stringify(result.diagnostic));
        }
        resolve(result.hasPending);
      }
    };
    
    ipcMain.on('platform:pending-result', handler);
    view.webContents.send('platform:check-pending', { requestId });
  });
}

/**
 * Switch to next running shop
 */
async function switchToNextRunningShop() {
  let runningShops = await getRunningShops();
  if (runningShops.length === 0) {
    console.log('[ShopRotation] No running shops found');
    return false;
  }
  
  // Filter out shops that were locally stopped (backend may not have processed yet)
  runningShops = runningShops.filter(s => !locallyStoppedShops.has(s.shop_id));
  if (runningShops.length === 0) {
    console.log('[ShopRotation] No running shops after filtering locally stopped');
    return false;
  }
  
  const currentShop = store.get('currentShop');
  const currentIndex = currentShop 
    ? runningShops.findIndex(s => s.shop_id === currentShop.shopId)
    : -1;
  
  // Get next shop (wrap around)
  const nextIndex = (currentIndex + 1) % runningShops.length;
  const nextShop = runningShops[nextIndex];
  
  // Don't switch if same shop
  if (currentShop && nextShop.shop_id === currentShop.shopId) {
    console.log('[ShopRotation] Only one running shop, staying');
    return false;
  }
  
  console.log(`[ShopRotation] Switching to shop: ${nextShop.shop_name}`);
  
  // Select the next shop (this will update BrowserView)
  const electronPlatform = mapBackendPlatformToElectron(nextShop.platform_type);
  if (!electronPlatform) {
    console.log(`[ShopRotation] Unsupported platform: ${nextShop.platform_type}`);
    return false;
  }
  
  showPlatformView(electronPlatform);
  
  // Update current shop context
  const credentials = store.get('shopCredentials') || {};
  const shopCreds = credentials[nextShop.shop_id] || {};
  const shopConfigs = store.get('shopConfigs') || {};
  const localConfig = shopConfigs[nextShop.shop_id] || {};
  
  store.set('currentShop', {
    shopId: nextShop.shop_id,
    shopName: nextShop.shop_name,
    platformId: electronPlatform,
    platformType: nextShop.platform_type,
    username: shopCreds.account || nextShop.account || '',
    password: shopCreds.password || '',
    config_json: Object.keys(localConfig).length > 0 ? localConfig : (nextShop.config_json || {})
  });
  
  // Notify renderer
  if (mainWindow) {
    mainWindow.webContents.send('shop:switched', { shop: nextShop });
  }
  
  return true;
}

/**
 * Refresh current shop's page to prevent freeze
 */
function refreshCurrentShopPage() {
  const currentShop = store.get('currentShop');
  if (!currentShop) return;
  
  const view = platformViews[currentShop.platformId];
  if (view && !view.webContents.isDestroyed()) {
    const now = Date.now();
    const lastRefresh = lastShopRefreshTime[currentShop.shopId] || 0;
    
    if (now - lastRefresh >= SHOP_REFRESH_INTERVAL) {
      console.log(`[ShopRefresh] Refreshing ${currentShop.shopName} page...`);
      view.webContents.reload();
      lastShopRefreshTime[currentShop.shopId] = now;
    }
  }
}

/**
 * Start shop rotation loop
 */
function startShopRotation() {
  if (shopRotationInterval) {
    clearInterval(shopRotationInterval);
  }
  
  console.log('[ShopRotation] Starting shop rotation loop');
  
  shopRotationInterval = setInterval(async () => {
    const autoReply = store.get('autoReply');
    if (!autoReply) return;  // Only rotate when auto-reply is enabled
    
    try {
      // Check if current shop has pending messages
      const hasPending = await checkCurrentShopPending();
      
      if (!hasPending) {
        console.log('[ShopRotation] Current shop has no pending messages, checking next...');
        await switchToNextRunningShop();
      }
      
      // Also check if page needs refresh
      refreshCurrentShopPage();
      
    } catch (e) {
      console.error('[ShopRotation] Error:', e.message);
    }
  }, SHOP_ROTATION_INTERVAL);
}

/**
 * Stop shop rotation loop
 */
function stopShopRotation() {
  if (shopRotationInterval) {
    clearInterval(shopRotationInterval);
    shopRotationInterval = null;
  }
  console.log('[ShopRotation] Stopped shop rotation loop');
}

/**
 * Clean up all active tasks - learning, debug, rotation
 * Called ONLY when app closes
 */
async function cleanupAllTasks() {
  console.log('[Cleanup] Cleaning up all active tasks...');
  
  // 1. Stop shop rotation
  stopShopRotation();
  
  // 2. Clean up learning tasks (close views and mark backend tasks as done)
  for (const [platformId, view] of Object.entries(learningViews)) {
    try {
      if (view._cleanupLoginCheck) view._cleanupLoginCheck();
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.removeBrowserView(view);
      }
      if (!view.webContents.isDestroyed()) {
        view.webContents.close();
      }
    } catch (e) {
      console.error(`[Cleanup] Error closing learning view ${platformId}:`, e.message);
    }
  }
  learningViews = {};
  
  // Complete current learning task on backend
  if (currentLearningTask && apiService) {
    try {
      await apiService.completeLearningTask(currentLearningTask.taskId);
      console.log(`[Cleanup] Completed learning task: ${currentLearningTask.taskId}`);
    } catch (e) {
      console.error('[Cleanup] Error completing learning task:', e.message);
    }
    currentLearningTask = null;
  }
  
  // Reset any stuck learning tasks on backend
  if (apiService) {
    try {
      const result = await apiService.resetAllLearningTasks();
      if (result.success && result.data?.reset_count > 0) {
        console.log(`[Cleanup] Reset ${result.data.reset_count} stuck learning tasks`);
      }
    } catch (e) {
      console.error('[Cleanup] Error resetting learning tasks:', e.message);
    }
  }
  
  // 3. Close debug window
  if (debugWindow && !debugWindow.isDestroyed()) {
    debugWindow.close();
    debugWindow = null;
  }
  if (debugCountdownTimer) {
    clearInterval(debugCountdownTimer);
    debugCountdownTimer = null;
  }
  pendingDebugMessage = null;
  
  // 4. Cleanup WeChat native adapter
  if (wechatAdapter) {
    try {
      await wechatAdapter.cleanup();
      console.log('[Cleanup] WeChat adapter cleaned up');
    } catch (e) {
      console.error('[Cleanup] Error cleaning up WeChat adapter:', e.message);
    }
    wechatAdapter = null;
  }
  
  console.log('[Cleanup] All tasks cleaned up');
}

/**
 * Clean up tasks for a specific shop only
 * Called when a single shop is stopped/paused/exited
 */
async function cleanupShopTasks(shopId, platformId) {
  console.log(`[Cleanup] Cleaning up tasks for shop ${shopId} (platform: ${platformId})...`);
  
  // 1. Clean up learning view for this platform
  const view = learningViews[platformId];
  if (view) {
    try {
      if (view._cleanupLoginCheck) view._cleanupLoginCheck();
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.removeBrowserView(view);
      }
      if (!view.webContents.isDestroyed()) {
        view.webContents.close();
      }
      delete learningViews[platformId];
      console.log(`[Cleanup] Closed learning view for ${platformId}`);
    } catch (e) {
      console.error(`[Cleanup] Error closing learning view ${platformId}:`, e.message);
    }
  }
  
  // 2. Complete current learning task if it belongs to this shop
  if (currentLearningTask && currentLearningTask.shopId === shopId && apiService) {
    try {
      await apiService.completeLearningTask(currentLearningTask.taskId);
      console.log(`[Cleanup] Completed learning task: ${currentLearningTask.taskId}`);
    } catch (e) {
      console.error('[Cleanup] Error completing learning task:', e.message);
    }
    currentLearningTask = null;
  }
  
  console.log(`[Cleanup] Shop ${shopId} tasks cleaned up`);
}

// ============ Auto Updater ============

/**
 * Setup auto-updater with electron-updater
 */
function setupAutoUpdater() {
  // Configure update source
  autoUpdater.setFeedURL({
    provider: 'generic',
    url: 'http://120.26.199.225:8080/releases/latest/win'
  });

  // Don't auto-download - let user confirm first
  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = true;

  autoUpdater.on('checking-for-update', () => {
    console.log('[Updater] Checking for updates...');
  });

  autoUpdater.on('update-available', (info) => {
    console.log('[Updater] Update available:', info.version);
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('update:available', {
        version: info.version,
        releaseNotes: info.releaseNotes || '',
        releaseDate: info.releaseDate || ''
      });
    }
  });

  autoUpdater.on('update-not-available', () => {
    console.log('[Updater] Already up to date');
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('update:not-available');
    }
  });

  autoUpdater.on('download-progress', (progress) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('update:progress', {
        percent: Math.round(progress.percent),
        transferred: progress.transferred,
        total: progress.total,
        bytesPerSecond: progress.bytesPerSecond
      });
    }
  });

  autoUpdater.on('update-downloaded', (info) => {
    console.log('[Updater] Update downloaded:', info.version);
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('update:downloaded', {
        version: info.version
      });
    }
  });

  autoUpdater.on('error', (err) => {
    // 404 means no release published yet - suppress this expected error
    if (err.message && err.message.includes('404')) {
      console.log('[Updater] No release published yet, skipping update check');
      return;
    }
    console.error('[Updater] Error:', err.message);
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('update:error', {
        message: err.message
      });
    }
  });
}

// Check for updates
ipcMain.handle('update:check', async () => {
  try {
    const result = await autoUpdater.checkForUpdates();
    return { success: true, data: result };
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// Download update
ipcMain.handle('update:download', async () => {
  try {
    await autoUpdater.downloadUpdate();
    return { success: true };
  } catch (error) {
    return { success: false, error: error.message };
  }
});

// Quit and install update
ipcMain.handle('update:install', () => {
  autoUpdater.quitAndInstall(false, true);
  return { success: true };
});

// Get current app version
ipcMain.handle('update:get-version', () => {
  return app.getVersion();
});

// ============ App Lifecycle ============

// Start backend server
function startBackendServer() {
  // Get backend path relative to electron-client directory
  const backendPath = path.resolve(__dirname, '..', 'backend');
  const managePy = path.join(backendPath, 'manage.py');
  
  console.log('[Backend] Starting backend server...');
  console.log('[Backend] Path:', backendPath);
  console.log('[Backend] manage.py:', managePy);
  
  // Use python to run manage.py runserver
  backendProcess = spawn('python', [managePy, 'runserver', '127.0.0.1:8000', '--noreload'], {
    cwd: backendPath,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' }
  });
  
  backendProcess.stdout.on('data', (data) => {
    console.log('[Backend]', data.toString().trim());
  });
  
  backendProcess.stderr.on('data', (data) => {
    console.log('[Backend]', data.toString().trim());
  });
  
  backendProcess.on('error', (err) => {
    console.error('[Backend] Failed to start:', err.message);
  });
  
  backendProcess.on('close', (code) => {
    console.log('[Backend] Process exited with code:', code);
    backendProcess = null;
  });
}

// Stop backend server
function stopBackendServer() {
  if (backendProcess) {
    console.log('[Backend] Stopping backend server...');
    if (process.platform === 'win32') {
      spawn('taskkill', ['/pid', backendProcess.pid, '/f', '/t']);
    } else {
      backendProcess.kill('SIGTERM');
    }
    backendProcess = null;
  }
}

app.whenReady().then(() => {
  // Setup auto-updater
  setupAutoUpdater();

  // Only start local backend if configured to do so
  const useLocalBackend = store.get('useLocalBackend');
  if (useLocalBackend) {
    console.log('[App] Starting local backend server...');
    startBackendServer();
  } else {
    console.log('[App] Using remote backend, skipping local backend startup');
  }
  
  // Wait for backend to start (or immediately if using remote), then create window
  setTimeout(() => {
    createMainWindow();

    // Initialize MQTT client for knowledge sync
    try {
      const serverUrl = store.get('serverUrl') || 'http://120.26.199.225:8080';
      const mqttHost = new URL(serverUrl).hostname;
      mqttClient = mqtt.connect(`mqtt://${mqttHost}:1883`, {
        clientId: `electron-${Date.now()}`,
        reconnectPeriod: 5000,
        connectTimeout: 10000,
      });
      mqttClient.on('connect', () => {
        console.log('[MQTT] Connected to broker');
      });
      mqttClient.on('error', (err) => {
        console.log('[MQTT] Connection error:', err.message);
      });
      mqttClient.on('message', (topic, payload) => {
        try {
          const data = JSON.parse(payload.toString());
          console.log('[MQTT] Received:', topic, data.action);
          if (mainWindow && !mainWindow.isDestroyed()) {
            mainWindow.webContents.send('knowledge:sync', data);
          }
        } catch (err) {
          console.log('[MQTT] Parse error:', err.message);
        }
      });
    } catch (err) {
      console.log('[MQTT] Init failed:', err.message);
    }

    // Initialize API service with stored credentials
    const serverUrl = store.get('serverUrl');
    const tokens = store.get('tokens');
    apiService = new ApiService(serverUrl);
    apiService.onTokenRefreshed((newTokens) => {
      store.set('tokens', newTokens);
    });
    if (tokens) {
      apiService.setTokens(tokens);
      // Reset all shop statuses to stopped on startup
      // since no BrowserViews are active on a fresh start
      apiService.resetAllShopStatuses().catch(err => {
        console.error('[App] Failed to reset shop statuses on startup:', err.message);
      });
      // Reset any stuck learning tasks from previous session
      apiService.resetAllLearningTasks().catch(err => {
        console.error('[App] Failed to reset learning tasks on startup:', err.message);
      });
    }
    
    // Start shop rotation after a delay (give time for shops to load)
    setTimeout(() => {
      startShopRotation();
      
      // Check if debug mode is already enabled on startup
      const debugMode = store.get('debugMode');
      if (debugMode) {
        console.log('[Debug] Debug mode was enabled, opening debug window...');
        createDebugWindow();
      }
      
      // Check for updates silently after startup
      setTimeout(() => {
        console.log('[Updater] Auto-checking for updates...');
        autoUpdater.checkForUpdates().catch(err => {
          console.log('[Updater] Auto-check failed:', err.message);
        });
      }, 3000);
    }, 5000);
  }, 3000);

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createMainWindow();
    }
  });
});

app.on('window-all-closed', async () => {
  // Clean up all tasks (learning, debug, rotation)
  await cleanupAllTasks();
  
  // Stop all running shops before shutting down
  if (apiService) {
    try {
      await apiService.resetAllShopStatuses();
    } catch (e) {
      console.error('[App] Failed to reset shop statuses on quit:', e.message);
    }
  }
  stopBackendServer();
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

// Handle certificate errors (for development)
app.on('certificate-error', (event, webContents, url, error, certificate, callback) => {
  if (url.includes('localhost')) {
    event.preventDefault();
    callback(true);
  } else {
    callback(false);
  }
});
