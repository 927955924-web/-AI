import request from './request'

export const shopsApi = {
  list(params = {}) {
    return request.get('/shops/', { params })
  },
  
  get(shopId) {
    return request.get(`/shops/${shopId}/`)
  },
  
  create(data) {
    return request.post('/shops/', data)
  },
  
  update(shopId, data) {
    return request.patch(`/shops/${shopId}/`, data)
  },
  
  delete(shopId) {
    return request.delete(`/shops/${shopId}/`)
  },
  
  start(shopId) {
    return request.post(`/shops/${shopId}/start/`)
  },
  
  stop(shopId) {
    return request.post(`/shops/${shopId}/stop/`)
  },
  
  platforms() {
    return request.get('/shops/platforms/')
  },
}
