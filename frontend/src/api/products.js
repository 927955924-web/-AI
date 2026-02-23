import request from './request'

export const productsApi = {
  list(params = {}) {
    return request.get('/products/', { params })
  },
  
  get(productId) {
    return request.get(`/products/${productId}/`)
  },
  
  create(data) {
    return request.post('/products/', data)
  },
  
  update(productId, data) {
    return request.patch(`/products/${productId}/`, data)
  },
  
  delete(productId) {
    return request.delete(`/products/${productId}/`)
  },
  
  importCsv(shopId, file) {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('shop', shopId)
    return request.post('/products/import_csv/', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  
  exportCsv(params = {}) {
    return request.get('/products/export_csv/', { 
      params,
      responseType: 'blob',
    })
  },
}
