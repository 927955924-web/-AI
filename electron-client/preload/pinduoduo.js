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
  shopId: null,                  // Shop ID for this BrowserView (set by main process)
  processedMessages: new Set(),  // Track processed message hashes
  repliedConversations: new Map(), // Track replied conversations: customerId -> lastReplyTime
  lastCustomerMessages: new Map(), // Track last message per customer: customerId -> messageHash
  sentMessages: new Set(),       // Track messages we sent (to avoid processing our own replies)
  isProcessing: false,           // Prevent concurrent processing
  isReplying: false,             // Prevent concurrent replies from processCurrentConversation
  replyingStartTime: 0,         // Timestamp when isReplying was set to true (safety timeout)
  observerActive: false,
  scanInterval: null,
  processTimer: null,
  lastScanTime: 0,
  replyTimeout: 60000,  // Don't reply again to same customer within 60 seconds unless they send new message
  lastShiftTabTime: 0,  // Track last Shift+Tab press time
  shiftTabCooldown: 5000,  // Cooldown between Shift+Tab presses (5 seconds, optimized from 10s)
  consecutiveNoUnread: 0,  // Track consecutive times no unread found after Shift+Tab
  consecutiveShiftTab: 0,  // Track consecutive Shift+Tab presses to prevent infinite loop
  consecutiveNoMessage: 0,  // Track conversations with no real buyer message
  visitedTimeoutConvs: new Set(),  // Track timeout conversations we've already checked (no real msg)
  // Human action detection - pause auto-reply when human is operating
  lastHumanActionTime: 0,        // Timestamp of last human action (keyboard/mouse)
  humanActionGracePeriod: 3000,  // Wait 3 seconds after human action before resuming auto-reply (optimized from 5s)
  humanActionListenersActive: false,  // Track if human action listeners are set up
  // Message preview tracking - detect new messages by preview text change
  conversationPreviews: new Map(),  // Track last message preview for each conversation: convId -> previewText
  lastFullScanTime: 0,  // Track last time we did a full conversation scan
  fullScanInterval: 10000,  // Do a full scan every 10 seconds to catch missed messages
};

// Listen for shop context from main process (so we know which shop this BrowserView belongs to)
ipcRenderer.on('shop:set-context', (event, data) => {
  state.shopId = data.shopId;
  if (data.contextMessages) {
    state.contextMessages = data.contextMessages;
  }
  logToMain(`Shop context set: shopId=${data.shopId}, contextMessages=${state.contextMessages || 10}`);
});

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

/**
 * Record human action timestamp - called when keyboard/mouse events detected
 */
function recordHumanAction(eventType) {
  state.lastHumanActionTime = Date.now();
  console.log(`[PDD][HumanAction] Detected human action: ${eventType}, pausing auto-reply for ${state.humanActionGracePeriod/1000}s`);
}

/**
 * Check if auto-reply should be paused due to recent human action
 * Returns true if human was active within grace period (should pause)
 */
function shouldPauseForHumanAction() {
  if (state.lastHumanActionTime === 0) return false;
  
  const timeSinceHumanAction = Date.now() - state.lastHumanActionTime;
  if (timeSinceHumanAction < state.humanActionGracePeriod) {
    const remainingWait = Math.ceil((state.humanActionGracePeriod - timeSinceHumanAction) / 1000);
    console.log(`[PDD][HumanAction] Human action detected ${Math.round(timeSinceHumanAction/1000)}s ago, waiting ${remainingWait}s more before auto-reply`);
    return true;
  }
  return false;
}

/**
 * Set up event listeners to detect human actions (keyboard/mouse)
 * Only captures events in the chat input area to avoid false positives
 */
function setupHumanActionListeners() {
  if (state.humanActionListenersActive) return;
  state.humanActionListenersActive = true;
  
  console.log('[PDD][HumanAction] Setting up human action detection listeners...');
  
  // Keyboard events - detect typing in input area
  document.addEventListener('keydown', (e) => {
    // Only record if the target is an input/textarea (user typing)
    const target = e.target;
    const tagName = target.tagName.toLowerCase();
    const isEditable = target.getAttribute('contenteditable') === 'true';
    
    if (tagName === 'input' || tagName === 'textarea' || isEditable) {
      // Ignore system keys (Shift+Tab is used for auto-switching)
      if (e.key === 'Tab' && e.shiftKey) return;
      if (e.key === 'Enter' && !e.shiftKey) return; // Enter alone might be auto-send
      
      recordHumanAction('keyboard:' + e.key);
    }
  }, true);
  
  // Mouse click events in chat area - detect manual conversation switching or clicking
  document.addEventListener('click', (e) => {
    const target = e.target;
    
    // Check if click is on conversation list items (manual switching)
    const chatListItem = target.closest('.chat-list, [class*="session-item"], [class*="conversation-item"], [class*="chat-item"]');
    if (chatListItem) {
      recordHumanAction('click:conversation-switch');
      return;
    }
    
    // Check if click is on input area (focusing to type)
    const inputArea = target.closest('textarea, input, [contenteditable="true"]');
    if (inputArea) {
      recordHumanAction('click:input-focus');
      return;
    }
    
    // Check if click is on send button (manual send)
    const sendBtn = target.closest('[class*="send-btn"], [class*="sendBtn"], button');
    if (sendBtn) {
      const text = sendBtn.textContent || '';
      if (text.includes('发送') || text === 'Send') {
        recordHumanAction('click:send-button');
        return;
      }
    }
  }, true);
  
  // Input events - detect direct text input (catches paste, voice input, etc.)
  document.addEventListener('input', (e) => {
    const target = e.target;
    const tagName = target.tagName.toLowerCase();
    const isEditable = target.getAttribute('contenteditable') === 'true';
    
    if (tagName === 'input' || tagName === 'textarea' || isEditable) {
      // Check if this input is from our auto-reply (sentMessages tracking)
      // We mark our sent messages, so if this appears to be a new manual input, record it
      const inputValue = target.value || target.innerText || '';
      if (inputValue.length > 0) {
        // Only record if it looks like manual input (not automated)
        // Our sendMessage function uses direct value setting, which may not trigger this
        recordHumanAction('input:text-change');
      }
    }
  }, true);
  
  console.log('[PDD][HumanAction] Human action listeners active');
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
  const unreadBadgeItems = []; // Items with unread badge (red dot)
  const previewChangedItems = []; // Items with message preview changed (new message detection)

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

    if (!foundTimeout) {
      const unreplyEl = item.querySelector('[class*="unreply"], [class*="unreplied"], [class*="unanswered"], [class*="no-reply"]');
      const unreplyText = (unreplyEl ? unreplyEl.textContent : '') || '';
      if (unreplyText.includes('未回复') || unreplyText.includes('待回复') || unreplyText.includes('未回')) {
        timeoutItems.push(item);
        foundTimeout = true;
      }
    }

    if (!foundTimeout) {
      if (itemText.includes('未回复') || itemText.includes('待回复') || itemText.includes('未回')) {
        timeoutItems.push(item);
        foundTimeout = true;
      }
    }
    
    // --- Check for unread badge (red dot) - NEW DETECTION STRATEGY ---
    if (!foundCountdown && !foundTimeout) {
      const badgeSelectors = [
        '[class*="badge"]', '[class*="unread"]', '[class*="dot"]', 
        '[class*="red-point"]', '[class*="new-msg"]', '[class*="count"]',
        '[class*="num"]', '[class*="tip"]'
      ];
      for (const sel of badgeSelectors) {
        const badge = item.querySelector(sel);
        if (badge) {
          const badgeText = badge.textContent.trim();
          const badgeStyle = window.getComputedStyle(badge);
          const bgColor = badgeStyle.backgroundColor;
          // Check if it's a red/orange badge (typical unread indicator)
          const isRedBadge = bgColor.includes('rgb(255') || bgColor.includes('rgb(238') || 
                             bgColor.includes('rgba(255') || badgeStyle.color === 'red';
          // Check if badge has number content (unread count)
          const hasNumber = /^\d+$/.test(badgeText) && parseInt(badgeText) > 0;
          
          if (isRedBadge || hasNumber) {
            unreadBadgeItems.push(item);
            break;
          }
        }
      }
    }
    
    // --- NEW: Check for message preview change (detect new messages without indicators) ---
    if (!foundCountdown && !foundTimeout) {
      // Extract conversation ID (customer name or unique identifier)
      const nameEl = item.querySelector('[class*="name"], [class*="nick"], [class*="title"]');
      const dataId =
        item?.dataset?.sessionId ||
        item?.dataset?.visitorId ||
        item?.dataset?.id ||
        item?.dataset?.uid ||
        item?.getAttribute?.('data-session-id') ||
        item?.getAttribute?.('data-visitor-id') ||
        item?.getAttribute?.('data-id') ||
        item?.getAttribute?.('data-uid');
      const convId = dataId ? `sid_${String(dataId).trim()}` : (nameEl ? nameEl.textContent.trim() : itemText.substring(0, 30));
      
      // Extract last message preview text
      const previewEl = item.querySelector('[class*="msg"], [class*="preview"], [class*="last-msg"], [class*="content"]');
      const previewText = previewEl ? previewEl.textContent.trim() : '';
      
      if (convId && previewText.length > 0) {
        const prevPreview = state.conversationPreviews.get(convId);
        
        // If preview changed and it's not our own message (check for common sent patterns)
        if (prevPreview && prevPreview !== previewText) {
          // Check if this looks like a buyer message (not starting with common merchant patterns)
          const isMerchantMsg = previewText.startsWith('亲，') || previewText.startsWith('您好') || 
                                previewText.includes('[客服]') || previewText.includes('已发送');
          
          if (!isMerchantMsg) {
            console.log(`[PDD] Preview changed for "${convId}": "${prevPreview.substring(0, 20)}" -> "${previewText.substring(0, 20)}"`);
            previewChangedItems.push(item);
          }
        }
        
        // Update stored preview
        state.conversationPreviews.set(convId, previewText);
      }
    }
  });

  // Return countdown items first (priority), then timeout, then unread badge, then preview-changed items
  console.log(`[PDD] Found ${countdownItems.length} countdown, ${timeoutItems.length} timeout, ${unreadBadgeItems.length} unread-badge, ${previewChangedItems.length} preview-changed conversations`);
  const merged = [...countdownItems, ...timeoutItems, ...unreadBadgeItems, ...previewChangedItems];
  return Array.from(new Set(merged));
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

    // Skip truly empty elements (no text AND no media)
    if (text.length < 2) {
      const hasMedia = item.querySelector('img[src*="http"], video, [class*="image"], [class*="video"], [class*="img"]');
      if (!hasMedia) continue;
    }

    // Check if it's a customer message (not from merchant/self)
    const isCustomer = isCustomerMessage(item);
    if (isCustomer) {
      // Extract just the message text (exclude timestamps, names, etc.)
      const msgText = extractMessageText(item);
      
      // For image-only messages, use "[图片]" as placeholder text
      const effectiveText = (msgText && msgText.length > 0) ? msgText : '[图片]';
      
      // Check if this is a message WE sent (avoid processing our own replies)
      const msgHash = hashMessage(effectiveText);
      if (state.sentMessages.has(msgHash)) {
        console.log('[PDD] Skipping our own sent message:', effectiveText.substring(0, 30));
        continue;
      }
      
      // Check if this is a PDD system/robot message (NOT a real buyer message)
      if (effectiveText !== '[图片]' && isPddSystemMessage(effectiveText)) {
        console.log('[PDD] Skipping PDD system/robot message:', effectiveText.substring(0, 50));
        continue;
      }
      
      // Check if this is just a product link/card (skip it to find real question)
      if (effectiveText !== '[图片]' && isProductLinkOnly(effectiveText)) {
        console.log('[PDD] Skipping product link, looking for real question...');
        continue;
      }
      
      return {
        text: effectiveText,
        element: item
      };
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
 * Check if message is PDD's official auto-reply from their robot
 * These are automated responses from PDD's platform robot (not human merchant)
 * When the last message is official auto-reply, the timeout status won't clear
 */
function isPddOfficialAutoReply(text) {
  if (!text) return false;
  
  // PDD official robot auto-reply patterns
  const officialAutoReplyPatterns = [
    // Common greeting auto-replies
    '亲，很高兴为您服务',
    '请问您要查询什么问题',
    '请问有什么可以帮您',
    '有什么可以帮到您',
    '您好，欢迎光临',
    // Order/shipping auto-replies
    '拼单成功后我们将会尽快发货',
    '请您耐心等待',
    '我们会尽快为您安排',
    '正在为您处理',
    // Common templated responses
    '感谢您的支持',
    '祝您购物愉快',
    '如有问题请随时联系',
    // Robot greeting patterns
    '我是智能客服',
    '我是机器人',
    '智能助手为您服务',
  ];
  
  for (const pattern of officialAutoReplyPatterns) {
    if (text.includes(pattern)) {
      return true;
    }
  }
  
  return false;
}

/**
 * Check if the last message in current chat is from PDD official auto-reply robot
 * Returns the message text if it is, null otherwise
 */
function getLastOfficialAutoReplyMessage() {
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

  if (messageItems.length === 0) return null;

  // Check the last few messages (official auto-reply might not be the very last)
  for (let i = messageItems.length - 1; i >= Math.max(0, messageItems.length - 3); i--) {
    const item = messageItems[i];
    const text = extractMessageText(item);
    
    if (!text || text.length < 2) continue;
    
    // Check if it's NOT a customer message (i.e., from merchant side)
    if (!isCustomerMessage(item)) {
      // Check if it's official auto-reply
      if (isPddOfficialAutoReply(text)) {
        console.log('[PDD] Detected official auto-reply:', text.substring(0, 50));
        return text;
      }
    }
  }

  return null;
}

/**
 * Send a handshake emoji to clear the timeout/countdown status
 * This is used when official auto-reply has responded but timeout still shows
 */
async function sendHandshakeToClearTimeout() {
  console.log('[PDD] Sending handshake emoji to clear timeout status...');
  const success = await sendMessage('🤝');
  if (success) {
    console.log('[PDD] Handshake sent successfully to clear timeout');
  } else {
    console.warn('[PDD] Failed to send handshake emoji');
  }
  return success;
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
 * Scroll chat area to load more history messages
 * Returns true if more messages were loaded
 */
async function scrollToLoadHistory() {
  const chatArea = findElement([
    '[class*="chat-content"]',
    '[class*="message-list"]',
    '[class*="msg-list"]',
    '[class*="chat-body"]',
    '[class*="im-content"]',
    '[class*="chat-record"]',
    '[class*="chat-box"]'
  ]);
  
  if (!chatArea) return false;
  
  const initialMsgCount = chatArea.children.length;
  const initialScrollTop = chatArea.scrollTop;
  
  // Scroll to top to trigger loading more messages
  chatArea.scrollTop = 0;
  
  // Wait for potential lazy-load
  await new Promise(r => setTimeout(r, 500));
  
  const newMsgCount = chatArea.children.length;
  const loadedMore = newMsgCount > initialMsgCount;
  
  // Scroll back to bottom
  chatArea.scrollTop = chatArea.scrollHeight;
  
  return loadedMore;
}

/**
 * Collect full conversation context with scroll to load history
 * This ensures we get the complete conversation, not just visible messages
 */
async function collectFullConversationContext() {
  const chatArea = findElement([
    '[class*="chat-content"]',
    '[class*="message-list"]',
    '[class*="msg-list"]',
    '[class*="chat-body"]',
    '[class*="im-content"]',
    '[class*="chat-record"]',
    '[class*="chat-box"]'
  ]);
  
  if (chatArea) {
    // Save current scroll position
    const originalScrollTop = chatArea.scrollTop;
    
    // Try to load more history by scrolling up (max 3 attempts)
    let loadAttempts = 0;
    while (loadAttempts < 3) {
      chatArea.scrollTop = 0;
      await new Promise(r => setTimeout(r, 300));
      
      // Check if we're at the very top (no more to load)
      if (chatArea.scrollTop === 0) {
        loadAttempts++;
      } else {
        break;
      }
    }
    
    // Small delay to ensure all messages are rendered
    await new Promise(r => setTimeout(r, 200));
    
    // Now collect all messages
    const context = collectConversationContext(true); // true = collect all, not just last 10
    
    // Scroll back to bottom so user sees latest messages
    chatArea.scrollTop = chatArea.scrollHeight;
    
    return context;
  }
  
  // Fallback to regular context collection
  return collectConversationContext(false);
}

/**
 * Check if a message element is a system or bot notification (not buyer/merchant content)
 */
function isSystemOrBotMessage(el) {
  const className = (el.className || '').toLowerCase();
  // System/notification class patterns
  if (className.includes('system') || className.includes('notice') ||
      className.includes('notification') || className.includes('tip') ||
      className.includes('time-line') || className.includes('timeline') ||
      className.includes('divider') || className.includes('separator')) {
    return true;
  }
  const text = (el.textContent || '').trim();
  // Typical system/bot notification patterns
  const systemPatterns = [
    /^以上是历史消息/,
    /^系统消息/,
    /^温馨提示/,
    /^自动回复/,
    /^当前会话已/,
    /^该买家.*?进入/,
    /^买家.*?已离开/,
    /^会话已结束/,
    /^您的服务评分/,
    /^该订单已/,
    /^平台提醒/,
    /^请注意.*?服务规范/,
    /^\d{4}[-\/]\d{1,2}[-\/]\d{1,2}\s+\d{1,2}:\d{2}(:\d{2})?$/  // timestamp-only lines
  ];
  for (const pattern of systemPatterns) {
    if (pattern.test(text)) return true;
  }
  // Very short text that's just a timestamp or divider
  if (text.length > 0 && text.length <= 5 && /^[\d:\/\-\s]+$/.test(text)) return true;
  return false;
}

/**
 * Collect full conversation context (recent messages)
 * @param {boolean} collectAll - If true, collect all visible messages; if false, only last 10
 */
function collectConversationContext(collectAll = false) {
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

  // Collect messages as context
  // If collectAll is true, collect a larger rolling window for better intent continuity
  // Otherwise, use the configured context message count (default 10)
  const configuredCount = state.contextMessages || 10;
  const maxMessages = collectAll ? Math.min(Math.max(configuredCount * 5, 40), 120) : configuredCount;
  const contextLines = [];
  const recentItems = messageItems.slice(-maxMessages);
  
  for (const item of recentItems) {
    // Skip system/bot notifications (timestamps, auto-replies, platform tips, etc.)
    if (isSystemOrBotMessage(item)) continue;
    
    const msgText = extractMessageText(item);
    if (!msgText || msgText.length < 2) continue;
    
    const role = isCustomerMessage(item) ? '买家' : '客服';
    contextLines.push(`${role}: ${msgText}`);
  }
  
  if (collectAll) {
    console.log(`[PDD] Collected ${contextLines.length} messages for full context`);
  }

  return contextLines.join('\n');
}

/**
 * Determine if a message element is from the customer (buyer)
 */
function isCustomerMessage(el) {
  const className = (el.className || '').toLowerCase();
  const classNameOrig = el.className || '';

  // Check for merchant/self indicators using LABEL elements only (not full message text)
  // PDD shows "主账号" as a label/tag next to merchant messages, not inside the message bubble
  const labelEls = el.querySelectorAll('[class*="name"], [class*="label"], [class*="tag"], [class*="nick"], [class*="title"], [class*="Name"], [class*="Label"]');
  for (const label of labelEls) {
    const labelText = (label.textContent || '').trim();
    // Only check short label elements (real labels are short, not message content)
    if (labelText.length <= 20) {
      if (labelText.includes('主账号') || labelText === '客服' || labelText === '商家' || 
          labelText.includes('子账号') || labelText.includes('店铺')) {
        return false;
      }
    }
  }

  // Positive indicators for customer/buyer messages (case-insensitive)
  if (className.includes('left') || className.includes('buyer') ||
      className.includes('customer') || className.includes('other') ||
      className.includes('receive') || className.includes('incoming') ||
      className.includes('peer') || className.includes('remote')) {
    return true;
  }
  
  // Check original className for camelCase patterns (PDD uses these)
  if (/Left|Buyer|Customer|Other|Receive|Incoming|Peer|Remote/i.test(classNameOrig)) {
    return true;
  }

  // Negative indicators for self/merchant messages
  if (className.includes('right') || className.includes('self') ||
      className.includes('merchant') || className.includes('mine') ||
      className.includes('send') || className.includes('outgoing') ||
      className.includes('local') || className.includes('owner')) {
    return false;
  }
  
  // Check original className for camelCase patterns
  if (/Right|Self|Merchant|Mine|Send|Outgoing|Local|Owner/i.test(classNameOrig)) {
    return false;
  }

  // Check for avatar or name indicator on the right side (merchant)
  const avatar = el.querySelector('[class*="avatar"], [class*="Avatar"]');
  if (avatar) {
    const avatarRect = avatar.getBoundingClientRect();
    const elRect = el.getBoundingClientRect();
    // If avatar is on the right side, it's merchant message
    if (avatarRect.left > elRect.left + elRect.width * 0.5) {
      return false;
    }
    // If avatar is on the left side, it's buyer message
    if (avatarRect.left < elRect.left + elRect.width * 0.3) {
      return true;
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
    const bubble = el.querySelector('[class*="bubble"], [class*="content"], [class*="text"], [class*="Bubble"], [class*="Content"]');
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

  // Default: assume it could be a buyer message to be inclusive
  return true;
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
          // Filter out system labels and merchant indicators
          if (name && !['主账号', '客服', '商家', '已超时', '收藏会话', '游客'].includes(name) && !name.includes('主账号')) {
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
        // Skip if it looks like a generic label or merchant indicator
        if (!['聊天', '会话', '客服', '商家', '主账号'].includes(name) && !name.includes('主账号')) {
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
          // Skip merchant labels and generic names
          if (name.length > 0 && !['聊天', '会话', '客服', '商家', '主账号'].includes(name) && !name.includes('主账号')) {
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
            // Skip merchant labels
            if (title && title.length > 0 && !['主账号', '客服', '商家'].includes(title) && !title.includes('主账号')) {
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

  // Set text using execCommand as PRIMARY method (best React/framework compatibility)
  // execCommand('insertText') fires native input events that React's onChange handler recognizes
  logToMain('Setting text content (execCommand primary)...');
  let textSetSuccess = false;
  
  // Method A: execCommand('insertText') - works for both textarea and contentEditable when focused
  try {
    input.focus();
    if (isContentEditable) {
      // Select all existing content first
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(input);
      selection.removeAllRanges();
      selection.addRange(range);
    } else {
      // Select all for textarea
      input.select();
    }
    const execResult = document.execCommand('insertText', false, text);
    if (execResult) {
      logToMain('execCommand insertText succeeded');
      textSetSuccess = true;
    } else {
      logToMain('execCommand insertText returned false, trying alternatives...', 'warn');
    }
  } catch (e) {
    logToMain(`execCommand failed: ${e.message}, trying alternatives...`, 'warn');
  }
  
  // Method B: Fallback to native setter + event dispatch (for older Electron or restricted environments)
  if (!textSetSuccess) {
    if (isContentEditable) {
      input.innerText = text;
      logToMain('Used innerText for contentEditable (fallback)');
    } else {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype, 'value'
      )?.set;
      if (setter) {
        setter.call(input, text);
        logToMain('Used native setter for React textarea (fallback)');
      } else {
        input.value = text;
        logToMain('Used direct value assignment (fallback)');
      }
    }
    
    // Dispatch events to notify React/framework about the value change
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    const nativeInputEvent = new InputEvent('input', { bubbles: true, data: text, inputType: 'insertText' });
    input.dispatchEvent(nativeInputEvent);
    logToMain('Dispatched input/change events (fallback)');
  }

  // Wait for the input to be processed by the framework
  await new Promise(r => setTimeout(r, 500));

  // Verify the text is in the input
  const currentValue = isContentEditable ? input.innerText : input.value;
  logToMain(`Verification - text in input: "${currentValue?.substring(0, 50)}..." (${currentValue?.length || 0} chars)`);
  
  if (!currentValue || currentValue.length < text.length * 0.8) {
    logToMain('Text not properly entered, retrying with all methods...', 'warn');
    // Last resort: try all methods
    input.focus();
    await new Promise(r => setTimeout(r, 100));
    if (isContentEditable) {
      document.execCommand('selectAll', false, null);
      document.execCommand('insertText', false, text);
    } else {
      // For textarea: try setting value via defineProperty to bypass React's tracker
      const nativeSet = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
      if (nativeSet) {
        nativeSet.call(input, text);
      } else {
        input.value = text;
      }
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }
    await new Promise(r => setTimeout(r, 300));
    
    // Final verification
    const retryValue = isContentEditable ? input.innerText : input.value;
    logToMain(`Retry verification - text in input: "${retryValue?.substring(0, 50)}..." (${retryValue?.length || 0} chars)`);
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
    // Ensure input is still focused before clicking (some UIs clear on blur)
    input.focus();
    await new Promise(r => setTimeout(r, 50));
    sendButton.click();
    await new Promise(r => setTimeout(r, 200));
  } else {
    logToMain('No send button found, will rely on Enter/Ctrl+Enter key', 'warn');
  }
  
  // Method 2: Use native Electron sendInputEvent for trusted Enter key (backup)
  // Try both Enter and Ctrl+Enter since PDD may use either to send
  logToMain('Also sending native Enter key as backup...');
  input.focus();
  ipcRenderer.send('platform:send-enter', PLATFORM_ID);
  
  // Method 3: Also try Ctrl+Enter (some PDD configurations use Ctrl+Enter to send)
  await new Promise(r => setTimeout(r, 200));
  ipcRenderer.send('platform:send-ctrl-enter', PLATFORM_ID);
  
  // Wait and verify message was sent
  await new Promise(r => setTimeout(r, 500));
  
  // Check if input was cleared (indicates message was sent)
  const afterSendValue = isContentEditable ? input.innerText : input.value;
  const wasSent = !afterSendValue || afterSendValue.length < 5;
  logToMain(`After send check - input value: "${afterSendValue?.substring(0, 30) || '(empty)'}", likely sent: ${wasSent}`);
  
  if (!wasSent) {
    logToMain('Message may not have been sent - input still contains text. Will retry once...', 'warn');
    // Retry: re-focus input and try send button + Enter again
    input.focus();
    await new Promise(r => setTimeout(r, 200));
    
    if (sendButton && sendButton.offsetParent !== null) {
      sendButton.click();
      await new Promise(r => setTimeout(r, 300));
    }
    ipcRenderer.send('platform:send-enter', PLATFORM_ID);
    await new Promise(r => setTimeout(r, 300));
    ipcRenderer.send('platform:send-ctrl-enter', PLATFORM_ID);
    await new Promise(r => setTimeout(r, 500));
    
    const retryValue = isContentEditable ? input.innerText : input.value;
    const retrySent = !retryValue || retryValue.length < 5;
    logToMain(`Retry send check - input value: "${retryValue?.substring(0, 30) || '(empty)'}", sent: ${retrySent}`);
    
    if (!retrySent) {
      logToMain('Message still not sent after retry', 'error');
      return false;
    }
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
    
    // Skip truly empty elements (no text AND no images/videos)
    if ((!text || text.length < 2)) {
      // But if it has images or videos, it's a real message - don't skip
      const hasMedia = item.querySelector('img[src*="http"], video, [class*="image"], [class*="video"], [class*="img"]');
      if (!hasMedia) continue;
    }
    
    if (text && text.length > 0 && isPddSystemMessage(text)) {
      continue;
    }

    // If last meaningful message is NOT from customer, it's from us
    return !isCustomerMessage(item);
  }

  return false;
}

/**
 * Process current active conversation - check and reply
 */
async function processCurrentConversation() {
  // Check for human action - pause auto-reply if human is operating
  if (shouldPauseForHumanAction()) {
    return false;
  }
  
  // Prevent concurrent calls - with safety timeout to prevent permanent lock
  if (state.isReplying) {
    const lockDuration = Date.now() - state.replyingStartTime;
    if (lockDuration > 30000) {
      // Lock has been held for over 30 seconds - force release (something went wrong)
      console.warn(`[PDD] isReplying lock stuck for ${Math.round(lockDuration/1000)}s, force releasing`);
      state.isReplying = false;
    } else {
      return false;
    }
  }
  
  // Skip if the last message is from us (already replied, buyer hasn't sent new message)
  if (isLastMessageFromMerchant()) {
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
  state.replyingStartTime = Date.now();

  try {
    // Mark as processed
    state.processedMessages.add(conversationKey);
    state.lastCustomerMessages.set(customerId, msgHash);

    // Trim processed set if too large
    if (state.processedMessages.size > 500) {
      const arr = Array.from(state.processedMessages);
      state.processedMessages = new Set(arr.slice(-300));
    }

    // Collect full conversation context with scroll to load history
    // This ensures AI has complete conversation context for accurate replies
    console.log(`[PDD] Loading full conversation history...`);
    const conversationContext = await collectFullConversationContext();
    
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
      orderInfo: orderInfo,  // Pre-extracted order info (orders, chatImages) for main process
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
  // Check for human action - pause auto-reply if human is operating
  if (shouldPauseForHumanAction()) {
    return;
  }
  
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
        // Check if the last message is official auto-reply (not human reply)
        // If so, the timeout status won't clear - we need to send handshake to clear it
        const officialAutoReply = getLastOfficialAutoReplyMessage();
        if (officialAutoReply) {
          console.log('[PDD] Timeout conversation has official auto-reply, sending handshake to clear status...');
          await sendHandshakeToClearTimeout();
          await new Promise(r => setTimeout(r, 1000));
        } else {
          console.log('[PDD] This conversation already has merchant reply as last message, skipping');
        }
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

  // Notify main process that login is successful (monitoring = on chat page = logged in)
  ipcRenderer.send('platform:login-success', { 
    platformId: PLATFORM_ID,
    shopId: state.shopId
  });

  // Set up human action detection listeners
  setupHumanActionListeners();

  // Initialize: only mark already-replied conversations as processed
  initializeExistingMessages();

  function scheduleProcess(delayMs = 600) {
    if (state.isProcessing) return;
    if (state.processTimer) {
      clearTimeout(state.processTimer);
    }
    state.processTimer = setTimeout(() => {
      state.processTimer = null;
      Promise.resolve(processCurrentConversation()).catch((e) => {
        console.error('[PDD] processCurrentConversation error:', e?.message || e);
      });
    }, delayMs);
  }

  // 1. Process current conversation if last message is from buyer (not merchant)
  if (!isLastMessageFromMerchant()) {
    scheduleProcess(800);
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
    try {
      findUnreadConversations();
      console.log('[PDD] Preview baseline ready');
    } catch (e) {
      console.warn('[PDD] Preview baseline init failed:', e?.message || e);
    }
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
    // Skip if human is operating
    if (shouldPauseForHumanAction()) {
      return;
    }
    
    let hasNewContent = false;
    for (const mutation of mutations) {
      if (mutation.addedNodes.length > 0) {
        hasNewContent = true;
        break;
      }
    }
    if (hasNewContent && !state.isProcessing) {
      scheduleProcess(600);
    }
  });

  observer.observe(chatArea, {
    childList: true,
    subtree: true
  });

  // 5. Periodic check for new messages - use Shift+Tab to switch (every 5 seconds, with cooldown)
  state.scanInterval = setInterval(() => {
    // Skip if human is operating
    if (shouldPauseForHumanAction()) {
      return;
    }
    
    if (!state.isProcessing) {
      const now = Date.now();
      
      // Check cooldown - don't send Shift+Tab too frequently
      if (now - state.lastShiftTabTime < state.shiftTabCooldown) {
        return;
      }
      
      // If we've had multiple consecutive "no unread" results, extend cooldown
      if (state.consecutiveNoUnread >= 3) {
        // After 3 consecutive failures, wait longer (15 seconds, optimized from 30s)
        if (now - state.lastShiftTabTime < 15000) {
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
        scheduleProcess(1500);
      } else {
        if (now - (state.lastFullScanTime || 0) > state.fullScanInterval) {
          state.lastFullScanTime = now;
          scanUnreadConversations();
        }
      }
    }
  }, 3000);  // Optimized from 5000ms to 3000ms for faster response

  // 6. Periodic check on current conversation (every 1.5 seconds, optimized from 2s)
  setInterval(() => {
    // Skip if human is operating
    if (shouldPauseForHumanAction()) {
      return;
    }
    
    if (!state.isProcessing) {
      scheduleProcess(0);
    }
  }, 1500);

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

    // Extract ALL visible order panels (multi-order support)
    const seenOrderIds = new Set();
    const MAX_ORDERS = 3;
    
    if (orderPanel) {
      // We found at least one; now collect all matching order panels
      const allOrderPanels = [];
      for (const selector of orderPanelSelectors) {
        try {
          const els = searchRoot.querySelectorAll(selector);
          for (const el of els) {
            if (isElementVisible(el) && el.offsetHeight > 10) {
              allOrderPanels.push(el);
            }
          }
          if (allOrderPanels.length > 0) break;
        } catch (e) {}
      }
      
      // If no multiple panels found, fallback to the single one we already found
      if (allOrderPanels.length === 0) {
        allOrderPanels.push(orderPanel);
      }
      
      for (const panel of allOrderPanels) {
        if (result.orders.length >= MAX_ORDERS) break;
        const order = extractSingleOrder(panel);
        if (order) {
          // Deduplicate by orderId
          if (order.orderId && seenOrderIds.has(order.orderId)) continue;
          if (order.orderId) seenOrderIds.add(order.orderId);
          result.orders.push(order);
        }
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
    trackingNumber: null,
    courierName: null,
    logisticsTrajectory: null,
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

  // --- Tracking Number (快递单号) ---
  const trackingSelectors = [
    '[class*="express-no"]', '[class*="tracking-no"]', '[class*="waybill"]',
    '[class*="logistics-no"]', '[class*="express-num"]', '[class*="tracking-num"]',
    '[class*="express-code"]', '[class*="ship-no"]', '[class*="delivery-no"]'
  ];
  for (const sel of trackingSelectors) {
    try {
      const el = container.querySelector(sel);
      if (el && isElementVisible(el)) {
        const tn = el.textContent.trim().replace(/[^A-Za-z0-9]/g, '');
        if (tn.length >= 8) {
          order.trackingNumber = tn;
          break;
        }
      }
    } catch (e) {}
  }
  // Regex fallback for tracking number patterns in text
  if (!order.trackingNumber) {
    const trackingPatterns = [
      /(?:快递单号|运单号|物流单号|快递号|运单编号)[：:\s]*([A-Za-z0-9]{8,30})/,
      /(?:SF|JT|YT|YD|ZTO|STO|YUND|EMS|JTSD)\d{10,18}/i,
      /\b(7[0-9]{14,17})\b/,  // Common ZTO/STO pattern
      /\b(SF\d{12,15})\b/i,   // SF Express
      /\b(JT\d{13,16})\b/i,   // JiTu Express
      /\b(YT\d{13,18})\b/i,   // YuanTong
      /\b(YD\d{13,18})\b/i,   // YunDa
    ];
    for (const pattern of trackingPatterns) {
      const m = text.match(pattern);
      if (m) {
        order.trackingNumber = m[1] || m[0];
        break;
      }
    }
  }

  // --- Courier Name (快递公司) ---
  const courierSelectors = [
    '[class*="express-name"]', '[class*="courier-name"]', '[class*="logistics-name"]',
    '[class*="express-company"]', '[class*="carrier"]', '[class*="ship-company"]'
  ];
  for (const sel of courierSelectors) {
    try {
      const el = container.querySelector(sel);
      if (el && isElementVisible(el)) {
        const cn = el.textContent.trim();
        if (cn.length >= 2 && cn.length <= 20) {
          order.courierName = cn;
          break;
        }
      }
    } catch (e) {}
  }
  // Regex fallback for courier name
  if (!order.courierName) {
    const courierMatch = text.match(/(顺丰|圆通|中通|韵达|申通|百世|极兔|邮政|EMS|京东物流|德邦|天天快递|丰巢)/);
    if (courierMatch) order.courierName = courierMatch[1];
  }

  // --- Logistics Trajectory (物流轨迹) ---
  const logisticsSelectors = [
    '[class*="logistics-track"]', '[class*="logistics-detail"]', '[class*="tracking-info"]',
    '[class*="logistics-info"]', '[class*="express-info"]', '[class*="delivery-track"]',
    '[class*="shipping-track"]', '[class*="logistics-timeline"]', '[class*="track-list"]'
  ];
  for (const sel of logisticsSelectors) {
    try {
      const el = container.querySelector(sel);
      if (el && isElementVisible(el)) {
        const trackText = el.textContent.trim();
        if (trackText.length > 5) {
          // Take first meaningful trajectory entry (latest status), limit to 200 chars
          order.logisticsTrajectory = trackText.substring(0, 200);
          break;
        }
      }
    } catch (e) {}
  }
  // Regex fallback: extract logistics keywords from text
  if (!order.logisticsTrajectory) {
    const logisticsKeywords = /(已揽收|已发出|派送中|正在派送|已签收|运输中|到达.*站|离开.*站|已到达|转运中|已装车|已取件|签收成功|正在运输)[^。\n]{0,60}/;
    const lm = text.match(logisticsKeywords);
    if (lm) {
      order.logisticsTrajectory = lm[0].substring(0, 200);
    }
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
  if (order.orderId || order.paymentStatus || order.shippingStatus || order.trackingNumber || order.products.length > 0) {
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
  const src = img.src || '';
  
  // Must have a valid src
  if (!src || src.startsWith('data:image/svg') || src.startsWith('data:image/gif;base64,R0lGOD')) {
    return false;
  }
  
  // Skip common non-content image patterns
  if (/emoji|icon|avatar|head_img|logo|badge|sticker|loading|placeholder|spinner/i.test(src)) {
    return false;
  }
  if (/emoji|icon|avatar|head|logo|badge|sticker/i.test(img.className || '')) {
    return false;
  }
  
  // Check dimensions - be more lenient for lazy-loaded images
  const w = img.naturalWidth || img.width || 0;
  const h = img.naturalHeight || img.height || 0;
  const rect = img.getBoundingClientRect();
  
  // Skip tiny images (emoji/icons) - but only if we have reliable dimension info
  if (w > 0 && w <= 30 && h > 0 && h <= 30) return false;
  if (rect.width > 0 && rect.width < 30 && rect.height > 0 && rect.height < 30) return false;
  
  // If image is from PDD CDN, it's likely a content image regardless of size
  if (/pddpic|pinduoduo|yangkeduo|t00img/i.test(src)) {
    return true;
  }
  
  // For other images, require reasonable displayed size
  if (rect.width > 0 && rect.width < 40) return false;
  
  return true;
}

/**
 * Check if an image is inside a product card, order card, or link card.
 * These should NOT be clicked (clicking navigates away from chat page).
 */
function isCardOrLinkImage(img) {
  // Check if img is inside a link (a tag) pointing to a product/order page
  const parentLink = img.closest('a[href]');
  if (parentLink) {
    const href = parentLink.href || '';
    if (/goods|product|item|order|detail|shop/i.test(href)) return true;
  }
  
  // Check parent containers for card/link/order/product indicators
  let el = img.parentElement;
  for (let depth = 0; el && depth < 6; depth++, el = el.parentElement) {
    const cls = (el.className || '').toLowerCase();
    const tagName = el.tagName || '';
    
    // Product card / order card / goods card patterns
    if (/product[-_]?card|goods[-_]?card|order[-_]?card|commodity|sku[-_]?card/i.test(cls)) return true;
    if (/card.*link|link.*card|msg[-_]?card|chat[-_]?card/i.test(cls)) return true;
    if (/goods[-_]?info|product[-_]?info|order[-_]?info/i.test(cls)) return true;
    if (/goods[-_]?msg|product[-_]?msg|order[-_]?msg/i.test(cls)) return true;
    
    // If the container has price text (¥) alongside the image, it's a product card
    if (el.textContent && /[¥￥]\s*\d/.test(el.textContent)) {
      // But only if the text is short (card-like), not a full message
      const textLen = el.textContent.replace(/\s/g, '').length;
      if (textLen < 200) return true;
    }
    
    // If parent is a link tag with navigation href, it's likely a clickable card
    if (tagName === 'A') {
      const href = (el.href || '').toLowerCase();
      // Only filter out links that navigate to product/order pages, not preview links
      if (href && /goods|product|item|order|detail|shop|mall\.pinduoduo/i.test(href)) return true;
      // Links with no href or blob/javascript/# are usually preview triggers, not navigation
    }
  }
  
  return false;
}

/**
 * Extract images sent by buyer in recent chat messages (thumbnail URLs)
 */
function extractChatImages() {
  const images = [];
  
  console.log('[PDD][Vision] ========== Starting image extraction ==========');
  
  // Find message containers - try PDD-specific then generic
  const messageSelectors = [
    '[class*="msg-item"]',
    '[class*="message-item"]',
    '[class*="chat-msg"]',
    '[class*="im-message"]',
    '[class*="msg-row"]',
    '[class*="message-row"]',
    '[class*="MsgItem"]',      // PDD uses camelCase sometimes
    '[class*="MessageItem"]',
    '[class*="chatItem"]',
    '[class*="msgContent"]',
    '[class*="bubble"]',       // Add bubble selector
    '[class*="Bubble"]'
  ];

  let messageItems = [];
  for (const selector of messageSelectors) {
    const items = document.querySelectorAll(selector);
    if (items.length > 0) {
      messageItems = Array.from(items);
      console.log(`[PDD][Vision] Found ${items.length} message items with selector: ${selector}`);
      break;
    }
  }

  // Fallback: find chat area and get direct children
  if (messageItems.length === 0) {
    const chatAreaSelectors = [
      '[class*="chat-content"]',
      '[class*="message-list"]',
      '[class*="msg-list"]',
      '[class*="chat-body"]',
      '[class*="im-content"]',
      '[class*="chat-record"]',
      '[class*="ChatContent"]',
      '[class*="MessageList"]',
      '[class*="chatList"]',
      '[class*="msgList"]',
      '[class*="chatWrap"]',
      '[class*="messageWrap"]'
    ];
    for (const selector of chatAreaSelectors) {
      const chatArea = document.querySelector(selector);
      if (chatArea && chatArea.children.length > 0) {
        messageItems = Array.from(chatArea.children);
        console.log(`[PDD][Vision] Fallback: found ${messageItems.length} children with selector: ${selector}`);
        break;
      }
    }
  }

  // Final fallback: scan all images in chat area directly
  if (messageItems.length === 0) {
    console.log('[PDD][Vision] No message containers found, scanning all images in document...');
    // Try to find images in the main chat area - expanded patterns
    const allImages = document.querySelectorAll('img[src*="pddpic"], img[src*="pinduoduo"], img[src*="yangkeduo"], img[src*="t00img"], img[src*="img.pddpic"]');
    console.log(`[PDD][Vision] Found ${allImages.length} PDD-hosted images`);
    for (const img of allImages) {
      if (!isContentImage(img)) continue;
      if (isCardOrLinkImage(img)) continue;
      let url = img.src || '';
      if (url && url.startsWith('http') && !images.includes(url)) {
        // Check if this image is likely from buyer (not in sidebar/header)
        const rect = img.getBoundingClientRect();
        if (rect.width >= 50 && rect.height >= 50) {
          images.push(url);
          console.log(`[PDD][Vision] Direct scan found image: ${url.substring(0, 80)}...`);
          if (images.length >= 3) break;
        }
      }
    }
    return images;
  }

  console.log(`[PDD][Vision] Processing ${messageItems.length} message items, checking last 8...`);

  // Scan last 8 messages for buyer-sent images
  const recentItems = messageItems.slice(-8);
  let buyerMsgCount = 0;
  let totalImgCount = 0;
  
  for (const item of recentItems) {
    const isBuyer = isCustomerMessage(item);
    const itemClass = (item.className || '').substring(0, 60);
    
    if (!isBuyer) {
      console.log(`[PDD][Vision] Skipping merchant message: ${itemClass}`);
      continue;
    }
    
    buyerMsgCount++;
    console.log(`[PDD][Vision] Checking buyer message: ${itemClass}`);

    const imgs = item.querySelectorAll('img[src]');
    totalImgCount += imgs.length;
    console.log(`[PDD][Vision] Found ${imgs.length} images in this message`);
    
    for (const img of imgs) {
      const src = img.src || '';
      const isContent = isContentImage(img);
      const isCard = isCardOrLinkImage(img);
      
      if (!isContent) {
        console.log(`[PDD][Vision] Skipping non-content image (icon/emoji): ${src.substring(0, 50)}...`);
        continue;
      }
      if (isCard) {
        console.log(`[PDD][Vision] Skipping card/link image: ${src.substring(0, 60)}...`);
        continue;
      }

      let url = src;
      if (!url.startsWith('http')) {
        try { url = new URL(url, window.location.href).href; } catch(e) { continue; }
      }
      if (url && !images.includes(url)) {
        images.push(url);
        console.log(`[PDD][Vision] ✓ Found buyer image thumbnail: ${url.substring(0, 80)}...`);
      }
    }
    if (images.length >= 3) break;
  }

  console.log(`[PDD][Vision] Summary: ${buyerMsgCount} buyer messages, ${totalImgCount} total images, ${images.length} extracted`);
  
  if (images.length === 0) {
    console.log('[PDD][Vision] No buyer images found in recent messages');
  }
  return images;
}

/**
 * Click image thumbnails in chat to open preview and get high-res URLs
 * PRIMARY method: Click to open preview (simulates human viewing)
 * FALLBACK: Clean URL parameters if click fails
 */
function getHighResImages() {
  const messageSelectors = [
    '[class*="msg-item"]',
    '[class*="message-item"]',
    '[class*="chat-msg"]',
    '[class*="im-message"]',
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

  // Fallback: chat area children
  if (messageItems.length === 0) {
    const chatArea = document.querySelector(
      '[class*="chat-content"], [class*="message-list"], [class*="msg-list"], [class*="chat-body"], [class*="im-content"], [class*="chat-record"]'
    );
    if (chatArea) {
      messageItems = Array.from(chatArea.children);
    }
  }

  const highResUrls = [];
  const recentItems = messageItems.slice(-8);

  console.log('[PDD][Vision] Starting non-invasive image URL extraction...');

  for (const item of recentItems) {
    if (!isCustomerMessage(item)) continue;

    const imgs = item.querySelectorAll('img[src]');
    for (const img of imgs) {
      if (!isContentImage(img)) continue;
      if (isCardOrLinkImage(img)) {
        console.log(`[PDD][Vision] Skipping card/link image: ${(img.src || '').substring(0, 60)}...`);
        continue;
      }
      if (highResUrls.length >= 3) break;

      const thumbnailUrl = img.src || '';
      if (!thumbnailUrl.startsWith('http')) continue;

      // Extract high-res URL from data attributes (no clicking needed)
      const dataSrc = img.getAttribute('data-src') || img.getAttribute('data-original') ||
                      img.getAttribute('data-origin') || img.getAttribute('data-big') || '';
      let highResUrl = dataSrc && dataSrc.startsWith('http')
        ? cleanImageUrl(dataSrc)
        : cleanImageUrl(thumbnailUrl);

      if (highResUrl && !highResUrls.includes(highResUrl)) {
        highResUrls.push(highResUrl);
        console.log(`[PDD][Vision] Got image URL: ${highResUrl.substring(0, 80)}...`);
      }
    }
    if (highResUrls.length >= 3) break;
  }

  console.log(`[PDD][Vision] Image extraction complete: ${highResUrls.length} images found`);
  return highResUrls;
}

/**
 * Clean CDN resize/quality parameters from image URL to get original resolution
 */
function cleanImageUrl(url) {
  if (!url) return url;
  let cleaned = url;
  cleaned = cleaned.replace(/[?&]x-oss-process=[^&]*/g, '');
  cleaned = cleaned.replace(/[?&]imageView2[^&]*/g, '');
  cleaned = cleaned.replace(/[?&](w|h|width|height|quality|q|resize|thumbnail|imageMogr2)=[^&]*/gi, '');
  // Also handle PDD style path-based params like /format/webp or /thumbnail/xxx
  cleaned = cleaned.replace(/\/thumbnail\/[^/]*/g, '');
  cleaned = cleaned.replace(/\/quality\/[^/]*/g, '');
  cleaned = cleaned.replace(/\/format\/webp/g, '');
  // Clean up trailing ? or &
  cleaned = cleaned.replace(/[?&]$/, '');
  return cleaned;
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
        // Get high-res images via URL extraction (non-invasive, no clicking)
        try {
          content.images = getHighResImages();
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
      // Skip auto-switching if human is operating
      if (shouldPauseForHumanAction()) {
        console.log('[PDD] Human action detected, skipping auto-switch to next conversation');
        return;
      }
      
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
