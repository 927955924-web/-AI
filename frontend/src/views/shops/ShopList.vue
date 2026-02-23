<template>
  <div class="shop-list">
    <div class="page-header">
      <h1 class="page-title">店铺管理</h1>
      <el-button type="primary" @click="showCreateDialog">
        <el-icon><Plus /></el-icon>
        新增店铺
      </el-button>
    </div>
    
    <!-- Filters -->
    <el-card class="mb-20">
      <el-form :inline="true" :model="filters">
        <el-form-item label="平台">
          <el-select v-model="filters.platform" clearable placeholder="全部平台" style="width: 150px;">
            <el-option
              v-for="p in platforms"
              :key="p.value"
              :label="p.label"
              :value="p.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filters.status" clearable placeholder="全部状态" style="width: 120px;">
            <el-option label="未启动" value="inactive" />
            <el-option label="运行中" value="running" />
            <el-option label="已停止" value="stopped" />
          </el-select>
        </el-form-item>
        <el-form-item label="搜索">
          <el-input v-model="filters.search" placeholder="店铺名称" clearable style="width: 200px;" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="fetchShops">查询</el-button>
        </el-form-item>
      </el-form>
    </el-card>
    
    <!-- Shop List -->
    <el-card>
      <el-table :data="shopsStore.shops" v-loading="shopsStore.loading" stripe>
        <el-table-column prop="shop_name" label="店铺名称" min-width="150" />
        <el-table-column prop="platform_display" label="平台" width="120" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)">
              {{ row.status_display }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="session_count" label="会话数" width="80" align="center" />
        <el-table-column prop="created_at" label="创建时间" width="180">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <el-button-group>
              <el-button 
                v-if="row.status !== 'running'" 
                type="success" 
                size="small"
                @click="handleStart(row)"
              >
                启动
              </el-button>
              <el-button 
                v-else 
                type="warning" 
                size="small"
                @click="handleStop(row)"
              >
                停止
              </el-button>
              <el-button size="small" @click="handleEdit(row)">编辑</el-button>
              <el-button size="small" @click="$router.push(`/shops/${row.shop_id}`)">详情</el-button>
              <el-button type="danger" size="small" @click="handleDelete(row)">删除</el-button>
            </el-button-group>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    
    <!-- Create/Edit Dialog -->
    <el-dialog 
      v-model="dialogVisible" 
      :title="editingShop ? '编辑店铺' : '新增店铺'"
      width="600px"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
        <el-form-item label="店铺名称" prop="shop_name">
          <el-input v-model="form.shop_name" placeholder="请输入店铺备注名称" />
        </el-form-item>
        <el-form-item label="平台" prop="platform_type">
          <el-select v-model="form.platform_type" placeholder="选择平台" style="width: 100%;">
            <el-option
              v-for="p in platforms"
              :key="p.value"
              :label="p.label"
              :value="p.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="登录账号" prop="account">
          <el-input v-model="form.account" placeholder="平台登录账号" />
        </el-form-item>
        <el-form-item label="登录密码">
          <el-input v-model="form.password" type="password" placeholder="留空则不修改" show-password />
        </el-form-item>
        <el-form-item label="登录地址">
          <el-input v-model="form.login_url" placeholder="https://" />
        </el-form-item>
        <el-form-item label="备注/知识库">
          <el-input v-model="form.notes" type="textarea" :rows="3" placeholder="店铺专属知识库内容" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">
          {{ editingShop ? '更新' : '创建' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useShopsStore } from '@/store/shops'
import { ElMessage, ElMessageBox } from 'element-plus'
import dayjs from 'dayjs'

const shopsStore = useShopsStore()

const platforms = ref([])
const dialogVisible = ref(false)
const editingShop = ref(null)
const submitting = ref(false)
const formRef = ref()

const filters = reactive({
  platform: '',
  status: '',
  search: '',
})

const form = reactive({
  shop_name: '',
  platform_type: '',
  account: '',
  password: '',
  login_url: '',
  notes: '',
})

const rules = {
  shop_name: [{ required: true, message: '请输入店铺名称', trigger: 'blur' }],
  platform_type: [{ required: true, message: '请选择平台', trigger: 'change' }],
  account: [{ required: true, message: '请输入登录账号', trigger: 'blur' }],
}

const fetchShops = () => {
  const params = {}
  if (filters.platform) params.platform = filters.platform
  if (filters.status) params.status = filters.status
  if (filters.search) params.search = filters.search
  shopsStore.fetchShops(params)
}

const fetchPlatforms = async () => {
  await shopsStore.fetchPlatforms()
  platforms.value = shopsStore.platforms
}

const showCreateDialog = () => {
  editingShop.value = null
  Object.assign(form, {
    shop_name: '',
    platform_type: '',
    account: '',
    password: '',
    login_url: '',
    notes: '',
  })
  dialogVisible.value = true
}

const handleEdit = (shop) => {
  editingShop.value = shop
  Object.assign(form, {
    shop_name: shop.shop_name,
    platform_type: shop.platform_type,
    account: shop.account,
    password: '',
    login_url: shop.login_url,
    notes: shop.notes,
  })
  dialogVisible.value = true
}

const handleSubmit = async () => {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  
  submitting.value = true
  try {
    const data = { ...form }
    if (!data.password) delete data.password
    
    let response
    if (editingShop.value) {
      response = await shopsStore.updateShop(editingShop.value.shop_id, data)
    } else {
      response = await shopsStore.createShop(data)
    }
    
    if (response.success) {
      ElMessage.success(response.message)
      dialogVisible.value = false
      fetchShops()
    }
  } finally {
    submitting.value = false
  }
}

const handleStart = async (shop) => {
  const response = await shopsStore.startShop(shop.shop_id)
  if (response.success) {
    ElMessage.success('店铺已启动')
  }
}

const handleStop = async (shop) => {
  const response = await shopsStore.stopShop(shop.shop_id)
  if (response.success) {
    ElMessage.success('店铺已停止')
  }
}

const handleDelete = async (shop) => {
  await ElMessageBox.confirm('确定要删除这个店铺吗？', '确认删除', {
    type: 'warning',
  })
  
  const response = await shopsStore.deleteShop(shop.shop_id)
  if (response.success) {
    ElMessage.success('店铺已删除')
  }
}

const getStatusType = (status) => {
  const types = {
    inactive: 'info',
    running: 'success',
    stopped: 'warning',
  }
  return types[status] || 'info'
}

const formatDate = (date) => {
  return date ? dayjs(date).format('YYYY-MM-DD HH:mm') : ''
}

onMounted(() => {
  fetchShops()
  fetchPlatforms()
})
</script>

<style scoped>
.shop-list {
  padding: 0;
}
</style>
