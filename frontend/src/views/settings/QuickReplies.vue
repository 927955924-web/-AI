<template>
  <div class="quick-replies">
    <div class="page-header">
      <h1 class="page-title">快捷回复管理</h1>
      <el-button type="primary" @click="showCreateDialog">
        <el-icon><Plus /></el-icon>
        新增快捷回复
      </el-button>
    </div>
    
    <!-- Category Tabs -->
    <el-card>
      <el-tabs v-model="activeCategory" @tab-change="fetchQuickReplies">
        <el-tab-pane label="全部" name="" />
        <el-tab-pane 
          v-for="cat in categories" 
          :key="cat.value" 
          :label="cat.label" 
          :name="cat.value" 
        />
      </el-tabs>
      
      <el-table :data="quickReplies" v-loading="loading" stripe>
        <el-table-column prop="title" label="标题" width="150" />
        <el-table-column prop="shortcut" label="快捷键" width="100">
          <template #default="{ row }">
            <el-tag size="small">{{ row.shortcut }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="content" label="内容" show-overflow-tooltip />
        <el-table-column prop="category_display" label="分类" width="100" />
        <el-table-column prop="usage_count" label="使用次数" width="90" align="center" />
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-switch v-model="row.is_active" @change="toggleActive(row)" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="handleEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    
    <!-- Create/Edit Dialog -->
    <el-dialog v-model="dialogVisible" :title="editingItem ? '编辑快捷回复' : '新增快捷回复'" width="600px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
        <el-form-item label="标题" prop="title">
          <el-input v-model="form.title" placeholder="如：欢迎语" />
        </el-form-item>
        <el-form-item label="快捷键" prop="shortcut">
          <el-input v-model="form.shortcut" placeholder="如：/welcome">
            <template #prepend>/</template>
          </el-input>
        </el-form-item>
        <el-form-item label="分类" prop="category">
          <el-select v-model="form.category" style="width: 100%;">
            <el-option
              v-for="cat in categories"
              :key="cat.value"
              :label="cat.label"
              :value="cat.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="内容" prop="content">
          <el-input v-model="form.content" type="textarea" :rows="5" placeholder="支持变量：{customer_name}, {order_id}" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="form.sort_order" :min="0" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.is_active" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">
          {{ editingItem ? '更新' : '创建' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { quickRepliesApi } from '@/api/quickReplies'
import { ElMessage, ElMessageBox } from 'element-plus'

const quickReplies = ref([])
const categories = ref([])
const loading = ref(false)
const submitting = ref(false)
const dialogVisible = ref(false)
const editingItem = ref(null)
const formRef = ref()
const activeCategory = ref('')

const form = reactive({
  title: '',
  shortcut: '',
  content: '',
  category: 'other',
  sort_order: 0,
  is_active: true,
})

const rules = {
  title: [{ required: true, message: '请输入标题', trigger: 'blur' }],
  content: [{ required: true, message: '请输入内容', trigger: 'blur' }],
  category: [{ required: true, message: '请选择分类', trigger: 'change' }],
}

const fetchQuickReplies = async () => {
  loading.value = true
  try {
    const params = {}
    if (activeCategory.value) params.category = activeCategory.value
    
    const response = await quickRepliesApi.list(params)
    if (response.success) {
      quickReplies.value = response.data
    }
  } finally {
    loading.value = false
  }
}

const fetchCategories = async () => {
  try {
    const response = await quickRepliesApi.categories()
    if (response.success) {
      categories.value = response.data
    }
  } catch (e) {
    console.error(e)
  }
}

const showCreateDialog = () => {
  editingItem.value = null
  Object.assign(form, {
    title: '',
    shortcut: '',
    content: '',
    category: 'other',
    sort_order: 0,
    is_active: true,
  })
  dialogVisible.value = true
}

const handleEdit = (item) => {
  editingItem.value = item
  Object.assign(form, {
    title: item.title,
    shortcut: item.shortcut?.replace(/^\//, '') || '',
    content: item.content,
    category: item.category,
    sort_order: item.sort_order,
    is_active: item.is_active,
  })
  dialogVisible.value = true
}

const handleSubmit = async () => {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  
  submitting.value = true
  try {
    const data = {
      ...form,
      shortcut: form.shortcut.startsWith('/') ? form.shortcut : '/' + form.shortcut,
    }
    
    let response
    if (editingItem.value) {
      response = await quickRepliesApi.update(editingItem.value.id, data)
    } else {
      response = await quickRepliesApi.create(data)
    }
    
    if (response.success) {
      ElMessage.success(response.message)
      dialogVisible.value = false
      fetchQuickReplies()
    }
  } finally {
    submitting.value = false
  }
}

const toggleActive = async (item) => {
  await quickRepliesApi.update(item.id, { is_active: item.is_active })
}

const handleDelete = async (item) => {
  await ElMessageBox.confirm('确定要删除这个快捷回复吗？', '确认删除', { type: 'warning' })
  
  const response = await quickRepliesApi.delete(item.id)
  if (response.success) {
    ElMessage.success('已删除')
    fetchQuickReplies()
  }
}

onMounted(() => {
  fetchQuickReplies()
  fetchCategories()
})
</script>

<style scoped>
.quick-replies {
  padding: 0;
}
</style>
