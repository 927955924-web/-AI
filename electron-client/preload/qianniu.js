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
async function checkNewMessages() {
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
    
    // Extract buyer-sent media (high-res images + video frames)
    let buyerImages = [];
    let buyerVideoFrames = [];
    
    const quickImages = extractChatImages();
    if (quickImages.length > 0) {
      console.log(`[千牛] 检测到 ${quickImages.length} 个买家媒体项，提取高清...`);
      try {
        const media = await extractMediaContent();
        buyerImages = media.images.length > 0 ? media.images : quickImages;
        buyerVideoFrames = media.videoFrames;
      } catch (err) {
        console.warn('[千牛] 媒体提取失败，使用缩略图:', err.message);
        buyerImages = quickImages;
      }
    }
    
    if (buyerImages.length > 0) {
      console.log(`[千牛] 提取到 ${buyerImages.length} 张买家图片`);
    }
    if (buyerVideoFrames.length > 0) {
      console.log(`[千牛] 捕获 ${buyerVideoFrames.length} 个视频帧`);
    }
    
    // 通知主进程
    ipcRenderer.send('platform:new-message', {
      platformId: PLATFORM_ID,
      customerId: state.currentBuyer.id,
      customerName: state.currentBuyer.name,
      message: latestMsg.text,
      buyerImages: buyerImages,
      buyerVideoFrames: buyerVideoFrames,
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
 * Check if an image element is a content image (not emoji/icon/avatar)
 */
function isContentImage(img) {
  if (img.naturalWidth > 0 && img.naturalWidth <= 50) return false;
  if (img.naturalHeight > 0 && img.naturalHeight <= 50) return false;
  const src = img.src || '';
  if (/emoji|icon|avatar|head|logo|badge|sticker/i.test(src)) return false;
  if (/emoji|icon|avatar|head|logo|badge|sticker/i.test(img.className || '')) return false;
  return true;
}

/**
 * Extract images sent by buyer in recent chat messages (thumbnail URLs)
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
      if (!isContentImage(img)) continue;

      const src = img.src || '';
      const url = src.startsWith('http') ? src : new URL(src, window.location.href).href;
      if (url && !images.includes(url)) {
        images.push(url);
      }
    }
    if (images.length >= 3) break;
  }

  return images;
}

/**
 * Click image thumbnails in chat to open preview and get high-res URLs
 */
async function getHighResImages() {
  const messageItems = findAllElements(SELECTORS.messageItem);
  const highResUrls = [];
  const recentItems = messageItems.slice(-10);
  let buyerMsgCount = 0;

  for (let i = recentItems.length - 1; i >= 0 && buyerMsgCount < 5; i--) {
    const item = recentItems[i];
    if (!isBuyerMessage(item)) continue;
    buyerMsgCount++;

    const imgs = item.querySelectorAll('img[src]');
    for (const img of imgs) {
      if (!isContentImage(img)) continue;
      if (highResUrls.length >= 3) break;

      try {
        // Click thumbnail to open preview
        img.click();
        await new Promise(r => setTimeout(r, 800));

        // Try to find the high-res preview image (千牛/淘宝 selectors)
        const previewSelectors = [
          '.image-viewer img',
          '[class*="ImageViewer"] img',
          'img[class*="preview"]',
          'img[class*="fullscreen"]',
          '.ant-image-preview img',
          '[class*="image-preview"] img',
          '[class*="viewer"] img[src*="http"]',
          '[class*="modal"] img[src*="alicdn"]',
          '[class*="modal"] img[src*="taobaocdn"]'
        ];

        let previewImg = null;
        for (const sel of previewSelectors) {
          previewImg = document.querySelector(sel);
          if (previewImg && previewImg.src && previewImg.src !== img.src) break;
          previewImg = null;
        }

        if (previewImg && previewImg.src) {
          let highResUrl = previewImg.src;
          highResUrl = highResUrl.replace(/[?&]x-oss-process=[^&]*/g, '');
          highResUrl = highResUrl.replace(/[?&]imageView2[^&]*/g, '');
          if (!highResUrls.includes(highResUrl)) {
            highResUrls.push(highResUrl);
            console.log(`[千牛][Vision] Got high-res image: ${highResUrl.substring(0, 80)}...`);
          }
        } else {
          // Fallback: use thumbnail URL with quality params removed
          let fallbackUrl = img.src;
          fallbackUrl = fallbackUrl.replace(/[?&]x-oss-process=[^&]*/g, '');
          fallbackUrl = fallbackUrl.replace(/[?&]imageView2[^&]*/g, '');
          if (!highResUrls.includes(fallbackUrl)) {
            highResUrls.push(fallbackUrl);
            console.log(`[千牛][Vision] Using fallback image: ${fallbackUrl.substring(0, 80)}...`);
          }
        }

        // Close preview modal
        const closeSelectors = [
          '[class*="close"]',
          '.ant-modal-close',
          '[aria-label="关闭"]',
          '[class*="viewer"] [class*="close"]',
          'button[class*="close"]'
        ];
        for (const sel of closeSelectors) {
          const closeBtn = document.querySelector(sel);
          if (closeBtn && closeBtn.offsetParent !== null) {
            closeBtn.click();
            break;
          }
        }
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        await new Promise(r => setTimeout(r, 400));
      } catch (err) {
        console.warn(`[千牛][Vision] Error getting high-res image:`, err.message);
      }
    }
    if (highResUrls.length >= 3) break;
  }

  return highResUrls;
}

/**
 * Extract video frames from buyer-sent videos using Canvas
 * @param {number} frameCount - Number of key frames to capture
 * @returns {Promise<Array<{timestamp: number, base64: string}>>}
 */
async function extractVideoFrames(frameCount = 3) {
  const frames = [];
  const messageItems = findAllElements(SELECTORS.messageItem);
  const recentItems = messageItems.slice(-10);
  let buyerMsgCount = 0;

  for (let i = recentItems.length - 1; i >= 0 && buyerMsgCount < 5; i--) {
    const item = recentItems[i];
    if (!isBuyerMessage(item)) continue;
    buyerMsgCount++;

    // Find video elements
    const videoSelectors = [
      'video',
      '[class*="video-player"] video',
      '[class*="video-msg"] video',
      '[class*="VideoPlayer"] video'
    ];

    let videoEl = null;
    for (const sel of videoSelectors) {
      videoEl = item.querySelector(sel);
      if (videoEl) break;
    }

    // Check for video cards that need clicking to play
    if (!videoEl) {
      const videoCards = item.querySelectorAll('[class*="video"], [class*="Video"]');
      for (const card of videoCards) {
        try {
          card.click();
          await new Promise(r => setTimeout(r, 1500));
          for (const sel of videoSelectors) {
            videoEl = document.querySelector(sel);
            if (videoEl) break;
          }
        } catch (e) {
          console.warn('[千牛][Vision] Error clicking video card:', e.message);
        }
        if (videoEl) break;
      }
    }

    if (!videoEl) continue;

    try {
      // Ensure metadata is loaded
      if (videoEl.readyState < 1) {
        await Promise.race([
          new Promise(resolve => {
            videoEl.addEventListener('loadedmetadata', resolve, { once: true });
            videoEl.load();
          }),
          new Promise(resolve => setTimeout(resolve, 5000))
        ]);
      }

      const duration = videoEl.duration;
      if (!duration || !isFinite(duration) || duration <= 0) {
        console.warn('[千牛][Vision] Video has invalid duration');
        continue;
      }

      const canvas = document.createElement('canvas');
      const ctx = canvas.getContext('2d');
      canvas.width = videoEl.videoWidth || 640;
      canvas.height = videoEl.videoHeight || 360;

      const timePoints = [];
      for (let j = 1; j <= frameCount; j++) {
        timePoints.push((duration / (frameCount + 1)) * j);
      }

      for (const time of timePoints) {
        videoEl.currentTime = time;
        await Promise.race([
          new Promise(resolve => videoEl.addEventListener('seeked', resolve, { once: true })),
          new Promise(resolve => setTimeout(resolve, 3000))
        ]);

        ctx.drawImage(videoEl, 0, 0, canvas.width, canvas.height);
        const base64 = canvas.toDataURL('image/jpeg', 0.8).split(',')[1];
        if (base64 && base64.length > 100) {
          frames.push({ timestamp: Math.round(time * 10) / 10, base64 });
          console.log(`[千牛][Vision] Captured video frame at ${time.toFixed(1)}s`);
        }
      }

      // Close video preview if in modal
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      await new Promise(r => setTimeout(r, 300));
    } catch (err) {
      console.warn(`[千牛][Vision] Error extracting video frames:`, err.message);
    }

    if (frames.length >= frameCount) break;
  }

  return frames;
}

/**
 * Extract all media content (high-res images + video frames) from recent buyer messages
 */
async function extractMediaContent() {
  const content = { images: [], videoFrames: [] };

  try {
    const result = await Promise.race([
      (async () => {
        try {
          content.images = await getHighResImages();
        } catch (err) {
          console.warn('[千牛][Vision] High-res image extraction failed, using thumbnails:', err.message);
          content.images = extractChatImages();
        }

        try {
          content.videoFrames = await extractVideoFrames(3);
        } catch (err) {
          console.warn('[千牛][Vision] Video frame extraction failed:', err.message);
        }

        return content;
      })(),
      new Promise(resolve => setTimeout(() => {
        console.warn('[千牛][Vision] Media extraction timeout (15s)');
        resolve(content);
      }, 15000))
    ]);

    return result;
  } catch (err) {
    console.error('[千牛][Vision] Fatal error in media extraction:', err.message);
    content.images = extractChatImages();
    return content;
  }
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
