<template>
  <div class="dashboard">
    <div class="page-header">
      <h1 class="page-title">仪表盘</h1>
    </div>
    
    <!-- Statistics Cards -->
    <el-row :gutter="20" class="mb-20">
      <el-col :span="6">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-value">{{ stats.shops }}</div>
          <div class="stat-label">店铺总数</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-value">{{ stats.products }}</div>
          <div class="stat-label">商品总数</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-value">{{ stats.sessions }}</div>
          <div class="stat-label">会话总数</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-value">{{ stats.messages }}</div>
          <div class="stat-label">消息总数</div>
        </el-card>
      </el-col>
    </el-row>
    
    <!-- AI Usage Stats -->
    <el-row :gutter="20" class="mb-20">
      <el-col :span="12">
        <el-card>
          <template #header>
            <span>AI调用统计</span>
          </template>
          <div class="ai-stats">
            <div class="ai-stat-item">
              <span class="label">知识库回复</span>
              <span class="value">{{ aiStats.by_source?.knowledge_base || 0 }}</span>
            </div>
            <div class="ai-stat-item">
              <span class="label">缓存回复</span>
              <span class="value">{{ aiStats.by_source?.cache || 0 }}</span>
            </div>
            <div class="ai-stat-item">
              <span class="label">API调用</span>
              <span class="value">{{ aiStats.by_source?.openai || 0 }}</span>
            </div>
            <div class="ai-stat-item highlight">
              <span class="label">节约率</span>
              <span class="value">{{ aiStats.savings_rate }}%</span>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card>
          <template #header>
            <span>快捷入口</span>
          </template>
          <div class="quick-links">
            <el-button @click="$router.push('/shops')" type="primary" plain>
              <el-icon><Shop /></el-icon>
              店铺管理
            </el-button>
            <el-button @click="$router.push('/chat')" type="success" plain>
              <el-icon><ChatDotRound /></el-icon>
              客服会话
            </el-button>
            <el-button @click="$router.push('/knowledge')" type="warning" plain>
              <el-icon><Reading /></el-icon>
              知识库
            </el-button>
            <el-button @click="$router.push('/settings/quick-replies')" type="info" plain>
              <el-icon><Promotion /></el-icon>
              快捷回复
            </el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>
    
    <!-- Daily Messages Chart -->
    <el-card>
      <template #header>
        <span>近14天消息趋势</span>
      </template>
      <div ref="chartRef" style="height: 300px;"></div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { statisticsApi } from '@/api/statistics'
import * as echarts from 'echarts'

const chartRef = ref()
let chartInstance = null

const stats = reactive({
  shops: 0,
  products: 0,
  sessions: 0,
  messages: 0,
  active_sessions: 0,
})

const aiStats = reactive({
  total_ai_responses: 0,
  by_source: {},
  api_calls_saved: 0,
  savings_rate: 0,
})

const dailyMessages = ref([])

const fetchData = async () => {
  try {
    const [overviewRes, aiRes] = await Promise.all([
      statisticsApi.overview(),
      statisticsApi.aiUsage(),
    ])
    
    if (overviewRes.success) {
      Object.assign(stats, overviewRes.data.totals)
      dailyMessages.value = overviewRes.data.daily_messages
      renderChart()
    }
    
    if (aiRes.success) {
      Object.assign(aiStats, aiRes.data)
    }
  } catch (e) {
    console.error('Failed to fetch dashboard data:', e)
  }
}

const renderChart = () => {
  if (!chartRef.value) return
  
  if (!chartInstance) {
    chartInstance = echarts.init(chartRef.value)
  }
  
  const dates = dailyMessages.value.map(d => d.date)
  const counts = dailyMessages.value.map(d => d.count)
  
  const option = {
    tooltip: {
      trigger: 'axis',
    },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: {
        formatter: (value) => value.slice(5), // MM-DD
      },
    },
    yAxis: {
      type: 'value',
    },
    series: [
      {
        name: '消息数',
        type: 'line',
        data: counts,
        smooth: true,
        areaStyle: {
          opacity: 0.3,
        },
        itemStyle: {
          color: '#409eff',
        },
      },
    ],
  }
  
  chartInstance.setOption(option)
}

onMounted(() => {
  fetchData()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  if (chartInstance) {
    chartInstance.dispose()
  }
})

const handleResize = () => {
  if (chartInstance) {
    chartInstance.resize()
  }
}
</script>

<style scoped>
.dashboard {
  padding: 0;
}

.ai-stats {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 20px;
}

.ai-stat-item {
  display: flex;
  flex-direction: column;
  padding: 15px;
  background: #f5f7fa;
  border-radius: 8px;
}

.ai-stat-item .label {
  font-size: 14px;
  color: #909399;
  margin-bottom: 8px;
}

.ai-stat-item .value {
  font-size: 24px;
  font-weight: 600;
  color: #303133;
}

.ai-stat-item.highlight .value {
  color: #67c23a;
}

.quick-links {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.quick-links .el-button {
  flex: 1;
  min-width: 120px;
}
</style>
