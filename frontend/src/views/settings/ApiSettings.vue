<template>
  <div class="api-settings">
    <div class="page-header">
      <h1 class="page-title">API设置</h1>
    </div>
    
    <el-card style="max-width: 700px;">
      <el-form :model="form" label-width="130px" v-loading="loading">
        <el-form-item label="模型提供商">
          <el-select v-model="form.provider" style="width: 100%;" @change="onProviderChange">
            <el-option label="DeepSeek (推荐)" value="deepseek" />
            <el-option label="通义千问 (Qwen)" value="qwen" />
            <el-option label="豆包 (Doubao)" value="doubao" />
            <el-option label="OpenAI" value="openai" />
            <el-option label="Gemini" value="gemini" />
          </el-select>
        </el-form-item>

        <el-form-item label="API Key">
          <el-input
            v-model="currentApiKey"
            type="password"
            :placeholder="apiKeyPlaceholder"
            show-password
          />
        </el-form-item>

        <el-form-item label="模型">
          <el-select v-model="form.model" style="width: 100%;">
            <el-option
              v-for="m in currentModels"
              :key="m.value"
              :label="m.label"
              :value="m.value"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="API Base URL">
          <el-input v-model="form.base_url" :placeholder="defaultBaseUrl" />
          <el-text type="info" size="small">留空则使用默认地址</el-text>
        </el-form-item>

        <el-form-item label="温度参数">
          <el-slider v-model="form.temperature" :min="0" :max="1" :step="0.1" show-input />
        </el-form-item>

        <el-form-item label="相似度阈值">
          <el-slider v-model="form.kb_similarity_threshold" :min="0.5" :max="1" :step="0.05" show-input />
          <el-text type="info" size="small">
            知识库匹配的最低相似度，值越高匹配越严格
          </el-text>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :loading="saving" @click="saveSettings">
            保存设置
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getApiSettings, saveApiSettings } from '@/api/settings'

const saving = ref(false)
const loading = ref(false)

const providerModels = {
  deepseek: [
    { label: 'DeepSeek Chat (V3)', value: 'deepseek-chat' },
    { label: 'DeepSeek Reasoner (R1)', value: 'deepseek-reasoner' },
  ],
  qwen: [
    { label: 'Qwen Turbo', value: 'qwen-turbo' },
    { label: 'Qwen Plus', value: 'qwen-plus' },
    { label: 'Qwen Max', value: 'qwen-max' },
    { label: 'Qwen Long', value: 'qwen-long' },
  ],
  doubao: [
    { label: '豆包 Seed 1.6', value: 'doubao-seed-1.6' },
    { label: '豆包 Pro 32K', value: 'doubao-pro-32k' },
    { label: '豆包 Lite 32K', value: 'doubao-lite-32k' },
  ],
  openai: [
    { label: 'GPT-4o Mini', value: 'gpt-4o-mini' },
    { label: 'GPT-4o', value: 'gpt-4o' },
    { label: 'GPT-4 Turbo', value: 'gpt-4-turbo' },
    { label: 'GPT-3.5 Turbo', value: 'gpt-3.5-turbo' },
  ],
  gemini: [
    { label: 'Gemini 2.0 Flash', value: 'gemini-2.0-flash' },
    { label: 'Gemini 1.5 Pro', value: 'gemini-1.5-pro' },
    { label: 'Gemini 1.5 Flash', value: 'gemini-1.5-flash' },
  ],
}

const defaultBaseUrls = {
  deepseek: 'https://api.deepseek.com/v1',
  qwen: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  doubao: 'https://ark.cn-beijing.volces.com/api/v3',
  openai: 'https://api.openai.com/v1',
  gemini: 'https://generativelanguage.googleapis.com/v1beta/openai/',
}

// API key fields per provider
const providerKeyField = {
  deepseek: 'deepseek_api_key',
  qwen: 'qwen_api_key',
  doubao: 'doubao_api_key',
  openai: 'openai_api_key',
  gemini: 'gemini_api_key',
}

const form = reactive({
  provider: 'deepseek',
  model: 'deepseek-chat',
  base_url: '',
  temperature: 0.3,
  kb_similarity_threshold: 0.7,
})

// Store all API keys separately
const apiKeys = reactive({
  deepseek_api_key: '',
  qwen_api_key: '',
  doubao_api_key: '',
  openai_api_key: '',
  gemini_api_key: '',
})

const currentApiKey = computed({
  get: () => apiKeys[providerKeyField[form.provider]] || '',
  set: (val) => { apiKeys[providerKeyField[form.provider]] = val },
})

const currentModels = computed(() => providerModels[form.provider] || [])
const defaultBaseUrl = computed(() => defaultBaseUrls[form.provider] || '')
const apiKeyPlaceholder = computed(() => {
  const map = {
    deepseek: 'sk-...',
    qwen: 'sk-...',
    doubao: 'API Key',
    openai: 'sk-...',
    gemini: 'AIza...',
  }
  return map[form.provider] || 'API Key'
})

const onProviderChange = () => {
  const models = providerModels[form.provider]
  if (models && models.length > 0) {
    form.model = models[0].value
  }
  form.base_url = ''
}

const fetchSettings = async () => {
  loading.value = true
  try {
    const res = await getApiSettings()
    if (res.success && res.data) {
      const d = res.data
      if (d.llm_provider) form.provider = d.llm_provider
      if (d.llm_model) form.model = d.llm_model
      if (d.llm_base_url) form.base_url = d.llm_base_url
      if (d.llm_temperature) form.temperature = parseFloat(d.llm_temperature)
      if (d.kb_similarity_threshold) form.kb_similarity_threshold = parseFloat(d.kb_similarity_threshold)
      // Load API keys (may be masked)
      for (const key of Object.keys(apiKeys)) {
        if (d[key]) apiKeys[key] = d[key]
      }
    }
  } catch (e) {
    console.error('Failed to load settings:', e)
  } finally {
    loading.value = false
  }
}

const saveSettings = async () => {
  saving.value = true
  try {
    const payload = {
      llm_provider: form.provider,
      llm_model: form.model,
      llm_base_url: form.base_url,
      llm_temperature: String(form.temperature),
      kb_similarity_threshold: String(form.kb_similarity_threshold),
      ...apiKeys,
    }
    const res = await saveApiSettings(payload)
    if (res.success) {
      ElMessage.success(res.message || '设置已保存')
    }
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  fetchSettings()
})
</script>

<style scoped>
.api-settings {
  padding: 0;
}
</style>
