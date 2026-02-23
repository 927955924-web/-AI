/**
 * API Service for backend communication
 */
const axios = require('axios');

class ApiService {
  constructor(baseUrl = 'http://localhost:8000') {
    this.baseUrl = baseUrl;
    this.tokens = null;
    this.client = axios.create({
      baseURL: `${baseUrl}/api/v1`,
      timeout: 30000,
      headers: {
        'Content-Type': 'application/json'
      }
    });

    // Response interceptor for token refresh
    this.client.interceptors.response.use(
      response => response,
      async error => {
        if (error.response?.status === 401 && this.tokens?.refresh) {
          try {
            const refreshed = await this.refreshToken();
            if (refreshed) {
              // Retry original request
              error.config.headers['Authorization'] = `Bearer ${this.tokens.access}`;
              return this.client.request(error.config);
            }
          } catch (e) {
            // Refresh failed
          }
        }
        return Promise.reject(error);
      }
    );
  }

  setTokens(tokens) {
    this.tokens = tokens;
    if (tokens?.access) {
      this.client.defaults.headers.common['Authorization'] = `Bearer ${tokens.access}`;
    }
  }

  onTokenRefreshed(callback) {
    this._onTokenRefreshed = callback;
  }

  async login(username, password) {
    try {
      const response = await this.client.post('/auth/login/', {
        username,
        password
      });
      return response.data;
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.message
      };
    }
  }

  async refreshToken() {
    if (!this.tokens?.refresh) return false;
    
    try {
      const response = await this.client.post('/auth/refresh/', {
        refresh: this.tokens.refresh
      });
      if (response.data.success) {
        this.tokens = response.data.data.tokens;
        this.setTokens(this.tokens);
        if (this._onTokenRefreshed) this._onTokenRefreshed(this.tokens);
        return true;
      }
    } catch (error) {
      this.tokens = null;
    }
    return false;
  }

  async generateReply(data) {
    try {
      const response = await this.client.post('/ai/generate-reply/', {
        question: data.question,
        context: data.context,
        shop_id: data.shop_id,
        order_detail: data.order_detail,
        model: data.model,
        product_names: data.product_names || [],
        product_card_ids: data.product_card_ids || [],
        buyer_images: data.buyer_images || [],
        buyer_video_frames: data.buyer_video_frames || []
      });
      return response.data;
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.message
      };
    }
  }

  async syncMessage(data) {
    try {
      const response = await this.client.post('/client/sync-message/', data);
      return response.data;
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.message
      };
    }
  }

  async heartbeat(clientId) {
    try {
      const response = await this.client.post('/client/heartbeat/', {
        client_id: clientId
      });
      return response.data;
    } catch (error) {
      return { success: false };
    }
  }

  async getShops() {
    try {
      const response = await this.client.get('/shops/');
      // Backend returns { success: true, data: [...] }
      const shops = response.data.data || response.data.results || response.data;
      return {
        success: true,
        data: Array.isArray(shops) ? shops : []
      };
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.message
      };
    }
  }

  async getKnowledgeBase(shopId = null) {
    try {
      const params = shopId ? { shop: shopId } : {};
      const response = await this.client.get('/knowledge/', { params });
      return {
        success: true,
        data: response.data.results || response.data
      };
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.message
      };
    }
  }

  /**
   * Search knowledge base for similar questions
   */
  async searchKnowledge(question, shopId) {
    try {
      const response = await this.client.post('/knowledge/search/', {
        question,
        shop: shopId
      });
      return {
        success: true,
        data: response.data.data || response.data.results || response.data
      };
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.message
      };
    }
  }

  /**
   * Create a new knowledge base entry
   */
  async createKnowledge(data) {
    try {
      const response = await this.client.post('/knowledge/', {
        shop: data.shop_id,
        question: data.question,
        answer: data.answer,
        category: data.category || 'general'
      });
      return {
        success: true,
        data: response.data.data || response.data
      };
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.response?.data?.detail || error.message
      };
    }
  }

  async updateKnowledge(id, data) {
    try {
      const response = await this.client.patch(`/knowledge/${id}/`, data);
      return {
        success: true,
        data: response.data.data || response.data
      };
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.response?.data?.detail || error.message
      };
    }
  }

  async deleteKnowledge(id) {
    try {
      await this.client.delete(`/knowledge/${id}/`);
      return { success: true };
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.response?.data?.detail || error.message
      };
    }
  }

  async getQuickReplies() {
    try {
      const response = await this.client.get('/quick-replies/');
      return {
        success: true,
        data: response.data.results || response.data
      };
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.message
      };
    }
  }

  // ============ Shop CRUD Methods ============

  async createShop(shopData) {
    try {
      const response = await this.client.post('/shops/', shopData);
      return response.data;
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.response?.data?.detail || error.message
      };
    }
  }

  async updateShop(shopId, shopData) {
    try {
      const response = await this.client.patch(`/shops/${shopId}/`, shopData);
      return response.data;
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.response?.data?.detail || error.message
      };
    }
  }

  async deleteShop(shopId) {
    try {
      const response = await this.client.delete(`/shops/${shopId}/`);
      return { success: true };
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.response?.data?.detail || error.message
      };
    }
  }

  async startShop(shopId) {
    try {
      const response = await this.client.post(`/shops/${shopId}/start/`);
      return response.data;
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.response?.data?.detail || error.message
      };
    }
  }

  async stopShop(shopId) {
    try {
      const response = await this.client.post(`/shops/${shopId}/stop/`);
      return response.data;
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.response?.data?.detail || error.message
      };
    }
  }

  /**
   * Reset all running shops to stopped status.
   * Called on app startup since no BrowserViews are active.
   */
  async resetAllShopStatuses() {
    try {
      const result = await this.getShops();
      if (!result.success || !Array.isArray(result.data)) return;

      for (const shop of result.data) {
        if (shop.status === 'running') {
          await this.stopShop(shop.shop_id);
          console.log(`[API] Reset shop "${shop.shop_name}" status from running to stopped`);
        }
      }
    } catch (error) {
      console.error('[API] Failed to reset shop statuses:', error.message);
    }
  }

  // ============ Learning API Methods ============

  async startLearningTask(shopId, platform) {
    try {
      const response = await this.client.post('/learning/start/', {
        shop_id: shopId,
        platform: platform
      });
      return response.data;
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.message
      };
    }
  }

  async getLearningTaskStatus(taskId) {
    try {
      const response = await this.client.get(`/learning/status/${taskId}/`);
      return response.data;
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.message
      };
    }
  }

  async updateLearningTaskProgress(taskId, totalProducts) {
    try {
      const response = await this.client.post(`/learning/progress/${taskId}/`, {
        total_products: totalProducts
      });
      return response.data;
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.message
      };
    }
  }

  async processProduct(taskId, productData) {
    try {
      const response = await this.client.post('/learning/process-product/', {
        task_id: taskId,
        ...productData
      });
      return response.data;
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.message
      };
    }
  }

  async completeLearningTask(taskId) {
    try {
      const response = await this.client.post(`/learning/complete/${taskId}/`);
      return response.data;
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.message
      };
    }
  }

  async resetAllLearningTasks() {
    try {
      const response = await this.client.post('/learning/reset-all/');
      return response.data;
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.message
      };
    }
  }

  // ============ Products API ============

  async getProducts(shopId) {
    try {
      const response = await this.client.get('/products/', {
        params: { shop: shopId }
      });
      return response.data;
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.message
      };
    }
  }

  async getProductDetail(productId) {
    try {
      const response = await this.client.get(`/products/${productId}/`);
      return response.data;
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.message
      };
    }
  }

  async deleteProduct(productId) {
    try {
      const response = await this.client.delete(`/products/${productId}/`);
      return response.data || { success: true };
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.message
      };
    }
  }

  async getKnowledgeByProduct(productId) {
    try {
      const response = await this.client.get('/knowledge/', {
        params: { product: productId }
      });
      return response.data;
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.message
      };
    }
  }

  // ============ AI Vision Learning API ============

  /**
   * Analyze page screenshot using vision model for product learning
   */
  async visionAnalyzePage(data) {
    try {
      const response = await this.client.post('/ai/vision-analyze-page/', {
        image_base64: data.image_base64,
        page_type: data.page_type || 'product_detail',
        extract_mode: data.extract_mode || 'full'
      }, {
        timeout: 120000  // Vision API needs more time for full page analysis
      });
      return response.data;
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.message
      };
    }
  }

  /**
   * Analyze page screenshot using vision language model
   */
  async visionAnalyze(data) {
    try {
      const response = await this.client.post('/ai/vision-analyze/', {
        image_base64: data.image_base64,
        page_type: data.page_type || 'list',
        session_id: data.session_id,
        model: data.model || 'qwen-vl-plus',
        shop_id: data.shop_id
      }, {
        timeout: 60000  // Vision API may take longer
      });
      return response.data;
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.message
      };
    }
  }

  /**
   * Process extracted product data and save to knowledge base
   */
  async visionExtract(data) {
    try {
      const response = await this.client.post('/ai/vision-extract/', {
        extraction_data: data.extraction_data,
        session_id: data.session_id,
        shop_id: data.shop_id,
        save_to_kb: data.save_to_kb !== false
      });
      return response.data;
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.message
      };
    }
  }

  /**
   * Get vision learning session status
   */
  async visionSessionStatus(sessionId) {
    try {
      const response = await this.client.get('/ai/vision-session/', {
        params: { session_id: sessionId }
      });
      return response.data;
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.message
      };
    }
  }

  /**
   * End vision learning session
   */
  async visionSessionEnd(sessionId) {
    try {
      const response = await this.client.delete('/ai/vision-session/', {
        params: { session_id: sessionId }
      });
      return response.data;
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.message
      };
    }
  }

  // ============ Conversation Recording & Training Data API ============

  /**
   * Save a conversation record for future local model training
   */
  async saveConversation(data) {
    try {
      const response = await this.client.post('/ai/save-conversation/', {
        buyer_message: data.buyer_message,
        customer_reply: data.customer_reply,
        conversation_context: data.conversation_context || '',
        buyer_name: data.buyer_name || '',
        image_analysis: data.image_analysis || '',
        order_info: data.order_info || '',
        shop_id: data.shop_id || '',
        platform: data.platform || '',
        source: data.source || 'ai_auto',
        model_used: data.model_used || '',
        confidence: data.confidence || 0,
      });
      return response.data;
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.message
      };
    }
  }

  /**
   * Save learning records (batch or single) for future model training
   */
  async saveLearningRecords(records) {
    try {
      const response = await this.client.post('/ai/save-learning-record/', {
        records: records,
      });
      return response.data;
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.message
      };
    }
  }

  /**
   * Export training data in specified format
   */
  async exportTrainingData(options = {}) {
    try {
      const response = await this.client.post('/ai/training-export/', {
        shop_id: options.shop_id || '',
        format: options.format || 'alpaca',
        quality_filter: options.quality_filter || 'all',
        include_learning: options.include_learning !== false,
        include_conversations: options.include_conversations !== false,
      });
      return response.data;
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.message
      };
    }
  }

  /**
   * Get training data statistics
   */
  async getTrainingStats(shopId) {
    try {
      const params = shopId ? { shop_id: shopId } : {};
      const response = await this.client.get('/ai/training-stats/', { params });
      return response.data;
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.message
      };
    }
  }

  // ============ Keyword Rules API ============

  async getKeywordRules(shopId) {
    try {
      const params = shopId ? { shop_id: shopId } : {};
      const response = await this.client.get('/ai/keyword-rules/', { params });
      return { success: true, data: response.data.results || response.data };
    } catch (error) {
      return { success: false, error: error.response?.data?.detail || error.message };
    }
  }

  async createKeywordRule(data) {
    try {
      const response = await this.client.post('/ai/keyword-rules/', data);
      return { success: true, data: response.data };
    } catch (error) {
      return { success: false, error: error.response?.data?.detail || error.message };
    }
  }

  async updateKeywordRule(ruleId, data) {
    try {
      const response = await this.client.patch(`/ai/keyword-rules/${ruleId}/`, data);
      return { success: true, data: response.data };
    } catch (error) {
      return { success: false, error: error.response?.data?.detail || error.message };
    }
  }

  async deleteKeywordRule(ruleId) {
    try {
      await this.client.delete(`/ai/keyword-rules/${ruleId}/`);
      return { success: true };
    } catch (error) {
      return { success: false, error: error.response?.data?.detail || error.message };
    }
  }

  // ============ Sensitive Word Rules API ============

  async getSensitiveWordRules(shopId) {
    try {
      const params = shopId ? { shop_id: shopId } : {};
      const response = await this.client.get('/ai/sensitive-words/', { params });
      return { success: true, data: response.data.results || response.data };
    } catch (error) {
      return { success: false, error: error.response?.data?.detail || error.message };
    }
  }

  async createSensitiveWordRule(data) {
    try {
      const response = await this.client.post('/ai/sensitive-words/', data);
      return { success: true, data: response.data };
    } catch (error) {
      return { success: false, error: error.response?.data?.detail || error.message };
    }
  }

  async updateSensitiveWordRule(ruleId, data) {
    try {
      const response = await this.client.patch(`/ai/sensitive-words/${ruleId}/`, data);
      return { success: true, data: response.data };
    } catch (error) {
      return { success: false, error: error.response?.data?.detail || error.message };
    }
  }

  async deleteSensitiveWordRule(ruleId) {
    try {
      await this.client.delete(`/ai/sensitive-words/${ruleId}/`);
      return { success: true };
    } catch (error) {
      return { success: false, error: error.response?.data?.detail || error.message };
    }
  }

  // ============ Scenario Rules API ============

  async getScenarioRules(shopId) {
    try {
      const params = shopId ? { shop_id: shopId } : {};
      const response = await this.client.get('/ai/scenario-rules/', { params });
      return { success: true, data: response.data.results || response.data };
    } catch (error) {
      return { success: false, error: error.response?.data?.detail || error.message };
    }
  }

  async createScenarioRule(data) {
    try {
      const response = await this.client.post('/ai/scenario-rules/', data);
      return { success: true, data: response.data };
    } catch (error) {
      return { success: false, error: error.response?.data?.detail || error.message };
    }
  }

  async updateScenarioRule(ruleId, data) {
    try {
      const response = await this.client.patch(`/ai/scenario-rules/${ruleId}/`, data);
      return { success: true, data: response.data };
    } catch (error) {
      return { success: false, error: error.response?.data?.detail || error.message };
    }
  }

  async deleteScenarioRule(ruleId) {
    try {
      await this.client.delete(`/ai/scenario-rules/${ruleId}/`);
      return { success: true };
    } catch (error) {
      return { success: false, error: error.response?.data?.detail || error.message };
    }
  }

  // ============ API Settings Management ============

  async getApiSettings() {
    try {
      const response = await this.client.get('/auth/api-settings/');
      return response.data;
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.response?.data?.detail || error.message
      };
    }
  }

  async saveApiSettings(data) {
    try {
      const response = await this.client.put('/auth/api-settings/', data);
      return response.data;
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.error?.message || error.response?.data?.detail || error.message
      };
    }
  }
}

module.exports = { ApiService };
