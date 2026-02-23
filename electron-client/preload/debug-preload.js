/**
 * 调试训练窗口 Preload 脚本
 * 用于在调试窗口和主进程之间建立 IPC 通信桥接
 */

const { contextBridge, ipcRenderer } = require('electron');

// 暴露调试 API 到渲染进程
contextBridge.exposeInMainWorld('debugAPI', {
    // 发送回复到平台
    sendReply: (reply) => {
        ipcRenderer.send('debug:send-reply', reply);
    },

    // 跳过当前消息
    skipMessage: () => {
        ipcRenderer.send('debug:skip-message');
    },

    // 暂停/恢复倒计时
    pauseCountdown: (paused) => {
        ipcRenderer.send('debug:pause-countdown', paused);
    },

    // 添加到知识库
    addToKnowledge: (data) => {
        return new Promise((resolve, reject) => {
            const requestId = Date.now() + Math.random();
            
            const handler = (event, result) => {
                if (result.requestId === requestId) {
                    ipcRenderer.removeListener('debug:add-knowledge-result', handler);
                    if (result.success) {
                        resolve(result.data);
                    } else {
                        reject(new Error(result.error));
                    }
                }
            };
            
            ipcRenderer.on('debug:add-knowledge-result', handler);
            ipcRenderer.send('debug:add-knowledge', { ...data, requestId });
        });
    },

    // 搜索知识库
    searchKnowledge: (question, shopId) => {
        return new Promise((resolve, reject) => {
            const requestId = Date.now() + Math.random();
            
            const handler = (event, result) => {
                if (result.requestId === requestId) {
                    ipcRenderer.removeListener('debug:search-knowledge-result', handler);
                    if (result.success) {
                        resolve(result.data);
                    } else {
                        reject(new Error(result.error));
                    }
                }
            };
            
            ipcRenderer.on('debug:search-knowledge-result', handler);
            ipcRenderer.send('debug:search-knowledge', { question, shopId, requestId });
        });
    },

    // 获取店铺列表
    getShops: () => {
        return new Promise((resolve, reject) => {
            const requestId = Date.now() + Math.random();
            
            const handler = (event, result) => {
                if (result.requestId === requestId) {
                    ipcRenderer.removeListener('debug:get-shops-result', handler);
                    if (result.success) {
                        resolve(result.data);
                    } else {
                        reject(new Error(result.error));
                    }
                }
            };
            
            ipcRenderer.on('debug:get-shops-result', handler);
            ipcRenderer.send('debug:get-shops', { requestId });
        });
    },

    // 设置窗口置顶
    setAlwaysOnTop: (flag) => {
        ipcRenderer.send('debug:set-always-on-top', flag);
    },

    // 关闭窗口
    closeWindow: () => {
        ipcRenderer.send('debug:close-window');
    },

    // 监听新消息
    onNewMessage: (callback) => {
        ipcRenderer.on('debug:new-message', (event, data) => {
            callback(data);
        });
    },

    // 监听倒计时更新
    onCountdownUpdate: (callback) => {
        ipcRenderer.on('debug:countdown-update', (event, seconds) => {
            callback(seconds);
        });
    },

    // 监听知识库搜索结果（被动推送）
    onKnowledgeResults: (callback) => {
        ipcRenderer.on('debug:knowledge-results', (event, results) => {
            callback(results);
        });
    }
});
