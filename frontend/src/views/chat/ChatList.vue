<template>
  <div class="chat-list">
    <div class="page-header">
      <h1 class="page-title">客服会话</h1>
      <el-button type="primary" @click="showCreateDialog">
        <el-icon><Plus /></el-icon>
        新建会话
      </el-button>
    </div>
    
    <!-- Filters -->
    <el-card class="mb-20">
      <el-form :inline="true" :model="filters">
        <el-form-item label="店铺">
          <el-select v-model="filters.shop" clearable placeholder="全部店铺" style="width: 180px;">
            <el-option
              v-for="s in shops"
              :key="s.shop_id"
              :label="s.shop_name"
              :value="s.shop_id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filters.status" clearable placeholder="全部状态" style="width: 120px;">
            <el-option label="进行中" value="active" />
            <el-option label="已关闭" value="closed" />
            <el-option label="已归档" value="archived" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="fetchSessions">查询</el-button>
        </el-form-item>
      </el-form>
    </el-card>
    
    <!-- Session List -->
    <el-card>
      <el-table :data="chatStore.sessions" v-loading="chatStore.loading" stripe>
        <el-table-column prop="shop_name" label="店铺" width="150" />
        <el-table-column prop="customer_name" label="客户" width="120">
          <template #default="{ row }">
            {{ row.customer_name || '未知客户' }}
          </template>
        </el-table-column>
        <el-table-column prop="last_message" label="最后消息" show-overflow-tooltip />
        <el-table-column prop="message_count" label="消息" width="70" align="center" />
        <el-table-column label="未读" width="70" align="center">
          <template #default="{ row }">
            <el-badge v-if="row.unread_count > 0" :value="row.unread_count" type="danger" />
            <span v-else>0</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)" size="small">
              {{ getStatusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="updated_at" label="更新时间" width="160">
          <template #default="{ row }">
            {{ formatDate(row.updated_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="openChat(row)">
              进入会话
            </el-button>
            <el-button 
              v-if="row.status === 'active'" 
              size="small" 
              @click="handleClose(row)"
            >
              关闭
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    
    <!-- Create Dialog -->
    <el-dialog v-model="dialogVisible" title="新建会话" width="500px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
        <el-form-item label="店铺" prop="shop">
          <el-select v-model="form.shop" placeholder="选择店铺" style="width: 100%;">
            <el-option
              v-for="s in shops"
              :key="s.shop_id"
              :label="s.shop_name"
              :value="s.shop_id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="客户名称">
          <el-input v-model="form.customer_name" placeholder="客户名称（选填）" />
        </el-form-item>
        <el-form-item label="平台">
          <el-input v-model="form.platform" placeholder="来源平台（选填）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useChatStore } from '@/store/chat'
import { useShopsStore } from '@/store/shops'
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'

const router = useRouter()
const chatStore = useChatStore()
const shopsStore = useShopsStore()

const shops = ref([])
const dialogVisible = ref(false)
const submitting = ref(false)
const formRef = ref()

const filters = reactive({
  shop: '',
  status: '',
})

const form = reactive({
  shop: '',
  customer_name: '',
  platform: '',
})

const rules = {
  shop: [{ required: true, message: '请选择店铺', trigger: 'change' }],
}

const fetchSessions = () => {
  const params = {}
  if (filters.shop) params.shop = filters.shop
  if (filters.status) params.status = filters.status
  chatStore.fetchSessions(params)
}

const fetchShops = async () => {
  await shopsStore.fetchShops()
  shops.value = shopsStore.shops
}

const showCreateDialog = () => {
  form.shop = ''
  form.customer_name = ''
  form.platform = ''
  dialogVisible.value = true
}

const handleCreate = async () => {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  
  submitting.value = true
  try {
    const response = await chatStore.createSession(form)
    if (response.success) {
      ElMessage.success('会话创建成功')
      dialogVisible.value = false
      router.push(`/chat/${response.data.session_id}`)
    }
  } finally {
    submitting.value = false
  }
}

const openChat = (session) => {
  router.push(`/chat/${session.session_id}`)
}

const handleClose = async (session) => {
  const response = await chatStore.closeSession(session.session_id)
  if (response.success) {
    ElMessage.success('会话已关闭')
  }
}

const getStatusType = (status) => {
  const types = { active: 'success', closed: 'info', archived: 'warning' }
  return types[status] || 'info'
}

const getStatusLabel = (status) => {
  const labels = { active: '进行中', closed: '已关闭', archived: '已归档' }
  return labels[status] || status
}

const formatDate = (date) => {
  return date ? dayjs(date).format('MM-DD HH:mm') : ''
}

onMounted(() => {
  fetchSessions()
  fetchShops()
})
</script>

<style scoped>
.chat-list {
  padding: 0;
}
</style>
