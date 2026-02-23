import request from './request'

export const chatApi = {
  list(params = {}) {
    return request.get('/sessions/', { params })
  },
  
  get(sessionId) {
    return request.get(`/sessions/${sessionId}/`)
  },
  
  create(data) {
    return request.post('/sessions/', data)
  },
  
  close(sessionId) {
    return request.post(`/sessions/${sessionId}/close/`)
  },
  
  archive(sessionId) {
    return request.post(`/sessions/${sessionId}/archive/`)
  },
  
  reopen(sessionId) {
    return request.post(`/sessions/${sessionId}/reopen/`)
  },
  
  markRead(sessionId) {
    return request.post(`/sessions/${sessionId}/mark_read/`)
  },
}

export const messagesApi = {
  list(params = {}) {
    return request.get('/sessions/messages/', { params })
  },
  
  create(data) {
    return request.post('/sessions/messages/', data)
  },
  
  get(messageId) {
    return request.get(`/sessions/messages/${messageId}/`)
  },
}
