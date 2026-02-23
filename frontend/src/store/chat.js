import { defineStore } from 'pinia'
import { chatApi, messagesApi } from '@/api/chat'

export const useChatStore = defineStore('chat', {
  state: () => ({
    sessions: [],
    currentSession: null,
    messages: [],
    loading: false,
  }),
  
  getters: {
    activeSessions: (state) => state.sessions.filter(s => s.status === 'active'),
    totalUnread: (state) => state.sessions.reduce((sum, s) => sum + (s.unread_count || 0), 0),
  },
  
  actions: {
    async fetchSessions(params = {}) {
      this.loading = true
      try {
        const response = await chatApi.list(params)
        if (response.success) {
          this.sessions = response.data
        }
      } finally {
        this.loading = false
      }
    },
    
    async fetchSession(sessionId) {
      try {
        const response = await chatApi.get(sessionId)
        if (response.success) {
          this.currentSession = response.data
          return response.data
        }
      } catch (e) {
        return null
      }
    },
    
    async createSession(data) {
      const response = await chatApi.create(data)
      if (response.success) {
        this.sessions.unshift(response.data)
        this.currentSession = response.data
      }
      return response
    },
    
    async closeSession(sessionId) {
      const response = await chatApi.close(sessionId)
      if (response.success) {
        const index = this.sessions.findIndex(s => s.session_id === sessionId)
        if (index !== -1) {
          this.sessions[index] = response.data
        }
      }
      return response
    },
    
    async fetchMessages(sessionId, params = {}) {
      try {
        const response = await messagesApi.list({ session: sessionId, ...params })
        if (response.success) {
          this.messages = response.data
        }
      } catch (e) {
        this.messages = []
      }
    },
    
    async sendMessage(data) {
      const response = await messagesApi.create(data)
      if (response.success) {
        this.messages.push(response.data)
        // Update session last message
        if (this.currentSession) {
          this.currentSession.last_message = data.content
          this.currentSession.message_count++
        }
      }
      return response
    },
    
    async markRead(sessionId) {
      await chatApi.markRead(sessionId)
      const index = this.sessions.findIndex(s => s.session_id === sessionId)
      if (index !== -1) {
        this.sessions[index].unread_count = 0
      }
    },
    
    addMessage(message) {
      this.messages.push(message)
    },
    
    clearMessages() {
      this.messages = []
      this.currentSession = null
    },
  },
})
