<template>
  <div class="knowledge-list">
    <div class="page-header">
      <h1 class="page-title">知识库</h1>
      <el-button type="primary" @click="showCreateDialog">
        <el-icon><Plus /></el-icon>
        新增问答
      </el-button>
    </div>
    
    <!-- Summary -->
    <el-row :gutter="20" class="mb-20">
      <el-col :span="6">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-value">{{ summary.total_questions }}</div>
          <div class="stat-label">今日新增</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-value">{{ summary.correct_answers }}</div>
          <div class="stat-label">正确答案</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-value">{{ (summary.accuracy_rate * 100).toFixed(1) }}%</div>
          <div class="stat-label">准确率</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-value">{{ totalCount }}</div>
          <div class="stat-label">总条目</div>
        </el-card>
      </el-col>
    </el-row>
    
    <!-- Search -->
    <el-card class="mb-20">
      <el-form :inline="true" :model="filters">
        <el-form-item label="搜索">
          <el-input v-model="filters.search" placeholder="问题关键词" clearable style="width: 250px;" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="filters.is_correct" clearable placeholder="全部" style="width: 120px;">
            <el-option label="正确答案" value="true" />
            <el-option label="待确认" value="false" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="() => { currentPage = 1; fetchKnowledge() }">查询</el-button>
        </el-form-item>
      </el-form>
    </el-card>
    
    <!-- Knowledge List -->
    <el-card>
      <el-table :data="numberedList" v-loading="loading" stripe>
        <el-table-column prop="index_label" label="编号" width="80" align="center" />
        <el-table-column prop="product_name" label="关联商品" width="160" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.product_name || '—' }}
          </template>
        </el-table-column>
        <el-table-column prop="question" label="问题" min-width="250" show-overflow-tooltip />
        <el-table-column prop="answer" label="回答" min-width="300" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_correct ? 'success' : 'warning'" size="small">
              {{ row.is_correct ? '正确' : '待确认' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="usage_count" label="使用次数" width="90" align="center" />
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button 
              v-if="!row.is_correct" 
              size="small" 
              type="success"
              @click="markCorrect(row)"
            >
              标记正确
            </el-button>
            <el-button size="small" @click="handleEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      
      <div style="margin-top: 16px; display: flex; justify-content: flex-end;">
        <el-pagination
          v-model:current-page="currentPage"
          :page-size="pageSize"
          :total="totalCount"
          layout="total, prev, pager, next"
          @current-change="handlePageChange"
        />
      </div>
    </el-card>
    
    <!-- Create/Edit Dialog -->
    <el-dialog v-model="dialogVisible" :title="editingItem ? '编辑问答' : '新增问答'" width="600px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
        <el-form-item label="问题" prop="question">
          <el-input v-model="form.question" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="回答" prop="answer">
          <el-input v-model="form.answer" type="textarea" :rows="4" />
        </el-form-item>
        <el-form-item label="关键词">
          <el-input v-model="form.keywords" placeholder="用逗号分隔" />
        </el-form-item>
        <el-form-item label="分类">
          <el-input v-model="form.category" placeholder="如：物流、退款、售后" />
        </el-form-item>
        <el-form-item label="正确答案">
          <el-switch v-model="form.is_correct" />
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
import { ref, reactive, computed, onMounted } from 'vue'
import { knowledgeApi } from '@/api/knowledge'
import { ElMessage, ElMessageBox } from 'element-plus'

const knowledgeList = ref([])
const loading = ref(false)
const submitting = ref(false)
const dialogVisible = ref(false)
const editingItem = ref(null)
const formRef = ref()
const totalCount = ref(0)
const currentPage = ref(1)
const pageSize = 20

const numberedList = computed(() => {
  const list = knowledgeList.value
  const offset = (currentPage.value - 1) * pageSize
  let productIndex = 0
  let qaIndex = 0
  let lastProductId = null

  return list.map((item, idx) => {
    if (item.product) {
      if (item.product !== lastProductId) {
        productIndex++
        qaIndex = 1
        lastProductId = item.product
      } else {
        qaIndex++
      }
      return { ...item, index_label: `${offset + idx + 1}` }
    }
    return { ...item, index_label: `${offset + idx + 1}` }
  })
})

const summary = reactive({
  total_questions: 0,
  correct_answers: 0,
  accuracy_rate: 0,
})

const filters = reactive({
  search: '',
  is_correct: '',
})

const form = reactive({
  question: '',
  answer: '',
  keywords: '',
  category: '',
  is_correct: false,
})

const rules = {
  question: [{ required: true, message: '请输入问题', trigger: 'blur' }],
  answer: [{ required: true, message: '请输入回答', trigger: 'blur' }],
}

const fetchKnowledge = async () => {
  loading.value = true
  try {
    const params = { page: currentPage.value }
    if (filters.search) params.search = filters.search
    if (filters.is_correct) params.is_correct = filters.is_correct
    
    const response = await knowledgeApi.list(params)
    if (response.success) {
      knowledgeList.value = response.data
      totalCount.value = response.count || response.data.length
    }
  } finally {
    loading.value = false
  }
}

const handlePageChange = (page) => {
  currentPage.value = page
  fetchKnowledge()
}

const fetchSummary = async () => {
  try {
    const response = await knowledgeApi.summary()
    if (response.success) {
      Object.assign(summary, response.data)
    }
  } catch (e) {
    console.error(e)
  }
}

const showCreateDialog = () => {
  editingItem.value = null
  Object.assign(form, {
    question: '',
    answer: '',
    keywords: '',
    category: '',
    is_correct: false,
  })
  dialogVisible.value = true
}

const handleEdit = (item) => {
  editingItem.value = item
  Object.assign(form, {
    question: item.question,
    answer: item.answer,
    keywords: item.keywords,
    category: item.category,
    is_correct: item.is_correct,
  })
  dialogVisible.value = true
}

const handleSubmit = async () => {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  
  submitting.value = true
  try {
    let response
    if (editingItem.value) {
      response = await knowledgeApi.update(editingItem.value.id, form)
    } else {
      response = await knowledgeApi.create(form)
    }
    
    if (response.success) {
      ElMessage.success(response.message)
      dialogVisible.value = false
      fetchKnowledge()
      fetchSummary()
    }
  } finally {
    submitting.value = false
  }
}

const markCorrect = async (item) => {
  const response = await knowledgeApi.markCorrect(item.id)
  if (response.success) {
    ElMessage.success('已标记为正确答案')
    item.is_correct = true
    fetchSummary()
  }
}

const handleDelete = async (item) => {
  await ElMessageBox.confirm('确定要删除这条问答吗？', '确认删除', { type: 'warning' })
  
  const response = await knowledgeApi.delete(item.id)
  if (response.success) {
    ElMessage.success('已删除')
    fetchKnowledge()
    fetchSummary()
  }
}

onMounted(() => {
  fetchKnowledge()
  fetchSummary()
})
</script>

<style scoped>
.knowledge-list {
  padding: 0;
}
</style>
