<template>
  <div class="stats-dashboard">
    <div class="page-header">
      <h1 class="page-title">数据统计</h1>
      <el-button @click="fetchData">
        <el-icon><Refresh /></el-icon>
        刷新
      </el-button>
    </div>
    
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
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { statisticsApi } from '@/api/statistics'
import * as echarts from 'echarts'

const messageChartRef = ref()
const sourceChartRef = ref()
let messageChart = null
let sourceChart = null

const aiStats = reactive({
  total_ai_responses: 0,
  by_source: {},
  api_calls_saved: 0,
  savings_rate: 0,
})

const dailyMessages = ref([])
const topQuestions = ref([])

const fetchData = async () => {
  try {
    const [overviewRes, aiRes, topRes] = await Promise.all([
      statisticsApi.overview(),
      statisticsApi.aiUsage(),
      statisticsApi.topQuestions(10),
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

const handleResize = () => {
  messageChart?.resize()
  sourceChart?.resize()
}

onMounted(() => {
  fetchData()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  messageChart?.dispose()
  sourceChart?.dispose()
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
</style>
