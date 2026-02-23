<template>
  <div class="chat-window">
    <div class="page-header">
      <div class="flex items-center gap-10">
        <el-button @click="$router.push('/chat')" :icon="ArrowLeft" circle />
        <h1 class="page-title">
          {{ session?.customer_name || '会话' }}
          <span class="shop-name">{{ session?.shop_name }}</span>
        </h1>
      </div>
      <div>
        <el-button v-if="session?.status === 'active'" @click="handleClose">
          关闭会话
        </el-button>
      </div>
    </div>
    
    <el-row :gutter="20" class="chat-content">
      <!-- Messages -->
      <el-col :span="16">
        <el-card class="message-card">
          <div ref="messageListRef" class="message-list">
            <div
              v-for="msg in chatStore.messages"
              :key="msg.message_id"
              :class="['message-item', msg.sender_type]"
            >
              <div class="message-avatar">
                <el-avatar :size="36">
                  {{ getAvatarText(msg.sender_type) }}
                </el-avatar>
              </div>
              <div class="message-content">
                <div class="message-header">
                  <span class="sender-name">{{ getSenderName(msg) }}</span>
                  <span class="message-time">{{ formatTime(msg.timestamp) }}</span>
                  <el-tag v-if="msg.ai_source" size="small" type="info">
                    {{ msg.ai_source }}
                  </el-tag>
                </div>
                <div class="message-text">{{ msg.content }}</div>
              </div>
            </div>
          </div>
          
          <!-- Input Area -->
          <div class="input-area">
            <el-input
              v-model="inputMessage"
              type="textarea"
              :rows="3"
              placeholder="输入消息... 输入 / 可触发快捷回复"
              @keydown.enter.ctrl="sendMessage"
            />
            <div class="input-actions">
              <el-button @click="showQuickReplies = !showQuickReplies">
                <el-icon><Promotion /></el-icon>
                快捷回复
              </el-button>
              <el-button type="primary" @click="generateAIReply" :loading="generating">
                <el-icon><MagicStick /></el-icon>
                AI回复
              </el-button>
              <el-button type="success" @click="sendMessage" :loading="sending">
                发送 (Ctrl+Enter)
              </el-button>
            </div>
          </div>
        </el-card>
      </el-col>
      
      <!-- Quick Replies & Info -->
      <el-col :span="8">
        <el-card v-if="showQuickReplies" class="mb-20">
          <template #header>快捷回复</template>
          <div class="quick-reply-list">
            <div
              v-for="qr in quickReplies"
              :key="qr.id"
              class="quick-reply-item"
              @click="useQuickReply(qr)"
            >
              <div class="qr-title">{{ qr.title }}</div>
              <div class="qr-shortcut">{{ qr.shortcut }}</div>
            </div>
          </div>
        </el-card>
        
        <el-card>
          <template #header>会话信息</template>
          <el-descriptions :column="1" size="small">
            <el-descriptions-item label="客户">
              {{ session?.customer_name || '未知' }}
            </el-descriptions-item>
            <el-descriptions-item label="店铺">
              {{ session?.shop_name }}
            </el-descriptions-item>
            <el-descriptions-item label="消息数">
              {{ session?.message_count || 0 }}
            </el-descriptions-item>
            <el-descriptions-item label="状态">
              <el-tag :type="session?.status === 'active' ? 'success' : 'info'" size="small">
                {{ session?.status === 'active' ? '进行中' : '已关闭' }}
              </el-tag>
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useChatStore } from '@/store/chat'
import { aiApi } from '@/api/ai'
import { quickRepliesApi } from '@/api/quickReplies'
import { ElMessage } from 'element-plus'
import { ArrowLeft } from '@element-plus/icons-vue'
import dayjs from 'dayjs'

const route = useRoute()
const router = useRouter()
const chatStore = useChatStore()

const sessionId = route.params.sessionId
const session = ref(null)
const inputMessage = ref('')
const sending = ref(false)
const generating = ref(false)
const showQuickReplies = ref(true)
const quickReplies = ref([])
const messageListRef = ref()

const fetchSession = async () => {
  session.value = await chatStore.fetchSession(sessionId)
  chatStore.fetchMessages(sessionId)
  chatStore.markRead(sessionId)
}

const fetchQuickReplies = async () => {
  try {
    const response = await quickRepliesApi.list({ is_active: 'true' })
    if (response.success) {
      quickReplies.value = response.data
    }
  } catch (e) {
    console.error(e)
  }
}

const sendMessage = async () => {
  const content = inputMessage.value.trim()
  if (!content || sending.value) return
  
  sending.value = true
  try {
    const response = await chatStore.sendMessage({
      session_id: sessionId,
      sender_type: 'agent',
      content: content,
    })
    
    if (response.success) {
      inputMessage.value = ''
      scrollToBottom()
    }
  } finally {
    sending.value = false
  }
}

const generateAIReply = async () => {
  // Get last customer message as the question
  const customerMessages = chatStore.messages.filter(m => m.sender_type === 'customer')
  const lastMessage = customerMessages[customerMessages.length - 1]
  
  if (!lastMessage) {
    ElMessage.warning('没有客户消息可回复')
    return
  }
  
  generating.value = true
  try {
    const response = await aiApi.generateReply({
      question: lastMessage.content,
      session_id: sessionId,
      shop_id: session.value?.shop,
    })
    
    if (response.success) {
      inputMessage.value = response.data.reply
      ElMessage.success(`回复来源: ${response.data.source}`)
    }
  } catch (e) {
    ElMessage.error('AI回复生成失败')
  } finally {
    generating.value = false
  }
}

const useQuickReply = (qr) => {
  inputMessage.value = qr.content
}

const handleClose = async () => {
  const response = await chatStore.closeSession(sessionId)
  if (response.success) {
    ElMessage.success('会话已关闭')
    session.value.status = 'closed'
  }
}

const getAvatarText = (senderType) => {
  const map = { customer: '客', agent: '服', ai: 'AI', system: '系' }
  return map[senderType] || '?'
}

const getSenderName = (msg) => {
  const map = { customer: '客户', agent: '客服', ai: 'AI助手', system: '系统' }
  return msg.sender_name || map[msg.sender_type] || msg.sender_type
}

const formatTime = (time) => {
  return time ? dayjs(time).format('HH:mm') : ''
}

const scrollToBottom = () => {
  nextTick(() => {
    if (messageListRef.value) {
      messageListRef.value.scrollTop = messageListRef.value.scrollHeight
    }
  })
}

watch(() => chatStore.messages.length, () => {
  scrollToBottom()
})

onMounted(() => {
  fetchSession()
  fetchQuickReplies()
})
</script>

<style scoped>
.chat-window {
  padding: 0;
}

.shop-name {
  font-size: 14px;
  color: #909399;
  font-weight: normal;
  margin-left: 10px;
}

.chat-content {
  height: calc(100vh - 180px);
}

.message-card {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.message-card :deep(.el-card__body) {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 0;
}

.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.message-item {
  display: flex;
  margin-bottom: 16px;
}

.message-item.customer {
  flex-direction: row;
}

.message-item.agent,
.message-item.ai {
  flex-direction: row-reverse;
}

.message-avatar {
  flex-shrink: 0;
}

.message-content {
  max-width: 70%;
  margin: 0 12px;
}

.message-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.sender-name {
  font-size: 12px;
  color: #909399;
}

.message-time {
  font-size: 12px;
  color: #c0c4cc;
}

.message-text {
  padding: 10px 14px;
  border-radius: 8px;
  background: #f5f7fa;
  line-height: 1.5;
}

.message-item.agent .message-text,
.message-item.ai .message-text {
  background: #ecf5ff;
}

.input-area {
  border-top: 1px solid #ebeef5;
  padding: 15px;
}

.input-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 10px;
}

.quick-reply-list {
  max-height: 300px;
  overflow-y: auto;
}

.quick-reply-item {
  padding: 10px;
  border-radius: 6px;
  cursor: pointer;
  margin-bottom: 8px;
  background: #f5f7fa;
  transition: background 0.2s;
}

.quick-reply-item:hover {
  background: #ecf5ff;
}

.qr-title {
  font-weight: 500;
  margin-bottom: 4px;
}

.qr-shortcut {
  font-size: 12px;
  color: #909399;
}
</style>
