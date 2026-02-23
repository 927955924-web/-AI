import request from './request'

export const aiApi = {
  generateReply(data) {
    return request.post('/ai/generate-reply/', data)
  },
  
  identifyIntent(message) {
    return request.post('/ai/identify-intent/', { message })
  },
}
