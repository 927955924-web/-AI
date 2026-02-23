<template>
  <div class="product-list">
    <div class="page-header">
      <h1 class="page-title">商品管理</h1>
      <div class="flex gap-10">
        <el-button @click="showImportDialog">
          <el-icon><Upload /></el-icon>
          导入CSV
        </el-button>
        <el-button @click="exportCsv">
          <el-icon><Download /></el-icon>
          导出CSV
        </el-button>
        <el-button type="primary" @click="showCreateDialog">
          <el-icon><Plus /></el-icon>
          新增商品
        </el-button>
      </div>
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
        <el-form-item label="搜索">
          <el-input v-model="filters.search" placeholder="商品名称/SKU" clearable style="width: 200px;" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="fetchProducts">查询</el-button>
        </el-form-item>
      </el-form>
    </el-card>
    
    <!-- Product List -->
    <el-card>
      <el-table :data="products" v-loading="loading" stripe>
        <el-table-column prop="sku" label="SKU" width="120" />
        <el-table-column prop="name" label="商品名称" min-width="200" />
        <el-table-column prop="price" label="价格" width="100">
          <template #default="{ row }">
            ¥{{ row.price }}
          </template>
        </el-table-column>
        <el-table-column prop="stock" label="库存" width="80" align="center" />
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">
              {{ row.status === 'active' ? '在售' : '下架' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="知识库" width="100" align="center">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click="showKnowledge(row)">
              {{ row.qa_count || 0 }} 条
            </el-button>
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
    <el-dialog v-model="dialogVisible" :title="editingProduct ? '编辑商品' : '新增商品'" width="500px">
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
        <el-form-item label="商品名称" prop="name">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="SKU">
          <el-input v-model="form.sku" />
        </el-form-item>
        <el-form-item label="价格" prop="price">
          <el-input-number v-model="form.price" :min="0" :precision="2" style="width: 100%;" />
        </el-form-item>
        <el-form-item label="库存" prop="stock">
          <el-input-number v-model="form.stock" :min="0" style="width: 100%;" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" style="width: 100%;">
            <el-option label="在售" value="active" />
            <el-option label="下架" value="inactive" />
          </el-select>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">
          {{ editingProduct ? '更新' : '创建' }}
        </el-button>
      </template>
    </el-dialog>
    
    <!-- Import Dialog -->
    <el-dialog v-model="importDialogVisible" title="导入CSV" width="500px">
      <el-form label-width="80px">
        <el-form-item label="店铺" required>
          <el-select v-model="importShop" placeholder="选择店铺" style="width: 100%;">
            <el-option
              v-for="s in shops"
              :key="s.shop_id"
              :label="s.shop_name"
              :value="s.shop_id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="CSV文件">
          <el-upload
            ref="uploadRef"
            :auto-upload="false"
            :limit="1"
            accept=".csv"
            :on-change="handleFileChange"
          >
            <el-button>选择文件</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item>
          <el-text type="info">
            CSV格式: sku, name/商品名称, price/价格, stock/库存, description/描述
          </el-text>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="importDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="importing" @click="handleImport">导入</el-button>
      </template>
    </el-dialog>
    <!-- Knowledge Dialog -->
    <el-dialog v-model="kbDialogVisible" :title="kbDialogTitle" width="800px" top="5vh">
      <el-table :data="kbList" v-loading="kbLoading" stripe max-height="500">
        <el-table-column prop="index_label" label="编号" width="70" align="center" />
        <el-table-column prop="question" label="问题" min-width="200" show-overflow-tooltip />
        <el-table-column prop="answer" label="回答" min-width="300" show-overflow-tooltip />
        <el-table-column label="状态" width="80" align="center">
          <template #default="{ row }">
            <el-tag :type="row.is_correct ? 'success' : 'warning'" size="small">
              {{ row.is_correct ? '已审核' : '待审核' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" align="center">
          <template #default="{ row }">
            <el-button size="small" type="danger" link @click="deleteKbItem(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="kbList.length === 0 && !kbLoading" style="text-align: center; padding: 40px 0; color: #999;">
        该商品暂无知识库数据
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { productsApi } from '@/api/products'
import { knowledgeApi } from '@/api/knowledge'
import { useShopsStore } from '@/store/shops'
import { ElMessage, ElMessageBox } from 'element-plus'

const shopsStore = useShopsStore()

const products = ref([])
const shops = ref([])
const loading = ref(false)
const submitting = ref(false)
const dialogVisible = ref(false)
const editingProduct = ref(null)
const formRef = ref()

const importDialogVisible = ref(false)
const importShop = ref('')
const importFile = ref(null)
const importing = ref(false)
const uploadRef = ref()

const kbDialogVisible = ref(false)
const kbDialogTitle = ref('知识库')
const kbList = ref([])
const kbLoading = ref(false)
const kbProduct = ref(null)

const filters = reactive({
  shop: '',
  search: '',
})

const form = reactive({
  shop: '',
  name: '',
  sku: '',
  price: 0,
  stock: 0,
  status: 'active',
  description: '',
})

const rules = {
  shop: [{ required: true, message: '请选择店铺', trigger: 'change' }],
  name: [{ required: true, message: '请输入商品名称', trigger: 'blur' }],
}

const fetchProducts = async () => {
  loading.value = true
  try {
    const params = {}
    if (filters.shop) params.shop = filters.shop
    if (filters.search) params.search = filters.search
    
    const response = await productsApi.list(params)
    if (response.success) {
      products.value = response.data
    }
  } finally {
    loading.value = false
  }
}

const fetchShops = async () => {
  await shopsStore.fetchShops()
  shops.value = shopsStore.shops
}

const showCreateDialog = () => {
  editingProduct.value = null
  Object.assign(form, {
    shop: filters.shop || '',
    name: '',
    sku: '',
    price: 0,
    stock: 0,
    status: 'active',
    description: '',
  })
  dialogVisible.value = true
}

const handleEdit = (product) => {
  editingProduct.value = product
  Object.assign(form, {
    shop: product.shop,
    name: product.name,
    sku: product.sku,
    price: product.price,
    stock: product.stock,
    status: product.status,
    description: product.description,
  })
  dialogVisible.value = true
}

const handleSubmit = async () => {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  
  submitting.value = true
  try {
    let response
    if (editingProduct.value) {
      response = await productsApi.update(editingProduct.value.product_id, form)
    } else {
      response = await productsApi.create(form)
    }
    
    if (response.success) {
      ElMessage.success(response.message)
      dialogVisible.value = false
      fetchProducts()
    }
  } finally {
    submitting.value = false
  }
}

const handleDelete = async (product) => {
  await ElMessageBox.confirm('确定要删除这个商品吗？', '确认删除', { type: 'warning' })
  
  const response = await productsApi.delete(product.product_id)
  if (response.success) {
    ElMessage.success('商品已删除')
    fetchProducts()
  }
}

const showImportDialog = () => {
  importShop.value = filters.shop || ''
  importFile.value = null
  importDialogVisible.value = true
}

const handleFileChange = (file) => {
  importFile.value = file.raw
}

const handleImport = async () => {
  if (!importShop.value) {
    ElMessage.warning('请选择店铺')
    return
  }
  if (!importFile.value) {
    ElMessage.warning('请选择CSV文件')
    return
  }
  
  importing.value = true
  try {
    const response = await productsApi.importCsv(importShop.value, importFile.value)
    if (response.success) {
      ElMessage.success(response.message)
      importDialogVisible.value = false
      fetchProducts()
    }
  } finally {
    importing.value = false
  }
}

const exportCsv = async () => {
  try {
    const params = {}
    if (filters.shop) params.shop = filters.shop
    
    const blob = await productsApi.exportCsv(params)
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'products.csv'
    a.click()
    window.URL.revokeObjectURL(url)
  } catch (e) {
    ElMessage.error('导出失败')
  }
}

const showKnowledge = async (product) => {
  kbProduct.value = product
  kbDialogTitle.value = `知识库 - ${product.name}`
  kbDialogVisible.value = true
  kbLoading.value = true
  kbList.value = []
  try {
    const response = await knowledgeApi.list({ product: product.product_id })
    if (response.success && response.data) {
      let idx = 0
      kbList.value = response.data.map(item => {
        idx++
        return { ...item, index_label: idx }
      })
    }
  } finally {
    kbLoading.value = false
  }
}

const deleteKbItem = async (row) => {
  await ElMessageBox.confirm('确定要删除这条知识吗？', '确认删除', { type: 'warning' })
  const response = await knowledgeApi.delete(row.id)
  if (response.success) {
    ElMessage.success('已删除')
    if (kbProduct.value) showKnowledge(kbProduct.value)
  }
}

onMounted(() => {
  fetchProducts()
  fetchShops()
})
</script>

<style scoped>
.product-list {
  padding: 0;
}
</style>
