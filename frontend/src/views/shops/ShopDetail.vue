<template>
  <div class="shop-detail" v-loading="loading">
    <div class="page-header">
      <div class="flex items-center gap-10">
        <el-button @click="$router.push('/shops')" :icon="ArrowLeft" circle />
        <h1 class="page-title">{{ shop?.shop_name || '店铺详情' }}</h1>
        <el-tag v-if="shop" :type="getStatusType(shop.status)">
          {{ shop.status_display }}
        </el-tag>
      </div>
      <div>
        <el-button 
          v-if="shop?.status !== 'running'" 
          type="success"
          @click="handleStart"
        >
          启动店铺
        </el-button>
        <el-button 
          v-else 
          type="warning"
          @click="handleStop"
        >
          停止店铺
        </el-button>
      </div>
    </div>
    
    <el-row :gutter="20">
      <el-col :span="16">
        <!-- Basic Info -->
        <el-card class="mb-20">
          <template #header>基本信息</template>
          <el-descriptions :column="2" border>
            <el-descriptions-item label="店铺名称">{{ shop?.shop_name }}</el-descriptions-item>
            <el-descriptions-item label="平台">{{ shop?.platform_display }}</el-descriptions-item>
            <el-descriptions-item label="账号">{{ shop?.account }}</el-descriptions-item>
            <el-descriptions-item label="登录地址">
              <el-link v-if="shop?.login_url" :href="shop.login_url" target="_blank" type="primary">
                {{ shop.login_url }}
              </el-link>
              <span v-else>-</span>
            </el-descriptions-item>
            <el-descriptions-item label="创建时间">{{ formatDate(shop?.created_at) }}</el-descriptions-item>
            <el-descriptions-item label="最后登录">{{ formatDate(shop?.last_login) || '-' }}</el-descriptions-item>
          </el-descriptions>
        </el-card>
        
        <!-- Sessions -->
        <el-card>
          <template #header>
            <div class="flex justify-between items-center">
              <span>会话列表</span>
              <el-button size="small" @click="fetchSessions">刷新</el-button>
            </div>
          </template>
          <el-table :data="sessions" stripe>
            <el-table-column prop="customer_name" label="客户" width="120" />
            <el-table-column prop="last_message" label="最后消息" show-overflow-tooltip />
            <el-table-column prop="message_count" label="消息数" width="80" align="center" />
            <el-table-column label="状态" width="80">
              <template #default="{ row }">
                <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">
                  {{ row.status === 'active' ? '进行中' : '已关闭' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100">
              <template #default="{ row }">
                <el-button size="small" @click="$router.push(`/chat/${row.session_id}`)">
                  查看
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
      
      <el-col :span="8">
        <!-- Notes / Knowledge Base -->
        <el-card>
          <template #header>店铺知识库</template>
          <el-input
            v-model="notes"
            type="textarea"
            :rows="15"
            placeholder="输入店铺专属知识库内容..."
          />
          <el-button type="primary" class="mt-10" @click="saveNotes" :loading="saving">
            保存
          </el-button>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useShopsStore } from '@/store/shops'
import { chatApi } from '@/api/chat'
import { ElMessage } from 'element-plus'
import { ArrowLeft } from '@element-plus/icons-vue'
import dayjs from 'dayjs'

const route = useRoute()
const shopsStore = useShopsStore()

const loading = ref(true)
const saving = ref(false)
const shop = ref(null)
const sessions = ref([])
const notes = ref('')

const shopId = route.params.id

const fetchShop = async () => {
  loading.value = true
  try {
    shop.value = await shopsStore.fetchShop(shopId)
    notes.value = shop.value?.notes || ''
  } finally {
    loading.value = false
  }
}

const fetchSessions = async () => {
  try {
    const response = await chatApi.list({ shop: shopId })
    if (response.success) {
      sessions.value = response.data
    }
  } catch (e) {
    console.error(e)
  }
}

const saveNotes = async () => {
  saving.value = true
  try {
    const response = await shopsStore.updateShop(shopId, { notes: notes.value })
    if (response.success) {
      ElMessage.success('保存成功')
    }
  } finally {
    saving.value = false
  }
}

const handleStart = async () => {
  const response = await shopsStore.startShop(shopId)
  if (response.success) {
    shop.value = response.data
    ElMessage.success('店铺已启动')
  }
}

const handleStop = async () => {
  const response = await shopsStore.stopShop(shopId)
  if (response.success) {
    shop.value = response.data
    ElMessage.success('店铺已停止')
  }
}

const getStatusType = (status) => {
  const types = { inactive: 'info', running: 'success', stopped: 'warning' }
  return types[status] || 'info'
}

const formatDate = (date) => {
  return date ? dayjs(date).format('YYYY-MM-DD HH:mm') : ''
}

onMounted(() => {
  fetchShop()
  fetchSessions()
})
</script>

<style scoped>
.shop-detail {
  padding: 0;
}
</style>
