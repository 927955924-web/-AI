/**
 * Douyin (TikTok Shop) Platform Preload Script
 * Injects into Douyin merchant backend to monitor and control messages
 */
const { contextBridge, ipcRenderer } = require('electron');

const PLATFORM_ID = 'douyin';

// Selectors for Douyin merchant backend (Feige)
const SELECTORS = {
  // Message list container
  messageList: '.im-message-list, .chat-message-list, [class*="message-list"]',
  // Single message item
  messageItem: '.im-message-item, .message-item, [class*="msg-item"]',
  // Customer message (incoming)
  customerMessage: '.message-left, .im-message-other, [class*="receive"]',
  // Message text content
  messageText: '.message-text, .im-text, [class*="text-content"]',
  // Input box
  inputBox: '.im-editor textarea, .chat-input textarea, [class*="editor"] textarea',
  // Send button
  sendButton: '.im-send-btn, .send-button, [class*="send"]',
  // Customer name
  customerName: '.im-user-name, .customer-name, [class*="nickname"]',
  // Conversation list
  conversationList: '.im-session-list, .conversation-list',
  // Active conversation
  activeConversation: '.im-session-item.active, .conversation-item.selected'
};

// State
let lastMessageId = null;
let observerActive = false;
let currentCustomer = null;

/**
 * Extract messages from DOM
 */
function extractMessages() {
  const messages = [];
  const messageElements = document.querySelectorAll(SELECTORS.messageItem);
  
  messageElements.forEach((el, index) => {
    const isCustomer = el.matches(SELECTORS.customerMessage) || 
                       el.querySelector(SELECTORS.customerMessage) ||
                       el.classList.contains('left') ||
                       el.classList.contains('receive');
    
    if (isCustomer) {
      const textEl = el.querySelector(SELECTORS.messageText);
      if (textEl) {
        messages.push({
          id: `msg_${index}_${Date.now()}`,
          text: textEl.textContent.trim(),
          timestamp: Date.now(),
          isCustomer: true
        });
      }
    }
  });
  
  return messages;
}

/**
 * Get current customer info
 */
function getCurrentCustomer() {
  const activeConv = document.querySelector(SELECTORS.activeConversation);
  if (activeConv) {
    const nameEl = activeConv.querySelector(SELECTORS.customerName);
    if (nameEl) {
      return {
        id: activeConv.getAttribute('data-id') || `dy_${Date.now()}`,
        name: nameEl.textContent.trim()
      };
    }
  }
  
  const nameEl = document.querySelector(SELECTORS.customerName);
  if (nameEl) {
    return {
      id: `dy_${Date.now()}`,
      name: nameEl.textContent.trim()
    };
  }
  
  return { id: 'unknown', name: '买家' };
}

/**
 * Simulate typing and sending a message
 */
function sendMessage(text) {
  const input = document.querySelector(SELECTORS.inputBox);
  if (!input) {
    console.error('[Douyin] Input box not found');
    return false;
  }
  
  input.focus();
  
  // For contenteditable divs
  if (input.contentEditable === 'true') {
    input.innerHTML = text;
    input.dispatchEvent(new Event('input', { bubbles: true }));
  } else {
    input.value = text;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }
  
  setTimeout(() => {
    const sendBtn = document.querySelector(SELECTORS.sendButton);
    if (sendBtn) {
      sendBtn.click();
      console.log('[Douyin] Message sent:', text);
    } else {
      input.dispatchEvent(new KeyboardEvent('keydown', {
        key: 'Enter',
        code: 'Enter',
        keyCode: 13,
        which: 13,
        bubbles: true,
        ctrlKey: true // Douyin often uses Ctrl+Enter
      }));
    }
  }, 100);
  
  return true;
}

/**
 * Check for new messages
 */
async function checkForNewMessages() {
  const messages = extractMessages();
  if (messages.length === 0) return;
  
  const lastMsg = messages[messages.length - 1];
  
  if (lastMsg.id !== lastMessageId) {
    lastMessageId = lastMsg.id;
    currentCustomer = getCurrentCustomer();
    
    // Extract buyer-sent media (high-res images + video frames)
    let buyerImages = [];
    let buyerVideoFrames = [];
    
    const quickImages = extractChatImages();
    if (quickImages.length > 0) {
      console.log(`[Douyin] Detected ${quickImages.length} buyer media items, extracting high-res...`);
      try {
        const media = await extractMediaContent();
        buyerImages = media.images.length > 0 ? media.images : quickImages;
        buyerVideoFrames = media.videoFrames;
      } catch (err) {
        console.warn('[Douyin] Media extraction failed, using thumbnails:', err.message);
        buyerImages = quickImages;
      }
    }
    
    if (buyerImages.length > 0) {
      console.log(`[Douyin] Found ${buyerImages.length} buyer images`);
    }
    if (buyerVideoFrames.length > 0) {
      console.log(`[Douyin] Captured ${buyerVideoFrames.length} video frames`);
    }
    
    ipcRenderer.send('platform:new-message', {
      platformId: PLATFORM_ID,
      customerId: currentCustomer.id,
      customerName: currentCustomer.name,
      message: lastMsg.text,
      buyerImages: buyerImages,
      buyerVideoFrames: buyerVideoFrames,
      timestamp: lastMsg.timestamp
    });
  }
}

/**
 * Start observing DOM for new messages
 */
function startObserver() {
  if (observerActive) return;
  
  const container = document.querySelector(SELECTORS.messageList) || document.body;
  
  const observer = new MutationObserver((mutations) => {
    let hasNewContent = false;
    mutations.forEach(mutation => {
      if (mutation.addedNodes.length > 0) hasNewContent = true;
    });
    
    if (hasNewContent) checkForNewMessages();
  });
  
  observer.observe(container, {
    childList: true,
    subtree: true,
    characterData: true
  });
  
  observerActive = true;
  console.log('[Douyin] Message observer started');
  
  setInterval(checkForNewMessages, 3000);
}

/**
 * Intercept WebSocket messages
 */
function interceptWebSocket() {
  const originalWebSocket = window.WebSocket;
  
  window.WebSocket = function(url, protocols) {
    const ws = new originalWebSocket(url, protocols);
    
    ws.addEventListener('message', (event) => {
      try {
        const data = JSON.parse(event.data);
        
        // Douyin IM uses different message formats
        if (data.cmd === 'msg' || data.type === 'im_msg' || data.action === 'push') {
          console.log('[Douyin] WebSocket message:', data);
          
          const msgContent = data.content || data.payload?.text || data.msg;
          const sender = data.sender?.nickname || data.from_user?.name || data.nick;
          
          if (msgContent && sender) {
            ipcRenderer.send('platform:new-message', {
              platformId: PLATFORM_ID,
              customerId: data.from_uid || data.sender?.uid || `ws_${Date.now()}`,
              customerName: sender,
              message: msgContent,
              timestamp: Date.now()
            });
          }
        }
      } catch (e) {}
    });
    
    return ws;
  };
  
  Object.keys(originalWebSocket).forEach(key => {
    window.WebSocket[key] = originalWebSocket[key];
  });
  
  console.log('[Douyin] WebSocket intercepted');
}

// ============ OrderDetect: Order Info Extraction ============

/**
 * Extract order information from the Douyin Feige chat page DOM
 */
function extractOrderInfo() {
  const result = {
    orders: [],
    chatImages: []
  };

  try {
    // --- 1. Locate order panel (Feige right sidebar / order cards) ---
    const orderPanel = findOrderPanel();

    if (orderPanel) {
      const order = extractSingleOrder(orderPanel);
      if (order) {
        result.orders.push(order);
      }
    } else {
      // Fallback: scan for order card elements
      const orderCards = document.querySelectorAll(
        '[class*="order-card"], [class*="order-item"], [class*="trade-card"], [class*="order-info"]'
      );
      for (const card of Array.from(orderCards).slice(0, 3)) {
        const order = extractSingleOrder(card);
        if (order) result.orders.push(order);
      }
    }

    // --- 2. Extract buyer-sent images from chat messages ---
    result.chatImages = extractChatImages();

  } catch (e) {
    console.error('[Douyin][OrderDetect] Error extracting order info:', e);
  }

  return result;
}

/**
 * Find the order panel in Douyin Feige's sidebar
 */
function findOrderPanel() {
  const selectors = [
    '[class*="order-panel"]',
    '[class*="order-info"]',
    '[class*="order-card"]',
    '.im-order-info',
    '[class*="aside"] [class*="order"]',
    '[class*="right-panel"] [class*="order"]',
    '[class*="sidebar"] [class*="order"]',
    '[class*="detail-panel"] [class*="order"]'
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
    '[class*="order-id"], [class*="order-no"], [class*="order-sn"], [class*="orderId"]'
  );
  if (orderIdEl) {
    const match = orderIdEl.textContent.match(/(\d{10,})/);
    if (match) order.orderId = match[1];
  }
  if (!order.orderId) {
    const idMatch = text.match(/(?:订单号|订单编号|单号)[：:\s]*(\d{10,})/);
    if (idMatch) order.orderId = idMatch[1];
  }

  // --- Payment Status ---
  const paymentEl = container.querySelector(
    '[class*="pay-status"], [class*="pay_status"], [class*="payment"]'
  );
  if (paymentEl) {
    order.paymentStatus = paymentEl.textContent.trim();
  }
  if (!order.paymentStatus) {
    const payMatch = text.match(/(已付款|已支付|待付款|待支付|未付款|退款中|已退款)/);
    if (payMatch) order.paymentStatus = payMatch[1];
  }

  // --- Shipping Status ---
  const shippingEl = container.querySelector(
    '[class*="logistics"], [class*="express"], [class*="delivery"], [class*="shipping"]'
  );
  if (shippingEl) {
    order.shippingStatus = shippingEl.textContent.trim();
  }
  if (!order.shippingStatus) {
    const shipMatch = text.match(/(待发货|已发货|已签收|运输中|配送中|已揽收|退货中|已退货)/);
    if (shipMatch) order.shippingStatus = shipMatch[1];
  }

  // --- Products ---
  const productEls = container.querySelectorAll(
    '[class*="product-item"], [class*="goods-item"], [class*="goods-info"], [class*="sku-item"]'
  );
  if (productEls.length > 0) {
    for (const pEl of productEls) {
      const product = extractProductFromElement(pEl);
      if (product) order.products.push(product);
    }
  } else {
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
    '[class*="product-name"], [class*="product-title"], [class*="goods-name"], [class*="title"], [class*="item-name"]'
  );
  if (nameEl) {
    product.name = nameEl.textContent.trim().substring(0, 100);
  }

  // Specs
  const specEl = el.querySelector(
    '[class*="spec"], [class*="sku"], [class*="attr"], [class*="prop"]'
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

  // Product image
  const imgEl = el.querySelector('img[src]');
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
  const messageElements = document.querySelectorAll(SELECTORS.messageItem);

  // Scan last 5 customer messages for images
  const recentItems = Array.from(messageElements).slice(-10);
  let customerMsgCount = 0;
  for (let i = recentItems.length - 1; i >= 0 && customerMsgCount < 5; i--) {
    const el = recentItems[i];
    const isCustomer = el.matches(SELECTORS.customerMessage) ||
                       el.querySelector(SELECTORS.customerMessage) ||
                       el.classList.contains('left') ||
                       el.classList.contains('receive');
    if (!isCustomer) continue;
    customerMsgCount++;

    const imgs = el.querySelectorAll('img[src]');
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
  const messageElements = document.querySelectorAll(SELECTORS.messageItem);
  const highResUrls = [];
  const recentItems = Array.from(messageElements).slice(-10);
  let customerMsgCount = 0;

  for (let i = recentItems.length - 1; i >= 0 && customerMsgCount < 5; i--) {
    const el = recentItems[i];
    const isCustomer = el.matches(SELECTORS.customerMessage) ||
                       el.querySelector(SELECTORS.customerMessage) ||
                       el.classList.contains('left') ||
                       el.classList.contains('receive');
    if (!isCustomer) continue;
    customerMsgCount++;

    const imgs = el.querySelectorAll('img[src]');
    for (const img of imgs) {
      if (!isContentImage(img)) continue;
      if (highResUrls.length >= 3) break;

      try {
        // Click thumbnail to open preview
        img.click();
        await new Promise(r => setTimeout(r, 800));

        // Try to find the high-res preview image (Feige/Douyin selectors)
        const previewSelectors = [
          '.im-image-viewer img',
          '[class*="image-viewer"] img',
          '[class*="ImageViewer"] img',
          'img[class*="preview"]',
          'img[class*="fullscreen"]',
          '[class*="image-preview"] img',
          '[class*="modal"] img[src*="http"]',
          '[class*="viewer"] img[src*="http"]'
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
            console.log(`[Douyin][Vision] Got high-res image: ${highResUrl.substring(0, 80)}...`);
          }
        } else {
          // Fallback: use thumbnail URL with quality params removed
          let fallbackUrl = img.src;
          fallbackUrl = fallbackUrl.replace(/[?&]x-oss-process=[^&]*/g, '');
          fallbackUrl = fallbackUrl.replace(/[?&]imageView2[^&]*/g, '');
          if (!highResUrls.includes(fallbackUrl)) {
            highResUrls.push(fallbackUrl);
            console.log(`[Douyin][Vision] Using fallback image: ${fallbackUrl.substring(0, 80)}...`);
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
        console.warn(`[Douyin][Vision] Error getting high-res image:`, err.message);
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
  const messageElements = document.querySelectorAll(SELECTORS.messageItem);
  const recentItems = Array.from(messageElements).slice(-10);
  let customerMsgCount = 0;

  for (let i = recentItems.length - 1; i >= 0 && customerMsgCount < 5; i--) {
    const el = recentItems[i];
    const isCustomer = el.matches(SELECTORS.customerMessage) ||
                       el.querySelector(SELECTORS.customerMessage) ||
                       el.classList.contains('left') ||
                       el.classList.contains('receive');
    if (!isCustomer) continue;
    customerMsgCount++;

    // Find video elements (Feige/Douyin specific)
    const videoSelectors = [
      'video',
      '.im-video-msg video',
      '[class*="video-player"] video',
      '[class*="video-msg"] video',
      '[class*="VideoPlayer"] video'
    ];

    let videoEl = null;
    for (const sel of videoSelectors) {
      videoEl = el.querySelector(sel);
      if (videoEl) break;
    }

    // Check for video cards that need clicking to play
    if (!videoEl) {
      const videoCards = el.querySelectorAll('[class*="video"], [class*="Video"], .im-video-msg');
      for (const card of videoCards) {
        try {
          card.click();
          await new Promise(r => setTimeout(r, 1500));
          for (const sel of videoSelectors) {
            videoEl = document.querySelector(sel);
            if (videoEl) break;
          }
        } catch (e) {
          console.warn('[Douyin][Vision] Error clicking video card:', e.message);
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
        console.warn('[Douyin][Vision] Video has invalid duration');
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
          console.log(`[Douyin][Vision] Captured video frame at ${time.toFixed(1)}s`);
        }
      }

      // Close video preview if in modal
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      await new Promise(r => setTimeout(r, 300));
    } catch (err) {
      console.warn(`[Douyin][Vision] Error extracting video frames:`, err.message);
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
          console.warn('[Douyin][Vision] High-res image extraction failed, using thumbnails:', err.message);
          content.images = extractChatImages();
        }

        try {
          content.videoFrames = await extractVideoFrames(3);
        } catch (err) {
          console.warn('[Douyin][Vision] Video frame extraction failed:', err.message);
        }

        return content;
      })(),
      new Promise(resolve => setTimeout(() => {
        console.warn('[Douyin][Vision] Media extraction timeout (15s)');
        resolve(content);
      }, 15000))
    ]);

    return result;
  } catch (err) {
    console.error('[Douyin][Vision] Fatal error in media extraction:', err.message);
    content.images = extractChatImages();
    return content;
  }
}

// Listen for order info extraction request from main process
ipcRenderer.on('platform:get-order-info', (event, payload) => {
  const requestId = payload?.requestId || '';
  console.log('[Douyin][OrderDetect] Received extraction request, requestId:', requestId);
  try {
    const orderInfo = extractOrderInfo();
    console.log('[Douyin][OrderDetect] Extracted:', JSON.stringify(orderInfo).substring(0, 200));
    ipcRenderer.send('platform:order-info-result', { requestId, data: orderInfo });
  } catch (e) {
    console.error('[Douyin][OrderDetect] Extraction failed:', e);
    ipcRenderer.send('platform:order-info-result', { requestId, data: null });
  }
});

// Listen for reply commands
ipcRenderer.on('platform:send-reply', (event, data) => {
  console.log('[Douyin] Sending reply:', data);
  sendMessage(data.reply);
});

// Initialize
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => setTimeout(() => {
    ipcRenderer.send('platform:login-success', { platformId: PLATFORM_ID });
    startObserver();
  }, 2000));
} else {
  setTimeout(() => {
    ipcRenderer.send('platform:login-success', { platformId: PLATFORM_ID });
    startObserver();
  }, 2000);
}

interceptWebSocket();
console.log('[Douyin] Preload script loaded');
