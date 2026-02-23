import request from './request'

export const quickRepliesApi = {
  list(params = {}) {
    return request.get('/quick-replies/', { params })
  },
  
  get(id) {
    return request.get(`/quick-replies/${id}/`)
  },
  
  create(data) {
    return request.post('/quick-replies/', data)
  },
  
  update(id, data) {
    return request.patch(`/quick-replies/${id}/`, data)
  },
  
  delete(id) {
    return request.delete(`/quick-replies/${id}/`)
  },
  
  render(id, context = {}) {
    return request.post(`/quick-replies/${id}/render/`, { context })
  },
  
  categories() {
    return request.get('/quick-replies/categories/')
  },
  
  byShortcut(shortcut) {
    return request.get('/quick-replies/by_shortcut/', { params: { shortcut } })
  },
}
