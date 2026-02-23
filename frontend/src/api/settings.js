import request from './request'

// Get API settings (LLM provider, model, keys, etc.)
export function getApiSettings() {
  return request.get('/auth/api-settings/')
}

// Save API settings
export function saveApiSettings(data) {
  return request.put('/auth/api-settings/', data)
}
