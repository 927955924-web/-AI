/**
 * 调试训练窗口逻辑
 */

// 全局状态
let currentMessage = null;
let isPaused = false;
let isPinned = true;
let currentShopId = null;
let countdownSeconds = 15;
let countdownTimer = null;

// DOM 元素
const elements = {
    pinBtn: document.getElementById('pinBtn'),
    followMainWindow: document.getElementById('followMainWindow'),
    messageHistory: document.getElementById('messageHistory'),
    questionContent: document.getElementById('questionContent'),
    replyContent: document.getElementById('replyContent'),
    referenceKnowledge: document.getElementById('referenceKnowledge'),
    btnProcessed: document.getElementById('btnProcessed'),
    btnPause: document.getElementById('btnPause'),
    countdownInput: document.getElementById('countdownInput'),
    statusMessage: document.getElementById('statusMessage'),
    kbSelect: document.getElementById('kbSelect'),
    btnAddToKb: document.getElementById('btnAddToKb'),
    sidebarToggle: document.getElementById('sidebarToggle'),
    toast: document.getElementById('toast')
};

// 初始化
async function init() {
    // 加载店铺列表
    await loadShops();
    
    // 绑定事件
    bindEvents();
    
    // 设置监听器
    setupListeners();
    
    // 设置初始置顶状态
    window.debugAPI.setAlwaysOnTop(true);
}

// 加载店铺列表
async function loadShops() {
    try {
        const shops = await window.debugAPI.getShops();
        elements.kbSelect.innerHTML = '';
        
        if (shops && shops.length > 0) {
            shops.forEach(shop => {
                const option = document.createElement('option');
                option.value = shop.id || shop.shop_id;
                option.textContent = `${shop.name || shop.shop_name || '店铺'} 的店铺知识库`;
                elements.kbSelect.appendChild(option);
            });
            
            // 自动选择第一个
            if (shops.length >= 1) {
                currentShopId = shops[0].id || shops[0].shop_id;
            }
        } else {
            elements.kbSelect.innerHTML = '<option value="">暂无店铺</option>';
        }
    } catch (error) {
        console.error('加载店铺失败:', error);
        elements.kbSelect.innerHTML = '<option value="">加载失败</option>';
    }
}

// 绑定事件
function bindEvents() {
    // 置顶按钮
    elements.pinBtn.addEventListener('click', togglePin);
    
    // 已处理按钮 - 发送回复并继续
    elements.btnProcessed.addEventListener('click', handleProcessed);
    
    // 暂停按钮
    elements.btnPause.addEventListener('click', handlePauseToggle);
    
    // 倒计时输入框
    elements.countdownInput.addEventListener('change', (e) => {
        countdownSeconds = parseInt(e.target.value) || 15;
    });
    
    // 店铺选择
    elements.kbSelect.addEventListener('change', (e) => {
        currentShopId = e.target.value;
    });
    
    // 添加到知识库按钮
    elements.btnAddToKb.addEventListener('click', handleAddToKb);
    
    // 侧边栏切换
    elements.sidebarToggle.addEventListener('click', () => {
        showToast('话术库功能开发中...', 'info');
    });
    
    // 跟随主窗口
    elements.followMainWindow.addEventListener('change', (e) => {
        // TODO: 实现跟随主窗口功能
    });
}

// 设置监听器
function setupListeners() {
    // 监听新消息
    window.debugAPI.onNewMessage((data) => {
        handleNewMessage(data);
    });
    
    // 监听倒计时更新
    window.debugAPI.onCountdownUpdate((seconds) => {
        // 使用本地倒计时，忽略主进程的
    });
    
    // 监听知识库结果
    window.debugAPI.onKnowledgeResults((results) => {
        displayKnowledgeResults(results);
    });
}

// 切换置顶状态
function togglePin() {
    isPinned = !isPinned;
    window.debugAPI.setAlwaysOnTop(isPinned);
    
    if (isPinned) {
        elements.pinBtn.textContent = '已置顶，点击取消';
        elements.pinBtn.classList.remove('unpinned');
    } else {
        elements.pinBtn.textContent = '点击置顶窗口';
        elements.pinBtn.classList.add('unpinned');
    }
}

// 处理新消息
function handleNewMessage(data) {
    currentMessage = data;
    
    // 更新状态
    elements.statusMessage.textContent = '正在处理消息...';
    elements.statusMessage.style.color = '#27ae60';
    
    // 填充历史记录
    let history = '';
    if (data.context) {
        history = data.context + '\n';
    }
    history += `买家: ${data.customerMessage || data.message || ''}`;
    elements.messageHistory.value = history;
    
    // 填充问题
    elements.questionContent.value = data.question || data.customerMessage || data.message || '';
    
    // 填充回复
    elements.replyContent.value = data.aiReply || data.reply || '';
    
    // 自动选择店铺
    if (data.shopId) {
        const option = elements.kbSelect.querySelector(`option[value="${data.shopId}"]`);
        if (option) {
            elements.kbSelect.value = data.shopId;
            currentShopId = data.shopId;
        }
    }
    
    // 搜索知识库参考
    searchKnowledgeReference(elements.questionContent.value);
    
    // 重置暂停状态
    isPaused = false;
    elements.btnPause.textContent = '暂停倒计时 | 我自己处理';
    
    // 开始本地倒计时
    startLocalCountdown();
}

// 开始本地倒计时
function startLocalCountdown() {
    if (countdownTimer) {
        clearInterval(countdownTimer);
    }
    
    let remaining = countdownSeconds;
    elements.countdownInput.value = remaining;
    
    countdownTimer = setInterval(() => {
        if (isPaused) return;
        
        remaining--;
        elements.countdownInput.value = remaining;
        
        if (remaining <= 0) {
            clearInterval(countdownTimer);
            countdownTimer = null;
            autoSendReply();
        }
    }, 1000);
}

// 自动发送回复
function autoSendReply() {
    const reply = elements.replyContent.value.trim();
    if (!reply || !currentMessage) {
        elements.statusMessage.textContent = '当前无正在处理的消息';
        elements.statusMessage.style.color = '#999';
        return;
    }
    
    window.debugAPI.sendReply(reply);
    showToast('回复已自动发送', 'success');
    resetState();
}

// 处理"已处理"按钮
function handleProcessed() {
    const reply = elements.replyContent.value.trim();
    
    if (!reply) {
        showToast('请输入回复内容', 'error');
        return;
    }
    
    // 停止倒计时
    if (countdownTimer) {
        clearInterval(countdownTimer);
        countdownTimer = null;
    }
    
    window.debugAPI.sendReply(reply);
    showToast('回复已发送，继续接待中...', 'success');
    resetState();
}

// 暂停/继续切换
function handlePauseToggle() {
    isPaused = !isPaused;
    window.debugAPI.pauseCountdown(isPaused);
    
    if (isPaused) {
        elements.btnPause.textContent = '继续倒计时 | 自动发送';
        showToast('倒计时已暂停', 'info');
    } else {
        elements.btnPause.textContent = '暂停倒计时 | 我自己处理';
        showToast('倒计时已继续', 'info');
    }
}

// 搜索知识库参考
async function searchKnowledgeReference(question) {
    if (!question || !currentShopId) {
        elements.referenceKnowledge.value = '';
        return;
    }
    
    try {
        const results = await window.debugAPI.searchKnowledge(question, currentShopId);
        displayKnowledgeResults(results);
    } catch (error) {
        console.error('搜索知识库失败:', error);
        elements.referenceKnowledge.value = '搜索失败';
    }
}

// 显示知识库结果
function displayKnowledgeResults(results) {
    if (!results || results.length === 0) {
        elements.referenceKnowledge.value = '未找到相关知识';
        return;
    }
    
    const text = results.slice(0, 3).map((item, i) => {
        const similarity = item.similarity ? ` (${(item.similarity * 100).toFixed(0)}%)` : '';
        return `${i + 1}. Q: ${item.question || item.q || ''}\n   A: ${item.answer || item.a || ''}${similarity}`;
    }).join('\n\n');
    
    elements.referenceKnowledge.value = text;
}

// 添加到知识库
async function handleAddToKb() {
    const question = elements.questionContent.value.trim();
    const answer = elements.replyContent.value.trim();
    
    if (!question || !answer) {
        showToast('请填写问题和回复内容', 'error');
        return;
    }
    
    if (!currentShopId) {
        showToast('请选择目标知识库', 'error');
        return;
    }
    
    // 先发送回复
    if (currentMessage) {
        window.debugAPI.sendReply(answer);
    }
    
    // 禁用按钮
    elements.btnAddToKb.disabled = true;
    elements.btnAddToKb.textContent = '添加中...';
    
    try {
        await window.debugAPI.addToKnowledge({
            shop_id: currentShopId,
            question: question,
            answer: answer,
            category: 'debug_training'
        });
        showToast('已发送回复并添加到知识库', 'success');
        resetState();
    } catch (error) {
        console.error('添加到知识库失败:', error);
        showToast('添加失败: ' + error.message, 'error');
    } finally {
        elements.btnAddToKb.disabled = false;
        elements.btnAddToKb.textContent = '发送并添加到知识库';
    }
}

// 重置状态
function resetState() {
    currentMessage = null;
    
    if (countdownTimer) {
        clearInterval(countdownTimer);
        countdownTimer = null;
    }
    
    elements.messageHistory.value = '';
    elements.questionContent.value = '';
    elements.replyContent.value = '';
    elements.referenceKnowledge.value = '';
    elements.countdownInput.value = countdownSeconds;
    elements.statusMessage.textContent = '当前无正在处理的消息';
    elements.statusMessage.style.color = '#999';
    
    isPaused = false;
    elements.btnPause.textContent = '暂停倒计时 | 我自己处理';
}

// 显示提示信息
function showToast(message, type = 'info') {
    elements.toast.textContent = message;
    elements.toast.className = 'toast ' + type + ' show';
    
    setTimeout(() => {
        elements.toast.classList.remove('show');
    }, 3000);
}

// 启动
document.addEventListener('DOMContentLoaded', init);
