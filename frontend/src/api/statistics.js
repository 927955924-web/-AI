import request from './request'

export const statisticsApi = {
  overview() {
    return request.get('/stats/overview/')
  },
  
  aiUsage() {
    return request.get('/stats/ai-usage/')
  },
  
  topQuestions(limit = 10) {
    return request.get('/stats/top-questions/', { params: { limit } })
  },
  
  shop(shopId) {
    return request.get(`/stats/shops/${shopId}/`)
  },
  
  tokenUsage(params = {}) {
    return request.get('/stats/token-usage/', { params })
  },
}
