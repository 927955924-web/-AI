/**
 * WeChat Web (wx.qq.com) Preload Script
 * Monitors and auto-replies to messages in WeChat Web interface
 */
const { ipcRenderer } = require('electron');

const PLATFORM_ID = 'wechat';

// State management
const state = {
  processedMessages: new Set(),
  repliedConversations: new Map(),
  lastCustomerMessages: new Map(),
  sentMessages: new Set(),
  isProcessing: false,
  isReplying: false,
  observerActive: false,
  scanInterval: null,
  lastScanTime: 0,
  replyTimeout: 60000,
  isLoggedIn: false
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
 * Find element using multiple selector strategies
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
 * Check if user is logged in to WeChat Web
 */
function checkLoginStatus() {
  // WeChat Web shows QR code when not logged in
  // When logged in, the chat panel is visible
  const qrCode = document.querySelector('.qrcode, .login__qrcode, [class*="qrcode"]');
  const chatPanel = document.querySelector('.chat, .box, #chatArea, [class*="chat_container"]');
  const contactList = document.querySelector('.nav_view, .chat_list, [class*="contact"]');
  
  const wasLoggedIn = state.isLoggedIn;
  state.isLoggedIn = !qrCode && (chatPanel || contactList);
  
  if (state.isLoggedIn && !wasLoggedIn) {
    console.log('[WeChat] Login detected!');
    ipcRenderer.send('platform:login-success', { platformId: PLATFORM_ID });
  }
  
  return state.isLoggedIn;
}

/**
 * Find conversations with unread messages
 */
function findUnreadConversations() {
  const unreadItems = [];
  
  // WeChat Web conversation list selectors
  const conversationSelectors = [
    '.chat_item',
    '.chatroom',
    '[class*="chat_item"]',
    '[class*="conversation"]',
    '.nav_view .chat_item'
  ];
  
  let conversations = [];
  for (const selector of conversationSelectors) {
    const items = document.querySelectorAll(selector);
    if (items.length > 0) {
      conversations = Array.from(items);
      break;
    }
  }
  
  conversations.forEach(item => {
    // Check for unread indicator (red dot/badge)
    const unreadBadge = item.querySelector(
      '.web_wechat_reddot, .web_wechat_reddot_middle, [class*="unread"], [class*="badge"], .icon_dot'
    );
    
    if (unreadBadge && unreadBadge.offsetParent !== null) {
      unreadItems.push(item);
    }
  });
  
  console.log(`[WeChat] Found ${unreadItems.length} unread conversations`);
  return unreadItems;
}

/**
 * Check if current conversation has any pending messages
 */
function hasAnyPendingMessages() {
  return findUnreadConversations().length > 0;
}

/**
 * Check if a message element is from the other party (not self)
 */
function isCustomerMessage(msgElement) {
  // WeChat Web: messages from others are on the left, self messages on the right
  // Check for class indicators
  const classList = msgElement.className || '';
  
  // Self messages usually have 'me' or 'self' or 'right' in class
  if (/\b(me|self|right|send)\b/i.test(classList)) {
    return false;
  }
  
  // Others' messages usually have 'other' or 'left' or 'receive' in class
  if (/\b(other|left|receive|you)\b/i.test(classList)) {
    return true;
  }
  
  // Check by avatar position (WeChat shows avatar on left for others)
  const avatar = msgElement.querySelector('.avatar, img[class*="avatar"], .headimg');
  if (avatar) {
    const msgRect = msgElement.getBoundingClientRect();
    const avatarRect = avatar.getBoundingClientRect();
    // If avatar is on left side of message, it's from others
    return avatarRect.left < msgRect.left + msgRect.width / 2;
  }
  
  // Default: assume it's from customer if we can't determine
  return true;
}

/**
 * Extract clean message text from element
 */
function extractMessageText(element) {
  // Try to find the text content container
  const textContainer = element.querySelector(
    '.plain, .js_message_plain, [class*="content"], [class*="text"], .bubble_cont'
  );
  
  if (textContainer) {
    return textContainer.textContent.trim();
  }
  
  // Fall back to element text, excluding timestamps and names
  const clone = element.cloneNode(true);
  // Remove time and name elements
  clone.querySelectorAll('.message_system, .time, .nickname, [class*="time"], [class*="name"]').forEach(el => el.remove());
  
  return clone.textContent.trim();
}

/**
 * Get the current chat partner's name
 */
function getCurrentCustomerName() {
  // Try to find the current chat title/name
  const nameSelectors = [
    '.chat_title .nickname',
    '.title_name',
    '.chat__title',
    '[class*="chat_title"] [class*="name"]',
    '.chatroom .title',
    '#chatArea .title'
  ];
  
  for (const selector of nameSelectors) {
    const el = document.querySelector(selector);
    if (el && el.textContent.trim()) {
      return el.textContent.trim();
    }
  }
  
  // Fallback: try to get from active conversation item
  const activeChat = document.querySelector('.chat_item.active, .chatroom.active, [class*="active"] .nickname');
  if (activeChat) {
    const nickname = activeChat.querySelector('.nickname, .name, [class*="name"]');
    if (nickname) return nickname.textContent.trim();
  }
  
  return '微信用户';
}

/**
 * Get the last customer message from current chat
 */
function getLastCustomerMessage() {
  const messageSelectors = [
    '.message',
    '.msg',
    '[class*="message"]',
    '.bubble',
    '.chat_content > div'
  ];
  
  let messageItems = [];
  for (const selector of messageSelectors) {
    const items = document.querySelectorAll(selector);
    if (items.length > 0) {
      messageItems = Array.from(items);
      break;
    }
  }
  
  // Look in chat content area if no messages found
  if (messageItems.length === 0) {
    const chatArea = findElement([
      '.chat_content',
      '#chatArea',
      '[class*="message_list"]',
      '[class*="chat_bd"]'
    ]);
    if (chatArea) {
      messageItems = Array.from(chatArea.children);
    }
  }
  
  // Reverse iterate to find last customer message
  for (let i = messageItems.length - 1; i >= 0; i--) {
    const item = messageItems[i];
    const text = item.textContent.trim();
    
    if (text.length < 1) continue;
    
    if (isCustomerMessage(item)) {
      const msgText = extractMessageText(item);
      if (msgText && msgText.length > 0) {
        const msgHash = hashMessage(msgText);
        if (state.sentMessages.has(msgHash)) {
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
 * Check if last message is from self (already replied)
 */
function isLastMessageFromSelf() {
  const messageSelectors = [
    '.message',
    '.msg',
    '[class*="message"]',
    '.bubble'
  ];
  
  let messageItems = [];
  for (const selector of messageSelectors) {
    const items = document.querySelectorAll(selector);
    if (items.length > 0) {
      messageItems = Array.from(items);
      break;
    }
  }
  
  if (messageItems.length === 0) return false;
  
  for (let i = messageItems.length - 1; i >= 0; i--) {
    const item = messageItems[i];
    const text = extractMessageText(item);
    if (!text || text.length < 1) continue;
    
    return !isCustomerMessage(item);
  }
  
  return false;
}

/**
 * Collect conversation context (last N messages)
 */
function collectConversationContext(maxMessages = 10) {
  const messages = [];
  const messageSelectors = [
    '.message',
    '.msg',
    '[class*="message"]',
    '.bubble'
  ];
  
  let messageItems = [];
  for (const selector of messageSelectors) {
    const items = document.querySelectorAll(selector);
    if (items.length > 0) {
      messageItems = Array.from(items);
      break;
    }
  }
  
  const startIdx = Math.max(0, messageItems.length - maxMessages);
  for (let i = startIdx; i < messageItems.length; i++) {
    const item = messageItems[i];
    const text = extractMessageText(item);
    if (!text || text.length < 1) continue;
    
    const isCustomer = isCustomerMessage(item);
    const role = isCustomer ? '买家' : '客服';
    messages.push(`${role}: ${text}`);
  }
  
  return messages.join('\n');
}

/**
 * Send message to input and submit
 */
async function sendMessage(text) {
  // Find input area
  const input = findElement([
    '#editArea',
    '.edit_area',
    '[contenteditable="true"]',
    'textarea.input',
    '[class*="input"][contenteditable]'
  ]);
  
  if (!input) {
    console.error('[WeChat] Input box not found');
    return false;
  }
  
  // Focus and clear
  input.click();
  input.focus();
  await new Promise(r => setTimeout(r, 300));
  
  const isContentEditable = input.getAttribute('contenteditable') === 'true';
  
  if (isContentEditable) {
    input.innerHTML = '';
    input.innerText = text;
  } else {
    input.value = text;
  }
  
  // Trigger input events
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
  
  await new Promise(r => setTimeout(r, 500));
  
  // Find and click send button
  const sendBtn = findElement([
    '.btn_send',
    '[class*="send"]',
    'a.btn.btn_send',
    'button[class*="send"]'
  ]);
  
  if (sendBtn) {
    sendBtn.click();
    console.log('[WeChat] Clicked send button');
  } else {
    // Try Enter key
    ipcRenderer.send('platform:send-enter', PLATFORM_ID);
    console.log('[WeChat] Sent Enter key');
  }
  
  // Track sent message
  state.sentMessages.add(hashMessage(text));
  if (state.sentMessages.size > 200) {
    const arr = Array.from(state.sentMessages);
    state.sentMessages = new Set(arr.slice(-100));
  }
  
  console.log('[WeChat] Message sent:', text.substring(0, 50));
  return true;
}

/**
 * Process current conversation
 */
async function processCurrentConversation() {
  if (state.isReplying) {
    console.log('[WeChat] Already replying, skipping');
    return false;
  }
  
  if (isLastMessageFromSelf()) {
    console.log('[WeChat] Last message is from self, skipping');
    return false;
  }
  
  const lastMsg = getLastCustomerMessage();
  if (!lastMsg) return false;
  
  const customerName = getCurrentCustomerName();
  const customerId = `wechat_${customerName}`;
  const msgHash = hashMessage(lastMsg.text);
  const conversationKey = `${customerId}_${msgHash}`;
  
  if (state.processedMessages.has(conversationKey)) {
    return false;
  }
  
  const lastKnownMsgHash = state.lastCustomerMessages.get(customerId);
  const lastReplyTime = state.repliedConversations.get(customerId);
  
  if (lastKnownMsgHash === msgHash && lastReplyTime) {
    const timeSinceReply = Date.now() - lastReplyTime;
    if (timeSinceReply < state.replyTimeout) {
      console.log(`[WeChat] Already replied to ${customerName}, waiting for new message`);
      return false;
    }
  }
  
  state.isReplying = true;
  
  try {
    state.processedMessages.add(conversationKey);
    state.lastCustomerMessages.set(customerId, msgHash);
    
    if (state.processedMessages.size > 500) {
      const arr = Array.from(state.processedMessages);
      state.processedMessages = new Set(arr.slice(-300));
    }
    
    const conversationContext = collectConversationContext();
    
    console.log(`[WeChat] New message from ${customerName}: ${lastMsg.text.substring(0, 50)}`);
    
    ipcRenderer.send('platform:new-message', {
      platformId: PLATFORM_ID,
      customerId: customerId,
      customerName: customerName,
      message: lastMsg.text,
      context: conversationContext,
      timestamp: Date.now()
    });
    
    return true;
  } finally {
    setTimeout(() => {
      state.isReplying = false;
    }, 2000);
  }
}

/**
 * Handle reply from main process
 */
ipcRenderer.on('platform:send-reply', async (event, data) => {
  const { customerId, reply } = data;
  console.log(`[WeChat] Received reply for ${customerId}: ${reply.substring(0, 50)}`);
  
  const success = await sendMessage(reply);
  
  if (success) {
    state.repliedConversations.set(customerId, Date.now());
    console.log('[WeChat] Reply sent successfully');
  } else {
    console.error('[WeChat] Failed to send reply');
  }
});

/**
 * Setup message observer
 */
function setupMessageObserver() {
  if (state.observerActive) return;
  
  const chatArea = findElement([
    '.chat_content',
    '#chatArea',
    '[class*="message_list"]',
    '.chat_bd'
  ]);
  
  if (!chatArea) {
    console.log('[WeChat] Chat area not found, retrying...');
    setTimeout(setupMessageObserver, 2000);
    return;
  }
  
  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      if (mutation.addedNodes.length > 0) {
        // New message added, process after short delay
        setTimeout(() => {
          if (!state.isReplying) {
            processCurrentConversation();
          }
        }, 500);
        break;
      }
    }
  });
  
  observer.observe(chatArea, {
    childList: true,
    subtree: true
  });
  
  state.observerActive = true;
  console.log('[WeChat] Message observer active');
}

/**
 * Periodic scan for unread messages
 */
function startPeriodicScan() {
  if (state.scanInterval) return;
  
  state.scanInterval = setInterval(async () => {
    if (!checkLoginStatus()) return;
    
    const now = Date.now();
    if (now - state.lastScanTime < 3000) return;
    state.lastScanTime = now;
    
    // Process current conversation first
    if (!state.isReplying) {
      await processCurrentConversation();
    }
    
  }, 5000);
  
  console.log('[WeChat] Periodic scan started');
}

/**
 * Initialize
 */
function init() {
  console.log('[WeChat] Preload script initializing...');
  
  // Check login status periodically
  const loginCheck = setInterval(() => {
    if (checkLoginStatus()) {
      console.log('[WeChat] User logged in, starting monitors');
      clearInterval(loginCheck);
      
      setTimeout(() => {
        setupMessageObserver();
        startPeriodicScan();
      }, 2000);
    }
  }, 2000);
  
  // Expose functions for main process
  ipcRenderer.on('platform:check-pending', (event) => {
    const hasPending = hasAnyPendingMessages();
    event.sender.send('platform:pending-result', { platformId: PLATFORM_ID, hasPending });
  });
  
  console.log('[WeChat] Preload script loaded');
}

// Start when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
