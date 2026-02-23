/**
 * Main Renderer Process Script
 * Shop Management Dashboard
 */

// ============ Application State ============
const appState = {
  isLoggedIn: false,
  shops: [],
  selectedShop: null,
  activeTab: 'workspace',
  editingShopId: null,
  batchDeleteMode: false,
  batchSelectedIds: new Set(),
  stats: { messages: 0, replies: 0, saved: 0 },
  // Track shops with new messages (shopId -> true)
  shopsWithNewMessages: new Set(),
  // Daily statistics
  dailyStats: {
    date: new Date().toDateString(),
    replies: 0,
    customers: new Set(),
    totalResponseTime: 0,
    responseCount: 0
  }
};

// ============ DOM Elements ============
const loginModal = document.getElementById('login-modal');
const loginBtn = document.getElementById('login-btn');
const logoutBtn = document.getElementById('logout-btn');
const shopList = document.getElementById('shop-list');
const workspaceView = document.getElementById('workspace-view');
const shopFormModal = document.getElementById('shop-form-modal');
const shopForm = document.getElementById('shop-form');
const shopFormTitle = document.getElementById('shop-form-title');
const shopModalClose = document.getElementById('shop-modal-close');
const cancelFormBtn = document.getElementById('cancel-form-btn');
const autoReplyToggle = document.getElementById('auto-reply-toggle');
const orderDetectToggle = document.getElementById('order-detect-toggle');
const debugModeToggle = document.getElementById('debug-mode-toggle');
const messageLog = document.getElementById('message-log');
const aiStatusBox = document.getElementById('ai-status-box');

// ============ Initialize ============
async function init() {
  try {
    console.log('[UI] init() starting...');

    const serverUrl = await window.electronAPI.store.get('serverUrl');
    if (serverUrl) {
      document.getElementById('server-url').value = serverUrl;
    }

    const autoReply = await window.electronAPI.store.get('autoReply');
    if (autoReplyToggle) {
      autoReplyToggle.checked = autoReply !== false;
    }

    const orderDetect = await window.electronAPI.store.get('orderDetect');
    if (orderDetectToggle) {
      orderDetectToggle.checked = orderDetect === true;
    }

    const debugMode = await window.electronAPI.store.get('debugMode');
    if (debugModeToggle) {
      debugModeToggle.checked = debugMode === true;
    }

    // Load daily statistics
    await loadDailyStats();

    setupEventListeners();
    setupMessageHandlers();
    setupUpdateHandlers();
    initApiSettingsListeners();

    // Check if already logged in
    const tokens = await window.electronAPI.store.get('tokens');
    if (tokens) {
      console.log('[UI] Found stored tokens, loading dashboard...');
      loginModal.style.display = 'none';
      const storedUsername = await window.electronAPI.store.get('username');
      if (storedUsername) {
        document.getElementById('user-display').textContent = storedUsername;
      } else {
        document.getElementById('user-display').textContent = '已登录';
      }
      await loadShops();
      appState.isLoggedIn = true;
      addLogMessage('system', '已自动登录');
      // Note: 不自动恢复店铺，需要用户手动点击启动
    }

    console.log('[UI] init() completed');
  } catch (error) {
    console.error('[UI] init() error:', error);
    // Show login modal on error
    if (loginModal) loginModal.style.display = 'flex';
  }
}

// ============ Event Listeners ============
function setupEventListeners() {
  // Login
  loginBtn.addEventListener('click', handleLogin);
  document.getElementById('password').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') handleLogin();
  });

  // Logout
  logoutBtn.addEventListener('click', handleLogout);

  // Shop form modal
  shopForm.addEventListener('submit', handleShopFormSubmit);
  cancelFormBtn.addEventListener('click', hideShopForm);
  shopModalClose.addEventListener('click', hideShopForm);

  // Platform pill buttons
  document.querySelectorAll('.platform-pill').forEach(pill => {
    pill.addEventListener('click', () => {
      document.querySelectorAll('.platform-pill').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      shopForm.platform_type.value = pill.dataset.platform;
    });
  });

  // Collapsible "更多设置" section
  const moreToggle = document.getElementById('sf-more-toggle');
  const moreBody = document.getElementById('sf-more-body');
  const collapseArrow = document.getElementById('sf-collapse-arrow');
  moreToggle.addEventListener('click', () => {
    const isOpen = moreBody.style.display !== 'none';
    moreBody.style.display = isOpen ? 'none' : 'block';
    collapseArrow.classList.toggle('open', !isOpen);
  });

  // Character counters
  shopForm.querySelectorAll('input[maxlength], textarea[maxlength]').forEach(field => {
    const counter = shopForm.querySelector(`.sf-count[data-for="${field.name}"]`);
    if (counter) {
      counter.textContent = field.value.length;
      field.addEventListener('input', () => {
        counter.textContent = field.value.length;
      });
    }
  });

  // Password visibility toggle
  const pwdToggle = document.getElementById('sf-pwd-toggle');
  const pwdInput = shopForm.querySelector('input[name="password"]');
  pwdToggle.addEventListener('click', () => {
    const isPassword = pwdInput.type === 'password';
    pwdInput.type = isPassword ? 'text' : 'password';
    pwdToggle.style.color = isPassword ? '#595959' : '#bfbfbf';
  });

  // Tab switching
  document.querySelectorAll('.nav-tab').forEach(tab => {
    tab.addEventListener('click', () => switchTab(tab.dataset.tab));
  });

  // Keywords sub-tab switching
  document.querySelectorAll('.kw-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.kw-tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.kw-tab-content').forEach(c => c.classList.remove('active'));
      tab.classList.add('active');
      const targetId = 'kw-' + tab.dataset.kwTab;
      document.getElementById(targetId)?.classList.add('active');
    });
  });

  // Keyword rules add button
  document.getElementById('kw-add-trigger')?.addEventListener('click', () => showKeywordRuleForm());
  
  // Sensitive word rules add button
  document.getElementById('kw-add-sensitive')?.addEventListener('click', () => showSensitiveRuleForm());
  
  // Scenario rules add button
  document.getElementById('scenario-add-btn')?.addEventListener('click', () => showScenarioRuleForm());

  // Auto reply toggle
  autoReplyToggle.addEventListener('change', async (e) => {
    await window.electronAPI.settings.setAutoReply(e.target.checked);
    updateAIStatus(e.target.checked);
    addLogMessage('system', `自动回复已${e.target.checked ? '开启' : '关闭'}`);
  });

  // Order detect toggle
  orderDetectToggle.addEventListener('change', async (e) => {
    await window.electronAPI.store.set('orderDetect', e.target.checked);
    addLogMessage('system', `识别订单已${e.target.checked ? '开启' : '关闭'}`);
  });

  // Debug mode toggle
  debugModeToggle.addEventListener('change', async (e) => {
    await window.electronAPI.store.set('debugMode', e.target.checked);
    addLogMessage('system', `调试模式已${e.target.checked ? '开启' : '关闭'}`);
  });

  // AI status box click to toggle
  aiStatusBox.addEventListener('click', () => {
    autoReplyToggle.checked = !autoReplyToggle.checked;
    autoReplyToggle.dispatchEvent(new Event('change'));
  });

  // "打开控制台" button - return to workspace view
  document.querySelector('.control-btn-area').addEventListener('click', () => {
    window.electronAPI.shops.hide();
    appState.selectedShop = null;
    workspaceView.style.display = 'block';
    renderShopList();
    renderWorkspaceShops();
  });

  // "显示所有" button
  document.getElementById('show-all-btn').addEventListener('click', () => {
    exitBatchDeleteMode();
    renderWorkspaceShops();
    addLogMessage('system', '已显示所有店铺');
  });

  // "批量删除" button
  document.getElementById('batch-delete-btn').addEventListener('click', () => {
    if (appState.shops.length === 0) {
      addLogMessage('system', '没有可删除的店铺');
      return;
    }
    enterBatchDeleteMode();
  });
}

// ============ Message Handlers ============
function setupMessageHandlers() {
  window.electronAPI.messages.onReceived((data) => {
    appState.stats.messages++;
    updateStats();
    addLogMessage('received', `${data.customerName}: ${data.message}`);
    
    // Track customer for daily stats (only from running shops)
    if (data.customerId) {
      checkAndResetDailyStats();
      appState.dailyStats.customers.add(data.customerId);
      // Record message receive time for response time calculation
      appState.pendingMessages = appState.pendingMessages || {};
      appState.pendingMessages[data.customerId] = Date.now();
      updateDailyStatsUI();
      saveDailyStats();
    }
    
    // Mark current shop as having new message
    if (appState.selectedShop) {
      appState.shopsWithNewMessages.add(appState.selectedShop.shop_id);
      renderShopList();
    }
  });

  window.electronAPI.messages.onReplied((data) => {
    appState.stats.replies++;
    if (data.source === 'knowledge_base' || data.source === 'cache') {
      appState.stats.saved++;
    }
    updateStats();
    addLogMessage('sent', `[回复] ${data.reply}`);
    
    // Update daily statistics
    checkAndResetDailyStats();
    appState.dailyStats.replies++;
    
    // Track unique customers
    if (data.customerId) {
      appState.dailyStats.customers.add(data.customerId);
      
      // Calculate response time if we have the receive timestamp
      appState.pendingMessages = appState.pendingMessages || {};
      const receiveTime = appState.pendingMessages[data.customerId];
      if (receiveTime) {
        const responseTime = (Date.now() - receiveTime) / 1000; // in seconds
        appState.dailyStats.totalResponseTime += responseTime;
        appState.dailyStats.responseCount++;
        delete appState.pendingMessages[data.customerId];
      }
    }
    
    updateDailyStatsUI();
    saveDailyStats();
    
    // Clear new message state for current shop after reply
    if (appState.selectedShop) {
      appState.shopsWithNewMessages.delete(appState.selectedShop.shop_id);
      renderShopList();
    }
  });

  window.electronAPI.messages.onError((data) => {
    addLogMessage('error', `[错误] ${data.error}`);
  });

  // Model unavailability warnings from backend
  window.electronAPI.messages.onLogWarn((msg) => {
    addLogMessage('error', msg);
  });

  // AI processing flow logs
  window.electronAPI.messages.onProcessLog((data) => {
    addLogMessage('system', data.message);
  });

  // Platform login success - update shop status to "已登录"
  window.electronAPI.messages.onLoginSuccess((data) => {
    const { platformId } = data;
    console.log('[UI] Platform login success:', platformId);
    // Find shops on this platform that are running and mark as logged in
    const platformMap = { pinduoduo: 'pdd', qianniu: 'taobao', douyin: 'douyin' };
    const backendPlatform = platformMap[platformId] || platformId;
    appState.shops.forEach(shop => {
      if (shop.platform_type === backendPlatform && shop.status === 'running') {
        shop.loggedIn = true;
      }
    });
    renderShopList();
    addLogMessage('system', `平台 ${platformId} 登录成功`);
  });
}

// ============ Login / Logout ============
async function handleLogin() {
  const serverUrl = document.getElementById('server-url').value.trim();
  const username = document.getElementById('username').value.trim();
  const password = document.getElementById('password').value;

  if (!serverUrl || !username || !password) {
    showLoginError('请填写所有字段');
    return;
  }

  loginBtn.disabled = true;
  loginBtn.textContent = '登录中...';

  await window.electronAPI.settings.setServerUrl(serverUrl);
  const result = await window.electronAPI.auth.login(username, password);

  if (result.success) {
    appState.isLoggedIn = true;
    const username = result.data.user.username;
    document.getElementById('user-display').textContent = username;
    await window.electronAPI.store.set('username', username);
    loginModal.style.display = 'none';
    await loadShops();
    addLogMessage('system', '登录成功');
  } else {
    showLoginError(result.error || '登录失败');
  }

  loginBtn.disabled = false;
  loginBtn.textContent = '登录';
}

async function handleLogout() {
  await window.electronAPI.store.set('tokens', null);
  await window.electronAPI.shops.hide();
  appState.isLoggedIn = false;
  appState.shops = [];
  appState.selectedShop = null;
  loginModal.style.display = 'flex';
  renderShopList();
  addLogMessage('system', '已退出登录');
}

function showLoginError(message) {
  document.getElementById('login-error').textContent = message;
}

// ============ Shop List ============
async function loadShops() {
  const result = await window.electronAPI.shops.list();

  if (result.success) {
    appState.shops = result.data || [];
  } else {
    appState.shops = [];
    addLogMessage('error', '加载店铺失败: ' + (result.error || '未知错误'));
  }
  
  // Always render shop list, even if empty
  renderShopList();
  renderWorkspaceShops();
}

function renderShopList() {
  const SHOP_COLOR_COUNT = 8;
  // Build shop cards HTML
  let html = appState.shops.map((shop, index) => {
    const isRunning = shop.status === 'running';
    const isLoggedIn = shop.loggedIn === true;
    const hasNewMessage = appState.shopsWithNewMessages.has(shop.shop_id);
    
    // Determine status text and class
    let statusText, statusClass;
    if (hasNewMessage && isRunning) {
      statusText = '新消息';
      statusClass = 'new-message';
    } else if (!isRunning) {
      statusText = '未启动';
      statusClass = 'inactive';
    } else if (isLoggedIn) {
      statusText = '已登录';
      statusClass = 'running';
    } else {
      statusText = '登录中...';
      statusClass = 'logging-in';
    }
    
    const platformText = shop.platform_display || shop.platform_type || '未知';
    const isPaused = shop.paused === true;
    const colorClass = `shop-color-${index % SHOP_COLOR_COUNT}`;
    const newMessageClass = hasNewMessage ? 'has-new-message' : '';
    
    // 根据状态显示不同的控制按钮
    let ctrlBtnsHtml;
    if (!isRunning) {
      // 未启动状态：显示启动按钮
      ctrlBtnsHtml = `
        <button class="shop-ctrl-btn shop-ctrl-start" data-start-id="${shop.shop_id}" title="启动">启动</button>
      `;
    } else if (isPaused) {
      // 已暂停状态：显示继续和退出按钮
      ctrlBtnsHtml = `
        <button class="shop-ctrl-btn shop-ctrl-resume" data-pause-id="${shop.shop_id}" title="继续">继续</button>
        <button class="shop-ctrl-btn shop-ctrl-exit" data-exit-id="${shop.shop_id}" title="退出">退出</button>
      `;
    } else {
      // 运行中状态：显示暂停和退出按钮
      ctrlBtnsHtml = `
        <button class="shop-ctrl-btn shop-ctrl-pause" data-pause-id="${shop.shop_id}" title="暂停">暂停</button>
        <button class="shop-ctrl-btn shop-ctrl-exit" data-exit-id="${shop.shop_id}" title="退出">退出</button>
      `;
    }
    
    return `
    <div class="shop-card ${colorClass} ${newMessageClass} ${appState.selectedShop && appState.selectedShop.shop_id === shop.shop_id ? 'active' : ''}"
         data-shop-id="${shop.shop_id}">
      <div class="shop-card-header">
        <div class="shop-card-name">${escapeHtml(shop.shop_name)}${hasNewMessage ? '<span class="shop-new-message-badge">新</span>' : ''}</div>
        <span class="shop-card-delete" data-delete-id="${shop.shop_id}" title="删除店铺">&times;</span>
      </div>
      <div class="shop-card-info">
        <span>状态: <em class="shop-status-text ${statusClass}">${statusText}</em></span>
        <span>平台: ${platformText}</span>
      </div>
      <div class="shop-card-actions">
        <button class="shop-manage-btn" data-manage-id="${shop.shop_id}">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>
          店铺管理
        </button>
        <div class="shop-ctrl-btns">
          ${ctrlBtnsHtml}
        </div>
      </div>
    </div>
  `;
  }).join('');

  shopList.innerHTML = html;

  // Bind click handlers for shop cards
  shopList.querySelectorAll('.shop-card').forEach(item => {
    item.addEventListener('click', (e) => {
      // Don't select shop if clicking delete, manage button, or control buttons
      if (e.target.closest('.shop-card-delete') || e.target.closest('.shop-manage-btn') || e.target.closest('.shop-ctrl-btn')) return;
      const shopId = item.dataset.shopId;
      const shop = appState.shops.find(s => s.shop_id === shopId);
      if (shop) selectShop(shop);
    });
  });

  // Bind delete buttons
  shopList.querySelectorAll('.shop-card-delete').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      deleteShop(btn.dataset.deleteId);
    });
  });

  // Bind manage buttons
  shopList.querySelectorAll('.shop-manage-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const shopId = btn.dataset.manageId;
      const shop = appState.shops.find(s => s.shop_id === shopId);
      if (shop) showShopForm(shop);
    });
  });

  // Bind pause/resume buttons
  shopList.querySelectorAll('[data-pause-id]').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const shopId = btn.dataset.pauseId;
      const shop = appState.shops.find(s => s.shop_id === shopId);
      if (shop) {
        const isPaused = shop.paused === true;
        if (isPaused) {
          // Resume
          await window.electronAPI.shops.resume(shopId);
          shop.paused = false;
          addLogMessage('system', `店铺 "${shop.shop_name}" 已继续运行`);
        } else {
          // Pause
          await window.electronAPI.shops.pause(shopId);
          shop.paused = true;
          addLogMessage('system', `店铺 "${shop.shop_name}" 已暂停`);
        }
        renderShopList();
      }
    });
  });

  // Bind exit buttons
  shopList.querySelectorAll('[data-exit-id]').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const shopId = btn.dataset.exitId;
      const shop = appState.shops.find(s => s.shop_id === shopId);
      if (shop) {
        if (confirm(`确定要退出店铺 "${shop.shop_name}" 吗？\n退出后登录状态将被清除，需要重新登录。`)) {
          // Clear selection FIRST to prevent any re-selection race conditions
          const wasSelected = appState.selectedShop && appState.selectedShop.shop_id === shopId;
          if (wasSelected) {
            appState.selectedShop = null;
            // Hide BrowserView immediately for instant visual feedback
            await window.electronAPI.shops.hide();
            workspaceView.style.display = 'block';
          }
          
          // Stop shop on backend
          await window.electronAPI.shops.stop(shopId);
          shop.status = 'stopped';
          shop.loggedIn = false;
          shop.paused = false;
          
          // Get platform ID for logout
          const platformId = mapPlatformTypeToId(shop.platform_type);
          
          // Logout - clear session and close BrowserView
          if (platformId) {
            await window.electronAPI.shops.logout(platformId);
          }
          
          addLogMessage('system', `店铺 "${shop.shop_name}" 已退出，登录状态已清除`);
          renderShopList();
          renderWorkspaceShops();
        }
      }
    });
  });

  // Bind start buttons
  shopList.querySelectorAll('[data-start-id]').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const shopId = btn.dataset.startId;
      const shop = appState.shops.find(s => s.shop_id === shopId);
      if (shop) {
        // Disable button to prevent double-clicks
        btn.disabled = true;
        btn.textContent = '启动中...';

        // Call backend to start shop
        const result = await window.electronAPI.shops.start(shopId);
        
        if (result.success) {
          shop.status = 'running';
          shop.loggedIn = false;  // Will be set to true when platform confirms login
          shop.paused = false;
          
          // Also select and open this shop
          await selectShop(shop);
          addLogMessage('system', `店铺 "${shop.shop_name}" 已启动`);
        } else {
          // Start failed - keep original status
          addLogMessage('error', `店铺 "${shop.shop_name}" 启动失败: ${result.error || '未知错误'}`);
          btn.disabled = false;
          btn.textContent = '启动';
        }
        
        renderShopList();
      }
    });
  });
}

function renderWorkspaceShops() {
  const container = document.getElementById('workspace-shops');

  // If in batch delete mode, render with checkboxes
  if (appState.batchDeleteMode) {
    renderBatchDeleteView(container);
    return;
  }

  let html = `
    <div class="shop-card-create workspace-create" id="add-shop-card-main">
      <div class="create-icon">+</div>
      <div class="create-label">创建店铺</div>
      <div class="create-hint">添加你的店铺账号</div>
    </div>
  `;

  html += appState.shops.map((shop, index) => {
    const colorClass = `shop-color-${index % 8}`;
    return `
    <div class="shop-card ${colorClass}" data-shop-id="${shop.shop_id}" style="width:200px;">
      <div class="shop-card-header">
        <div class="shop-card-name">${escapeHtml(shop.shop_name)}</div>
        <span class="shop-card-delete" data-delete-id="${shop.shop_id}" title="删除店铺">&times;</span>
      </div>
      <div class="shop-card-platform">${shop.platform_display || shop.platform_type}</div>
    </div>
  `;
  }).join('');

  container.innerHTML = html;

  // Bind click handlers
  container.querySelectorAll('.shop-card').forEach(item => {
    item.addEventListener('click', () => {
      const shopId = item.dataset.shopId;
      const shop = appState.shops.find(s => s.shop_id === shopId);
      if (shop) showShopDetail(shop);
    });
  });

  // Bind delete buttons
  container.querySelectorAll('.shop-card-delete').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      deleteShop(btn.dataset.deleteId);
    });
  });

  const createCard = container.querySelector('.shop-card-create');
  if (createCard) {
    createCard.addEventListener('click', () => showShopForm());
  }
}

// ============ Shop Delete ============
async function deleteShop(shopId) {
  const shop = appState.shops.find(s => s.shop_id === shopId);
  if (!shop) return;

  if (!confirm(`确定要删除店铺 "${shop.shop_name}" 吗？`)) return;

  const result = await window.electronAPI.shops.delete(shopId);
  if (result.success) {
    if (appState.selectedShop && appState.selectedShop.shop_id === shopId) {
      appState.selectedShop = null;
      workspaceView.style.display = 'block';
    }
    addLogMessage('system', `已删除店铺: ${shop.shop_name}`);
    await loadShops();
  } else {
    addLogMessage('error', `删除失败: ${result.error || '未知错误'}`);
  }
}

// ============ Batch Delete ============
function enterBatchDeleteMode() {
  appState.batchDeleteMode = true;
  appState.batchSelectedIds = new Set();
  renderWorkspaceShops();
}

function exitBatchDeleteMode() {
  appState.batchDeleteMode = false;
  appState.batchSelectedIds = new Set();
  renderWorkspaceShops();
}

function renderBatchDeleteView(container) {
  let html = `
    <div class="workspace-batch-bar">
      <span>已选择 <strong id="batch-count">0</strong> / ${appState.shops.length} 个店铺</span>
      <div class="batch-actions">
        <button class="batch-confirm-btn" id="batch-confirm-delete">确认删除</button>
        <button class="batch-cancel-btn" id="batch-cancel-delete">取消</button>
      </div>
    </div>
  `;

  html += '<div class="workspace-shops-grid">';
  html += appState.shops.map(shop => `
    <div class="shop-card shop-card-selectable" data-shop-id="${shop.shop_id}" style="width:200px;">
      <input type="checkbox" class="shop-card-checkbox" data-batch-id="${shop.shop_id}" />
      <div class="shop-card-header">
        <div class="shop-card-name">${escapeHtml(shop.shop_name)}</div>
      </div>
      <div class="shop-card-platform">${shop.platform_display || shop.platform_type}</div>
    </div>
  `).join('');
  html += '</div>';

  container.innerHTML = html;

  // Bind checkbox handlers
  container.querySelectorAll('.shop-card-checkbox').forEach(cb => {
    cb.addEventListener('change', () => {
      const id = cb.dataset.batchId;
      if (cb.checked) {
        appState.batchSelectedIds.add(id);
      } else {
        appState.batchSelectedIds.delete(id);
      }
      document.getElementById('batch-count').textContent = appState.batchSelectedIds.size;
    });
  });

  // Click on card toggles checkbox
  container.querySelectorAll('.shop-card-selectable').forEach(card => {
    card.addEventListener('click', (e) => {
      if (e.target.classList.contains('shop-card-checkbox')) return;
      const cb = card.querySelector('.shop-card-checkbox');
      cb.checked = !cb.checked;
      cb.dispatchEvent(new Event('change'));
    });
  });

  // Confirm delete
  document.getElementById('batch-confirm-delete').addEventListener('click', async () => {
    if (appState.batchSelectedIds.size === 0) {
      addLogMessage('system', '请先选择要删除的店铺');
      return;
    }
    const count = appState.batchSelectedIds.size;
    if (!confirm(`确定要删除选中的 ${count} 个店铺吗？`)) return;

    let successCount = 0;
    for (const shopId of appState.batchSelectedIds) {
      const result = await window.electronAPI.shops.delete(shopId);
      if (result.success) {
        successCount++;
        if (appState.selectedShop && appState.selectedShop.shop_id === shopId) {
          appState.selectedShop = null;
        }
      }
    }
    addLogMessage('system', `批量删除完成: 成功 ${successCount} 个`);
    appState.batchDeleteMode = false;
    appState.batchSelectedIds = new Set();
    await loadShops();
  });

  // Cancel
  document.getElementById('batch-cancel-delete').addEventListener('click', () => {
    exitBatchDeleteMode();
  });
}

// ============ Shop Selection ============
async function selectShop(shop) {
  appState.selectedShop = shop;

  // Hide workspace view for BrowserView
  workspaceView.style.display = 'none';

  if (appState.activeTab === 'workspace') {
    const result = await window.electronAPI.shops.select(shop);
    if (!result.success) {
      addLogMessage('error', result.error || '打开店铺失败');
      workspaceView.style.display = 'block';
      return;
    }

    // 不自动启动店铺，需要用户手动点击启动按钮
    // 只有当店铺状态已经是running时才保持，否则显示为未启动
    if (shop.status !== 'running') {
      shop.status = 'selected';
      shop.status_display = '已选择';
    }

    addLogMessage('system', `已打开店铺: ${shop.shop_name}`);
  }

  renderShopList();
  renderWorkspaceShops();
}

// ============ Shop Detail Page ============
const shopDetailModal = document.getElementById('shop-detail-modal');
const shopDetailClose = document.getElementById('shop-detail-close');
let currentDetailShop = null;

shopDetailClose.addEventListener('click', hideShopDetail);

// Tab switching for detail page
document.querySelectorAll('.sd-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.sd-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.sd-tab-content').forEach(c => c.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(`sd-${tab.dataset.sdTab}`).classList.add('active');

    // Load products when switching to products tab
    if (tab.dataset.sdTab === 'products' && currentDetailShop) {
      loadShopProducts(currentDetailShop.shop_id);
    }
  });
});

// Character counters for detail page
document.getElementById('sd-shop-knowledge').addEventListener('input', (e) => {
  document.getElementById('sd-knowledge-count').textContent = e.target.value.length;
});
document.getElementById('sd-system-prompt').addEventListener('input', (e) => {
  document.getElementById('sd-prompt-count').textContent = e.target.value.length;
});

// Save knowledge & prompt
document.getElementById('sd-save-knowledge').addEventListener('click', async () => {
  if (!currentDetailShop) return;
  const notes = document.getElementById('sd-shop-knowledge').value.trim();
  const systemPrompt = document.getElementById('sd-system-prompt').value.trim();

  const updateData = {
    notes: notes,
    config_json: {
      system_prompt: systemPrompt,
      ai_model: currentDetailShop.config_json?.ai_model || ''
    }
  };

  const result = await window.electronAPI.shops.update(currentDetailShop.shop_id, updateData);
  if (result.success) {
    addLogMessage('system', `店铺 "${currentDetailShop.shop_name}" 知识与提示词已保存`);
    // Update local state
    currentDetailShop.notes = notes;
    if (!currentDetailShop.config_json) currentDetailShop.config_json = {};
    currentDetailShop.config_json.system_prompt = systemPrompt;
  } else {
    addLogMessage('error', `保存失败: ${result.error || '未知错误'}`);
  }
});

function showShopDetail(shop) {
  currentDetailShop = shop;

  // Hide BrowserView if open
  if (appState.selectedShop) {
    window.electronAPI.shops.hide();
  }

  // Set title
  document.getElementById('shop-detail-title').textContent = `${shop.shop_name} - 店铺详情`;

  // Fill knowledge tab
  document.getElementById('sd-shop-knowledge').value = shop.notes || '';
  document.getElementById('sd-knowledge-count').textContent = (shop.notes || '').length;

  const config = shop.config_json || {};
  const prompt = config.system_prompt || '你是一名专业的电商客服，请根据我提供给你的上下文给出对客户的回复，你只需要输出对客户的回复即可，请勿包含任何其他内容。';
  document.getElementById('sd-system-prompt').value = prompt;
  document.getElementById('sd-prompt-count').textContent = prompt.length;

  // Fill info tab
  const infoGrid = document.getElementById('sd-info-grid');
  infoGrid.innerHTML = `
    <div class="sd-info-item">
      <span class="sd-info-label">店铺名称</span>
      <span class="sd-info-value">${escapeHtml(shop.shop_name)}</span>
    </div>
    <div class="sd-info-item">
      <span class="sd-info-label">平台</span>
      <span class="sd-info-value">${shop.platform_display || shop.platform_type || '未知'}</span>
    </div>
    <div class="sd-info-item">
      <span class="sd-info-label">登录账号</span>
      <span class="sd-info-value">${escapeHtml(shop.account || '未设置')}</span>
    </div>
    <div class="sd-info-item">
      <span class="sd-info-label">状态</span>
      <span class="sd-info-value">${shop.status === 'running' ? '运行中' : (shop.status_display || '未启动')}</span>
    </div>
    <div class="sd-info-item">
      <span class="sd-info-label">店铺链接</span>
      <span class="sd-info-value">${escapeHtml(shop.login_url || '未设置')}</span>
    </div>
    <div class="sd-info-item">
      <span class="sd-info-label">AI模型</span>
      <span class="sd-info-value">${config.ai_model || '默认'}</span>
    </div>
  `;

  // Reset to first tab
  document.querySelectorAll('.sd-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.sd-tab-content').forEach(c => c.classList.remove('active'));
  document.querySelector('.sd-tab[data-sd-tab="knowledge"]').classList.add('active');
  document.getElementById('sd-knowledge').classList.add('active');

  shopDetailModal.style.display = 'flex';

  // Preload products for when user switches to products tab
  loadShopProducts(shop.shop_id);

  // Load knowledge list for the knowledge tab
  loadShopKnowledgeList(shop.shop_id);
}

function hideShopDetail() {
  shopDetailModal.style.display = 'none';
  currentDetailShop = null;

  // Restore BrowserView if a shop was selected
  if (appState.selectedShop) {
    window.electronAPI.shops.select(appState.selectedShop);
  }
}

// Product management button handlers
document.getElementById('sd-product-add').addEventListener('click', () => {
  addLogMessage('system', '添加商品功能即将上线');
});

// Knowledge search/show-all handlers
document.getElementById('sd-kb-search-btn').addEventListener('click', () => {
  const query = document.getElementById('sd-kb-search-input').value.trim().toLowerCase();
  if (!query || !currentDetailShop) return;
  const rows = document.querySelectorAll('#sd-kb-tbody tr[data-qa-id]');
  rows.forEach(row => {
    const text = row.textContent.toLowerCase();
    row.style.display = text.includes(query) ? '' : 'none';
  });
});

document.getElementById('sd-kb-show-all').addEventListener('click', () => {
  if (currentDetailShop) loadShopKnowledgeList(currentDetailShop.shop_id);
});

// ============ Shop Knowledge List ============

async function loadShopKnowledgeList(shopId) {
  const tbody = document.getElementById('sd-kb-tbody');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="5" class="sd-kb-empty">加载中...</td></tr>';

  try {
    const result = await window.electronAPI.knowledge.list(shopId);
    if (!result.success || !result.data || result.data.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="sd-kb-empty">暂无数据</td></tr>';
      return;
    }

    const items = result.data;
    // Compute product-based numbering (X-Y)
    let productIndex = 0;
    let qaIndex = 0;
    let lastProductId = null;

    tbody.innerHTML = items.map(item => {
      let label = '—';
      if (item.product) {
        if (item.product !== lastProductId) {
          productIndex++;
          qaIndex = 1;
          lastProductId = item.product;
        } else {
          qaIndex++;
        }
        label = `${productIndex}-${qaIndex}`;
      }
      return `<tr data-qa-id="${item.id}">
        <td>${label}</td>
        <td title="${escapeHtml(item.product_name || '')}">${escapeHtml(item.product_name || '—')}</td>
        <td title="${escapeHtml(item.question || '')}">${escapeHtml(item.question || '')}</td>
        <td title="${escapeHtml(item.answer || '')}">${escapeHtml(item.answer || '')}</td>
        <td>
          <button class="pd-qa-btn pd-qa-delete" onclick="deleteShopKbItem(${item.id}, '${shopId}')">删除</button>
        </td>
      </tr>`;
    }).join('');
  } catch (error) {
    tbody.innerHTML = '<tr><td colspan="5" class="sd-kb-empty">加载失败</td></tr>';
  }
}

async function deleteShopKbItem(id, shopId) {
  if (!confirm('确定要删除这条知识吗？')) return;
  const result = await window.electronAPI.knowledge.delete(id);
  if (result.success) {
    addLogMessage('system', '知识库条目已删除');
    loadShopKnowledgeList(shopId);
  } else {
    addLogMessage('error', `删除失败: ${result.error || '未知错误'}`);
  }
}

// Make deleteShopKbItem available globally for inline onclick
window.deleteShopKbItem = deleteShopKbItem;

// ============ Knowledge Sync via MQTT ============
let _kbSyncTimer = null;
window.electronAPI.knowledge.onSync((data) => {
  console.log('[KnowledgeSync] Received:', data.action);
  // Debounce: if multiple events arrive within 1s, only refresh once
  if (_kbSyncTimer) clearTimeout(_kbSyncTimer);
  _kbSyncTimer = setTimeout(() => {
    _kbSyncTimer = null;
    if (currentDetailShop && currentDetailShop.shop_id) {
      loadShopKnowledgeList(currentDetailShop.shop_id);
      addLogMessage('system', '知识库已同步更新');
    }
  }, 1000);
});

// ============ Product Cards & Detail ============

async function loadShopProducts(shopId) {
  const container = document.getElementById('sd-products-list');
  if (!shopId) {
    container.innerHTML = '<div class="sd-empty-state"><p>暂无商品</p></div>';
    return;
  }
  container.innerHTML = '<div class="sd-empty-state"><p>加载中...</p></div>';
  
  // Exit batch mode when reloading
  exitProductBatchMode();
  
  try {
    const result = await window.electronAPI.products.list(shopId);
    // Handle both paginated ({count, results}) and direct ({success, data}) response formats
    let products = [];
    if (result) {
      if (Array.isArray(result.results)) {
        products = result.results;
      } else if (Array.isArray(result.data)) {
        products = result.data;
      } else if (result.data && Array.isArray(result.data.results)) {
        products = result.data.results;
      }
    }
    renderProductCards(products);
  } catch (error) {
    console.error('[Products] Failed to load:', error);
    container.innerHTML = '<div class="sd-empty-state"><p>加载失败</p></div>';
  }
}

function renderProductCards(products) {
  const container = document.getElementById('sd-products-list');
  
  if (!products || products.length === 0) {
    container.innerHTML = `
      <div class="sd-empty-state">
        <div class="sd-empty-box-icon">
          <svg width="80" height="80" viewBox="0 0 100 100" fill="none">
            <rect x="20" y="40" width="60" height="40" rx="4" fill="#f0f0f0" stroke="#d9d9d9" stroke-width="1.5"/>
            <path d="M20 50L35 40H65L80 50" stroke="#d9d9d9" stroke-width="1.5" fill="#fafafa"/>
            <rect x="40" y="45" width="20" height="12" rx="2" fill="#e8e8e8"/>
          </svg>
        </div>
        <p>暂无商品，请点击"AI学习店铺商品"开始学习</p>
      </div>
    `;
    return;
  }
  
  let html = '<div class="sd-product-grid">';
  products.forEach((product, idx) => {
    const imgHtml = product.image_url
      ? `<img src="${escapeHtml(product.image_url)}" alt="" class="sd-product-card-img" />`
      : `<div class="sd-product-card-img sd-product-card-placeholder"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#ccc" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg></div>`;
    const qaCount = product.qa_count || 0;
    const name = product.name || '未命名商品';
    html += `
      <div class="sd-product-card" data-product-id="${product.product_id}">
        <span class="sd-product-card-index">${idx + 1}</span>
        <button class="sd-product-card-delete" data-product-id="${product.product_id}" title="删除商品">&times;</button>
        ${imgHtml}
        <div class="sd-product-card-name" title="${escapeHtml(name)}">${escapeHtml(name)}</div>
        <div class="sd-product-card-qa">${qaCount} 条问答</div>
      </div>
    `;
  });
  html += '</div>';
  container.innerHTML = html;
  
  // Bind click events for opening detail
  container.querySelectorAll('.sd-product-card').forEach(card => {
    card.addEventListener('click', (e) => {
      // Don't open detail if in batch delete mode
      if (productBatchMode) return;
      // Don't open detail if delete button was clicked
      if (e.target.closest('.sd-product-card-delete')) return;
      const productId = card.dataset.productId;
      const product = products.find(p => p.product_id === productId);
      if (product) showProductDetail(product);
    });
  });
  
  // Bind delete buttons on cards
  container.querySelectorAll('.sd-product-card-delete').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const productId = btn.dataset.productId;
      const product = products.find(p => p.product_id === productId);
      const productName = product ? product.name : productId;
      if (!confirm(`确定要删除商品「${productName}」及其所有知识库数据吗？`)) return;
      btn.disabled = true;
      const result = await window.electronAPI.products.delete(productId);
      if (result.success) {
        addLogMessage('system', `商品「${productName}」已删除`);
        // Reload product cards
        if (currentDetailShop) loadShopProducts(currentDetailShop.shop_id);
      } else {
        addLogMessage('error', `删除失败: ${result.error || '未知错误'}`);
        btn.disabled = false;
      }
    });
  });
}

async function showProductDetail(product) {
  const modal = document.getElementById('product-detail-modal');
  // Store current product for reload after edit/delete
  modal._currentProduct = product;
  document.getElementById('pd-title').textContent = `${product.name} - 商品详情`;
  
  // Reset tabs
  modal.querySelectorAll('[data-pd-tab]').forEach(t => t.classList.remove('active'));
  modal.querySelectorAll('.sd-tab-content').forEach(c => c.classList.remove('active'));
  modal.querySelector('[data-pd-tab="pd-knowledge"]').classList.add('active');
  document.getElementById('pd-knowledge').classList.add('active');
  
  // Fill product info tab
  const infoGrid = document.getElementById('pd-info-grid');
  const imgHtml = product.image_url
    ? `<div class="pd-product-image"><img src="${escapeHtml(product.image_url)}" alt="" style="max-width:200px;max-height:200px;border-radius:8px;" /></div>`
    : '';
  infoGrid.innerHTML = `
    ${imgHtml}
    <div class="sd-info-item"><span class="sd-info-label">商品名称</span><span class="sd-info-value">${escapeHtml(product.name || '')}</span></div>
    <div class="sd-info-item"><span class="sd-info-label">SKU</span><span class="sd-info-value">${escapeHtml(product.sku || '无')}</span></div>
    <div class="sd-info-item"><span class="sd-info-label">价格</span><span class="sd-info-value">${product.price || 0} 元</span></div>
    <div class="sd-info-item"><span class="sd-info-label">库存</span><span class="sd-info-value">${product.stock || 0}</span></div>
    <div class="sd-info-item"><span class="sd-info-label">状态</span><span class="sd-info-value">${product.status === 'active' ? '在售' : '下架'}</span></div>
    <div class="sd-info-item"><span class="sd-info-label">平台商品ID</span><span class="sd-info-value">${escapeHtml(product.platform_product_id || '无')}</span></div>
  `;
  
  modal.style.display = 'flex';
  
  // Load QA list
  await loadProductKnowledge(product.product_id);
}

async function loadProductKnowledge(productId) {
  const qaList = document.getElementById('pd-qa-list');
  qaList.innerHTML = '<p class="pd-loading">加载中...</p>';
  
  try {
    const result = await window.electronAPI.products.knowledge(productId);
    // Handle both paginated ({count, results}) and direct ({success, data}) response formats
    let qaItems = [];
    if (result) {
      if (Array.isArray(result.results)) {
        qaItems = result.results;
      } else if (Array.isArray(result.data)) {
        qaItems = result.data;
      } else if (result.data && Array.isArray(result.data.results)) {
        qaItems = result.data.results;
      }
    }
    
    if (qaItems.length === 0) {
      qaList.innerHTML = '<div class="sd-empty-state"><p>暂无知识库数据</p></div>';
    } else {
      let tableHtml = `
        <table class="pd-qa-table">
          <thead>
            <tr><th style="width:30px">#</th><th style="width:30%">问题</th><th>回答</th><th style="width:90px">操作</th></tr>
          </thead>
          <tbody>
      `;
      qaItems.forEach((qa, idx) => {
        tableHtml += `
          <tr data-qa-id="${qa.id}">
            <td>${idx + 1}</td>
            <td class="pd-qa-question">${escapeHtml(qa.question || '')}</td>
            <td class="pd-qa-answer">${escapeHtml(qa.answer || '')}</td>
            <td class="pd-qa-actions">
              <button class="pd-qa-btn pd-qa-edit" data-qa-id="${qa.id}" title="编辑">编辑</button>
              <button class="pd-qa-btn pd-qa-delete" data-qa-id="${qa.id}" title="删除">删除</button>
            </td>
          </tr>
        `;
      });
      tableHtml += '</tbody></table>';
      qaList.innerHTML = tableHtml;
      
      // Bind edit buttons
      qaList.querySelectorAll('.pd-qa-edit').forEach(btn => {
        btn.addEventListener('click', () => {
          const qaId = btn.dataset.qaId;
          const qa = qaItems.find(q => String(q.id) === qaId);
          if (qa) showQaEditRow(btn.closest('tr'), qa, productId);
        });
      });
      
      // Bind delete buttons
      qaList.querySelectorAll('.pd-qa-delete').forEach(btn => {
        btn.addEventListener('click', async () => {
          const qaId = btn.dataset.qaId;
          if (!confirm('确定要删除这条知识吗？')) return;
          btn.disabled = true;
          btn.textContent = '删除中...';
          const result = await window.electronAPI.knowledge.delete(qaId);
          if (result.success) {
            addLogMessage('system', '知识库条目已删除');
            await loadProductKnowledge(productId);
          } else {
            addLogMessage('error', `删除失败: ${result.error || '未知错误'}`);
            btn.disabled = false;
            btn.textContent = '删除';
          }
        });
      });
    }
  } catch (error) {
    qaList.innerHTML = '<div class="sd-empty-state"><p>加载失败</p></div>';
  }
}

function showQaEditRow(tr, qa, productId) {
  const questionTd = tr.querySelector('.pd-qa-question');
  const answerTd = tr.querySelector('.pd-qa-answer');
  const actionsTd = tr.querySelector('.pd-qa-actions');
  
  // Replace text with input fields
  questionTd.innerHTML = `<textarea class="pd-qa-input" rows="2">${escapeHtml(qa.question || '')}</textarea>`;
  answerTd.innerHTML = `<textarea class="pd-qa-input" rows="2">${escapeHtml(qa.answer || '')}</textarea>`;
  actionsTd.innerHTML = `
    <button class="pd-qa-btn pd-qa-save" title="保存">保存</button>
    <button class="pd-qa-btn pd-qa-cancel" title="取消">取消</button>
  `;
  
  // Save handler
  actionsTd.querySelector('.pd-qa-save').addEventListener('click', async () => {
    const newQuestion = questionTd.querySelector('textarea').value.trim();
    const newAnswer = answerTd.querySelector('textarea').value.trim();
    if (!newQuestion || !newAnswer) {
      addLogMessage('error', '问题和回答不能为空');
      return;
    }
    const saveBtn = actionsTd.querySelector('.pd-qa-save');
    saveBtn.disabled = true;
    saveBtn.textContent = '保存中...';
    const result = await window.electronAPI.knowledge.update(qa.id, { question: newQuestion, answer: newAnswer });
    if (result.success) {
      addLogMessage('system', '知识库条目已更新');
      await loadProductKnowledge(productId);
    } else {
      addLogMessage('error', `更新失败: ${result.error || '未知错误'}`);
      saveBtn.disabled = false;
      saveBtn.textContent = '保存';
    }
  });
  
  // Cancel handler
  actionsTd.querySelector('.pd-qa-cancel').addEventListener('click', () => {
    loadProductKnowledge(productId);
  });
}

// Product detail modal close
document.getElementById('pd-close').addEventListener('click', () => {
  document.getElementById('product-detail-modal').style.display = 'none';
});

// Product detail tab switching
document.querySelectorAll('[data-pd-tab]').forEach(tab => {
  tab.addEventListener('click', () => {
    const modal = document.getElementById('product-detail-modal');
    modal.querySelectorAll('[data-pd-tab]').forEach(t => t.classList.remove('active'));
    modal.querySelectorAll('.sd-tab-content').forEach(c => c.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(tab.dataset.pdTab).classList.add('active');
  });
});

// Platform type mapping for learning system
function getLearningPlatformId(platformType) {
  const map = {
    'taobao': 'qianniu',
    'pdd': 'pinduoduo',
    'douyin': 'douyin',
    'kuaishou': 'kuaishou',
    'jd': 'jd',
    'xianyu': 'xianyu',
    'wechat': 'wechat'
  };
  return map[platformType] || platformType;
}

// Alias for platform type to ID mapping
function mapPlatformTypeToId(platformType) {
  return getLearningPlatformId(platformType);
}

let isLearningActive = false;
let currentLearningPlatformId = null;

// Learning Control Panel Elements
const learningControlPanel = document.getElementById('learning-control-panel');
const learningControlStatus = document.getElementById('learning-control-status');
const learningControlProgress = document.getElementById('learning-control-progress');
const learningCtrlProgressBar = document.getElementById('learning-ctrl-progress-bar');
const learningCtrlProgressText = document.getElementById('learning-ctrl-progress-text');
const learningStartBtn = document.getElementById('learning-start-btn');
const learningStopBtn = document.getElementById('learning-stop-btn');
const learningCloseBtn = document.getElementById('learning-close-btn');

function showLearningControlPanel() {
  learningControlPanel.style.display = 'block';
  learningControlStatus.textContent = '状态：请勾选需要学习的商品，并点击开始学习';
  learningControlProgress.style.display = 'none';
  learningStartBtn.style.display = 'inline-block';
  learningStartBtn.disabled = false;
  learningStopBtn.style.display = 'none';
  learningCtrlProgressBar.style.width = '0%';
  learningCtrlProgressText.textContent = '0 / 0 商品已处理';
  initLearningPanelDrag();
}

function hideLearningControlPanel() {
  learningControlPanel.style.display = 'none';
  if (currentLearningPlatformId) {
    window.electronAPI.learning.close(currentLearningPlatformId);
    currentLearningPlatformId = null;
  }
  isLearningActive = false;
}

// Make learning control panel draggable by its header
function initLearningPanelDrag() {
  const header = document.querySelector('.learning-control-header');
  if (!header || header._dragInitialized) return;
  header._dragInitialized = true;
  
  let isDragging = false;
  let offsetX = 0, offsetY = 0;
  
  header.addEventListener('mousedown', (e) => {
    // Don't drag if clicking the close button
    if (e.target.closest('.learning-control-close')) return;
    isDragging = true;
    const rect = learningControlPanel.getBoundingClientRect();
    offsetX = e.clientX - rect.left;
    offsetY = e.clientY - rect.top;
    e.preventDefault();
  });
  
  document.addEventListener('mousemove', (e) => {
    if (!isDragging) return;
    let newX = e.clientX - offsetX;
    let newY = e.clientY - offsetY;
    // No boundary constraints - allow free movement anywhere
    learningControlPanel.style.left = newX + 'px';
    learningControlPanel.style.top = newY + 'px';
    learningControlPanel.style.right = 'auto';
  });
  
  document.addEventListener('mouseup', () => {
    isDragging = false;
  });
}

function updateLearningControlStatus(text) {
  learningControlStatus.textContent = '状态：' + text;
}

function updateLearningControlProgress(processed, total) {
  learningControlProgress.style.display = 'block';
  const pct = total > 0 ? Math.round((processed / total) * 100) : 0;
  learningCtrlProgressBar.style.width = pct + '%';
  learningCtrlProgressText.textContent = `${processed} / ${total} 商品已处理 (${pct}%)`;
}

// Start Learning Button Click
learningStartBtn.addEventListener('click', async () => {
  if (!currentLearningPlatformId) return;
  
  learningStartBtn.disabled = true;
  learningStartBtn.textContent = '学习中...';
  learningStopBtn.style.display = 'inline-block';
  updateLearningControlStatus('正在提取商品数据...');
  
  // Trigger extraction
  await window.electronAPI.learning.extract(currentLearningPlatformId);
});

// Stop Learning Button Click
learningStopBtn.addEventListener('click', async () => {
  if (!currentLearningPlatformId) return;
  await window.electronAPI.learning.stop(currentLearningPlatformId);
  updateLearningControlStatus('已停止学习');
  learningStartBtn.style.display = 'inline-block';
  learningStartBtn.disabled = false;
  learningStartBtn.textContent = '开始学习';
  learningStopBtn.style.display = 'none';
  addLogMessage('system', '已停止学习任务');
});

// Close Panel Button Click
learningCloseBtn.addEventListener('click', () => {
  hideLearningControlPanel();
  hideShopDetail();
});

document.getElementById('sd-product-ai-learn').addEventListener('click', async () => {
  if (!currentDetailShop) return;
  if (isLearningActive) {
    addLogMessage('system', '学习任务正在进行中，请等待完成');
    return;
  }

  const platformId = getLearningPlatformId(currentDetailShop.platform_type);
  const shopId = currentDetailShop.shop_id;

  isLearningActive = true;
  currentLearningPlatformId = platformId;
  addLogMessage('system', `正在启动AI学习 "${currentDetailShop.shop_name}" 的店铺商品...`);

  // Show learning control panel
  showLearningControlPanel();
  updateLearningControlStatus('正在打开平台登录页面...');

  // Hide shop detail modal (so BrowserView is visible)
  shopDetailModal.style.display = 'none';

  try {
    const result = await window.electronAPI.learning.start(platformId, shopId);
    if (result.success || result.data) {
      addLogMessage('system', `学习任务已创建`);
      updateLearningControlStatus('请登录后勾选商品，点击开始学习');
    } else {
      addLogMessage('error', `启动学习失败: ${result.error || '未知错误'}`);
      hideLearningControlPanel();
    }
  } catch (error) {
    addLogMessage('error', `启动学习出错: ${error.message}`);
    hideLearningControlPanel();
  }
});

// Product batch delete state
let productBatchMode = false;
let productBatchSelectedIds = new Set();
let productBatchProducts = []; // Keep reference to current products

document.getElementById('sd-product-batch-delete').addEventListener('click', () => {
  if (!productBatchMode) {
    enterProductBatchMode();
  } else {
    confirmProductBatchDelete();
  }
});

function enterProductBatchMode() {
  productBatchMode = true;
  productBatchSelectedIds.clear();
  
  const btn = document.getElementById('sd-product-batch-delete');
  btn.innerHTML = '<span class="ws-btn-icon">&#10003;</span> 确认删除(0)';
  
  // Add cancel button if not already there
  let cancelBtn = document.getElementById('sd-product-batch-cancel');
  if (!cancelBtn) {
    cancelBtn = document.createElement('button');
    cancelBtn.id = 'sd-product-batch-cancel';
    cancelBtn.className = 'ws-btn ws-btn-default';
    cancelBtn.style.marginLeft = '8px';
    cancelBtn.textContent = '取消';
    cancelBtn.addEventListener('click', exitProductBatchMode);
    btn.parentElement.appendChild(cancelBtn);
  }
  cancelBtn.style.display = '';
  
  // Show checkboxes on product cards
  document.querySelectorAll('.sd-product-card').forEach(card => {
    card.classList.add('sd-product-selectable');
    
    // Add checkbox if not exists
    if (!card.querySelector('.sd-product-checkbox')) {
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.className = 'sd-product-checkbox';
      cb.addEventListener('click', (e) => e.stopPropagation());
      cb.addEventListener('change', (e) => {
        e.stopPropagation();
        const pid = card.dataset.productId;
        if (cb.checked) {
          productBatchSelectedIds.add(pid);
          card.classList.add('sd-product-selected');
        } else {
          productBatchSelectedIds.delete(pid);
          card.classList.remove('sd-product-selected');
        }
        updateProductBatchCount();
      });
      card.insertBefore(cb, card.firstChild);
    }
    
    // Override card click to toggle selection in batch mode
    card._batchClickHandler = (e) => {
      if (!productBatchMode) return;
      if (e.target.closest('.sd-product-card-delete')) return;
      // If user clicked directly on checkbox, let native behavior handle it
      if (e.target.classList.contains('sd-product-checkbox')) return;
      e.preventDefault();
      e.stopPropagation();
      const cb = card.querySelector('.sd-product-checkbox');
      if (cb) {
        cb.checked = !cb.checked;
        cb.dispatchEvent(new Event('change'));
      }
    };
    card.addEventListener('click', card._batchClickHandler);
  });
}

function exitProductBatchMode() {
  productBatchMode = false;
  productBatchSelectedIds.clear();
  
  const btn = document.getElementById('sd-product-batch-delete');
  btn.innerHTML = '<span class="ws-btn-icon">&#128465;</span> 批量删除';
  
  const cancelBtn = document.getElementById('sd-product-batch-cancel');
  if (cancelBtn) cancelBtn.style.display = 'none';
  
  // Remove checkboxes and selection styles
  document.querySelectorAll('.sd-product-card').forEach(card => {
    card.classList.remove('sd-product-selectable', 'sd-product-selected');
    const cb = card.querySelector('.sd-product-checkbox');
    if (cb) cb.remove();
    if (card._batchClickHandler) {
      card.removeEventListener('click', card._batchClickHandler);
      delete card._batchClickHandler;
    }
  });
}

function updateProductBatchCount() {
  const btn = document.getElementById('sd-product-batch-delete');
  const count = productBatchSelectedIds.size;
  btn.innerHTML = `<span class="ws-btn-icon">&#10003;</span> 确认删除(${count})`;
}

async function confirmProductBatchDelete() {
  const count = productBatchSelectedIds.size;
  if (count === 0) {
    addLogMessage('system', '请先勾选要删除的商品');
    return;
  }
  
  if (!confirm(`确定要删除选中的 ${count} 个商品及其所有知识库数据吗？`)) return;
  
  const btn = document.getElementById('sd-product-batch-delete');
  btn.disabled = true;
  btn.textContent = '删除中...';
  
  let successCount = 0;
  let failCount = 0;
  
  for (const pid of productBatchSelectedIds) {
    try {
      const result = await window.electronAPI.products.delete(pid);
      if (result.success) {
        successCount++;
      } else {
        failCount++;
      }
    } catch (e) {
      failCount++;
    }
  }
  
  addLogMessage('system', `批量删除完成: 成功 ${successCount} 个${failCount > 0 ? `, 失败 ${failCount} 个` : ''}`);
  
  btn.disabled = false;
  exitProductBatchMode();
  
  // Reload products
  if (currentDetailShop) loadShopProducts(currentDetailShop.shop_id);
}

// Learning progress UI
let learningState = { processed: 0, total: 0, logs: [] };

function showLearningProgress() {
  learningState = { processed: 0, total: 0, logs: [] };
  const container = document.getElementById('sd-products-list');
  container.innerHTML = `
    <div class="learning-progress-view">
      <div class="learning-status" id="learning-status">正在启动学习任务...</div>
      <div class="learning-progress-bar-wrap">
        <div class="learning-progress-bar" id="learning-progress-bar" style="width: 0%"></div>
      </div>
      <div class="learning-counter" id="learning-counter">0 / 0 商品已处理</div>
      <div class="learning-logs" id="learning-logs"></div>
      <button class="ws-btn ws-btn-danger" id="learning-stop-btn" style="margin-top:12px;">停止学习</button>
    </div>
  `;
  document.getElementById('learning-stop-btn').addEventListener('click', async () => {
    if (!currentDetailShop) return;
    const platformId = getLearningPlatformId(currentDetailShop.platform_type);
    await window.electronAPI.learning.stop(platformId);
    addLogMessage('system', '已停止学习任务');
    hideLearningProgress();
    isLearningActive = false;
  });
}

function hideLearningProgress() {
  const container = document.getElementById('sd-products-list');
  container.innerHTML = `
    <div class="sd-empty-state">
      <div class="sd-empty-box-icon">
        <svg width="80" height="80" viewBox="0 0 100 100" fill="none">
          <rect x="20" y="40" width="60" height="40" rx="4" fill="#f0f0f0" stroke="#d9d9d9" stroke-width="1.5"/>
          <path d="M20 50L35 40H65L80 50" stroke="#d9d9d9" stroke-width="1.5" fill="#fafafa"/>
          <rect x="40" y="45" width="20" height="12" rx="2" fill="#e8e8e8"/>
        </svg>
      </div>
      <p>暂无商品</p>
    </div>
  `;
}

function updateLearningStatus(text) {
  const el = document.getElementById('learning-status');
  if (el) el.textContent = text;
}

function updateLearningProgress() {
  const bar = document.getElementById('learning-progress-bar');
  const counter = document.getElementById('learning-counter');
  if (bar && counter) {
    const pct = learningState.total > 0 ? Math.round((learningState.processed / learningState.total) * 100) : 0;
    bar.style.width = pct + '%';
    counter.textContent = `${learningState.processed} / ${learningState.total} 商品已处理 (${pct}%)`;
  }
}

function addLearningLog(message) {
  learningState.logs.push(message);
  const el = document.getElementById('learning-logs');
  if (el) {
    const div = document.createElement('div');
    div.className = 'learning-log-item';
    div.textContent = message;
    el.appendChild(div);
    el.scrollTop = el.scrollHeight;
  }
}

// Learning event listeners
window.electronAPI.learning.onTaskCreated((data) => {
  updateLearningStatus('学习任务已创建，正在等待平台页面加载...');
  updateLearningControlStatus('学习任务已创建，请等待页面加载...');
  addLearningLog(`任务已创建: ${data.task_id}`);
});

window.electronAPI.learning.onReady((data) => {
  // Only show "select products" message if not already learning
  if (!isLearningActive) {
    updateLearningStatus('平台页面已加载，请勾选商品后点击开始学习');
    updateLearningControlStatus('请勾选需要学习的商品，并点击开始学习');
    addLearningLog('平台页面加载完成');
  } else {
    // Learning in progress - just log page load without changing status
    addLearningLog('页面已加载');
  }
});

window.electronAPI.learning.onStarted((data) => {
  isLearningActive = true;  // Mark learning as active
  updateLearningStatus('正在提取商品数据...');
  updateLearningControlStatus('正在提取商品数据...');
  addLearningLog('商品提取已开始');
});

window.electronAPI.learning.onProgress((data) => {
  isLearningActive = true;  // Ensure learning is marked as active
  const phase = data.phase || 'listing';
  
  if (phase === 'detail') {
    // Phase 2: Fetching product details
    const current = data.current || 0;
    const total = data.total || 0;
    const productName = data.productName ? data.productName.substring(0, 20) : '';
    const message = data.message || `正在获取商品详情 (${current}/${total})...`;
    updateLearningStatus(message);
    updateLearningControlStatus(message);
    if (productName) {
      addLearningLog(`获取详情: ${productName}...`);
    }
  } else {
    // Phase 1: Extracting product list
    const extracted = data.extracted || 0;
    const page = data.currentPage || 0;
    updateLearningStatus(`正在提取商品列表... 已提取 ${extracted} 个 (第${page}页)`);
    updateLearningControlStatus(`正在提取商品列表... 已提取 ${extracted} 个 (第${page}页)`);
  }
});

window.electronAPI.learning.onProductProcessed((data) => {
  if (data.progress) {
    learningState.processed = data.progress.processed;
    learningState.total = data.progress.total;
  } else {
    learningState.processed = learningState.processed + 1;
  }
  updateLearningProgress();
  updateLearningControlProgress(learningState.processed, learningState.total);
  const msg = data.success
    ? `✓ ${data.productName || '商品'} - 生成${data.qaCount || 0}条问答`
    : `✗ ${data.productName || '商品'} - 处理失败`;
  addLearningLog(msg);
  updateLearningStatus(`正在处理商品 (${learningState.processed}/${learningState.total})...`);
  updateLearningControlStatus(`正在处理商品 (${learningState.processed}/${learningState.total})...`);
});

window.electronAPI.learning.onCompleted((data) => {
  isLearningActive = false;
  updateLearningStatus('学习完成！');
  updateLearningControlStatus('学习完成！');
  const summary = `学习完成: 共处理 ${data.totalProducts || learningState.total} 个商品，成功 ${data.successCount || 0}，生成 ${data.qaGenerated || 0} 条问答`;
  addLearningLog(summary);
  addLogMessage('system', summary);

  // Update control panel buttons
  learningStartBtn.style.display = 'none';
  learningStopBtn.style.display = 'none';
  
  // Replace stop button with close button
  const stopBtn = document.getElementById('learning-stop-btn');
  if (stopBtn) {
    stopBtn.textContent = '完成';
    stopBtn.className = 'ws-btn ws-btn-default';
    stopBtn.onclick = () => hideLearningProgress();
  }

  // Refresh product cards after learning completes
  if (currentDetailShop) {
    loadShopProducts(currentDetailShop.shop_id);
  }
});

window.electronAPI.learning.onError((data) => {
  isLearningActive = false;
  const errMsg = data.error || data.message || '未知错误';
  updateLearningStatus(`学习出错: ${errMsg}`);
  updateLearningControlStatus(`学习出错: ${errMsg}`);
  addLearningLog(`错误: ${errMsg}`);
  addLogMessage('error', `AI学习出错: ${errMsg}`);
});

window.electronAPI.learning.onLog((data) => {
  addLearningLog(data.message || data);
});

// ============ AI Vision Learning Event Handlers ============

window.electronAPI.learning.onVisionStarted((data) => {
  addLogMessage('system', `AI视觉学习已启动 (会话: ${data.sessionId})`);
  updateLearningControlStatus('AI视觉学习已启动，正在分析页面...');
  addLearningLog('AI视觉智能体已启动');
});

window.electronAPI.learning.onVisionProgress((data) => {
  const { iteration, action, pageType, productsProcessed } = data;
  let statusText = `AI分析中 (第${iteration}轮) - `;
  
  switch (action) {
    case 'click':
      statusText += '正在点击商品...';
      break;
    case 'scroll':
      statusText += '正在滚动页面...';
      break;
    case 'extract':
      statusText += '正在提取商品信息...';
      break;
    case 'back':
      statusText += '正在返回列表...';
      break;
    default:
      statusText += `执行: ${action}`;
  }
  
  updateLearningControlStatus(statusText);
  addLearningLog(`[${pageType}] ${action}: 已处理 ${productsProcessed} 个商品`);
  
  // Update progress if we have data
  if (data.data && data.data.remaining_count !== undefined) {
    const total = productsProcessed + (data.data.remaining_count || 0);
    updateLearningControlProgress(productsProcessed, total);
  }
});

window.electronAPI.learning.onVisionCompleted((data) => {
  const { productsProcessed, iterations, extractedProducts } = data;
  
  isLearningActive = false;
  updateLearningControlStatus(`AI视觉学习完成！处理了 ${productsProcessed} 个商品`);
  addLearningLog(`学习完成: ${productsProcessed} 个商品，${iterations} 轮分析`);
  
  // Log extracted products
  if (extractedProducts && extractedProducts.length > 0) {
    extractedProducts.forEach(p => {
      addLearningLog(`  - ${p.name}: ${p.qaCount || 0} 条问答`);
    });
  }
  
  addLogMessage('system', `AI视觉学习完成: ${productsProcessed} 个商品`);
  
  // Update buttons
  learningStartBtn.style.display = 'none';
  learningStopBtn.style.display = 'none';
  
  // Refresh product list
  if (currentDetailShop) {
    loadShopProducts(currentDetailShop.shop_id);
  }
});

window.electronAPI.learning.onVisionError((data) => {
  const errMsg = data.error || '未知错误';
  updateLearningControlStatus(`AI视觉学习出错: ${errMsg}`);
  addLearningLog(`错误: ${errMsg}`);
  addLogMessage('error', `AI视觉学习出错: ${errMsg}`);
});

// ============ Shop Form ============
async function showShopForm(editShop) {
  // Hide BrowserView if a shop is currently open, to avoid it covering the modal
  if (appState.selectedShop) {
    window.electronAPI.shops.hide();
  }

  shopFormModal.style.display = 'flex';

  // Populate bind_shop dropdown with existing shops
  const bindShopSelect = shopForm.querySelector('select[name="bind_shop"]');
  let bindOpts = '<option value="">不绑定其他店铺</option>';
  appState.shops.forEach(s => {
    bindOpts += `<option value="${s.shop_id}">${escapeHtml(s.shop_name)}</option>`;
  });
  bindShopSelect.innerHTML = bindOpts;

  if (editShop) {
    appState.editingShopId = editShop.shop_id;
    shopFormTitle.textContent = '编辑店铺';
    shopForm.shop_name.value = editShop.shop_name || '';
    
    // Load credentials from local store
    const credentials = await window.electronAPI.store.get('shopCredentials') || {};
    console.log('[ShopForm] Loaded credentials:', credentials);
    const shopCreds = credentials[editShop.shop_id] || {};
    console.log('[ShopForm] Shop credentials for', editShop.shop_id, ':', shopCreds);
    
    shopForm.account.value = shopCreds.account || editShop.account || '';
    shopForm.password.value = shopCreds.password || '';
    
    shopForm.login_url.value = editShop.login_url || '';
    shopForm.notes.value = editShop.notes || '';

    // Set platform pill
    const platformType = editShop.platform_type || 'taobao';
    shopForm.platform_type.value = platformType;
    document.querySelectorAll('.platform-pill').forEach(p => {
      p.classList.toggle('active', p.dataset.platform === platformType);
    });

    // Set config_json fields - load from local store first, then fallback to API data
    const shopConfigs = await window.electronAPI.store.get('shopConfigs') || {};
    const localConfig = shopConfigs[editShop.shop_id] || {};
    const config = Object.keys(localConfig).length > 0 ? localConfig : (editShop.config_json || {});
    
    shopForm.system_prompt.value = config.system_prompt || '你是一名专业的电商客服，请根据我提供给你的上下文给出对客户的回复，你只需要输出对客户的回复即可，请勿包含任何其他内容。';
    shopForm.ai_model.value = config.ai_model || '';
    
    // Expand "更多设置" section if there are config values
    const moreBody = document.getElementById('sf-more-body');
    const collapseArrow = document.getElementById('sf-collapse-arrow');
    if (config.ai_model || config.system_prompt || editShop.login_url || editShop.notes) {
      moreBody.style.display = 'block';
      collapseArrow.classList.add('open');
    }
  } else {
    appState.editingShopId = null;
    shopFormTitle.textContent = '添加店铺';
    shopForm.reset();
    shopForm.platform_type.value = 'taobao';
    shopForm.system_prompt.value = '你是一名专业的电商客服，请根据我提供给你的上下文给出对客户的回复，你只需要输出对客户的回复即可，请勿包含任何其他内容。';

    // Reset platform pills to default
    document.querySelectorAll('.platform-pill').forEach(p => {
      p.classList.toggle('active', p.dataset.platform === 'taobao');
    });
    
    // Collapse "更多设置" section
    const moreBody = document.getElementById('sf-more-body');
    const collapseArrow = document.getElementById('sf-collapse-arrow');
    moreBody.style.display = 'none';
    collapseArrow.classList.remove('open');
  }

  // Update all character counters
  shopForm.querySelectorAll('input[maxlength], textarea[maxlength]').forEach(field => {
    const counter = shopForm.querySelector(`.sf-count[data-for="${field.name}"]`);
    if (counter) counter.textContent = field.value.length;
  });
}

function hideShopForm() {
  shopFormModal.style.display = 'none';

  // Restore BrowserView if a shop was selected
  if (appState.selectedShop) {
    window.electronAPI.shops.select(appState.selectedShop);
  }
}

async function handleShopFormSubmit(e) {
  e.preventDefault();

  const shopData = {
    shop_name: shopForm.shop_name.value.trim(),
    platform_type: shopForm.platform_type.value,
    account: shopForm.account.value.trim(),
    login_url: shopForm.login_url.value.trim(),
    notes: shopForm.notes.value.trim(),
    config_json: {
      system_prompt: shopForm.system_prompt.value.trim(),
      ai_model: shopForm.ai_model.value
    }
  };

  // Get credentials for local storage
  const account = shopForm.account.value.trim();
  const password = shopForm.password.value;

  // Remove empty optional fields
  if (!shopData.login_url) delete shopData.login_url;
  if (!shopData.notes) delete shopData.notes;
  if (!shopData.account) delete shopData.account;

  if (!shopData.shop_name || !shopData.platform_type) {
    addLogMessage('error', '请填写备注名称和选择平台');
    return;
  }

  let result;
  let shopId = appState.editingShopId;
  
  if (appState.editingShopId) {
    result = await window.electronAPI.shops.update(appState.editingShopId, shopData);
  } else {
    result = await window.electronAPI.shops.create(shopData);
    // Get new shop_id from result
    if (result.success && result.data) {
      shopId = result.data.shop_id;
    }
  }

  // Save credentials and config to local store (independent of backend API result)
  if (shopId) {
    const credentials = await window.electronAPI.store.get('shopCredentials') || {};
    credentials[shopId] = { account, password };
    await window.electronAPI.store.set('shopCredentials', credentials);
    
    // Save config_json locally (ai_model, system_prompt)
    const shopConfigs = await window.electronAPI.store.get('shopConfigs') || {};
    shopConfigs[shopId] = shopData.config_json || {};
    await window.electronAPI.store.set('shopConfigs', shopConfigs);
    
    console.log('[ShopForm] Credentials and config saved for shopId:', shopId, shopData.config_json);
  }

  if (result.success) {
    addLogMessage('system', `店铺 ${shopData.shop_name} ${appState.editingShopId ? '更新' : '创建'}成功`);
    hideShopForm();
    await loadShops();
  } else {
    // Still close the form and save credentials locally even if backend fails
    if (appState.editingShopId) {
      addLogMessage('system', `凭据已保存到本地 (后端同步失败: ${result.error || '未知错误'})`);
      hideShopForm();
    } else {
      addLogMessage('error', `操作失败: ${result.error || '未知错误'}`);
    }
  }
}

// ============ Tab Switching ============
function switchTab(tabName) {
  appState.activeTab = tabName;

  document.querySelectorAll('.nav-tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.tab === tabName);
  });

  // Hide all views first
  const keywordsView = document.getElementById('keywords-view');
  const monitoringView = document.getElementById('monitoring-view');
  const settingsView = document.getElementById('settings-view');
  
  workspaceView.style.display = 'none';
  if (keywordsView) keywordsView.style.display = 'none';
  if (monitoringView) monitoringView.style.display = 'none';
  if (settingsView) settingsView.style.display = 'none';
  window.electronAPI.shops.hide();

  if (tabName === 'workspace') {
    if (appState.selectedShop) {
      window.electronAPI.shops.select(appState.selectedShop);
    } else {
      workspaceView.style.display = 'block';
    }
  } else if (tabName === 'keywords') {
    if (keywordsView) {
      keywordsView.style.display = 'block';
      loadKeywordRules();
      loadSensitiveWordRules();
    }
  } else if (tabName === 'monitoring') {
    if (monitoringView) {
      monitoringView.style.display = 'block';
      loadScenarioRules();
    }
  } else if (tabName === 'settings') {
    if (settingsView) {
      settingsView.style.display = 'block';
      loadApiSettings();
    }
  } else {
    workspaceView.style.display = 'block';
  }
}

// ============ Keyword Rules Management ============

async function loadKeywordRules() {
  const tbody = document.getElementById('kw-trigger-tbody');
  if (!tbody) return;

  tbody.innerHTML = '<tr><td colspan="7" class="kw-empty">加载中...</td></tr>';

  const result = await window.electronAPI.keywordRules.list();
  if (!result.success || !result.data || result.data.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="kw-empty">暂无关键词规则</td></tr>';
    return;
  }

  tbody.innerHTML = result.data.map(rule => `
    <tr data-rule-id="${rule.rule_id}">
      <td>
        <label class="switch">
          <input type="checkbox" ${rule.is_active ? 'checked' : ''} onchange="toggleKeywordRule('${rule.rule_id}', this.checked)">
          <span class="slider"></span>
        </label>
      </td>
      <td>${escapeHtml(rule.name)}</td>
      <td class="kw-keywords-display" title="${escapeHtml(rule.keywords.replace(/\n/g, ', '))}">${escapeHtml(rule.keywords.split('\n').slice(0, 3).join(', '))}${rule.keywords.split('\n').length > 3 ? '...' : ''}</td>
      <td>${rule.match_type === 'contains' ? '包含任意' : rule.match_type === 'equals' ? '完全匹配' : '包含所有'}</td>
      <td class="kw-reply-display" title="${escapeHtml(rule.reply_text)}">${escapeHtml(rule.reply_text.substring(0, 50))}${rule.reply_text.length > 50 ? '...' : ''}</td>
      <td>${rule.priority}</td>
      <td>
        <button class="kw-action-btn kw-action-edit" onclick="editKeywordRule('${rule.rule_id}')">编辑</button>
        <button class="kw-action-btn kw-action-delete" onclick="deleteKeywordRule('${rule.rule_id}')">删除</button>
      </td>
    </tr>
  `).join('');
}

async function toggleKeywordRule(ruleId, isActive) {
  await window.electronAPI.keywordRules.update(ruleId, { is_active: isActive });
}

async function deleteKeywordRule(ruleId) {
  if (!confirm('确定要删除这条规则吗？')) return;
  const result = await window.electronAPI.keywordRules.delete(ruleId);
  if (result.success) {
    loadKeywordRules();
    addLogMessage('system', '关键词规则已删除');
  } else {
    alert('删除失败: ' + result.error);
  }
}

function editKeywordRule(ruleId) {
  showKeywordRuleForm(ruleId);
}

async function showKeywordRuleForm(ruleId = null) {
  let rule = null;
  if (ruleId) {
    const result = await window.electronAPI.keywordRules.list();
    rule = result.data?.find(r => r.rule_id === ruleId);
  }

  const modal = document.createElement('div');
  modal.className = 'rule-form-modal';
  modal.innerHTML = `
    <div class="rule-form-card">
      <div class="rule-form-header">
        <h3>${rule ? '编辑关键词规则' : '添加关键词规则'}</h3>
        <span class="rule-form-close" onclick="this.closest('.rule-form-modal').remove()">&times;</span>
      </div>
      <div class="rule-form-body">
        <div class="rule-form-row">
          <label>规则名称 *</label>
          <input type="text" id="kw-form-name" value="${rule?.name || ''}" placeholder="例如：发货询问">
        </div>
        <div class="rule-form-row">
          <label>关键词 *</label>
          <textarea id="kw-form-keywords" rows="4" placeholder="每行一个关键词">${rule?.keywords || ''}</textarea>
          <div class="rule-form-hint">每行输入一个关键词</div>
        </div>
        <div class="rule-form-row">
          <label>匹配方式</label>
          <select id="kw-form-match-type">
            <option value="contains" ${rule?.match_type === 'contains' ? 'selected' : ''}>包含任意关键词</option>
            <option value="equals" ${rule?.match_type === 'equals' ? 'selected' : ''}>完全匹配</option>
            <option value="all_contains" ${rule?.match_type === 'all_contains' ? 'selected' : ''}>包含所有关键词</option>
          </select>
        </div>
        <div class="rule-form-row">
          <label>预设回复 *</label>
          <textarea id="kw-form-reply" rows="4" placeholder="匹配关键词后的自动回复内容">${rule?.reply_text || ''}</textarea>
        </div>
        <div class="rule-form-row">
          <label>优先级</label>
          <input type="number" id="kw-form-priority" value="${rule?.priority || 0}" placeholder="数字越大优先级越高">
        </div>
        <div class="rule-form-row">
          <label>适用平台</label>
          <select id="kw-form-platform">
            <option value="" ${!rule?.platform ? 'selected' : ''}>所有平台</option>
            <option value="taobao" ${rule?.platform === 'taobao' ? 'selected' : ''}>淘宝/千牛</option>
            <option value="pdd" ${rule?.platform === 'pdd' ? 'selected' : ''}>拼多多</option>
            <option value="douyin" ${rule?.platform === 'douyin' ? 'selected' : ''}>抖音</option>
          </select>
        </div>
      </div>
      <div class="rule-form-footer">
        <button class="btn btn-cancel" onclick="this.closest('.rule-form-modal').remove()">取消</button>
        <button class="btn btn-primary" onclick="saveKeywordRule('${ruleId || ''}')">保存</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);
}

async function saveKeywordRule(ruleId) {
  const name = document.getElementById('kw-form-name').value.trim();
  const keywords = document.getElementById('kw-form-keywords').value.trim();
  const matchType = document.getElementById('kw-form-match-type').value;
  const replyText = document.getElementById('kw-form-reply').value.trim();
  const priority = parseInt(document.getElementById('kw-form-priority').value) || 0;
  const platform = document.getElementById('kw-form-platform').value;

  if (!name || !keywords || !replyText) {
    alert('请填写必填字段');
    return;
  }

  const data = { name, keywords, match_type: matchType, reply_text: replyText, priority, platform };

  let result;
  if (ruleId) {
    result = await window.electronAPI.keywordRules.update(ruleId, data);
  } else {
    result = await window.electronAPI.keywordRules.create(data);
  }

  if (result.success) {
    document.querySelector('.rule-form-modal')?.remove();
    loadKeywordRules();
    addLogMessage('system', ruleId ? '关键词规则已更新' : '关键词规则已创建');
  } else {
    alert('保存失败: ' + result.error);
  }
}

// ============ Sensitive Word Rules Management ============

async function loadSensitiveWordRules() {
  const tbody = document.getElementById('kw-sensitive-tbody');
  if (!tbody) return;

  tbody.innerHTML = '<tr><td colspan="5" class="kw-empty">加载中...</td></tr>';

  const result = await window.electronAPI.sensitiveWords.list();
  if (!result.success || !result.data || result.data.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="kw-empty">暂无敏感词规则</td></tr>';
    return;
  }

  tbody.innerHTML = result.data.map(rule => `
    <tr data-rule-id="${rule.rule_id}">
      <td>
        <label class="switch">
          <input type="checkbox" ${rule.is_active ? 'checked' : ''} onchange="toggleSensitiveRule('${rule.rule_id}', this.checked)">
          <span class="slider"></span>
        </label>
      </td>
      <td>${escapeHtml(rule.name || '未命名')}</td>
      <td class="kw-keywords-display" title="${escapeHtml(rule.sensitive_words.replace(/\n/g, ', '))}">${escapeHtml(rule.sensitive_words.split('\n').slice(0, 5).join(', '))}${rule.sensitive_words.split('\n').length > 5 ? '...' : ''}</td>
      <td>${escapeHtml(rule.replacement)}</td>
      <td>
        <button class="kw-action-btn kw-action-edit" onclick="editSensitiveRule('${rule.rule_id}')">编辑</button>
        <button class="kw-action-btn kw-action-delete" onclick="deleteSensitiveRule('${rule.rule_id}')">删除</button>
      </td>
    </tr>
  `).join('');
}

async function toggleSensitiveRule(ruleId, isActive) {
  await window.electronAPI.sensitiveWords.update(ruleId, { is_active: isActive });
}

async function deleteSensitiveRule(ruleId) {
  if (!confirm('确定要删除这条规则吗？')) return;
  const result = await window.electronAPI.sensitiveWords.delete(ruleId);
  if (result.success) {
    loadSensitiveWordRules();
    addLogMessage('system', '敏感词规则已删除');
  } else {
    alert('删除失败: ' + result.error);
  }
}

function editSensitiveRule(ruleId) {
  showSensitiveRuleForm(ruleId);
}

async function showSensitiveRuleForm(ruleId = null) {
  let rule = null;
  if (ruleId) {
    const result = await window.electronAPI.sensitiveWords.list();
    rule = result.data?.find(r => r.rule_id === ruleId);
  }

  const modal = document.createElement('div');
  modal.className = 'rule-form-modal';
  modal.innerHTML = `
    <div class="rule-form-card">
      <div class="rule-form-header">
        <h3>${rule ? '编辑敏感词规则' : '添加敏感词规则'}</h3>
        <span class="rule-form-close" onclick="this.closest('.rule-form-modal').remove()">&times;</span>
      </div>
      <div class="rule-form-body">
        <div class="rule-form-row">
          <label>规则名称</label>
          <input type="text" id="sw-form-name" value="${rule?.name || ''}" placeholder="例如：违禁词过滤">
        </div>
        <div class="rule-form-row">
          <label>敏感词列表 *</label>
          <textarea id="sw-form-words" rows="6" placeholder="每行一个敏感词">${rule?.sensitive_words || ''}</textarea>
          <div class="rule-form-hint">每行输入一个敏感词，AI回复中包含这些词时会被替换</div>
        </div>
        <div class="rule-form-row">
          <label>替换为</label>
          <input type="text" id="sw-form-replacement" value="${rule?.replacement || '***'}" placeholder="默认: ***">
        </div>
        <div class="rule-form-row">
          <label>适用平台</label>
          <select id="sw-form-platform">
            <option value="" ${!rule?.platform ? 'selected' : ''}>所有平台</option>
            <option value="taobao" ${rule?.platform === 'taobao' ? 'selected' : ''}>淘宝/千牛</option>
            <option value="pdd" ${rule?.platform === 'pdd' ? 'selected' : ''}>拼多多</option>
            <option value="douyin" ${rule?.platform === 'douyin' ? 'selected' : ''}>抖音</option>
          </select>
        </div>
      </div>
      <div class="rule-form-footer">
        <button class="btn btn-cancel" onclick="this.closest('.rule-form-modal').remove()">取消</button>
        <button class="btn btn-primary" onclick="saveSensitiveRule('${ruleId || ''}')">保存</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);
}

async function saveSensitiveRule(ruleId) {
  const name = document.getElementById('sw-form-name').value.trim();
  const sensitiveWords = document.getElementById('sw-form-words').value.trim();
  const replacement = document.getElementById('sw-form-replacement').value || '***';
  const platform = document.getElementById('sw-form-platform').value;

  if (!sensitiveWords) {
    alert('请填写敏感词列表');
    return;
  }

  const data = { name, sensitive_words: sensitiveWords, replacement, platform };

  let result;
  if (ruleId) {
    result = await window.electronAPI.sensitiveWords.update(ruleId, data);
  } else {
    result = await window.electronAPI.sensitiveWords.create(data);
  }

  if (result.success) {
    document.querySelector('.rule-form-modal')?.remove();
    loadSensitiveWordRules();
    addLogMessage('system', ruleId ? '敏感词规则已更新' : '敏感词规则已创建');
  } else {
    alert('保存失败: ' + result.error);
  }
}

// ============ Scenario Rules Management ============

const SCENARIO_TYPES = {
  angry: '客户愤怒',
  complaint: '投诉举报',
  urgent: '紧急问题',
  night_message: '深夜消息',
  refund_request: '退款请求',
  custom: '自定义'
};

const DETECTION_METHODS = {
  ai_judge: 'AI判断',
  keyword: '关键词匹配',
  time_based: '时间条件'
};

const ACTION_TYPES = {
  transfer_human: '转人工客服',
  send_reply: '发送特定回复',
  no_auto_reply: '不自动回复',
  notify_only: '仅通知'
};

async function loadScenarioRules() {
  const tbody = document.getElementById('scenario-tbody');
  if (!tbody) return;

  tbody.innerHTML = '<tr><td colspan="8" class="kw-empty">加载中...</td></tr>';

  const result = await window.electronAPI.scenarioRules.list();
  if (!result.success || !result.data || result.data.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" class="kw-empty">暂无情景规则</td></tr>';
    return;
  }

  tbody.innerHTML = result.data.map(rule => {
    const conditionText = formatTriggerCondition(rule.detection_method, rule.trigger_condition);
    return `
      <tr data-rule-id="${rule.rule_id}">
        <td>
          <label class="switch">
            <input type="checkbox" ${rule.is_active ? 'checked' : ''} onchange="toggleScenarioRule('${rule.rule_id}', this.checked)">
            <span class="slider"></span>
          </label>
        </td>
        <td>${escapeHtml(rule.name)}</td>
        <td><span class="scenario-type-badge scenario-type-${rule.scenario_type}">${SCENARIO_TYPES[rule.scenario_type] || rule.scenario_type}</span></td>
        <td>${DETECTION_METHODS[rule.detection_method] || rule.detection_method}</td>
        <td class="kw-keywords-display" title="${escapeHtml(conditionText)}">${escapeHtml(conditionText.substring(0, 30))}${conditionText.length > 30 ? '...' : ''}</td>
        <td><span class="action-type-badge action-type-${rule.action_type}">${ACTION_TYPES[rule.action_type] || rule.action_type}</span></td>
        <td>${rule.trigger_count || 0}</td>
        <td>
          <button class="kw-action-btn kw-action-edit" onclick="editScenarioRule('${rule.rule_id}')">编辑</button>
          <button class="kw-action-btn kw-action-delete" onclick="deleteScenarioRule('${rule.rule_id}')">删除</button>
        </td>
      </tr>
    `;
  }).join('');
}

function formatTriggerCondition(method, condition) {
  if (method === 'keyword') {
    return (condition.keywords || []).join(', ');
  } else if (method === 'time_based') {
    return `${condition.start_hour || 22}:00 - ${condition.end_hour || 6}:00`;
  } else if (method === 'ai_judge') {
    return condition.prompt || 'AI自动判断';
  }
  return JSON.stringify(condition);
}

async function toggleScenarioRule(ruleId, isActive) {
  await window.electronAPI.scenarioRules.update(ruleId, { is_active: isActive });
}

async function deleteScenarioRule(ruleId) {
  if (!confirm('确定要删除这条规则吗？')) return;
  const result = await window.electronAPI.scenarioRules.delete(ruleId);
  if (result.success) {
    loadScenarioRules();
    addLogMessage('system', '情景规则已删除');
  } else {
    alert('删除失败: ' + result.error);
  }
}

function editScenarioRule(ruleId) {
  showScenarioRuleForm(ruleId);
}

async function showScenarioRuleForm(ruleId = null) {
  let rule = null;
  if (ruleId) {
    const result = await window.electronAPI.scenarioRules.list();
    rule = result.data?.find(r => r.rule_id === ruleId);
  }

  const modal = document.createElement('div');
  modal.className = 'rule-form-modal';
  modal.innerHTML = `
    <div class="rule-form-card" style="width: 620px;">
      <div class="rule-form-header">
        <h3>${rule ? '编辑情景规则' : '添加情景规则'}</h3>
        <span class="rule-form-close" onclick="this.closest('.rule-form-modal').remove()">&times;</span>
      </div>
      <div class="rule-form-body">
        <div class="rule-form-row">
          <label>规则名称 *</label>
          <input type="text" id="sr-form-name" value="${rule?.name || ''}" placeholder="例如：愤怒客户转人工">
        </div>
        <div class="rule-form-row">
          <label>情景类型</label>
          <select id="sr-form-scenario-type">
            ${Object.entries(SCENARIO_TYPES).map(([k, v]) => `<option value="${k}" ${rule?.scenario_type === k ? 'selected' : ''}>${v}</option>`).join('')}
          </select>
        </div>
        <div class="rule-form-row">
          <label>检测方式</label>
          <select id="sr-form-detection-method" onchange="updateScenarioConditionUI()">
            ${Object.entries(DETECTION_METHODS).map(([k, v]) => `<option value="${k}" ${rule?.detection_method === k ? 'selected' : ''}>${v}</option>`).join('')}
          </select>
        </div>
        <div class="rule-form-row" id="sr-condition-row">
          <label>触发条件</label>
          <div id="sr-condition-input"></div>
        </div>
        <div class="rule-form-row">
          <label>触发动作</label>
          <select id="sr-form-action-type" onchange="updateScenarioActionUI()">
            ${Object.entries(ACTION_TYPES).map(([k, v]) => `<option value="${k}" ${rule?.action_type === k ? 'selected' : ''}>${v}</option>`).join('')}
          </select>
        </div>
        <div class="rule-form-row" id="sr-action-config-row" style="display:none;">
          <label>动作配置</label>
          <textarea id="sr-form-action-reply" rows="3" placeholder="回复内容模板">${rule?.action_config?.reply_template || ''}</textarea>
        </div>
        <div class="rule-form-row">
          <label>优先级</label>
          <input type="number" id="sr-form-priority" value="${rule?.priority || 0}" placeholder="数字越大优先级越高">
        </div>
        <div class="rule-form-row">
          <label>适用平台</label>
          <select id="sr-form-platform">
            <option value="" ${!rule?.platform ? 'selected' : ''}>所有平台</option>
            <option value="taobao" ${rule?.platform === 'taobao' ? 'selected' : ''}>淘宝/千牛</option>
            <option value="pdd" ${rule?.platform === 'pdd' ? 'selected' : ''}>拼多多</option>
            <option value="douyin" ${rule?.platform === 'douyin' ? 'selected' : ''}>抖音</option>
          </select>
        </div>
      </div>
      <div class="rule-form-footer">
        <button class="btn btn-cancel" onclick="this.closest('.rule-form-modal').remove()">取消</button>
        <button class="btn btn-primary" onclick="saveScenarioRule('${ruleId || ''}')">保存</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);

  // Store current rule for condition UI
  window._currentScenarioRule = rule;
  updateScenarioConditionUI();
  updateScenarioActionUI();
}

function updateScenarioConditionUI() {
  const method = document.getElementById('sr-form-detection-method').value;
  const container = document.getElementById('sr-condition-input');
  const rule = window._currentScenarioRule;

  if (method === 'keyword') {
    const keywords = rule?.trigger_condition?.keywords?.join('\n') || '';
    container.innerHTML = `<textarea id="sr-form-condition" rows="3" placeholder="每行一个触发关键词">${keywords}</textarea>
      <div class="rule-form-hint">买家消息包含这些关键词时触发</div>`;
  } else if (method === 'time_based') {
    const start = rule?.trigger_condition?.start_hour ?? 22;
    const end = rule?.trigger_condition?.end_hour ?? 6;
    container.innerHTML = `
      <div style="display:flex;gap:10px;align-items:center;">
        <input type="number" id="sr-form-start-hour" value="${start}" min="0" max="23" style="width:80px;"> 点 到
        <input type="number" id="sr-form-end-hour" value="${end}" min="0" max="23" style="width:80px;"> 点
      </div>
      <div class="rule-form-hint">在该时间段内收到消息时触发</div>`;
  } else {
    const prompt = rule?.trigger_condition?.prompt || '';
    container.innerHTML = `<textarea id="sr-form-condition" rows="3" placeholder="描述需要AI判断的情景，如：客户情绪激动或使用脏话">${prompt}</textarea>
      <div class="rule-form-hint">AI会根据描述自动判断是否触发</div>`;
  }
}

function updateScenarioActionUI() {
  const actionType = document.getElementById('sr-form-action-type').value;
  const configRow = document.getElementById('sr-action-config-row');
  configRow.style.display = actionType === 'send_reply' ? 'block' : 'none';
}

async function saveScenarioRule(ruleId) {
  const name = document.getElementById('sr-form-name').value.trim();
  const scenarioType = document.getElementById('sr-form-scenario-type').value;
  const detectionMethod = document.getElementById('sr-form-detection-method').value;
  const actionType = document.getElementById('sr-form-action-type').value;
  const priority = parseInt(document.getElementById('sr-form-priority').value) || 0;
  const platform = document.getElementById('sr-form-platform').value;

  if (!name) {
    alert('请填写规则名称');
    return;
  }

  // Build trigger condition based on detection method
  let triggerCondition = {};
  if (detectionMethod === 'keyword') {
    const keywords = document.getElementById('sr-form-condition')?.value.trim().split('\n').filter(k => k.trim());
    triggerCondition = { keywords };
  } else if (detectionMethod === 'time_based') {
    triggerCondition = {
      start_hour: parseInt(document.getElementById('sr-form-start-hour').value) || 22,
      end_hour: parseInt(document.getElementById('sr-form-end-hour').value) || 6
    };
  } else {
    triggerCondition = { prompt: document.getElementById('sr-form-condition')?.value.trim() || '' };
  }

  // Build action config
  let actionConfig = {};
  if (actionType === 'send_reply') {
    actionConfig.reply_template = document.getElementById('sr-form-action-reply').value.trim();
  }

  const data = {
    name,
    scenario_type: scenarioType,
    detection_method: detectionMethod,
    trigger_condition: triggerCondition,
    action_type: actionType,
    action_config: actionConfig,
    priority,
    platform
  };

  let result;
  if (ruleId) {
    result = await window.electronAPI.scenarioRules.update(ruleId, data);
  } else {
    result = await window.electronAPI.scenarioRules.create(data);
  }

  if (result.success) {
    document.querySelector('.rule-form-modal')?.remove();
    window._currentScenarioRule = null;
    loadScenarioRules();
    addLogMessage('system', ruleId ? '情景规则已更新' : '情景规则已创建');
  } else {
    alert('保存失败: ' + result.error);
  }
}

// Utility function
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text || '';
  return div.innerHTML;
}

// ============ AI Status ============
function updateAIStatus(running) {
  const indicator = aiStatusBox.querySelector('.ai-status-indicator');
  const text = aiStatusBox.querySelector('.ai-status-text strong');

  if (running) {
    indicator.className = 'ai-status-indicator running';
    text.textContent = 'AI运行中';
    aiStatusBox.style.background = '#f6ffed';
  } else {
    indicator.className = 'ai-status-indicator paused';
    text.textContent = 'AI已暂停';
    aiStatusBox.style.background = '#fffbe6';
  }
}

// ============ Stats ============
function updateStats() {
  // Stats shown in log messages for now
}

// ============ Daily Stats ============
function checkAndResetDailyStats() {
  const today = new Date().toDateString();
  if (appState.dailyStats.date !== today) {
    // Reset stats for new day
    appState.dailyStats = {
      date: today,
      replies: 0,
      customers: new Set(),
      totalResponseTime: 0,
      responseCount: 0
    };
    appState.pendingMessages = {};
  }
}

function updateDailyStatsUI() {
  const repliesEl = document.getElementById('stat-replies');
  const customersEl = document.getElementById('stat-customers');
  const avgTimeEl = document.getElementById('stat-avg-time');
  
  if (repliesEl) {
    repliesEl.textContent = appState.dailyStats.replies;
  }
  if (customersEl) {
    customersEl.textContent = appState.dailyStats.customers.size;
  }
  if (avgTimeEl) {
    const avgTime = appState.dailyStats.responseCount > 0 
      ? Math.round(appState.dailyStats.totalResponseTime / appState.dailyStats.responseCount)
      : 0;
    avgTimeEl.textContent = avgTime;
  }
}

async function saveDailyStats() {
  try {
    // Convert Set to Array for storage
    const statsToSave = {
      date: appState.dailyStats.date,
      replies: appState.dailyStats.replies,
      customers: Array.from(appState.dailyStats.customers),
      totalResponseTime: appState.dailyStats.totalResponseTime,
      responseCount: appState.dailyStats.responseCount
    };
    await window.electronAPI.store.set('dailyStats', statsToSave);
  } catch (error) {
    console.error('[DailyStats] Failed to save:', error);
  }
}

async function loadDailyStats() {
  try {
    const saved = await window.electronAPI.store.get('dailyStats');
    if (saved) {
      const today = new Date().toDateString();
      if (saved.date === today) {
        // Restore today's stats
        appState.dailyStats = {
          date: saved.date,
          replies: saved.replies || 0,
          customers: new Set(saved.customers || []),
          totalResponseTime: saved.totalResponseTime || 0,
          responseCount: saved.responseCount || 0
        };
      } else {
        // Different day, reset stats
        appState.dailyStats = {
          date: today,
          replies: 0,
          customers: new Set(),
          totalResponseTime: 0,
          responseCount: 0
        };
      }
    }
    updateDailyStatsUI();
  } catch (error) {
    console.error('[DailyStats] Failed to load:', error);
  }
}

// ============ Log ============
function addLogMessage(type, message) {
  const now = new Date();
  const dateStr = `${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  const timeStr = now.toLocaleTimeString();
  const div = document.createElement('div');
  div.className = `log-item log-${type}`;
  div.innerHTML = `<span class="log-time">${dateStr} ${timeStr}</span>${escapeHtml(message)}`;
  messageLog.insertBefore(div, messageLog.firstChild);

  while (messageLog.children.length > 100) {
    messageLog.removeChild(messageLog.lastChild);
  }
}

// ============ Utilities ============
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ============ Auto-Update Handlers ============

function setupUpdateHandlers() {
  const updateBar = document.getElementById('update-bar');
  const updateMessage = document.getElementById('update-message');
  const updateDownloadBtn = document.getElementById('update-download-btn');
  const updateInstallBtn = document.getElementById('update-install-btn');
  const updateDismissBtn = document.getElementById('update-dismiss-btn');
  const updateProgressWrap = document.getElementById('update-progress-wrap');
  const updateProgressFill = document.getElementById('update-progress-fill');
  const updateProgressText = document.getElementById('update-progress-text');

  if (!updateBar) return;

  // New version available
  window.electronAPI.updater.onUpdateAvailable((data) => {
    updateBar.style.display = 'flex';
    updateMessage.textContent = `发现新版本 v${data.version}，是否立即更新？`;
    updateDownloadBtn.style.display = 'inline-block';
    updateInstallBtn.style.display = 'none';
    updateProgressWrap.style.display = 'none';
    addLogMessage('system', `发现新版本 v${data.version}`);
  });

  // No update
  window.electronAPI.updater.onUpdateNotAvailable(() => {
    console.log('[Update] Already up to date');
  });

  // Download progress
  window.electronAPI.updater.onDownloadProgress((data) => {
    updateBar.style.display = 'flex';
    updateDownloadBtn.style.display = 'none';
    updateProgressWrap.style.display = 'flex';
    updateProgressFill.style.width = data.percent + '%';
    updateProgressText.textContent = data.percent + '%';
    updateMessage.textContent = '正在下载更新...';
  });

  // Download complete
  window.electronAPI.updater.onUpdateDownloaded((data) => {
    updateMessage.textContent = `v${data.version} 下载完成，重启后自动安装`;
    updateProgressWrap.style.display = 'none';
    updateDownloadBtn.style.display = 'none';
    updateInstallBtn.style.display = 'inline-block';
    addLogMessage('system', `v${data.version} 下载完成，等待安装`);
  });

  // Error
  window.electronAPI.updater.onUpdateError((data) => {
    console.error('[Update] Error:', data.message);
    updateBar.style.display = 'none';
  });

  // Button handlers
  updateDownloadBtn.addEventListener('click', () => {
    window.electronAPI.updater.downloadUpdate();
    updateDownloadBtn.style.display = 'none';
    updateProgressWrap.style.display = 'flex';
    updateMessage.textContent = '正在下载更新...';
  });

  updateInstallBtn.addEventListener('click', () => {
    window.electronAPI.updater.installUpdate();
  });

  updateDismissBtn.addEventListener('click', () => {
    updateBar.style.display = 'none';
  });
}

// ============================================
// API Settings Management
// ============================================

const apiSettingsState = {
  provider: 'deepseek',
  apiKeys: {
    deepseek_api_key: '',
    qwen_api_key: '',
    doubao_api_key: '',
    openai_api_key: '',
    gemini_api_key: ''
  },
  providerModels: {
    deepseek: [
      { label: 'DeepSeek Chat (V3)', value: 'deepseek-chat' },
      { label: 'DeepSeek Reasoner (R1)', value: 'deepseek-reasoner' }
    ],
    qwen: [
      { label: 'Qwen Turbo', value: 'qwen-turbo' },
      { label: 'Qwen Plus', value: 'qwen-plus' },
      { label: 'Qwen Max', value: 'qwen-max' },
      { label: 'Qwen Long', value: 'qwen-long' }
    ],
    doubao: [
      { label: '豆包 Seed 1.6', value: 'doubao-seed-1.6' },
      { label: '豆包 Pro 32K', value: 'doubao-pro-32k' },
      { label: '豆包 Lite 32K', value: 'doubao-lite-32k' }
    ],
    openai: [
      { label: 'GPT-4o Mini', value: 'gpt-4o-mini' },
      { label: 'GPT-4o', value: 'gpt-4o' },
      { label: 'GPT-4 Turbo', value: 'gpt-4-turbo' },
      { label: 'GPT-3.5 Turbo', value: 'gpt-3.5-turbo' }
    ],
    gemini: [
      { label: 'Gemini 2.0 Flash', value: 'gemini-2.0-flash' },
      { label: 'Gemini 1.5 Pro', value: 'gemini-1.5-pro' },
      { label: 'Gemini 1.5 Flash', value: 'gemini-1.5-flash' }
    ]
  },
  defaultBaseUrls: {
    deepseek: 'https://api.deepseek.com/v1',
    qwen: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    doubao: 'https://ark.cn-beijing.volces.com/api/v3',
    openai: 'https://api.openai.com/v1',
    gemini: 'https://generativelanguage.googleapis.com/v1beta/openai/'
  },
  providerKeyField: {
    deepseek: 'deepseek_api_key',
    qwen: 'qwen_api_key',
    doubao: 'doubao_api_key',
    openai: 'openai_api_key',
    gemini: 'gemini_api_key'
  }
};

// Initialize API Settings Event Listeners
function initApiSettingsListeners() {
  const form = document.getElementById('api-settings-form');
  if (!form) return;

  const providerSelect = document.getElementById('settings-provider');
  const modelSelect = document.getElementById('settings-model');
  const apiKeyInput = document.getElementById('settings-api-key');
  const baseUrlHint = document.getElementById('settings-base-url-hint');
  const temperatureSlider = document.getElementById('settings-temperature');
  const temperatureValue = document.getElementById('settings-temperature-value');
  const similaritySlider = document.getElementById('settings-similarity');
  const similarityValue = document.getElementById('settings-similarity-value');
  const pwdToggle = document.getElementById('settings-pwd-toggle');
  const resetBtn = document.getElementById('settings-reset-btn');

  // Provider change handler
  providerSelect.addEventListener('change', () => {
    const provider = providerSelect.value;
    apiSettingsState.provider = provider;
    
    // Update model options
    updateModelOptions(provider);
    
    // Update base URL hint
    baseUrlHint.textContent = '默认：' + apiSettingsState.defaultBaseUrls[provider];
    
    // Update API key field
    const keyField = apiSettingsState.providerKeyField[provider];
    apiKeyInput.value = apiSettingsState.apiKeys[keyField] || '';
  });

  // Temperature slider
  temperatureSlider.addEventListener('input', (e) => {
    temperatureValue.textContent = e.target.value;
  });

  // Similarity slider
  similaritySlider.addEventListener('input', (e) => {
    similarityValue.textContent = e.target.value;
  });

  // Password toggle
  pwdToggle.addEventListener('click', () => {
    const type = apiKeyInput.type === 'password' ? 'text' : 'password';
    apiKeyInput.type = type;
    pwdToggle.style.opacity = type === 'text' ? '0.8' : '0.5';
  });

  // Form submit
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    await saveApiSettings();
  });

  // Reset button
  resetBtn.addEventListener('click', () => {
    loadApiSettings();
  });

  // Initialize model options for default provider
  updateModelOptions(apiSettingsState.provider);
}

// Update model options based on selected provider
function updateModelOptions(provider) {
  const modelSelect = document.getElementById('settings-model');
  if (!modelSelect) return;
  
  const models = apiSettingsState.providerModels[provider] || [];
  
  modelSelect.innerHTML = models.map(m => 
    '<option value="' + m.value + '">' + m.label + '</option>'
  ).join('');
}

// Load API settings from backend
async function loadApiSettings() {
  const form = document.getElementById('api-settings-form');
  const saveBtn = document.getElementById('settings-save-btn');
  if (!form || !saveBtn) return;
  
  saveBtn.disabled = true;
  saveBtn.textContent = '加载中...';
  
  try {
    const result = await window.electronAPI.api.getApiSettings();
    
    if (result.success && result.data) {
      const data = result.data;
      
      // Set provider
      const provider = data.llm_provider || 'deepseek';
      apiSettingsState.provider = provider;
      form.llm_provider.value = provider;
      
      // Update models and select
      updateModelOptions(provider);
      if (data.llm_model) {
        form.llm_model.value = data.llm_model;
      }
      
      // Store all API keys (may be masked)
      ['deepseek_api_key', 'qwen_api_key', 'doubao_api_key', 'openai_api_key', 'gemini_api_key'].forEach(key => {
        if (data[key]) {
          apiSettingsState.apiKeys[key] = data[key];
        }
      });
      
      // Display current provider's key
      const keyField = apiSettingsState.providerKeyField[provider];
      form.api_key.value = apiSettingsState.apiKeys[keyField] || '';
      
      // Set other fields
      form.llm_base_url.value = data.llm_base_url || '';
      form.llm_temperature.value = data.llm_temperature || '0.3';
      document.getElementById('settings-temperature-value').textContent = form.llm_temperature.value;
      
      form.kb_similarity_threshold.value = data.kb_similarity_threshold || '0.7';
      document.getElementById('settings-similarity-value').textContent = form.kb_similarity_threshold.value;
      
      // Update base URL hint
      document.getElementById('settings-base-url-hint').textContent = 
        '默认：' + apiSettingsState.defaultBaseUrls[provider];
      
      addLogMessage('system', 'API 设置已加载');
    } else {
      addLogMessage('error', '加载 API 设置失败: ' + (result.error || '未知错误'));
    }
  } catch (error) {
    console.error('[Settings] Failed to load:', error);
    addLogMessage('error', '加载 API 设置出错: ' + error.message);
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = '保存设置';
  }
}

// Save API settings to backend
async function saveApiSettings() {
  const form = document.getElementById('api-settings-form');
  const saveBtn = document.getElementById('settings-save-btn');
  if (!form || !saveBtn) return;
  
  saveBtn.disabled = true;
  saveBtn.textContent = '保存中...';
  
  try {
    const provider = form.llm_provider.value;
    const apiKey = form.api_key.value.trim();
    
    // Validate API key - if it contains **** it's a masked key, user hasn't changed it
    if (!apiKey) {
      addLogMessage('error', '请输入 API Key');
      saveBtn.disabled = false;
      saveBtn.textContent = '保存设置';
      return;
    }
    
    // Update apiKeys state (only if it's a new key, not masked)
    const keyField = apiSettingsState.providerKeyField[provider];
    if (!apiKey.includes('****')) {
      apiSettingsState.apiKeys[keyField] = apiKey;
    }
    
    // Prepare payload - only include non-masked keys
    const payload = {
      llm_provider: provider,
      llm_model: form.llm_model.value,
      llm_base_url: form.llm_base_url.value.trim(),
      llm_temperature: form.llm_temperature.value,
      kb_similarity_threshold: form.kb_similarity_threshold.value
    };
    
    // Add API keys that are not masked
    Object.keys(apiSettingsState.apiKeys).forEach(key => {
      const value = apiSettingsState.apiKeys[key];
      if (value && !value.includes('****')) {
        payload[key] = value;
      }
    });
    
    // Also add the current key if it's new
    if (!apiKey.includes('****')) {
      payload[keyField] = apiKey;
    }
    
    const result = await window.electronAPI.api.saveApiSettings(payload);
    
    if (result.success) {
      addLogMessage('system', result.message || 'API 设置已保存');
      // Reload to get masked keys
      await loadApiSettings();
    } else {
      addLogMessage('error', '保存失败: ' + (result.error || '未知错误'));
    }
  } catch (error) {
    console.error('[Settings] Failed to save:', error);
    addLogMessage('error', '保存 API 设置出错: ' + error.message);
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = '保存设置';
  }
}

// ============ Initialize on Load ============
document.addEventListener('DOMContentLoaded', init);
