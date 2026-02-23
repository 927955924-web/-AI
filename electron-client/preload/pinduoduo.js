/**
 * Pinduoduo Chat-Merchant Preload Script
 * Injects into mms.pinduoduo.com/chat-merchant to monitor and auto-reply messages
 */
const { ipcRenderer } = require('electron');

const PLATFORM_ID = 'pinduoduo';

/**
 * Send log message to main process for visibility in console
 */
function logToMain(message, level = 'info') {
  ipcRenderer.send('platform:log', { platformId: PLATFORM_ID, message, level });
}

// State management
const state = {
  processedMessages: new Set(),  // Track processed message hashes
  repliedConversations: new Map(), // Track replied conversations: customerId -> lastReplyTime
  lastCustomerMessages: new Map(), // Track last message per customer: customerId -> messageHash
  sentMessages: new Set(),       // Track messages we sent (to avoid processing our own replies)
  isProcessing: false,           // Prevent concurrent processing
  isReplying: false,             // Prevent concurrent replies from processCurrentConversation
  observerActive: false,
  scanInterval: null,
  lastScanTime: 0,
  replyTimeout: 60000,  // Don't reply again to same customer within 60 seconds unless they send new message
  lastShiftTabTime: 0,  // Track last Shift+Tab press time
  shiftTabCooldown: 10000,  // Cooldown between Shift+Tab presses (10 seconds)
  consecutiveNoUnread: 0,  // Track consecutive times no unread found after Shift+Tab
  consecutiveShiftTab: 0,  // Track consecutive Shift+Tab presses to prevent infinite loop
  consecutiveNoMessage: 0,  // Track conversations with no real buyer message
  visitedTimeoutConvs: new Set()  // Track timeout conversations we've already checked (no real msg)
};

/**
 * Generate a simple hash for deduplication
 */
function hashMessage(text) {
  let hash = 0;
  const str = text.trim();
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash |= 0;
  }
  return hash.toString();
}

/**
 * Adaptive element finder - tries multiple selector strategies
 */
function findElement(strategies) {
  for (const selector of strategies) {
    try {
      const el = document.querySelector(selector);
      if (el) return el;
    } catch (e) {}
  }
  return null;
}

/**
 * Check if a DOM element is actually visible on the page
 */
function isElementVisible(el) {
  if (!el) return false;
  // Check offsetHeight/offsetWidth (0 = hidden)
  if (el.offsetHeight === 0 && el.offsetWidth === 0) return false;
  const style = window.getComputedStyle(el);
  if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
  return true;
}

function findElements(strategies) {
  for (const selector of strategies) {
    try {
      const els = document.querySelectorAll(selector);
      if (els.length > 0) return Array.from(els);
    } catch (e) {}
  }
  return [];
}

/**
 * Find conversation list items with pending messages
 * Only detects: 1) Countdown timer (new messages) 2) Timeout indicator (overdue)
 * Priority: Countdown > Timeout
 * 
 * PDD actual DOM structure (discovered via diagnostic):
 *   Container: div.chat-list-box.custom-scroll
 *   Items: div.chat-list (direct children, exclude div.more-btn-box)
 *   Timeout: div.timeout-unreply > div.chat-list-title "已超时"
 */
function findUnreadConversations() {
  const countdownItems = [];  // New messages with countdown
  const timeoutItems = [];    // Overdue messages

  let allItems = [];
  
  // === Strategy 1: PDD-specific selectors (known DOM structure) ===
  // Container is div.chat-list-box, items are div.chat-list
  const pddContainer = document.querySelector('.chat-list-box, [class="chat-list-box custom-scroll"]');
  if (pddContainer) {
    // Get direct child div.chat-list items (exclude more-btn-box, etc.)
    allItems = Array.from(pddContainer.children).filter(el => {
      if (el.nodeType !== 1) return false;
      const cls = el.className || '';
      // Include elements with class "chat-list" but not "more-btn-box" etc.
      return cls.includes('chat-list') && !cls.includes('more-btn') && !cls.includes('load-more');
    });
    if (allItems.length > 0) {
      console.log(`[PDD] Found ${allItems.length} conversation items via PDD-specific selector (.chat-list-box > .chat-list)`);
    }
  }
  
  // === Strategy 2: Generic selectors (fallback for other layouts) ===
  if (allItems.length === 0) {
    const listSelectors = [
      '.chat-list-box',
      '[class*="session-list"]',
      '[class*="conversation-list"]',
      '[class*="im-list"]',
      '[class*="contact-list"]'
    ];
    
    let sessionList = null;
    for (const sel of listSelectors) {
      const el = document.querySelector(sel);
      // Must have children to be a valid container
      if (el && el.children.length >= 2) {
        sessionList = el;
        break;
      }
    }
    
    if (sessionList) {
      const itemSelectors = [
        '[class*="session-item"]',
        '[class*="conversation-item"]',
        '[class*="chat-item"]',
        '[class*="list-item"]',
        '[class*="im-item"]'
      ];
      
      for (const sel of itemSelectors) {
        const items = sessionList.querySelectorAll(sel);
        if (items.length > 0) {
          allItems = Array.from(items);
          break;
        }
      }
      
      // Fallback: direct children of list container
      if (allItems.length === 0) {
        allItems = Array.from(sessionList.children).filter(el => 
          el.nodeType === 1 && el.offsetParent !== null && 
          !(el.className || '').includes('more-btn') &&
          !(el.className || '').includes('load-more')
        );
      }
    }
  }
  
  // === Strategy 3: Search globally ===
  if (allItems.length === 0) {
    // Try to find chat-list items anywhere in the page
    const globalItems = document.querySelectorAll('div.chat-list');
    if (globalItems.length > 0) {
      allItems = Array.from(globalItems).filter(el => {
        // Must look like conversation items (have text content > 10 chars)
        return el.textContent && el.textContent.length > 10 && el.children.length > 0;
      });
    }
  }
  
  console.log(`[PDD] findUnreadConversations: found ${allItems.length} conversation items`);

  allItems.forEach(item => {
    const itemText = item.textContent || '';
    
    // --- Check for countdown timer (new message indicator) ---
    let foundCountdown = false;
    
    // PDD-specific: look for countdown elements
    const countdownSelectors = [
      '[class*="countdown"]', '[class*="timer"]', '[class*="time-left"]',
      '[class*="reply-time"]', '[class*="Countdown"]', '[class*="replyTime"]',
      '[class*="count-down"]'
    ];
    
    for (const sel of countdownSelectors) {
      const countdownEl = item.querySelector(sel);
      if (countdownEl) {
        const text = countdownEl.textContent.trim();
        if (/\d+.*秒/.test(text) || /\d+.*分/.test(text)) {
          countdownItems.push(item);
          foundCountdown = true;
          break;
        }
      }
    }
    
    // Fallback: text pattern in item
    if (!foundCountdown) {
      const countdownMatch = itemText.match(/(\d+分)?\d+秒/);
      if (countdownMatch) {
        const matchStr = countdownMatch[0];
        const secMatch = matchStr.match(/(\d+)秒/);
        const minMatch = matchStr.match(/(\d+)分/);
        const totalSec = (minMatch ? parseInt(minMatch[1]) * 60 : 0) + (secMatch ? parseInt(secMatch[1]) : 0);
        if (totalSec > 0 && totalSec <= 300) {
          countdownItems.push(item);
          foundCountdown = true;
        }
      }
    }
    
    if (foundCountdown) return;

    // --- Check for timeout/overdue indicator ---
    let foundTimeout = false;
    
    // PDD-specific: div.timeout-unreply is the timeout indicator
    const pddTimeout = item.querySelector('.timeout-unreply, [class*="timeout-unreply"]');
    if (pddTimeout) {
      timeoutItems.push(item);
      foundTimeout = true;
    }
    
    // Generic: look for timeout class patterns
    if (!foundTimeout) {
      const timeoutSelectors = [
        '[class*="timeout"]', '[class*="overtime"]', '[class*="overdue"]',
        '[class*="expired"]', '[class*="exceed"]'
      ];
      for (const sel of timeoutSelectors) {
        const timeoutEl = item.querySelector(sel);
        if (timeoutEl) {
          const text = timeoutEl.textContent.trim();
          if (text.includes('超时') || text.includes('逾期') || text.includes('过期') || text.includes('已超')) {
            timeoutItems.push(item);
            foundTimeout = true;
            break;
          }
        }
      }
    }
    
    // Fallback: detect by text content
    if (!foundTimeout) {
      if (itemText.includes('已超时') || itemText.includes('超时') || itemText.includes('逾期')) {
        timeoutItems.push(item);
        foundTimeout = true;
      }
    }
  });

  // Return countdown items first (priority), then timeout items
  console.log(`[PDD] Found ${countdownItems.length} countdown, ${timeoutItems.length} timeout conversations`);
  return [...countdownItems, ...timeoutItems];
}

/**
 * Check if current shop has any pending messages
 */
function hasAnyPendingMessages() {
  return findUnreadConversations().length > 0;
}

/**
 * Get the last customer message from current chat area
 */
function getLastCustomerMessage() {
  // Strategy: find message containers and get the last buyer message
  const messageSelectors = [
    '[class*="msg-item"]',
    '[class*="message-item"]',
    '[class*="chat-msg"]',
    '[class*="bubble"]',
    '[class*="msg-row"]',
    '[class*="message-row"]'
  ];

  let messageItems = [];
  for (const selector of messageSelectors) {
    const items = document.querySelectorAll(selector);
    if (items.length > 0) {
      messageItems = Array.from(items);
      break;
    }
  }

  // If no specific selectors work, try to find message structure
  if (messageItems.length === 0) {
    // Look for chat area and its children
    const chatArea = findElement([
      '[class*="chat-content"]',
      '[class*="message-list"]',
      '[class*="msg-list"]',
      '[class*="chat-body"]',
      '[class*="im-content"]',
      '[class*="chat-record"]'
    ]);
    if (chatArea) {
      messageItems = Array.from(chatArea.children);
    }
  }

  // Reverse iterate to find last REAL customer message (not just product links)
  for (let i = messageItems.length - 1; i >= 0; i--) {
    const item = messageItems[i];
    const text = item.textContent.trim();

    // Skip empty or very short items
    if (text.length < 2) continue;

    // Check if it's a customer message (not from merchant/self)
    const isCustomer = isCustomerMessage(item);
    if (isCustomer) {
      // Extract just the message text (exclude timestamps, names, etc.)
      const msgText = extractMessageText(item);
      if (msgText && msgText.length > 0) {
        // Check if this is a message WE sent (avoid processing our own replies)
        const msgHash = hashMessage(msgText);
        if (state.sentMessages.has(msgHash)) {
          console.log('[PDD] Skipping our own sent message:', msgText.substring(0, 30));
          continue;
        }
        
        // Check if this is a PDD system/robot message (NOT a real buyer message)
        if (isPddSystemMessage(msgText)) {
          console.log('[PDD] Skipping PDD system/robot message:', msgText.substring(0, 50));
          continue;
        }
        
        // Check if this is just a product link/card (skip it to find real question)
        if (isProductLinkOnly(msgText)) {
          console.log('[PDD] Skipping product link, looking for real question...');
          continue;
        }
        
        return {
          text: msgText,
          element: item
        };
      }
    }
  }

  return null;
}

/**
 * Check if message is a PDD system/robot message (not a real buyer message)
 * These are automated messages from PDD's chat system that should not trigger AI replies
 */
function isPddSystemMessage(text) {
  if (!text) return false;
  
  // PDD robot system messages patterns
  const systemPatterns = [
    // Robot couldn't find answer
    '机器人未找到对应的回复',
    '点击添加',
    // Robot paused notifications
    '机器人已暂停接待',
    '您接待过此消费者',
    '为避免插嘴',
    '为避免抢答',
    '立即恢复接待',
    // Auto-reply system messages
    '自动回复',
    '系统消息',
    '系统提示',
    // Session/waiting messages
    '会话已结束',
    '会话超时',
    '正在排队',
    '请稍候',
    // Transfer notifications
    '转接给',
    '已转接',
    // Rating/evaluation prompts
    '请对本次服务进行评价',
    '服务评价',
    // System notifications about merchant
    '商家已回复',
    '商家正在输入',
    // Welcome/greeting system messages
    '欢迎光临',
    '感谢您的咨询',
    // Common system action prompts
    '>>点此',
    '【立即',
    '点击查看',
    '点击领取',
  ];
  
  const lowerText = text.toLowerCase();
  
  for (const pattern of systemPatterns) {
    if (text.includes(pattern) || lowerText.includes(pattern.toLowerCase())) {
      return true;
    }
  }
  
  return false;
}

/**
 * Check if message is only a product link/card without real question
 */
function isProductLinkOnly(text) {
  // Product card patterns: contains price (￥) and product name but no question
  const hasPrice = /[￥¥]\s*\d+/.test(text);
  const hasQuestion = /[？?]|怎么|为什么|什么|如何|能不能|可以|吗|呢|嘛|多少|几/.test(text);
  
  // If has price but no question words, likely just a product link
  if (hasPrice && !hasQuestion && text.length < 100) {
    return true;
  }
  
  // Very short messages with only product ID or link patterns
  if (/^(商品ID|订单编号|http|https|链接)[：:\s]/i.test(text)) {
    return true;
  }
  
  return false;
}

/**
 * Collect full conversation context (recent messages)
 */
function collectConversationContext() {
  const messageSelectors = [
    '[class*="msg-item"]',
    '[class*="message-item"]',
    '[class*="chat-msg"]',
    '[class*="bubble"]',
    '[class*="msg-row"]',
    '[class*="message-row"]'
  ];

  let messageItems = [];
  for (const selector of messageSelectors) {
    const items = document.querySelectorAll(selector);
    if (items.length > 0) {
      messageItems = Array.from(items);
      break;
    }
  }

  if (messageItems.length === 0) {
    const chatArea = findElement([
      '[class*="chat-content"]',
      '[class*="message-list"]',
      '[class*="msg-list"]',
      '[class*="chat-body"]',
      '[class*="im-content"]',
      '[class*="chat-record"]'
    ]);
    if (chatArea) {
      messageItems = Array.from(chatArea.children);
    }
  }

  // Collect last 10 messages as context
  const contextLines = [];
  const recentItems = messageItems.slice(-10);
  
  for (const item of recentItems) {
    const msgText = extractMessageText(item);
    if (!msgText || msgText.length < 2) continue;
    
    const role = isCustomerMessage(item) ? '买家' : '客服';
    contextLines.push(`${role}: ${msgText}`);
  }

  return contextLines.join('\n');
}

/**
 * Determine if a message element is from the customer (buyer)
 */
function isCustomerMessage(el) {
  const className = (el.className || '').toLowerCase();
  const html = el.outerHTML.toLowerCase();
  const text = el.textContent || '';

  // Check for merchant/self indicators in the message content
  // Pinduoduo shows "主账号" label next to merchant messages
  if (text.includes('主账号') || text.includes('客服') || text.includes('商家')) {
    return false;
  }

  // Positive indicators for customer/buyer messages
  if (className.includes('left') || className.includes('buyer') ||
      className.includes('customer') || className.includes('other') ||
      className.includes('receive') || className.includes('incoming')) {
    return true;
  }

  // Negative indicators for self/merchant messages
  if (className.includes('right') || className.includes('self') ||
      className.includes('merchant') || className.includes('mine') ||
      className.includes('send') || className.includes('outgoing')) {
    return false;
  }

  // Check for avatar or name indicator on the right side (merchant)
  const avatar = el.querySelector('[class*="avatar"], img');
  if (avatar) {
    const avatarRect = avatar.getBoundingClientRect();
    const elRect = el.getBoundingClientRect();
    // If avatar is on the right side, it's merchant message
    if (avatarRect.left > elRect.left + elRect.width * 0.5) {
      return false;
    }
  }

  // Check position - buyer messages typically aligned left
  const rect = el.getBoundingClientRect();
  const parentRect = el.parentElement ? el.parentElement.getBoundingClientRect() : { width: window.innerWidth, left: 0 };
  const relativeX = rect.left - parentRect.left;
  const elWidth = rect.width;
  const parentWidth = parentRect.width;

  // If element takes most of the width, check inner content alignment
  if (elWidth > parentWidth * 0.8) {
    // Look for inner bubble/content element
    const bubble = el.querySelector('[class*="bubble"], [class*="content"], [class*="text"]');
    if (bubble) {
      const bubbleRect = bubble.getBoundingClientRect();
      const bubbleRelX = bubbleRect.left - parentRect.left;
      // If bubble is in left third, it's customer message
      if (bubbleRelX < parentWidth * 0.3) return true;
      // If bubble is in right third, it's merchant message
      if (bubbleRelX > parentWidth * 0.5) return false;
    }
  }

  // If positioned in the left third, likely a buyer message
  if (relativeX < parentWidth * 0.3) return true;
  // If positioned in the right half, likely a merchant message
  if (relativeX > parentWidth * 0.5) return false;

  return false;
}

/**
 * Extract clean message text from element
 */
function extractMessageText(el) {
  // Try specific content selectors first
  const contentEl = el.querySelector('[class*="content"], [class*="text"], [class*="body"], [class*="bubble"]');
  if (contentEl) {
    return contentEl.textContent.trim();
  }

  // Fallback: get text but exclude time stamps and names
  const clone = el.cloneNode(true);
  const timeEls = clone.querySelectorAll('[class*="time"], [class*="date"], [class*="name"], [class*="avatar"]');
  timeEls.forEach(t => t.remove());

  return clone.textContent.trim();
}

/**
 * Extract product card IDs from recent chat messages
 * Looks for patterns like "商品ID: 633766363069" in product cards
 */
function extractProductCardIds() {
  const productIds = [];
  
  // Find all message elements in chat
  const messageSelectors = [
    '[class*="msg-item"]',
    '[class*="message-item"]',
    '[class*="chat-msg"]',
    '[class*="bubble"]',
    '[class*="msg-row"]',
    '[class*="message-row"]',
    '[class*="product-card"]',
    '[class*="goods-card"]'
  ];

  let messageItems = [];
  for (const selector of messageSelectors) {
    const items = document.querySelectorAll(selector);
    if (items.length > 0) {
      messageItems = Array.from(items);
      break;
    }
  }

  // Check last 10 messages for product cards
  const recentItems = messageItems.slice(-10);
  
  for (const item of recentItems) {
    const text = item.textContent || '';
    
    // Pattern 1: "商品ID: 633766363069" or "商品ID：633766363069"
    const idMatch = text.match(/商品ID[：:]\s*(\d+)/);
    if (idMatch && idMatch[1]) {
      productIds.push(idMatch[1]);
      console.log(`[PDD] Found product ID from card: ${idMatch[1]}`);
    }
    
    // Pattern 2: PDD goods_id in URLs
    const urlMatch = text.match(/goods_id[=:](\d+)/i);
    if (urlMatch && urlMatch[1]) {
      productIds.push(urlMatch[1]);
      console.log(`[PDD] Found product ID from URL: ${urlMatch[1]}`);
    }
  }
  
  // Return unique IDs
  return [...new Set(productIds)];
}

/**
 * Get current customer name
 */
function getCurrentCustomerName() {
  // Method 0: PDD-specific - get from selected chat-list item
  // Based on diagnostic: container is .chat-list-box, items are .chat-list
  try {
    const chatListBox = document.querySelector('.chat-list-box, [class*="chat-list-box"]');
    if (chatListBox) {
      // Find selected/active chat-list item
      const selectedItem = chatListBox.querySelector('.chat-list.active, .chat-list.selected, .chat-list[class*="active"], .chat-list[class*="selected"]');
      if (selectedItem) {
        // Look for name element - usually in a specific class
        const nameEl = selectedItem.querySelector('[class*="nick"], [class*="name"], .chat-list-name, .visitor-name');
        if (nameEl && nameEl.textContent.trim()) {
          const name = nameEl.textContent.trim();
          // Filter out system labels
          if (name && !['主账号', '客服', '商家', '已超时', '收藏会话', '游客'].includes(name)) {
            logToMain(`Found customer name from PDD chat-list: ${name}`);
            return name;
          }
        }
        
        // Alternative: extract name from the text preview (format: "已超时 买家名 消息内容")
        const textContent = selectedItem.textContent || '';
        // Common patterns: "已超时 买**家 消息内容" or "买**家 消息内容"
        const textParts = textContent.split(/\s+/).filter(p => p.length > 0);
        for (let i = 0; i < textParts.length; i++) {
          const part = textParts[i];
          // Look for masked name pattern (e.g., "知**彼", "民**强", "浮**梦")
          if (/^[\u4e00-\u9fa5].{0,2}\*{1,3}.{0,2}[\u4e00-\u9fa5]?$/.test(part)) {
            logToMain(`Found customer name from PDD chat-list text: ${part}`);
            return part;
          }
          // Look for English/number masked pattern
          if (/^[a-zA-Z0-9].{0,3}\*{1,3}.{0,3}[a-zA-Z0-9]?$/.test(part)) {
            logToMain(`Found customer name from PDD chat-list text: ${part}`);
            return part;
          }
        }
      }
    }
  } catch (e) {
    console.error('[PDD] Error in PDD-specific name extraction:', e);
  }
  
  // Method 1: Try to get from chat header area (most reliable)
  const headerSelectors = [
    // PDD specific header selectors
    '.im-header .name',
    '.im-header .nick',
    '.chat-header .name',
    '.chat-header .nick-name',
    '[class*="ChatHeader"] [class*="name"]',
    '[class*="chatHeader"] [class*="nickName"]',
    '[class*="session-header"] [class*="name"]',
    '[class*="conversation-header"] [class*="name"]',
    // Generic header selectors
    '[class*="chat-header"] [class*="name"]',
    '[class*="header"] [class*="nick"]',
    '[class*="title-bar"] [class*="name"]',
    '[class*="user-name"]',
    '[class*="buyer-name"]',
    '[class*="customer-name"]',
    '[class*="chat-title"]',
    '[class*="session-title"]',
  ];
  
  for (const selector of headerSelectors) {
    try {
      const el = document.querySelector(selector);
      if (el && el.textContent.trim() && el.textContent.trim().length > 0) {
        const name = el.textContent.trim();
        // Skip if it looks like a generic label
        if (!['聊天', '会话', '客服', '商家'].includes(name)) {
          console.log(`[PDD] Found customer name from header: ${name}`);
          return name;
        }
      }
    } catch (e) {}
  }
  
  // Method 2: Try to get name from currently selected/active conversation in list
  const activeItemSelectors = [
    '.session-item.active',
    '.session-item.selected',
    '.conversation-item.active',
    '.conversation-item.selected',
    '[class*="session-item"][class*="active"]',
    '[class*="session-item"][class*="selected"]',
    '[class*="conversation-item"][class*="active"]',
    '[class*="conversation-item"][class*="selected"]',
    '[class*="chat-item"][class*="active"]',
    '[class*="im-item"][class*="current"]',
  ];
  
  for (const selector of activeItemSelectors) {
    try {
      const selectedItem = document.querySelector(selector);
      if (selectedItem) {
        // Try to find name element inside
        const nameEl = selectedItem.querySelector('[class*="name"], [class*="nick"], [class*="title"]');
        if (nameEl && nameEl.textContent.trim()) {
          const name = nameEl.textContent.trim();
          if (name.length > 0 && !['聊天', '会话'].includes(name)) {
            console.log(`[PDD] Found customer name from active item: ${name}`);
            return name;
          }
        }
        
        // Try data attributes for unique ID
        const dataId = selectedItem.dataset.id || 
                       selectedItem.dataset.visitorId || 
                       selectedItem.dataset.sessionId ||
                       selectedItem.dataset.visitorid ||
                       selectedItem.dataset.sessionid ||
                       selectedItem.getAttribute('data-id') ||
                       selectedItem.getAttribute('data-visitor-id');
        if (dataId) {
          console.log(`[PDD] Using data-id as customer identifier: ${dataId}`);
          return `买家_${dataId}`;
        }
        
        // Use item index as fallback identifier
        const parent = selectedItem.parentElement;
        if (parent) {
          const siblings = Array.from(parent.children).filter(c => 
            c.className && (c.className.includes('session') || c.className.includes('conversation') || c.className.includes('item'))
          );
          const index = siblings.indexOf(selectedItem);
          if (index >= 0) {
            console.log(`[PDD] Using conversation index as identifier: ${index}`);
            return `会话${index + 1}`;
          }
        }
      }
    } catch (e) {}
  }
  
  // Method 3: Try to extract from the first buyer message in current chat
  const messageSelectors = [
    '[class*="msg-item"]',
    '[class*="message-item"]',
    '[class*="chat-msg"]',
    '[class*="bubble"]',
  ];
  
  for (const selector of messageSelectors) {
    try {
      const messages = document.querySelectorAll(selector);
      for (const msg of messages) {
        if (isCustomerMessage(msg)) {
          // Try to find sender name in message
          const senderEl = msg.querySelector('[class*="sender"], [class*="nick"], [class*="name"], [class*="avatar"]');
          if (senderEl) {
            const title = senderEl.getAttribute('title') || senderEl.getAttribute('alt');
            if (title && title.length > 0) {
              console.log(`[PDD] Found customer name from message: ${title}`);
              return title;
            }
          }
          break;
        }
      }
    } catch (e) {}
  }
  
  // Method 4: Try to find any identifier in the chat panel
  const chatPanel = findElement(['[class*="chat-panel"]', '[class*="im-panel"]', '[class*="message-panel"]']);
  if (chatPanel) {
    const dataId = chatPanel.dataset.id || chatPanel.dataset.visitorId || chatPanel.dataset.uid;
    if (dataId) {
      console.log(`[PDD] Using chat panel data-id: ${dataId}`);
      return `买家_${dataId}`;
    }
  }
  
  // Method 5: Generate unique ID based on current timestamp + random
  // This ensures each conversation is counted separately even if we can't identify the name
  const uniqueId = `${Date.now().toString(36)}_${Math.random().toString(36).substr(2, 4)}`;
  console.log(`[PDD] Generated unique conversation ID: ${uniqueId}`);
  return `买家_${uniqueId}`;
}

/**
 * Type text into the input box and send - uses direct value setting to avoid issues
 */
async function sendMessage(text) {
  logToMain(`sendMessage called with text: ${text?.substring(0, 50)}`);
  
  // Debug: log all available input elements
  const allTextareas = document.querySelectorAll('textarea');
  const allContentEditable = document.querySelectorAll('[contenteditable="true"]');
  logToMain(`Found ${allTextareas.length} textareas, ${allContentEditable.length} contenteditable elements`);
  
  // Log specific details about potential inputs
  allTextareas.forEach((ta, i) => {
    logToMain(`Textarea ${i}: class="${ta.className?.substring(0, 60)}", visible=${ta.offsetParent !== null}, size=${ta.offsetWidth}x${ta.offsetHeight}`);
  });
  
  // PDD-specific: look for common input patterns in PDD chat
  const pddInputSelectors = [
    // PDD specific selectors first
    '.chat-input textarea',
    '.im-editor textarea',
    '.message-input textarea',
    '[class*="InputArea"] textarea',
    '[class*="inputArea"] textarea',
    '[class*="chat-editor"] textarea',
    '[class*="reply-input"] textarea',
    // Generic selectors
    '[class*="chat-input"] textarea',
    '[class*="editor"] textarea',
    '[class*="input-area"] textarea',
    '[class*="chat"] textarea',
    'textarea[class*="input"]',
    '[contenteditable="true"][class*="input"]',
    '[contenteditable="true"][class*="editor"]',
    '[class*="chat-input"] [contenteditable]',
    '[contenteditable="true"]',
    'textarea'
  ];
  
  // Find input area
  let input = null;
  let matchedSelector = '';
  for (const selector of pddInputSelectors) {
    const el = document.querySelector(selector);
    if (el && el.offsetParent !== null) {  // Check if visible
      input = el;
      matchedSelector = selector;
      break;
    }
  }
  
  // If still not found, try any visible textarea
  if (!input) {
    for (const ta of allTextareas) {
      if (ta.offsetParent !== null && ta.offsetWidth > 50) {
        input = ta;
        matchedSelector = 'fallback textarea';
        break;
      }
    }
  }

  if (!input) {
    logToMain('Input box not found after trying all selectors', 'error');
    return false;
  }
  
  logToMain(`Found input via "${matchedSelector}": tag=${input.tagName}, class="${input.className?.substring(0, 60)}"`);
  logToMain(`Input dimensions: ${input.offsetWidth}x${input.offsetHeight}, visible=${input.offsetParent !== null}`);
  

  // Click and focus the input
  logToMain('Clicking and focusing input...');
  input.click();
  input.focus();
  await new Promise(r => setTimeout(r, 300));
  logToMain(`Input focused, activeElement: ${document.activeElement?.tagName}, class=${document.activeElement?.className?.substring(0, 40)}`);

  const isContentEditable = input.getAttribute('contenteditable') === 'true';
  logToMain(`Input type: ${isContentEditable ? 'contentEditable' : 'textarea'}`);

  // Clear existing content first
  if (isContentEditable) {
    input.innerHTML = '';
  } else {
    input.value = '';
  }
  input.dispatchEvent(new Event('input', { bubbles: true }));
  await new Promise(r => setTimeout(r, 100));

  // Set the full text directly (more reliable than character-by-character)
  logToMain('Setting text content...');
  if (isContentEditable) {
    input.innerText = text;
  } else {
    // Use native setter for React-controlled inputs
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype, 'value'
    )?.set;
    if (setter) {
      setter.call(input, text);
      logToMain('Used native setter for React textarea');
    } else {
      input.value = text;
      logToMain('Used direct value assignment');
    }
  }

  // Trigger input event to notify the app
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
  
  // Also dispatch React-style events
  const nativeInputEvent = new InputEvent('input', { bubbles: true, data: text, inputType: 'insertText' });
  input.dispatchEvent(nativeInputEvent);
  logToMain('Dispatched input/change events');

  // Wait for the input to be processed
  await new Promise(r => setTimeout(r, 500));

  // Verify the text is in the input
  const currentValue = isContentEditable ? input.innerText : input.value;
  logToMain(`Verification - text in input: "${currentValue?.substring(0, 50)}..." (${currentValue?.length || 0} chars)`);
  
  if (!currentValue || currentValue.length < text.length * 0.8) {
    logToMain('Text not properly entered, retrying with alternative method...', 'warn');
    // Retry with execCommand for contentEditable
    if (isContentEditable) {
      input.focus();
      document.execCommand('selectAll', false, null);
      document.execCommand('insertText', false, text);
    }
    await new Promise(r => setTimeout(r, 300));
  }

  logToMain('Text entered, attempting to send...');

  // Try multiple send methods
  
  // Method 1: Look for send button and click it (most reliable)
  const sendButtonSelectors = [
    '[class*="send-btn"]',
    '[class*="sendBtn"]',
    '[class*="send_btn"]',
    'button[class*="send"]',
    '[class*="submit-btn"]',
    '[class*="chat-send"]',
    '[class*="im-send"]',
    // Text-based fallback
    'button:contains("发送")',
  ];
  
  let sendButton = null;
  for (const selector of sendButtonSelectors) {
    try {
      sendButton = document.querySelector(selector);
      if (sendButton && sendButton.offsetParent !== null) {
        logToMain(`Found send button via "${selector}": class="${sendButton.className?.substring(0, 40)}"`);
        break;
      }
    } catch(e) {}
  }
  
  // Try finding button by text content
  if (!sendButton) {
    const allButtons = document.querySelectorAll('button, [role="button"], [class*="btn"]');
    for (const btn of allButtons) {
      const text = (btn.textContent || '').trim();
      if (text === '发送' || text === 'Send') {
        sendButton = btn;
        logToMain(`Found send button by text content: "${text}"`);
        break;
      }
    }
  }
  
  if (sendButton) {
    logToMain('Clicking send button...');
    sendButton.click();
    await new Promise(r => setTimeout(r, 200));
  } else {
    logToMain('No send button found, will rely on Enter key', 'warn');
  }
  
  // Method 2: Use native Electron sendInputEvent for trusted Enter key (backup)
  logToMain('Also sending native Enter key as backup...');
  ipcRenderer.send('platform:send-enter', PLATFORM_ID);
  
  // Wait and verify message was sent
  await new Promise(r => setTimeout(r, 500));
  
  // Check if input was cleared (indicates message was sent)
  const afterSendValue = isContentEditable ? input.innerText : input.value;
  const wasSent = !afterSendValue || afterSendValue.length < 5;
  logToMain(`After send check - input value: "${afterSendValue?.substring(0, 30) || '(empty)'}", likely sent: ${wasSent}`);
  
  if (!wasSent) {
    logToMain('Message may not have been sent - input still contains text', 'warn');
  }
  
  logToMain(`Message send attempt completed for: ${text.substring(0, 50)}`);

  return true;
}

/**
 * Check if the absolute last message in the chat is from merchant (us)
 * If so, it means we already replied and buyer hasn't sent a new message
 */
function isLastMessageFromMerchant() {
  const messageSelectors = [
    '[class*="msg-item"]',
    '[class*="message-item"]',
    '[class*="chat-msg"]',
    '[class*="bubble"]',
    '[class*="msg-row"]',
    '[class*="message-row"]'
  ];

  let messageItems = [];
  for (const selector of messageSelectors) {
    const items = document.querySelectorAll(selector);
    if (items.length > 0) {
      messageItems = Array.from(items);
      break;
    }
  }

  if (messageItems.length === 0) {
    const chatArea = findElement([
      '[class*="chat-content"]',
      '[class*="message-list"]',
      '[class*="msg-list"]',
      '[class*="chat-body"]',
      '[class*="im-content"]',
      '[class*="chat-record"]'
    ]);
    if (chatArea) {
      messageItems = Array.from(chatArea.children);
    }
  }

  if (messageItems.length === 0) return false;

  // Check the last message
  for (let i = messageItems.length - 1; i >= 0; i--) {
    const item = messageItems[i];
    const text = extractMessageText(item);
    if (!text || text.length < 2) continue;

    // If last meaningful message is NOT from customer, it's from us
    return !isCustomerMessage(item);
  }

  return false;
}

/**
 * Process current active conversation - check and reply
 */
async function processCurrentConversation() {
  // Prevent concurrent calls
  if (state.isReplying) {
    console.log('[PDD] Already replying, skipping concurrent call');
    return false;
  }
  
  // Skip if the last message is from us (already replied, buyer hasn't sent new message)
  if (isLastMessageFromMerchant()) {
    console.log('[PDD] Last message is from merchant, skipping - waiting for new buyer message');
    return false;
  }

  const lastMsg = getLastCustomerMessage();
  if (!lastMsg) return false;

  const customerName = getCurrentCustomerName();
  const customerId = `pdd_${customerName}`;
  const msgHash = hashMessage(lastMsg.text);
  const conversationKey = `${customerId}_${msgHash}`;

  // Check if we've already processed this exact message from this customer
  if (state.processedMessages.has(conversationKey)) {
    return false;
  }

  // Check if customer sent a new message since our last reply
  const lastKnownMsgHash = state.lastCustomerMessages.get(customerId);
  const lastReplyTime = state.repliedConversations.get(customerId);
  
  if (lastKnownMsgHash === msgHash && lastReplyTime) {
    // Same message as before, check if enough time has passed
    const timeSinceReply = Date.now() - lastReplyTime;
    if (timeSinceReply < state.replyTimeout) {
      // Already replied to this message, don't reply again
      console.log(`[PDD] Skipping - already replied to ${customerName}, waiting for new message`);
      return false;
    }
  }

  // Set lock before processing
  state.isReplying = true;

  try {
    // Mark as processed
    state.processedMessages.add(conversationKey);
    state.lastCustomerMessages.set(customerId, msgHash);

    // Trim processed set if too large
    if (state.processedMessages.size > 500) {
      const arr = Array.from(state.processedMessages);
      state.processedMessages = new Set(arr.slice(-300));
    }

    // Collect full conversation context
    const conversationContext = collectConversationContext();
    
    // Extract product names from order panel for product-specific KB matching
    // Click "个人订单" tab first to get buyer-specific orders
    const orderInfo = await extractOrderInfo();
    const productNames = orderInfo.orders
      .flatMap(o => (o.products || []).map(p => p.name))
      .filter(Boolean);
    
    console.log(`[PDD] New message from ${customerName}: ${lastMsg.text.substring(0, 50)}`);
    if (productNames.length > 0) {
      console.log(`[PDD] Product context from order panel: ${productNames.join(', ').substring(0, 100)}`);
    }

    // Extract buyer-sent media (high-res images + video frames)
    let buyerImages = [];
    let buyerVideoFrames = [];
    
    // Quick check: are there any images or videos in recent buyer messages?
    const quickImages = extractChatImages();
    if (quickImages.length > 0) {
      console.log(`[PDD] Detected ${quickImages.length} buyer media items, extracting high-res...`);
      try {
        const media = await extractMediaContent();
        buyerImages = media.images.length > 0 ? media.images : quickImages;
        buyerVideoFrames = media.videoFrames;
      } catch (err) {
        console.warn('[PDD] Media extraction failed, using thumbnails:', err.message);
        buyerImages = quickImages;
      }
    }
    
    if (buyerImages.length > 0) {
      console.log(`[PDD] Found ${buyerImages.length} buyer images: ${buyerImages.join(', ').substring(0, 100)}`);
    }
    if (buyerVideoFrames.length > 0) {
      console.log(`[PDD] Captured ${buyerVideoFrames.length} video frames`);
    }

    // Extract product card IDs from chat messages
    const productCardIds = extractProductCardIds();
    if (productCardIds.length > 0) {
      console.log(`[PDD] Found product card IDs: ${productCardIds.join(', ')}`);
    }

    // Send to main process with context
    ipcRenderer.send('platform:new-message', {
      platformId: PLATFORM_ID,
      customerId: customerId,
      customerName: customerName,
      message: lastMsg.text,
      context: conversationContext,
      productNames: productNames,
      productCardIds: productCardIds,  // Include product IDs from chat cards
      buyerImages: buyerImages,  // Include buyer-sent images for vision analysis
      buyerVideoFrames: buyerVideoFrames,  // Include video key frames for vision analysis
      timestamp: Date.now()
    });

    return true;
  } finally {
    // Release lock after a short delay to prevent rapid re-triggering
    setTimeout(() => {
      state.isReplying = false;
    }, 2000);
  }
}

/**
 * Scan and process all unread conversations
 */
async function scanUnreadConversations() {
  if (state.isProcessing) return;
  state.isProcessing = true;

  try {
    const unreadItems = findUnreadConversations();
    console.log(`[PDD] Scanning ${unreadItems.length} unread/timeout conversations`);

    for (const item of unreadItems) {
      // Log which item we're clicking
      const itemPreview = (item.textContent || '').substring(0, 50).replace(/\s+/g, ' ').trim();
      console.log(`[PDD] Clicking conversation: "${itemPreview}..."`);
      
      // Click on the conversation
      item.click();
      // Wait for chat to load
      await new Promise(r => setTimeout(r, 1500));

      // Check if last message is from merchant (already replied)
      if (isLastMessageFromMerchant()) {
        console.log('[PDD] This conversation already has merchant reply as last message, skipping');
        await new Promise(r => setTimeout(r, 300));
        continue;
      }

      // Process the conversation
      const processed = await processCurrentConversation();

      if (processed) {
        // Wait 2-3 seconds to see if buyer responds
        console.log('[PDD] Waiting 2-3s for buyer response...');
        await new Promise(r => setTimeout(r, 2000 + Math.random() * 1000));
        
        // Check if buyer sent a new message
        const newMsg = getLastCustomerMessage();
        const customerName = getCurrentCustomerName();
        const customerId = `pdd_${customerName}`;
        
        if (newMsg) {
          const newMsgHash = hashMessage(newMsg.text);
          const lastKnownHash = state.lastCustomerMessages.get(customerId);
          
          if (newMsgHash !== lastKnownHash) {
            // Buyer sent a new message, process it
            console.log('[PDD] Buyer sent new message, processing...');
            await processCurrentConversation();
            await new Promise(r => setTimeout(r, 2000));
          } else {
            console.log('[PDD] No new message from buyer, moving to next conversation');
          }
        }
      } else {
        console.log('[PDD] Conversation not processed (may be already handled or no customer message found)');
      }

      // Small delay before next conversation
      await new Promise(r => setTimeout(r, 500));
    }
    
    if (unreadItems.length === 0) {
      console.log('[PDD] No unread/timeout conversations found in this scan');
    } else {
      console.log(`[PDD] Finished scanning ${unreadItems.length} conversations`);
    }
  } catch (e) {
    console.error('[PDD] Error scanning conversations:', e);
  } finally {
    state.isProcessing = false;
  }
}

/**
 * Initialize state by marking already-replied messages as processed
 * Only marks conversations where the LAST message is from merchant (already replied)
 * Leaves unreplied conversations (last message from buyer) UNPROCESSED so they get handled
 */
function initializeExistingMessages() {
  // Only mark the current conversation as processed if we already replied
  // (i.e., last message is from merchant). If last message is from buyer,
  // leave it unprocessed so scanUnreadConversations() or processCurrentConversation() picks it up.
  if (isLastMessageFromMerchant()) {
    const lastMsg = getLastCustomerMessage();
    if (lastMsg) {
      const customerName = getCurrentCustomerName();
      const customerId = `pdd_${customerName}`;
      const msgHash = hashMessage(lastMsg.text);
      const conversationKey = `${customerId}_${msgHash}`;

      // Mark current message as already processed (merchant already replied)
      state.processedMessages.add(conversationKey);
      state.lastCustomerMessages.set(customerId, msgHash);
      state.repliedConversations.set(customerId, Date.now());

      console.log(`[PDD] Init: marked already-replied conversation as processed from ${customerName}`);
    }
  } else {
    console.log('[PDD] Init: current conversation has unreplied buyer message, will process it');
  }
}

/**
 * Start monitoring for messages
 */
function startMonitoring() {
  if (state.observerActive) return;
  state.observerActive = true;

  console.log('[PDD] Starting message monitoring...');

  // Initialize: only mark already-replied conversations as processed
  initializeExistingMessages();

  // 1. Process current conversation if last message is from buyer (not merchant)
  if (!isLastMessageFromMerchant()) {
    processCurrentConversation();
  } else {
    console.log('[PDD] Last message is from merchant on startup, skipping initial process');
  }

  // 2. Click "Load More" button to load all conversations first
  async function loadAllConversations() {
    const loadMoreBtn = document.querySelector('.more-btn-box, [class*="more-btn"], [class*="load-more"]');
    if (loadMoreBtn && loadMoreBtn.textContent.includes('加载更多')) {
      console.log('[PDD] Found "加载更多会话" button, clicking to load more conversations...');
      loadMoreBtn.click();
      await new Promise(r => setTimeout(r, 1500));  // Wait for conversations to load
      // Recursively load more if button still exists
      await loadAllConversations();
    }
  }
  
  // Load all conversations before scanning
  setTimeout(async () => {
    await loadAllConversations();
  }, 1500);

  // 3. Aggressive startup scan: scan unread/timeout conversations immediately and again after delay
  // First scan at 2s (page may still be loading)
  setTimeout(() => {
    console.log('[PDD] Startup scan #1: scanning for timeout/unread conversations...');
    scanUnreadConversations();
  }, 2000);
  
  // Second scan at 6s (ensure page is fully loaded, catches late-rendering items)
  setTimeout(() => {
    console.log('[PDD] Startup scan #2: re-scanning for any missed timeout conversations...');
    scanUnreadConversations();
  }, 6000);
  
  // Third scan at 15s (final catch-all for slow-loading conversation lists)
  setTimeout(() => {
    console.log('[PDD] Startup scan #3: final scan for timeout conversations...');
    scanUnreadConversations();
  }, 15000);

  // 4. Set up MutationObserver for new messages in chat area
  const chatArea = findElement([
    '[class*="chat-content"]',
    '[class*="message-list"]',
    '[class*="msg-list"]',
    '[class*="chat-body"]',
    '[class*="im-content"]'
  ]) || document.body;

  const observer = new MutationObserver((mutations) => {
    let hasNewContent = false;
    for (const mutation of mutations) {
      if (mutation.addedNodes.length > 0) {
        hasNewContent = true;
        break;
      }
    }
    if (hasNewContent && !state.isProcessing) {
      setTimeout(() => processCurrentConversation(), 500);
    }
  });

  observer.observe(chatArea, {
    childList: true,
    subtree: true
  });

  // 5. Periodic check for new messages - use Shift+Tab to switch (every 5 seconds, with cooldown)
  state.scanInterval = setInterval(() => {
    if (!state.isProcessing) {
      const now = Date.now();
      
      // Check cooldown - don't send Shift+Tab too frequently
      if (now - state.lastShiftTabTime < state.shiftTabCooldown) {
        return;
      }
      
      // If we've had multiple consecutive "no unread" results, extend cooldown
      if (state.consecutiveNoUnread >= 3) {
        // After 3 consecutive failures, wait longer (30 seconds)
        if (now - state.lastShiftTabTime < 30000) {
          return;
        }
        // Reset counter after extended wait
        state.consecutiveNoUnread = 0;
      }
      
      // Check if there are unread indicators
      const unreadConvs = findUnreadConversations();
      if (unreadConvs.length > 0) {
        console.log(`[PDD] Found ${unreadConvs.length} unread conversations, pressing Shift+Tab...`);
        state.lastShiftTabTime = now;
        state.consecutiveNoUnread = 0;  // Reset counter on success
        ipcRenderer.send('platform:send-shift-tab', PLATFORM_ID);
        // Process after switch
        setTimeout(() => processCurrentConversation(), 1500);
      }
    }
  }, 5000);  // Changed from 3000 to 5000ms

  // 6. Periodic check on current conversation (every 2 seconds)
  setInterval(() => {
    if (!state.isProcessing) {
      processCurrentConversation();
    }
  }, 2000);

  console.log('[PDD] Message monitoring active');
}

// ============ OrderDetect: Order Info Extraction ============

/**
 * Try to click "个人订单" (personal orders) tab to show buyer-specific orders.
 * Returns an object with { success, debug } for diagnostics.
 */
async function clickPersonalOrderTab() {
  const debug = { strategy: 'none', found: false, tag: null, class: null, text: null, xpathCount: 0 };
  try {
    // Strategy 1: Use XPath to find elements with exact text "个人订单"
    const xpath = '//span[text()="个人订单"] | //div[text()="个人订单"] | //a[text()="个人订单"] | //p[text()="个人订单"] | //*[contains(text(),"个人订单")]';
    const xpathResult = document.evaluate(xpath, document.body, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
    debug.xpathCount = xpathResult.snapshotLength;
    
    for (let i = 0; i < xpathResult.snapshotLength; i++) {
      const el = xpathResult.snapshotItem(i);
      const directText = el.childNodes.length <= 3 ? (el.textContent || '').trim() : '';
      if (directText.includes('个人订单') && directText.length < 20) {
        const classList = el.classList ? el.classList.toString() : '';
        debug.strategy = 'xpath';
        debug.found = true;
        debug.tag = el.tagName;
        debug.class = classList.substring(0, 80);
        debug.text = directText.substring(0, 30);
        const isActive = classList.includes('active') || classList.includes('selected') || classList.includes('current');
        if (!isActive) {
          el.click();
          await new Promise(resolve => setTimeout(resolve, 600));
        }
        debug.alreadyActive = isActive;
        debug._element = el;  // Keep reference for DOM navigation
        return { success: true, debug };
      }
    }

    // Strategy 2: Find tab-like containers with "个人订单" text
    const allElements = document.querySelectorAll('[class*="tab"], [class*="Tab"], [role="tab"], [class*="menu"], [class*="nav"], [class*="order"] span, [class*="order"] div');
    debug.strategy2Count = allElements.length;
    for (const el of allElements) {
      const text = (el.textContent || '').trim();
      if (text.includes('个人订单') && text.length < 20) {
        const classList = el.classList ? el.classList.toString() : '';
        debug.strategy = 'css';
        debug.found = true;
        debug.tag = el.tagName;
        debug.class = classList.substring(0, 80);
        debug.text = text.substring(0, 30);
        const isActive = classList.includes('active') || classList.includes('selected') || classList.includes('current');
        if (!isActive) {
          el.click();
          await new Promise(resolve => setTimeout(resolve, 600));
        }
        debug.alreadyActive = isActive;
        return { success: true, debug };
      }
    }

    debug.strategy = 'not_found';
    return { success: false, debug };
  } catch (e) {
    debug.error = e.message;
    return { success: false, debug };
  }
}

/**
 * Extract order information from the chat page DOM (right sidebar / order panel)
 * First clicks "个人订单" tab to get buyer-specific orders instead of shop-wide orders.
 * IMPORTANT: Only extracts orders after confirming we're on "个人订单" tab.
 * If tab switch fails, returns empty orders to avoid sending shop-wide order context to AI.
 */
async function extractOrderInfo() {
  const result = {
    orders: [],
    chatImages: [],
    _tabDebug: null
  };

  try {
    // --- 0. Click "个人订单" tab to show buyer-specific orders ---
    const tabResult = await clickPersonalOrderTab();
    result._tabDebug = tabResult.debug;

    // CRITICAL: Only extract orders if we confirmed we're on buyer-specific tab
    if (!tabResult.success) {
      result.chatImages = extractChatImages();
      return result;
    }

    // --- 1. Try to find the active tab content area ---
    // Since the tab is LI.order-panel-second-bar, navigate to the content panel
    // PDD likely has: tab bar (UL/container) + content panels below
    let orderContentArea = null;
    
    // Strategy A: Find the "个人订单" tab's parent, then find the active content panel
    const personalTab = tabResult.debug._element;
    if (personalTab) {
      // Look for content area: sibling of tab's parent container, or next sibling content
      const tabParent = personalTab.parentElement;
      if (tabParent) {
        // Check siblings after the tab container for content panels
        let sibling = tabParent.nextElementSibling;
        while (sibling) {
          if (isElementVisible(sibling) && sibling.offsetHeight > 20) {
            orderContentArea = sibling;
            break;
          }
          sibling = sibling.nextElementSibling;
        }
        // Also try: parent's parent, then find content area
        if (!orderContentArea && tabParent.parentElement) {
          const grandParent = tabParent.parentElement;
          for (const child of grandParent.children) {
            if (child !== tabParent && isElementVisible(child) && child.offsetHeight > 30) {
              // This might be the content area
              const text = child.textContent || '';
              // Skip if it's a completely different section (chat, input, etc.)
              if (!text.includes('发送') && !text.includes('输入') && child.children.length > 0) {
                orderContentArea = child;
                break;
              }
            }
          }
        }
      }
    }

    // Add content area debug info
    result._panelDebug = {
      foundContentArea: !!orderContentArea,
      contentTag: orderContentArea?.tagName,
      contentClass: orderContentArea?.classList?.toString()?.substring(0, 80),
      contentText: orderContentArea?.textContent?.substring(0, 100),
      contentChildCount: orderContentArea?.children?.length
    };

    // If we found the specific content area for "个人订单", extract from it
    const searchRoot = orderContentArea || document;
    
    const orderPanelSelectors = [
      '[class*="order-card"]',
      '[class*="order-info"]:not([class*="order-info-tab"])',
      '[class*="order-detail"]',
      '[class*="trade-card"]',
      '[class*="trade-info"]'
    ];
    
    let orderPanel = null;
    for (const selector of orderPanelSelectors) {
      try {
        const els = searchRoot.querySelectorAll(selector);
        for (const el of els) {
          if (isElementVisible(el)) {
            orderPanel = el;
            break;
          }
        }
        if (orderPanel) break;
      } catch (e) {}
    }

    if (orderPanel) {
      const order = extractSingleOrder(orderPanel);
      if (order) {
        result.orders.push(order);
      }
    }

    // --- 2. Extract buyer-sent images from chat messages ---
    result.chatImages = extractChatImages();

  } catch (e) {
    console.error('[PDD][OrderDetect] Error extracting order info:', e);
  }

  return result;
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
  const orderIdEl = container.querySelector('[class*="order-no"], [class*="order-id"], [class*="order-sn"], [class*="orderId"]');
  if (orderIdEl) {
    const match = orderIdEl.textContent.match(/(\d{10,})/);
    if (match) order.orderId = match[1];
  }
  if (!order.orderId) {
    const idMatch = text.match(/(?:订单号|订单编号|单号)[：:\s]*(\d{10,})/);
    if (idMatch) order.orderId = idMatch[1];
  }

  // --- Payment Status ---
  const paymentEl = container.querySelector('[class*="pay-status"], [class*="pay_status"], [class*="payment"]');
  if (paymentEl) {
    order.paymentStatus = paymentEl.textContent.trim();
  }
  if (!order.paymentStatus) {
    const payMatch = text.match(/(已付款|已支付|待付款|待支付|未付款|退款中|已退款|部分退款)/);
    if (payMatch) order.paymentStatus = payMatch[1];
  }

  // --- Shipping Status ---
  const shippingEl = container.querySelector('[class*="logistics"], [class*="express"], [class*="delivery"], [class*="shipping"], [class*="ship-status"]');
  if (shippingEl) {
    order.shippingStatus = shippingEl.textContent.trim();
  }
  if (!order.shippingStatus) {
    const shipMatch = text.match(/(待发货|已发货|已签收|运输中|配送中|已揽收|退货中|已退货)/);
    if (shipMatch) order.shippingStatus = shipMatch[1];
  }

  // --- Products ---
  const productEls = container.querySelectorAll('[class*="goods-item"], [class*="goods-info"], [class*="product-item"], [class*="product-info"], [class*="sku-item"]');
  if (productEls.length > 0) {
    for (const pEl of productEls) {
      const product = extractProductFromElement(pEl);
      if (product) order.products.push(product);
    }
  } else {
    // Fallback: try to extract product info from the container itself
    const product = extractProductFromElement(container);
    if (product && product.name) order.products.push(product);
  }

  // Only return if we found at least some useful info
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
  const nameEl = el.querySelector('[class*="goods-name"], [class*="product-name"], [class*="product-title"], [class*="title"], [class*="item-name"]');
  if (nameEl) {
    product.name = nameEl.textContent.trim().substring(0, 100);
  }

  // Specs / SKU
  const specEl = el.querySelector('[class*="goods-spec"], [class*="sku-info"], [class*="sku-name"], [class*="spec"], [class*="attr"]');
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
  const messageSelectors = [
    '[class*="msg-item"]',
    '[class*="message-item"]',
    '[class*="chat-msg"]',
    '[class*="bubble"]',
    '[class*="msg-row"]',
    '[class*="message-row"]'
  ];

  let messageItems = [];
  for (const selector of messageSelectors) {
    const items = document.querySelectorAll(selector);
    if (items.length > 0) {
      messageItems = Array.from(items);
      break;
    }
  }

  // Scan last 5 messages for buyer-sent images
  const recentItems = messageItems.slice(-5);
  for (const item of recentItems) {
    if (!isCustomerMessage(item)) continue;

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
  const messageSelectors = [
    '[class*="msg-item"]',
    '[class*="message-item"]',
    '[class*="chat-msg"]',
    '[class*="bubble"]',
    '[class*="msg-row"]',
    '[class*="message-row"]'
  ];

  let messageItems = [];
  for (const selector of messageSelectors) {
    const items = document.querySelectorAll(selector);
    if (items.length > 0) {
      messageItems = Array.from(items);
      break;
    }
  }

  const highResUrls = [];
  const recentItems = messageItems.slice(-5);

  for (const item of recentItems) {
    if (!isCustomerMessage(item)) continue;

    const imgs = item.querySelectorAll('img[src]');
    for (const img of imgs) {
      if (!isContentImage(img)) continue;
      if (highResUrls.length >= 3) break;

      try {
        // Click thumbnail to open preview
        img.click();
        await new Promise(r => setTimeout(r, 800));

        // Try to find the high-res preview image
        const previewSelectors = [
          'img[class*="preview"]',
          'img[class*="fullscreen"]',
          '.image-preview img',
          '.ant-image-preview img',
          '[class*="ImagePreview"] img',
          '[class*="image-viewer"] img',
          '[class*="modal"] img[src*="http"]'
        ];

        let previewImg = null;
        for (const sel of previewSelectors) {
          previewImg = document.querySelector(sel);
          if (previewImg && previewImg.src && previewImg.src !== img.src) break;
          previewImg = null;
        }

        if (previewImg && previewImg.src) {
          // Remove resize/quality parameters to get original image
          let highResUrl = previewImg.src;
          highResUrl = highResUrl.replace(/[?&]x-oss-process=[^&]*/g, '');
          highResUrl = highResUrl.replace(/[?&]imageView2[^&]*/g, '');
          if (!highResUrls.includes(highResUrl)) {
            highResUrls.push(highResUrl);
            console.log(`[PDD][Vision] Got high-res image: ${highResUrl.substring(0, 80)}...`);
          }
        } else {
          // Fallback: use the thumbnail URL with quality upgrade
          let fallbackUrl = img.src;
          fallbackUrl = fallbackUrl.replace(/[?&]x-oss-process=[^&]*/g, '');
          fallbackUrl = fallbackUrl.replace(/[?&]imageView2[^&]*/g, '');
          if (!highResUrls.includes(fallbackUrl)) {
            highResUrls.push(fallbackUrl);
            console.log(`[PDD][Vision] Using fallback image: ${fallbackUrl.substring(0, 80)}...`);
          }
        }

        // Close preview
        const closeSelectors = [
          '[class*="close"]',
          '.ant-modal-close',
          '[aria-label="关闭"]',
          '[class*="preview"] [class*="close"]',
          'button[class*="close"]'
        ];
        for (const sel of closeSelectors) {
          const closeBtn = document.querySelector(sel);
          if (closeBtn && closeBtn.offsetParent !== null) {
            closeBtn.click();
            break;
          }
        }
        // Also try pressing Escape to close
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        await new Promise(r => setTimeout(r, 400));
      } catch (err) {
        console.warn(`[PDD][Vision] Error getting high-res image:`, err.message);
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
  const messageSelectors = [
    '[class*="msg-item"]',
    '[class*="message-item"]',
    '[class*="chat-msg"]',
    '[class*="bubble"]',
    '[class*="msg-row"]',
    '[class*="message-row"]'
  ];

  let messageItems = [];
  for (const selector of messageSelectors) {
    const items = document.querySelectorAll(selector);
    if (items.length > 0) {
      messageItems = Array.from(items);
      break;
    }
  }

  // Scan last 5 buyer messages for video elements
  const recentItems = messageItems.slice(-5);
  for (const item of recentItems) {
    if (!isCustomerMessage(item)) continue;

    // Find video elements or video cards
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

    // Also check for video cards that need clicking to play
    if (!videoEl) {
      const videoCards = item.querySelectorAll('[class*="video"], [class*="Video"]');
      for (const card of videoCards) {
        // Click to start playing
        try {
          card.click();
          await new Promise(r => setTimeout(r, 1500));
          // Try to find the video element after clicking
          for (const sel of videoSelectors) {
            videoEl = document.querySelector(sel);
            if (videoEl) break;
          }
        } catch (e) {
          console.warn('[PDD][Vision] Error clicking video card:', e.message);
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
        console.warn('[PDD][Vision] Video has invalid duration');
        continue;
      }

      const canvas = document.createElement('canvas');
      const ctx = canvas.getContext('2d');
      canvas.width = videoEl.videoWidth || 640;
      canvas.height = videoEl.videoHeight || 360;

      // Capture frames at evenly-spaced time points
      const timePoints = [];
      for (let i = 1; i <= frameCount; i++) {
        timePoints.push((duration / (frameCount + 1)) * i);
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
          console.log(`[PDD][Vision] Captured video frame at ${time.toFixed(1)}s`);
        }
      }

      // Close video preview if in modal
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      await new Promise(r => setTimeout(r, 300));
    } catch (err) {
      console.warn(`[PDD][Vision] Error extracting video frames:`, err.message);
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
    // Set a total timeout for media extraction
    const result = await Promise.race([
      (async () => {
        // Get high-res images by clicking preview
        try {
          content.images = await getHighResImages();
        } catch (err) {
          console.warn('[PDD][Vision] High-res image extraction failed, using thumbnails:', err.message);
          content.images = extractChatImages();
        }

        // Extract video frames
        try {
          content.videoFrames = await extractVideoFrames(3);
        } catch (err) {
          console.warn('[PDD][Vision] Video frame extraction failed:', err.message);
        }

        return content;
      })(),
      new Promise(resolve => setTimeout(() => {
        console.warn('[PDD][Vision] Media extraction timeout (15s)');
        resolve(content);
      }, 15000))
    ]);

    return result;
  } catch (err) {
    console.error('[PDD][Vision] Fatal error in media extraction:', err.message);
    // Fallback to basic thumbnail extraction
    content.images = extractChatImages();
    return content;
  }
}

// Listen for order info extraction request from main process
ipcRenderer.on('platform:get-order-info', async (event, payload) => {
  const requestId = payload?.requestId || '';
  console.log('[PDD][OrderDetect] Received extraction request, requestId:', requestId);
  try {
    const orderInfo = await extractOrderInfo();
    console.log('[PDD][OrderDetect] Extracted:', JSON.stringify(orderInfo).substring(0, 200));
    ipcRenderer.send('platform:order-info-result', { requestId, data: orderInfo });
  } catch (e) {
    console.error('[PDD][OrderDetect] Extraction failed:', e);
    ipcRenderer.send('platform:order-info-result', { requestId, data: null });
  }
});

// Listen for pending message check from main process (for shop rotation)
ipcRenderer.on('platform:check-pending', (event, payload) => {
  const requestId = payload?.requestId || '';
  try {
    const pendingConvs = findUnreadConversations();
    const hasPending = pendingConvs.length > 0;
    console.log(`[PDD] Pending check: ${hasPending ? pendingConvs.length + ' pending' : 'no pending messages'}`);
    
    // Diagnostic: dump sidebar DOM structure to help debug selector issues
    const diagnostic = diagnoseSidebarDOM();
    
    ipcRenderer.send('platform:pending-result', { 
      requestId, 
      hasPending,
      countdownCount: pendingConvs.filter(el => {
        const countdown = el.querySelector('[class*="countdown"], [class*="timer"]');
        return countdown && /\d+.*秒/.test(countdown.textContent);
      }).length,
      timeoutCount: pendingConvs.filter(el => {
        const timeout = el.querySelector('[class*="timeout"], [class*="overtime"]');
        return timeout && timeout.textContent.includes('超时');
      }).length,
      diagnostic: diagnostic
    });
  } catch (e) {
    console.error('[PDD] Pending check failed:', e);
    ipcRenderer.send('platform:pending-result', { requestId, hasPending: false, error: e.message });
  }
});

/**
 * Diagnostic: dump sidebar DOM structure to identify correct selectors
 * Only runs detailed dump a few times to avoid log spam
 */
let diagnosticRunCount = 0;
function diagnoseSidebarDOM() {
  diagnosticRunCount++;
  // Only do detailed dump for first 5 checks
  if (diagnosticRunCount > 5) return null;
  
  const result = {
    listContainerFound: false,
    listContainerSelector: null,
    listContainerClass: null,
    itemCount: 0,
    itemSampleClasses: [],
    textContainingTimeout: [],
    textContainingCountdown: [],
    allRedElements: [],
    sidebarChildTags: []
  };
  
  try {
    // Step 1: Find the sidebar/left panel area
    const sidebarSelectors = [
      '[class*="session-list"]', '[class*="conversation-list"]', '[class*="chat-list"]',
      '[class*="im-list"]', '[class*="contact-list"]', '[class*="SessionList"]',
      '[class*="ConversationList"]', '[class*="sidebar"]', '[class*="left-panel"]',
      '[class*="leftPanel"]', '[class*="aside"]', '[class*="session"]',
      '[class*="sideBar"]', '[class*="side-bar"]'
    ];
    
    let sidebar = null;
    for (const sel of sidebarSelectors) {
      const el = document.querySelector(sel);
      if (el && el.children.length > 0) {
        sidebar = el;
        result.listContainerFound = true;
        result.listContainerSelector = sel;
        result.listContainerClass = el.className?.substring?.(0, 150) || '';
        break;
      }
    }
    
    // Step 2: If no sidebar found by class, try to find by structure
    // Look for a scrollable container with many similar child elements (likely conversation list)
    if (!sidebar) {
      const allDivs = document.querySelectorAll('div');
      for (const div of allDivs) {
        if (div.children.length >= 3 && div.children.length <= 200) {
          // Check if children have similar structure (typical for lists)
          const firstChild = div.children[0];
          const secondChild = div.children[1];
          if (firstChild && secondChild && 
              firstChild.tagName === secondChild.tagName &&
              firstChild.className === secondChild.className &&
              firstChild.children.length > 0) {
            // Check if these look like conversation items (have text and maybe images)
            const hasAvatar = firstChild.querySelector('img') !== null;
            const hasText = firstChild.textContent.length > 10;
            if (hasAvatar || hasText) {
              // Check scroll - conversation lists are usually scrollable
              const style = window.getComputedStyle(div);
              const parentStyle = div.parentElement ? window.getComputedStyle(div.parentElement) : null;
              if (style.overflow === 'auto' || style.overflow === 'scroll' || 
                  style.overflowY === 'auto' || style.overflowY === 'scroll' ||
                  (parentStyle && (parentStyle.overflow === 'auto' || parentStyle.overflowY === 'auto'))) {
                sidebar = div;
                result.listContainerFound = true;
                result.listContainerSelector = 'structural-match';
                result.listContainerClass = div.className?.substring?.(0, 150) || '';
                break;
              }
            }
          }
        }
      }
    }
    
    // Step 3: Examine sidebar items
    if (sidebar) {
      const children = Array.from(sidebar.children).filter(c => c.nodeType === 1);
      result.itemCount = children.length;
      result.sidebarChildTags = children.slice(0, 3).map(c => ({
        tag: c.tagName,
        className: c.className?.substring?.(0, 100) || '',
        textPreview: c.textContent?.substring?.(0, 60)?.replace(/\s+/g, ' ')?.trim() || '',
        childCount: c.children.length
      }));
      
      // Sample first 3 item classes
      result.itemSampleClasses = children.slice(0, 3).map(c => c.className?.substring?.(0, 100) || '');
    }
    
    // Step 4: Search ENTIRE page for text containing "超时" or countdown patterns
    const allElements = document.querySelectorAll('*');
    for (const el of allElements) {
      if (el.childNodes.length === 1 && el.childNodes[0].nodeType === 3) {
        const text = el.textContent.trim();
        if (text.includes('超时') || text.includes('逾期')) {
          result.textContainingTimeout.push({
            tag: el.tagName,
            className: el.className?.substring?.(0, 80) || '',
            text: text.substring(0, 50),
            parentClass: el.parentElement?.className?.substring?.(0, 80) || ''
          });
          if (result.textContainingTimeout.length >= 5) break;
        }
        if (/\d+秒|\d+分\d+秒/.test(text) && text.length < 20) {
          result.textContainingCountdown.push({
            tag: el.tagName,
            className: el.className?.substring?.(0, 80) || '',
            text: text.substring(0, 30),
            parentClass: el.parentElement?.className?.substring?.(0, 80) || ''
          });
          if (result.textContainingCountdown.length >= 5) break;
        }
      }
    }
    
  } catch (e) {
    result.error = e.message;
  }
  
  return result;
}

// Listen for reply commands from main process
ipcRenderer.on('platform:send-reply', async (event, data) => {
  console.log('[PDD] Sending reply:', data.reply?.substring(0, 50));
  
  // Record this message as sent by us (to avoid processing it as customer message)
  const replyHash = hashMessage(data.reply);
  state.sentMessages.add(replyHash);
  console.log('[PDD] Added to sentMessages, hash:', replyHash);
  
  // Keep sent messages set small
  if (state.sentMessages.size > 100) {
    const arr = Array.from(state.sentMessages);
    state.sentMessages = new Set(arr.slice(-50));
  }
  
  const success = await sendMessage(data.reply);
  
  if (success) {
    // Mark this conversation as replied
    const customerId = data.customerId || `pdd_${getCurrentCustomerName()}`;
    state.repliedConversations.set(customerId, Date.now());
    console.log(`[PDD] Marked ${customerId} as replied`);
    
    // Reset consecutive no-message counter on successful reply
    state.consecutiveNoMessage = 0;
    
    // Wait 2 seconds, then check if there are more unread conversations before switching
    setTimeout(() => {
      const unreadConvs = findUnreadConversations();
      if (unreadConvs.length > 0) {
        // Limit consecutive Shift+Tab to prevent infinite loop
        const now = Date.now();
        const timeSinceLastShiftTab = now - (state.lastShiftTabTime || 0);
        
        // If we've been rapidly switching (more than 10 times in 30 seconds), pause
        if (state.consecutiveShiftTab >= 10 && timeSinceLastShiftTab < 30000) {
          console.log('[PDD] Too many rapid Shift+Tab switches, pausing for 30s to prevent loop');
          state.consecutiveShiftTab = 0;
          return;
        }
        
        console.log(`[PDD] Found ${unreadConvs.length} more unread conversations, pressing Shift+Tab...`);
        state.lastShiftTabTime = now;
        state.consecutiveShiftTab = (state.consecutiveShiftTab || 0) + 1;
        ipcRenderer.send('platform:send-shift-tab', PLATFORM_ID);
      } else {
        console.log('[PDD] No more unread conversations, staying in current chat');
        state.consecutiveNoUnread++;
        state.consecutiveShiftTab = 0;  // Reset on no unread
      }
    }, 2000);
  }
});

// Initialize when page is ready
/**
 * Auto-close promotional popups/dialogs
 */
function autoClosePopups() {
  // Common popup close button selectors
  const closeSelectors = [
    // Generic close buttons
    '[class*="modal"] [class*="close"]',
    '[class*="dialog"] [class*="close"]',
    '[class*="popup"] [class*="close"]',
    '[class*="toast"] [class*="close"]',
    '[class*="notice"] [class*="close"]',
    '[class*="modal"] .close',
    '[class*="dialog"] .close',
    // X buttons (often use × character or icon)
    '[class*="modal"] button:has(svg)',
    '[class*="dialog"] button:has(svg)',
    // Pinduoduo specific patterns
    '[class*="Modal"] [class*="Close"]',
    '[class*="Popup"] [class*="Close"]',
    '[class*="layer"] [class*="close"]',
    '[class*="mask"] [class*="close"]',
    // Icon-based close buttons
    '[class*="icon-close"]',
    '[class*="icon_close"]',
    '[class*="iconClose"]'
  ];

  for (const selector of closeSelectors) {
    try {
      const closeBtn = document.querySelector(selector);
      if (closeBtn && closeBtn.offsetParent !== null) {
        console.log('[PDD] Found popup close button, clicking:', selector);
        closeBtn.click();
        return true;
      }
    } catch (e) {}
  }

  // Also try to find and click "我知道了" or "关闭" buttons
  const dismissTexts = ['我知道了', '关闭', '不再提示', '取消', '暂不', '以后再说'];
  const allButtons = document.querySelectorAll('button, [role="button"], [class*="btn"], a[class*="btn"]');
  for (const btn of allButtons) {
    const text = btn.textContent.trim();
    if (dismissTexts.some(t => text === t)) {
      // Make sure it's visible and in a modal/popup
      const parent = btn.closest('[class*="modal"], [class*="dialog"], [class*="popup"], [class*="layer"], [class*="mask"]');
      if (parent && btn.offsetParent !== null) {
        console.log('[PDD] Found dismiss button:', text);
        btn.click();
        return true;
      }
    }
  }

  // Try to find close button by position (top-right corner of modal)
  const modals = document.querySelectorAll('[class*="modal"], [class*="dialog"], [class*="popup"], [class*="layer"]');
  for (const modal of modals) {
    if (modal.offsetParent === null) continue;
    const rect = modal.getBoundingClientRect();
    // Look for clickable element in top-right area
    const buttons = modal.querySelectorAll('button, span, div, i, svg');
    for (const btn of buttons) {
      const btnRect = btn.getBoundingClientRect();
      // Check if in top-right corner (within 60px of top and right edges)
      if (btnRect.top < rect.top + 60 && btnRect.right > rect.right - 60) {
        if (btn.offsetParent !== null && (btn.textContent.includes('×') || btn.textContent.includes('X') || btn.innerHTML.includes('svg') || btn.className.toLowerCase().includes('close'))) {
          console.log('[PDD] Found corner close button');
          btn.click();
          return true;
        }
      }
    }
  }

  return false;
}

/**
 * Auto-login with provided credentials
 * Uses human-like typing simulation to avoid anti-bot detection
 */
function performAutoLogin(username, password) {
  console.log('[PDD] Attempting auto-login with username:', username);
  
  // Check if we're on the login page
  const currentUrl = window.location.href;
  console.log('[PDD] Current URL:', currentUrl);
  
  if (!currentUrl.includes('pinduoduo.com')) {
    console.log('[PDD] Not on pinduoduo page, skipping auto-login');
    return;
  }

  const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
  
  // Random delay between characters (50-150ms) to simulate human typing
  const randomDelay = () => Math.floor(Math.random() * 100) + 50;
  
  /**
   * Simulate human typing - type each character one by one
   */
  const simulateHumanTyping = async (input, text) => {
    // Focus on the input first
    input.focus();
    input.click();
    await sleep(100);
    
    // Clear any existing value
    input.value = '';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    await sleep(50);
    
    // Type each character one by one
    for (let i = 0; i < text.length; i++) {
      const char = text[i];
      
      // Simulate keydown event
      input.dispatchEvent(new KeyboardEvent('keydown', {
        key: char,
        code: `Key${char.toUpperCase()}`,
        bubbles: true,
        cancelable: true
      }));
      
      // Append the character to value
      input.value += char;
      
      // Simulate input event (for React state updates)
      input.dispatchEvent(new Event('input', { bubbles: true }));
      
      // Simulate keyup event
      input.dispatchEvent(new KeyboardEvent('keyup', {
        key: char,
        code: `Key${char.toUpperCase()}`,
        bubbles: true,
        cancelable: true
      }));
      
      // Random delay between characters
      await sleep(randomDelay());
    }
    
    // Final change event
    input.dispatchEvent(new Event('change', { bubbles: true }));
    input.dispatchEvent(new Event('blur', { bubbles: true }));
  };

  // Step 1: Click "账号登录" tab to switch from QR code login
  const switchToAccountLogin = () => {
    console.log('[PDD] Looking for account login tab...');
    
    // Try multiple selectors
    const selectors = [
      'div[class*="tab"]',
      'span[class*="tab"]',
      'a[class*="tab"]',
      'button',
      '[role="tab"]'
    ];
    
    for (const selector of selectors) {
      const elements = document.querySelectorAll(selector);
      for (const el of elements) {
        const text = el.textContent.trim();
        if (text === '账号登录' || text === '密码登录') {
          console.log('[PDD] Found account login tab:', text, el);
          el.click();
          return true;
        }
      }
    }
    
    // Fallback: search all elements
    const allElements = document.querySelectorAll('*');
    for (const el of allElements) {
      if (el.childNodes.length === 1 && el.childNodes[0].nodeType === 3) {
        const text = el.textContent.trim();
        if (text === '账号登录' || text === '密码登录') {
          console.log('[PDD] Found account login tab (fallback):', text, el);
          el.click();
          return true;
        }
      }
    }
    
    console.log('[PDD] Account login tab not found');
    return false;
  };

  // Step 2: Fill in username and password with human-like typing
  const fillCredentials = async () => {
    console.log('[PDD] Looking for login inputs...');
    
    // Find all inputs
    const allInputs = document.querySelectorAll('input');
    console.log('[PDD] Found', allInputs.length, 'inputs');
    
    let usernameInput = null;
    let passwordInput = null;
    
    for (const input of allInputs) {
      const type = input.type.toLowerCase();
      const placeholder = (input.placeholder || '').toLowerCase();
      
      console.log('[PDD] Input:', type, placeholder, input);
      
      if (type === 'password') {
        passwordInput = input;
      } else if (type === 'text' || type === 'tel' || type === 'number') {
        if (!usernameInput) {
          usernameInput = input;
        }
      }
    }
    
    if (usernameInput && passwordInput) {
      console.log('[PDD] Found both inputs, filling credentials with human-like typing...');
      
      // Type username character by character
      console.log('[PDD] Typing username...');
      await simulateHumanTyping(usernameInput, username);
      
      // Wait a moment like a human would
      await sleep(300 + Math.random() * 200);
      
      // Click on password field (simulate human clicking)
      console.log('[PDD] Clicking password field...');
      passwordInput.click();
      passwordInput.focus();
      await sleep(200 + Math.random() * 100);
      
      // Type password character by character
      console.log('[PDD] Typing password...');
      await simulateHumanTyping(passwordInput, password);
      
      console.log('[PDD] Credentials filled with human-like typing');
      return true;
    }
    
    console.log('[PDD] Inputs not found - username:', !!usernameInput, 'password:', !!passwordInput);
    return false;
  };

  // Step 3: Click the login button
  const clickLoginButton = () => {
    console.log('[PDD] Looking for login button...');
    
    const buttons = document.querySelectorAll('button, [role="button"], div[class*="btn"], span[class*="btn"]');
    console.log('[PDD] Found', buttons.length, 'buttons');
    
    for (const btn of buttons) {
      const text = btn.textContent.trim();
      if (text === '登录' || text === '登 录') {
        console.log('[PDD] Found login button:', text, btn);
        btn.click();
        return true;
      }
    }
    
    // Fallback
    for (const btn of buttons) {
      if (btn.textContent.includes('登录') && !btn.textContent.includes('扫码')) {
        console.log('[PDD] Found login button (fallback):', btn.textContent.trim(), btn);
        btn.click();
        return true;
      }
    }
    
    console.log('[PDD] Login button not found');
    return false;
  };

  // Execute login sequence with retries
  const executeLogin = async () => {
    console.log('[PDD] Starting login sequence...');
    
    // Wait for page to fully load
    await sleep(1000);
    
    // Try to switch to account login
    let switched = switchToAccountLogin();
    if (!switched) {
      await sleep(1000);
      switched = switchToAccountLogin();
    }
    
    // Wait for tab switch
    await sleep(2000);
    
    // Fill credentials (async with human-like typing)
    let filled = await fillCredentials();
    if (!filled) {
      await sleep(1500);
      filled = await fillCredentials();
    }
    
    if (filled) {
      // Wait a bit then click login
      await sleep(500 + Math.random() * 500);
      clickLoginButton();
    }
  };
  
  // Start the login process
  executeLogin();
}

// Listen for auto-login command from main process
ipcRenderer.on('shop:auto-login', (event, data) => {
  console.log('[PDD] Received auto-login command');
  if (data.username && data.password) {
    // Wait for page to fully load
    if (document.readyState === 'complete') {
      performAutoLogin(data.username, data.password);
    } else {
      window.addEventListener('load', () => {
        performAutoLogin(data.username, data.password);
      });
    }
  }
});

/**
 * Check if we're on login page and request auto-login credentials
 */
async function checkAndRequestAutoLogin() {
  const currentUrl = window.location.href;
  
  // Check if we're on login page
  if (!currentUrl.includes('login') && !currentUrl.includes('mms.pinduoduo.com/login')) {
    return;
  }
  
  console.log('[PDD] Detected login page, requesting auto-login credentials...');
  
  // Wait a bit for page to stabilize
  await new Promise(resolve => setTimeout(resolve, 2000));
  
  try {
    // Request credentials from main process
    const result = await ipcRenderer.invoke('shop:request-auto-login', PLATFORM_ID);
    
    if (result && result.success && result.username && result.password) {
      console.log('[PDD] Auto-login credentials received, attempting login...');
      performAutoLogin(result.username, result.password);
    } else {
      console.log('[PDD] No auto-login credentials available');
    }
  } catch (error) {
    console.error('[PDD] Error requesting auto-login:', error.message);
  }
}

function init() {
  console.log('[PDD] Preload script loaded, waiting for page...');
  
  // Check if we're on login page and need auto-login
  checkAndRequestAutoLogin();
  
  // Start popup auto-close checker
  setInterval(() => {
    autoClosePopups();
  }, 3000);
  
  // Start offline detection and auto-refresh (check more frequently)
  setInterval(() => {
    checkOfflineAndRefresh();
  }, 5000);
  
  // Wait for the chat page to fully render
  const checkReady = setInterval(() => {
    const hasChat = findElement([
      '[class*="chat"]',
      '[class*="session"]',
      '[class*="conversation"]',
      '[class*="im-"]',
      'textarea'
    ]);
    if (hasChat) {
      clearInterval(checkReady);
      console.log('[PDD] Chat page detected, starting monitoring');
      // Notify main process that login is successful
      ipcRenderer.send('platform:login-success', { platformId: PLATFORM_ID });
      startMonitoring();
    }
  }, 2000);

  // Force start after 15 seconds even if not detected
  setTimeout(() => {
    clearInterval(checkReady);
    if (!state.observerActive) {
      console.log('[PDD] Timeout - force starting monitoring');
      startMonitoring();
    }
  }, 15000);
}

/**
 * Check if page shows offline/disconnected status and auto-refresh
 */
function checkOfflineAndRefresh() {
  // Check for common offline/error messages
  const offlineIndicators = [
    '账户在别处登录',
    '网络出现问题',
    '请检查后刷新',
    '连接已断开',
    '登录已过期',
    '会话已过期',
    '请重新登录',
    '网络异常',
    '服务暂时不可用',
    '页面加载失败',
    '系统繁忙',
    '登录失效'
  ];
  
  // Check entire page text (including overlays/modals)
  const pageText = document.body ? document.body.innerText : '';
  
  // Also check all visible text in dialogs/modals
  const dialogTexts = [];
  const dialogs = document.querySelectorAll(
    '[class*="dialog"], [class*="modal"], [class*="overlay"], [class*="mask"], [class*="popup"], [class*="toast"], [class*="alert"], [role="dialog"], [role="alertdialog"]'
  );
  for (const d of dialogs) {
    if (d.offsetParent !== null || d.style.display !== 'none') {
      dialogTexts.push(d.innerText || '');
    }
  }
  
  const allText = pageText + ' ' + dialogTexts.join(' ');
  
  for (const indicator of offlineIndicators) {
    if (allText.includes(indicator)) {
      console.log('[PDD] Offline/error detected:', indicator);
      
      // Try to click refresh button first
      const refreshBtn = findRefreshButton();
      if (refreshBtn) {
        console.log('[PDD] Found refresh button, clicking...');
        refreshBtn.click();
        return;
      }
      
      // Fallback: reload entire page
      console.log('[PDD] No refresh button found, reloading page in 2s...');
      setTimeout(() => {
        window.location.reload();
      }, 2000);
      return;
    }
  }
}

/**
 * Find refresh/retry button on the page
 */
function findRefreshButton() {
  // Search in modals/overlays first (higher priority)
  const containers = [
    ...document.querySelectorAll('[class*="dialog"], [class*="modal"], [class*="overlay"], [class*="popup"], [role="dialog"]'),
    document.body
  ];
  
  const buttonTexts = ['刷新', '重试', '重新加载', '重新连接', '重新登录', '确定'];
  
  for (const container of containers) {
    if (!container) continue;
    
    // Check all clickable elements
    const clickables = container.querySelectorAll('button, [role="button"], a, div[class*="btn"], span[class*="btn"], [class*="button"]');
    
    for (const el of clickables) {
      const text = el.textContent.trim();
      if (buttonTexts.includes(text)) {
        // Make sure it's visible
        if (el.offsetParent !== null || el.offsetWidth > 0) {
          return el;
        }
      }
    }
  }
  
  return null;
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
