import { defineStore } from 'pinia'
import { shopsApi } from '@/api/shops'

export const useShopsStore = defineStore('shops', {
  state: () => ({
    shops: [],
    currentShop: null,
    loading: false,
    platforms: [],
  }),
  
  getters: {
    activeShops: (state) => state.shops.filter(s => s.is_active),
    runningShops: (state) => state.shops.filter(s => s.status === 'running'),
  },
  
  actions: {
    async fetchShops(params = {}) {
      this.loading = true
      try {
        const response = await shopsApi.list(params)
        if (response.success) {
          this.shops = response.data
        }
      } finally {
        this.loading = false
      }
    },
    
    async fetchShop(shopId) {
      try {
        const response = await shopsApi.get(shopId)
        if (response.success) {
          this.currentShop = response.data
          return response.data
        }
      } catch (e) {
        return null
      }
    },
    
    async createShop(data) {
      const response = await shopsApi.create(data)
      if (response.success) {
        this.shops.unshift(response.data)
      }
      return response
    },
    
    async updateShop(shopId, data) {
      const response = await shopsApi.update(shopId, data)
      if (response.success) {
        const index = this.shops.findIndex(s => s.shop_id === shopId)
        if (index !== -1) {
          this.shops[index] = response.data
        }
        if (this.currentShop?.shop_id === shopId) {
          this.currentShop = response.data
        }
      }
      return response
    },
    
    async deleteShop(shopId) {
      const response = await shopsApi.delete(shopId)
      if (response.success) {
        this.shops = this.shops.filter(s => s.shop_id !== shopId)
      }
      return response
    },
    
    async startShop(shopId) {
      const response = await shopsApi.start(shopId)
      if (response.success) {
        const index = this.shops.findIndex(s => s.shop_id === shopId)
        if (index !== -1) {
          this.shops[index] = response.data
        }
      }
      return response
    },
    
    async stopShop(shopId) {
      const response = await shopsApi.stop(shopId)
      if (response.success) {
        const index = this.shops.findIndex(s => s.shop_id === shopId)
        if (index !== -1) {
          this.shops[index] = response.data
        }
      }
      return response
    },
    
    async fetchPlatforms() {
      const response = await shopsApi.platforms()
      if (response.success) {
        this.platforms = response.data
      }
    },
  },
})
