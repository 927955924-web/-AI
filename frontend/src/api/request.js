import axios from 'axios'
import { useAuthStore } from '@/store/auth'
import { ElMessage } from 'element-plus'
import router from '@/router'

// Create axios instance
const request = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor
request.interceptors.request.use(
  (config) => {
    const authStore = useAuthStore()
    if (authStore.tokens.access) {
      config.headers.Authorization = `Bearer ${authStore.tokens.access}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// Response interceptor
request.interceptors.response.use(
  (response) => {
    return response.data
  },
  async (error) => {
    const authStore = useAuthStore()
    const originalRequest = error.config
    
    // Handle 401 errors
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true
      
      // Try to refresh token
      const refreshed = await authStore.refreshToken()
      if (refreshed) {
        originalRequest.headers.Authorization = `Bearer ${authStore.tokens.access}`
        return request(originalRequest)
      }
      
      // Redirect to login
      router.push({ name: 'Login' })
      return Promise.reject(error)
    }
    
    // Handle other errors
    const message = error.response?.data?.error?.message || 
                   error.response?.data?.detail ||
                   error.message || 
                   '请求失败'
    
    ElMessage.error(message)
    
    return Promise.reject(error)
  }
)

export default request
