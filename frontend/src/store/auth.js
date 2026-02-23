import { defineStore } from 'pinia'
import { authApi } from '@/api/auth'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null,
    tokens: {
      access: null,
      refresh: null,
    },
  }),
  
  getters: {
    isAuthenticated: (state) => !!state.tokens.access,
    currentUser: (state) => state.user,
    isVip: (state) => state.user?.vip_status || false,
    isAdmin: (state) => state.user?.role === 'admin',
  },
  
  actions: {
    async login(credentials) {
      try {
        const response = await authApi.login(credentials)
        if (response.success) {
          this.user = response.data.user
          this.tokens = response.data.tokens
          return { success: true }
        }
        return { success: false, message: response.error?.message || '登录失败' }
      } catch (error) {
        return { success: false, message: error.message || '登录失败' }
      }
    },
    
    async register(data) {
      try {
        const response = await authApi.register(data)
        if (response.success) {
          this.user = response.data.user
          this.tokens = response.data.tokens
          return { success: true }
        }
        return { success: false, message: response.error?.message || '注册失败' }
      } catch (error) {
        return { success: false, message: error.message || '注册失败' }
      }
    },
    
    async logout() {
      try {
        await authApi.logout(this.tokens.refresh)
      } catch (e) {
        // Ignore logout errors
      }
      this.user = null
      this.tokens = { access: null, refresh: null }
    },
    
    async refreshToken() {
      if (!this.tokens.refresh) {
        return false
      }
      try {
        const response = await authApi.refresh(this.tokens.refresh)
        if (response.success) {
          this.tokens = response.data.tokens
          return true
        }
      } catch (e) {
        // Token refresh failed
      }
      this.logout()
      return false
    },
    
    async fetchUser() {
      try {
        const response = await authApi.me()
        if (response.success) {
          this.user = response.data
        }
      } catch (e) {
        // Ignore errors
      }
    },
    
    setTokens(tokens) {
      this.tokens = tokens
    },
  },
  
  persist: {
    key: 'auth',
    storage: localStorage,
    paths: ['user', 'tokens'],
  },
})
