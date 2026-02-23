<template>
  <div class="stats-dashboard">
    <div class="page-header">
      <h1 class="page-title">数据统计</h1>
      <el-button @click="fetchData">
        <el-icon><Refresh /></el-icon>
        刷新
      </el-button>
    </div>
    
    <!-- Token Usage Stats -->
    <el-card class="mb-20">
      <template #header>Token 使用统计</template>
      <el-row :gutter="20">
        <el-col :span="6">
          <div class="ai-stat-box primary">
            <div class="label">总 Token 数</div>
            <div class="value">{{ formatTokens(tokenStats.total_tokens) }}</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="ai-stat-box warning">
            <div class="label">预估成本</div>
            <div class="value">¥{{ tokenStats.total_cost.toFixed(2) }}</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="ai-stat-box info">
            <div class="label">API 调用次数</div>
            <div class="value">{{ tokenStats.total_requests }}</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="ai-stat-box success">
            <div class="label">主要模型</div>
            <div class="value small">{{ topModelName }}</div>
          </div>
        </el-col>
      </el-row>
    </el-card>
    
    <!-- Token Charts -->
    <el-row :gutter="20" class="mb-20">
      <el-col :span="12">
        <el-card>
          <template #header>Token 使用趋势（近30天）</template>
          <div ref="tokenTrendChartRef" style="height: 300px;"></div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card>
          <template #header>模型 Token 分布</template>
          <div ref="modelPieChartRef" style="height: 300px;"></div>
        </el-card>
      </el-col>
    </el-row>
    
    <!-- AI Usage Stats -->
    <el-card class="mb-20">
      <template #header>AI调用统计 - 节约Credits</template>
      <el-row :gutter="20">
        <el-col :span="6">
          <div class="ai-stat-box">
            <div class="label">总AI响应</div>
            <div class="value">{{ aiStats.total_ai_responses }}</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="ai-stat-box success">
            <div class="label">知识库回复</div>
            <div class="value">{{ aiStats.by_source?.knowledge_base || 0 }}</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="ai-stat-box info">
            <div class="label">缓存回复</div>
            <div class="value">{{ aiStats.by_source?.cache || 0 }}</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="ai-stat-box warning">
            <div class="label">API调用</div>
            <div class="value">{{ aiStats.by_source?.openai || 0 }}</div>
            <div class="model-detail" v-if="aiStats.by_model?.length">
              <span v-for="(m, i) in aiStats.by_model" :key="i" class="model-tag">
                {{ m.model }}: {{ m.count }}
              </span>
            </div>
          </div>
        </el-col>
      </el-row>
      <el-row class="mt-20">
        <el-col :span="24">
          <el-progress
            :percentage="aiStats.savings_rate"
            :stroke-width="20"
            :format="() => `节约率 ${aiStats.savings_rate}%`"
            status="success"
          />
        </el-col>
      </el-row>
    </el-card>
    
    <!-- Charts -->
    <el-row :gutter="20" class="mb-20">
      <el-col :span="12">
        <el-card>
          <template #header>消息趋势（近14天）</template>
          <div ref="messageChartRef" style="height: 300px;"></div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card>
          <template #header>AI来源分布</template>
          <div ref="sourceChartRef" style="height: 300px;"></div>
        </el-card>
      </el-col>
    </el-row>
    
    <!-- Top Questions -->
    <el-card>
      <template #header>高频问题 Top 10</template>
      <el-table :data="topQuestions" stripe>
        <el-table-column type="index" width="60" />
        <el-table-column prop="question" label="问题" show-overflow-tooltip />
        <el-table-column prop="usage_count" label="使用次数" width="100" align="center" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_correct ? 'success' : 'warning'" size="small">
              {{ row.is_correct ? '正确' : '待确认' }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { statisticsApi } from '@/api/statistics'
import * as echarts from 'echarts'

const messageChartRef = ref()
const sourceChartRef = ref()
const tokenTrendChartRef = ref()
const modelPieChartRef = ref()

let messageChart = null
let sourceChart = null
let tokenTrendChart = null
let modelPieChart = null
let refreshTimer = null

const aiStats = reactive({
  total_ai_responses: 0,
  by_source: {},
  by_model: [],
  api_calls_saved: 0,
  savings_rate: 0,
})

const tokenStats = reactive({
  total_tokens: 0,
  total_cost: 0,
  total_requests: 0,
  by_model: [],
  trend: [],
})

const dailyMessages = ref([])
const topQuestions = ref([])

// Computed properties
const topModelName = computed(() => {
  if (tokenStats.by_model.length === 0) return '-'
  const modelNames = {
    deepseek: 'DeepSeek',
    qwen: '通义千问',
    doubao: '豆包',
    openai: 'OpenAI',
    gemini: 'Gemini',
  }
  return modelNames[tokenStats.by_model[0]?.model_name] || tokenStats.by_model[0]?.model_name || '-'
})

// Format tokens (K/M)
const formatTokens = (num) => {
  if (!num) return '0'
  if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M'
  if (num >= 1000) return (num / 1000).toFixed(1) + 'K'
  return num.toString()
}

const fetchData = async () => {
  try {
    const [overviewRes, aiRes, topRes, tokenRes] = await Promise.all([
      statisticsApi.overview(),
      statisticsApi.aiUsage(),
      statisticsApi.topQuestions(10),
      statisticsApi.tokenUsage(),
    ])
    
    if (overviewRes.success) {
      dailyMessages.value = overviewRes.data.daily_messages
      renderMessageChart()
    }
    
    if (aiRes.success) {
      Object.assign(aiStats, aiRes.data)
      renderSourceChart()
    }
    
    if (topRes.success) {
      topQuestions.value = topRes.data
    }
    
    if (tokenRes.success) {
      Object.assign(tokenStats, tokenRes.data)
      renderTokenTrendChart()
      renderModelPieChart()
    }
  } catch (e) {
    console.error('Failed to fetch stats:', e)
  }
}

const renderMessageChart = () => {
  if (!messageChartRef.value) return
  
  if (!messageChart) {
    messageChart = echarts.init(messageChartRef.value)
  }
  
  const dates = dailyMessages.value.map(d => d.date?.slice(5) || '')
  const counts = dailyMessages.value.map(d => d.count)
  
  const option = {
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: dates },
    yAxis: { type: 'value' },
    series: [{
      name: '消息数',
      type: 'bar',
      data: counts,
      itemStyle: { color: '#409eff' },
    }],
  }
  
  messageChart.setOption(option)
}

const renderSourceChart = () => {
  if (!sourceChartRef.value) return
  
  if (!sourceChart) {
    sourceChart = echarts.init(sourceChartRef.value)
  }
  
  const data = [
    { value: aiStats.by_source?.knowledge_base || 0, name: '知识库' },
    { value: aiStats.by_source?.cache || 0, name: '缓存' },
    { value: aiStats.by_source?.openai || 0, name: 'API调用' },
    { value: aiStats.by_source?.template || 0, name: '模板' },
  ].filter(d => d.value > 0)
  
  const option = {
    tooltip: { trigger: 'item' },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      data: data,
      label: {
        formatter: '{b}: {c} ({d}%)',
      },
    }],
  }
  
  sourceChart.setOption(option)
}

const renderTokenTrendChart = () => {
  if (!tokenTrendChartRef.value) return
  
  if (!tokenTrendChart) {
    tokenTrendChart = echarts.init(tokenTrendChartRef.value)
  }
  
  const dates = tokenStats.trend.map(d => d.date?.slice(5) || '')
  const tokens = tokenStats.trend.map(d => d.total_tokens)
  const costs = tokenStats.trend.map(d => d.cost_estimate)
  
  const option = {
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const date = params[0].axisValue
        let html = `${date}<br/>`
        params.forEach(p => {
          const value = p.seriesName === '成本' ? `¥${p.value.toFixed(4)}` : formatTokens(p.value)
          html += `${p.marker} ${p.seriesName}: ${value}<br/>`
        })
        return html
      }
    },
    legend: { data: ['Token数', '成本'], bottom: 0 },
    xAxis: { type: 'category', data: dates },
    yAxis: [
      { type: 'value', name: 'Token', position: 'left' },
      { type: 'value', name: '成本(¥)', position: 'right' }
    ],
    series: [
      {
        name: 'Token数',
        type: 'line',
        smooth: true,
        data: tokens,
        itemStyle: { color: '#409eff' },
        areaStyle: { color: 'rgba(64, 158, 255, 0.1)' }
      },
      {
        name: '成本',
        type: 'line',
        smooth: true,
        yAxisIndex: 1,
        data: costs,
        itemStyle: { color: '#e6a23c' },
      }
    ],
  }
  
  tokenTrendChart.setOption(option)
}

const renderModelPieChart = () => {
  if (!modelPieChartRef.value) return
  
  if (!modelPieChart) {
    modelPieChart = echarts.init(modelPieChartRef.value)
  }
  
  const modelNames = {
    deepseek: 'DeepSeek',
    qwen: '通义千问',
    doubao: '豆包',
    openai: 'OpenAI',
    gemini: 'Gemini',
  }
  
  const colors = {
    deepseek: '#409eff',
    qwen: '#67c23a',
    doubao: '#e6a23c',
    openai: '#f56c6c',
    gemini: '#909399',
  }
  
  const data = tokenStats.by_model.map(m => ({
    value: m.total_tokens,
    name: modelNames[m.model_name] || m.model_name,
    itemStyle: { color: colors[m.model_name] || '#909399' }
  })).filter(d => d.value > 0)
  
  const option = {
    tooltip: {
      trigger: 'item',
      formatter: (params) => {
        return `${params.name}<br/>
          Token: ${formatTokens(params.value)}<br/>
          占比: ${params.percent.toFixed(1)}%`
      }
    },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      data: data,
      label: {
        formatter: '{b}: {d}%',
      },
    }],
  }
  
  modelPieChart.setOption(option)
}

const handleResize = () => {
  messageChart?.resize()
  sourceChart?.resize()
  tokenTrendChart?.resize()
  modelPieChart?.resize()
}

onMounted(() => {
  fetchData()
  window.addEventListener('resize', handleResize)
  // Auto refresh every 5 seconds
  refreshTimer = setInterval(() => {
    fetchData()
  }, 5000)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  // Clear auto refresh timer
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
  messageChart?.dispose()
  sourceChart?.dispose()
  tokenTrendChart?.dispose()
  modelPieChart?.dispose()
})
</script>

<style scoped>
.stats-dashboard {
  padding: 0;
}

.ai-stat-box {
  text-align: center;
  padding: 20px;
  background: #f5f7fa;
  border-radius: 8px;
}

.ai-stat-box.success {
  background: #f0f9eb;
}

.ai-stat-box.info {
  background: #ecf5ff;
}

.ai-stat-box.warning {
  background: #fdf6ec;
}

.ai-stat-box.primary {
  background: #ecf5ff;
}

.ai-stat-box .label {
  font-size: 14px;
  color: #606266;
  margin-bottom: 8px;
}

.ai-stat-box .value {
  font-size: 28px;
  font-weight: 600;
  color: #303133;
}

.ai-stat-box .value.small {
  font-size: 20px;
}

.ai-stat-box .model-detail {
  margin-top: 8px;
  font-size: 12px;
}

.ai-stat-box .model-tag {
  display: inline-block;
  background: rgba(230, 162, 60, 0.2);
  color: #e6a23c;
  padding: 2px 8px;
  border-radius: 4px;
  margin: 2px;
}
</style>
