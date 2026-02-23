import request from './request'

export const knowledgeApi = {
  list(params = {}) {
    return request.get('/knowledge/', { params })
  },
  
  get(id) {
    return request.get(`/knowledge/${id}/`)
  },
  
  create(data) {
    return request.post('/knowledge/', data)
  },
  
  update(id, data) {
    return request.patch(`/knowledge/${id}/`, data)
  },
  
  delete(id) {
    return request.delete(`/knowledge/${id}/`)
  },
  
  search(data) {
    return request.post('/knowledge/search/', data)
  },
  
  markCorrect(id) {
    return request.post(`/knowledge/${id}/mark_correct/`)
  },
  
  markIncorrect(id) {
    return request.post(`/knowledge/${id}/mark_incorrect/`)
  },
  
  summary() {
    return request.get('/knowledge/summary/')
  },
}
