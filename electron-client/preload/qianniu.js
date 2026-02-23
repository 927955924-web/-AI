/**
 * Qianniu (Taobao/Tmall) Platform Preload Script
 * 利用"讲述人模式"（无障碍模式）进行稳定的消息抓取
 * 
 * 重要：用户需要在千牛中开启以下设置：
 * 1. 系统设置 → 网页浏览 → 启用页面讲述人模式（无障碍模式）
 * 2. 接待设置 → 开启气泡模式
 * 3. 窗口最大化，避免元素被遮挡
 */
const { contextBridge, ipcRenderer } = require('electron');

const PLATFORM_ID = 'qianniu';

// 无障碍模式下的选择器 - 更稳定，不易因前端更新失效
const SELECTORS = {
  // 无障碍模式下的消息容器 (ARIA标签)
  messageContainer: [
    '[role="log"]',
    '[role="list"][aria-label*="消息"]',
    '[aria-label*="聊天"]',
    '.message-list',
    '[class*="chat-content"]'
  ],
  
  // 消息项 (无障碍模式会添加role属性)
  messageItem: [
    '[role="listitem"]',
    '[role="article"]',
    '[aria-label*="消息"]',
    '.message-item',
    '[class*="msg-bubble"]'
  ],
  
  // 买家消息 (通过aria-label或class判断)
  buyerMessage: [
    '[aria-label*="买家"]',
    '[aria-label*="对方"]',
    '[aria-label*="收到"]',
    '[class*="other"]',
    '[class*="left"]',
    '[class*="receive"]'
  ],
  
  // 消息文本内容
  messageText: [
    '[role="text"]',
    '[aria-label]',
    '.message-text',
    '.msg-content',
    '[class*="text"]'
  ],
  
  // 输入框 (无障碍模式下有明确的role)
  inputBox: [
    '[role="textbox"]',
    'textarea[aria-label*="输入"]',
    'textarea[aria-label*="回复"]',
    '[contenteditable="true"]',
    'textarea.chat-input',
    '[class*="editor"] textarea'
  ],
  
  // 发送按钮
  sendButton: [
    '[role="button"][aria-label*="发送"]',
    'button[aria-label*="发送"]',
    '[aria-label="发送"]',
    'button.send-btn',
    '[class*="send"]'
  ],
  
  // 当前会话买家信息
  buyerInfo: [
    '[role="heading"]',
    '[aria-label*="买家"]',
    '.buyer-nick',
    '.customer-name',
    '[class*="nick"]'
  ],
  
  // 会话列表
  sessionList: [
    '[role="listbox"]',
    '[role="menu"]',
    '.session-list',
    '[class*="contact-list"]'
  ],
  
  // 当前选中会话
  activeSession: [
    '[aria-selected="true"]',
    '[aria-current="true"]',
    '.active',
    '.selected',
    '[class*="current"]'
  ]
};

// 状态管理
let state = {
  lastMessageHash: null,
  currentBuyer: null,
  isObserving: false,
  messageQueue: [],
  processedMessages: new Set()
};

/**
 * 查找元素 - 尝试多个选择器
 */
function findElement(selectorList) {
  for (const selector of selectorList) {
    const el = document.querySelector(selector);
    if (el) return el;
  }
  return null;
}

/**
 * 查找所有元素
 */
function findAllElements(selectorList) {
  const results = [];
  const seen = new Set();
  
  for (const selector of selectorList) {
    const elements = document.querySelectorAll(selector);
    elements.forEach(el => {
      if (!seen.has(el)) {
        seen.add(el);
        results.push(el);
      }
    });
  }
  
  return results;
}

/**
 * 从元素提取文本内容（支持无障碍属性）
 */
function extractText(element) {
  if (!element) return '';
  
  // 优先使用aria-label
  const ariaLabel = element.getAttribute('aria-label');
  if (ariaLabel && !ariaLabel.includes('消息') && !ariaLabel.includes('发送')) {
    return ariaLabel.trim();
  }
  
  // 然后使用textContent
  const text = element.textContent || element.innerText || '';
  return text.trim();
}

/**
 * 生成消息哈希用于去重
 */
function hashMessage(text, timestamp) {
  return `${text.substring(0, 50)}_${Math.floor(timestamp / 1000)}`;
}

/**
 * 判断元素是否为买家消息
 */
function isBuyerMessage(element) {
  // 检查aria-label
  const ariaLabel = (element.getAttribute('aria-label') || '').toLowerCase();
  if (ariaLabel.includes('买家') || ariaLabel.includes('对方') || ariaLabel.includes('收到')) {
    return true;
  }
  
  // 检查class
  const className = (element.className || '').toLowerCase();
  if (className.includes('other') || className.includes('left') || 
      className.includes('receive') || className.includes('buyer')) {
    return true;
  }
  
  // 检查父元素
  const parent = element.closest('[class*="other"], [class*="left"], [aria-label*="买家"]');
  if (parent) return true;
  
  // 检查data属性
  const role = element.getAttribute('data-role') || element.getAttribute('data-type') || '';
  if (role.includes('buyer') || role.includes('customer') || role.includes('other')) {
    return true;
  }
  
  return false;
}

/**
 * 获取当前买家信息
 */
function getCurrentBuyer() {
  // 方法1: 从当前选中会话获取
  const activeSession = findElement(SELECTORS.activeSession);
  if (activeSession) {
    const nameEl = activeSession.querySelector('[class*="nick"], [class*="name"]');
    if (nameEl) {
      return {
        id: activeSession.getAttribute('data-id') || 
            activeSession.getAttribute('data-uid') || 
            `qn_${Date.now()}`,
        name: extractText(nameEl) || '买家'
      };
    }
  }
  
  // 方法2: 从聊天头部获取
  const buyerInfo = findElement(SELECTORS.buyerInfo);
  if (buyerInfo) {
    return {
      id: `qn_${Date.now()}`,
      name: extractText(buyerInfo) || '买家'
    };
  }
  
  return { id: `qn_${Date.now()}`, name: '买家' };
}

/**
 * 提取所有买家消息
 */
function extractBuyerMessages() {
  const messages = [];
  const container = findElement(SELECTORS.messageContainer);
  
  if (!container) {
    console.log('[千牛] 未找到消息容器，请确认已开启讲述人模式');
    return messages;
  }
  
  // 获取所有消息项
  const messageItems = findAllElements(SELECTORS.messageItem);
  
  messageItems.forEach((item, index) => {
    if (isBuyerMessage(item)) {
      // 查找消息文本
      const textEl = item.querySelector(SELECTORS.messageText.join(',')) || item;
      const text = extractText(textEl);
      
      if (text && text.length > 0 && text.length < 1000) {
        const timestamp = Date.now();
        const hash = hashMessage(text, timestamp);
        
        // 去重
        if (!state.processedMessages.has(hash)) {
          messages.push({
            id: `msg_${index}_${timestamp}`,
            text: text,
            timestamp: timestamp,
            hash: hash
          });
        }
      }
    }
  });
  
  return messages;
}

/**
 * 模拟输入消息
 */
function simulateInput(text) {
  const input = findElement(SELECTORS.inputBox);
  
  if (!input) {
    console.error('[千牛] 未找到输入框');
    return false;
  }
  
  // 聚焦
  input.focus();
  
  // 判断输入框类型
  if (input.contentEditable === 'true') {
    // contentEditable元素
    input.innerHTML = '';
    input.textContent = text;
    
    // 触发输入事件
    input.dispatchEvent(new InputEvent('input', {
      bubbles: true,
      cancelable: true,
      inputType: 'insertText',
      data: text
    }));
  } else {
    // textarea或input
    input.value = text;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }
  
  return true;
}

/**
 * 模拟点击发送
 */
function simulateSend() {
  const sendBtn = findElement(SELECTORS.sendButton);
  
  if (sendBtn) {
    // 模拟真实的鼠标事件序列
    sendBtn.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
    sendBtn.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
    
    setTimeout(() => {
      sendBtn.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      sendBtn.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
      sendBtn.click();
      console.log('[千牛] 已点击发送按钮');
    }, 50);
    
    return true;
  }
  
  // 备用：尝试按Enter键
  const input = findElement(SELECTORS.inputBox);
  if (input) {
    input.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'Enter',
      code: 'Enter',
      keyCode: 13,
      which: 13,
      bubbles: true
    }));
    input.dispatchEvent(new KeyboardEvent('keyup', {
      key: 'Enter',
      code: 'Enter',
      keyCode: 13,
      which: 13,
      bubbles: true
    }));
    console.log('[千牛] 已触发Enter键发送');
    return true;
  }
  
  console.error('[千牛] 未找到发送按钮');
  return false;
}

/**
 * 发送消息完整流程
 */
function sendMessage(text) {
  console.log('[千牛] 准备发送:', text);
  
  // 添加随机延迟，模拟人工输入
  const delay = 300 + Math.random() * 500;
  
  setTimeout(() => {
    if (simulateInput(text)) {
      // 输入后等待一下再发送
      setTimeout(() => {
        simulateSend();
      }, 200 + Math.random() * 300);
    }
  }, delay);
  
  return true;
}

/**
 * 检查新消息
 */
function checkNewMessages() {
  const messages = extractBuyerMessages();
  
  if (messages.length === 0) return;
  
  // 获取最新的未处理消息
  const newMessages = messages.filter(m => !state.processedMessages.has(m.hash));
  
  if (newMessages.length > 0) {
    const latestMsg = newMessages[newMessages.length - 1];
    
    // 标记为已处理
    state.processedMessages.add(latestMsg.hash);
    
    // 限制已处理集合大小
    if (state.processedMessages.size > 500) {
      const arr = Array.from(state.processedMessages);
      state.processedMessages = new Set(arr.slice(-200));
    }
    
    // 获取买家信息
    state.currentBuyer = getCurrentBuyer();
    
    console.log('[千牛] 检测到新消息:', latestMsg.text);
    
    // 通知主进程
    ipcRenderer.send('platform:new-message', {
      platformId: PLATFORM_ID,
      customerId: state.currentBuyer.id,
      customerName: state.currentBuyer.name,
      message: latestMsg.text,
      timestamp: latestMsg.timestamp
    });
  }
}

/**
 * 启动消息观察器
 */
function startObserver() {
  if (state.isObserving) return;
  
  const container = findElement(SELECTORS.messageContainer) || document.body;
  
  const observer = new MutationObserver((mutations) => {
    // 检查是否有新节点添加
    let hasNewNodes = false;
    for (const mutation of mutations) {
      if (mutation.addedNodes.length > 0) {
        hasNewNodes = true;
        break;
      }
    }
    
    if (hasNewNodes) {
      // 延迟检查，等待DOM完全更新
      setTimeout(checkNewMessages, 100);
    }
  });
  
  observer.observe(container, {
    childList: true,
    subtree: true,
    characterData: true,
    attributes: true,
    attributeFilter: ['aria-label', 'class']
  });
  
  state.isObserving = true;
  console.log('[千牛] 消息观察器已启动（无障碍模式）');
  
  // 定时检查作为备份
  setInterval(checkNewMessages, 2000);
}

/**
 * 拦截WebSocket（补充方案）
 */
function interceptWebSocket() {
  const OriginalWebSocket = window.WebSocket;
  
  window.WebSocket = function(url, protocols) {
    const ws = protocols ? new OriginalWebSocket(url, protocols) : new OriginalWebSocket(url);
    
    ws.addEventListener('message', (event) => {
      try {
        const data = JSON.parse(event.data);
        
        // 检测消息类型
        if (data.type === 'message' || data.cmd === 'msg' || 
            data.action === 'receive' || data.method === 'push') {
          
          const content = data.content || data.msg || data.text || 
                         data.body?.text || data.payload?.text;
          const sender = data.sender || data.from || data.nick ||
                        data.fromNick || data.buyerNick;
          
          if (content && sender) {
            const hash = hashMessage(content, Date.now());
            
            if (!state.processedMessages.has(hash)) {
              state.processedMessages.add(hash);
              
              console.log('[千牛] WebSocket消息:', content);
              
              ipcRenderer.send('platform:new-message', {
                platformId: PLATFORM_ID,
                customerId: data.fromId || data.senderId || `ws_${Date.now()}`,
                customerName: sender,
                message: content,
                timestamp: Date.now()
              });
            }
          }
        }
      } catch (e) {
        // 非JSON数据，忽略
      }
    });
    
    return ws;
  };
  
  // 复制静态属性
  Object.keys(OriginalWebSocket).forEach(key => {
    window.WebSocket[key] = OriginalWebSocket[key];
  });
  
  window.WebSocket.prototype = OriginalWebSocket.prototype;
  
  console.log('[千牛] WebSocket已拦截');
}

// ============ OrderDetect: Order Info Extraction ============

/**
 * Extract order information from the Qianniu chat page DOM
 * Uses ARIA selectors for stability. Order info is typically in the sidebar/panel next to chat.
 */
function extractOrderInfo() {
  const result = {
    orders: [],
    chatImages: []
  };

  try {
    // --- 1. Locate order panel (sidebar / complementary region) ---
    const orderPanel = findOrderPanel();

    if (orderPanel) {
      const order = extractSingleOrder(orderPanel);
      if (order) {
        result.orders.push(order);
      }
    } else {
      // Fallback: scan for order card elements anywhere on page
      const orderCards = findAllElements([
        '[class*="order-card"]',
        '[class*="order-item"]',
        '[class*="trade-card"]',
        '[aria-label*="订单"]'
      ]);
      for (const card of orderCards.slice(0, 3)) {
        const order = extractSingleOrder(card);
        if (order) result.orders.push(order);
      }
    }

    // --- 2. Extract buyer-sent images from chat messages ---
    result.chatImages = extractChatImages();

  } catch (e) {
    console.error('[千牛][OrderDetect] 提取订单信息失败:', e);
  }

  return result;
}

/**
 * Find the order panel in Qianniu's sidebar
 */
function findOrderPanel() {
  // ARIA-based (most stable)
  const ariaPanel = document.querySelector('[role="complementary"]');
  if (ariaPanel) {
    const hasOrder = ariaPanel.textContent && /订单|交易|付款/.test(ariaPanel.textContent);
    if (hasOrder) return ariaPanel;
  }

  // Label-based
  const labelPanels = document.querySelectorAll('[aria-label*="订单"], [aria-label*="交易"]');
  if (labelPanels.length > 0) return labelPanels[0];

  // Class-based fallback
  const selectors = [
    '[class*="order-panel"]',
    '[class*="order-info"]',
    '[class*="order-card"]',
    '[class*="trade-info"]',
    '[class*="aside"] [class*="order"]',
    '[class*="sidebar"] [class*="order"]',
    '[class*="right-panel"] [class*="order"]'
  ];
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el) return el;
  }
  return null;
}

/**
 * Extract info from a single order panel/card element
 */
function extractSingleOrder(container) {
  if (!container) return null;

  const order = {
    orderId: null,
    paymentStatus: null,
    shippingStatus: null,
    products: []
  };

  const text = container.textContent || '';

  // --- Order ID ---
  const orderIdEl = container.querySelector(
    '[class*="order-id"], [class*="order-no"], [class*="order-sn"], [aria-label*="订单号"]'
  );
  if (orderIdEl) {
    const match = orderIdEl.textContent.match(/(\d{10,})/);
    if (match) order.orderId = match[1];
  }
  if (!order.orderId) {
    const idMatch = text.match(/(?:订单号|订单编号|交易号)[：:\s]*(\d{10,})/);
    if (idMatch) order.orderId = idMatch[1];
  }

  // --- Payment Status ---
  const paymentEl = container.querySelector(
    '[class*="pay-status"], [class*="pay_status"], [class*="payment"], [aria-label*="付款"]'
  );
  if (paymentEl) {
    order.paymentStatus = paymentEl.textContent.trim();
  }
  if (!order.paymentStatus) {
    const payMatch = text.match(/(已付款|待付款|未付款|等待买家付款|买家已付款|退款中|已退款)/);
    if (payMatch) order.paymentStatus = payMatch[1];
  }

  // --- Shipping Status ---
  const shippingEl = container.querySelector(
    '[class*="logistics"], [class*="express"], [class*="delivery"], [class*="shipping"], [aria-label*="物流"]'
  );
  if (shippingEl) {
    order.shippingStatus = shippingEl.textContent.trim();
  }
  if (!order.shippingStatus) {
    const shipMatch = text.match(/(待发货|已发货|已签收|运输中|已揽收|退货中|卖家已发货|等待卖家发货)/);
    if (shipMatch) order.shippingStatus = shipMatch[1];
  }

  // --- Products ---
  const productEls = container.querySelectorAll(
    '[class*="goods-item"], [class*="goods-info"], [class*="item-info"], [class*="product-item"]'
  );
  if (productEls.length > 0) {
    for (const pEl of productEls) {
      const product = extractProductFromElement(pEl);
      if (product) order.products.push(product);
    }
  } else {
    // Fallback: try to extract product info from the container
    const product = extractProductFromElement(container);
    if (product && product.name) order.products.push(product);
  }

  if (order.orderId || order.paymentStatus || order.shippingStatus || order.products.length > 0) {
    return order;
  }
  return null;
}

/**
 * Extract product details from a DOM element
 */
function extractProductFromElement(el) {
  const product = { name: null, specs: null, price: null, imageUrl: null };

  // Product name
  const nameEl = el.querySelector(
    '[class*="item-name"], [class*="goods-title"], [class*="product-title"], [class*="title"], [class*="name"]'
  );
  if (nameEl) {
    product.name = nameEl.textContent.trim().substring(0, 100);
  }

  // Specs / SKU
  const specEl = el.querySelector(
    '[class*="sku"], [class*="spec"], [class*="attr"], [class*="prop"]'
  );
  if (specEl) {
    product.specs = specEl.textContent.trim().substring(0, 100);
  }

  // Price
  const priceEl = el.querySelector('[class*="price"], [class*="amount"]');
  if (priceEl) {
    const priceMatch = priceEl.textContent.match(/[￥¥]?\s*(\d+(?:\.\d{1,2})?)/);
    if (priceMatch) product.price = priceMatch[1];
  }

  // Product image (alicdn or taobaocdn images)
  const imgEl = el.querySelector('img[src*="alicdn"], img[src*="taobaocdn"], img[src]');
  if (imgEl && imgEl.src) {
    product.imageUrl = imgEl.src.startsWith('http') ? imgEl.src : new URL(imgEl.src, window.location.href).href;
  }

  return (product.name || product.specs) ? product : null;
}

/**
 * Extract images sent by buyer in recent chat messages
 */
function extractChatImages() {
  const images = [];
  const messageItems = findAllElements(SELECTORS.messageItem);

  // Scan last 5 buyer messages for images
  const recentItems = messageItems.slice(-10);
  let buyerMsgCount = 0;
  for (let i = recentItems.length - 1; i >= 0 && buyerMsgCount < 5; i--) {
    const item = recentItems[i];
    if (!isBuyerMessage(item)) continue;
    buyerMsgCount++;

    const imgs = item.querySelectorAll('img[src]');
    for (const img of imgs) {
      // Filter out emoji, icons, avatars
      if (img.naturalWidth > 0 && img.naturalWidth <= 50) continue;
      if (img.naturalHeight > 0 && img.naturalHeight <= 50) continue;

      const src = img.src || '';
      if (/emoji|icon|avatar|head|logo|badge/i.test(src)) continue;
      if (/emoji|icon|avatar|head|logo|badge/i.test(img.className || '')) continue;

      const url = src.startsWith('http') ? src : new URL(src, window.location.href).href;
      if (url && !images.includes(url)) {
        images.push(url);
      }
    }
    if (images.length >= 3) break;
  }

  return images;
}

// Listen for order info extraction request from main process
ipcRenderer.on('platform:get-order-info', (event, payload) => {
  const requestId = payload?.requestId || '';
  console.log('[千牛][OrderDetect] 收到订单提取请求, requestId:', requestId);
  try {
    const orderInfo = extractOrderInfo();
    console.log('[千牛][OrderDetect] 提取结果:', JSON.stringify(orderInfo).substring(0, 200));
    ipcRenderer.send('platform:order-info-result', { requestId, data: orderInfo });
  } catch (e) {
    console.error('[千牛][OrderDetect] 提取失败:', e);
    ipcRenderer.send('platform:order-info-result', { requestId, data: null });
  }
});

// 监听回复指令
ipcRenderer.on('platform:send-reply', (event, data) => {
  console.log('[千牛] 收到回复指令:', data);
  sendMessage(data.reply);
});

// 初始化
function initialize() {
  console.log('[千牛] 初始化中...');
  console.log('[千牛] 请确认已开启：讲述人模式 + 气泡模式');
  
  // 延迟启动，等待页面完全加载
  setTimeout(() => {
    interceptWebSocket();
    startObserver();
    
    // Notify main process that login is successful
    ipcRenderer.send('platform:login-success', { platformId: PLATFORM_ID });
    
    // 初始检查
    setTimeout(checkNewMessages, 1000);
  }, 2000);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initialize);
} else {
  initialize();
}

console.log('[千牛] Preload脚本已加载（无障碍模式优化版）');
