import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/store/auth'

// Layout
import AppLayout from '@/components/layout/AppLayout.vue'

// Views
import Login from '@/views/Login.vue'
import Dashboard from '@/views/Dashboard.vue'
import ShopList from '@/views/shops/ShopList.vue'
import ShopDetail from '@/views/shops/ShopDetail.vue'
import ChatList from '@/views/chat/ChatList.vue'
import ChatWindow from '@/views/chat/ChatWindow.vue'
import ProductList from '@/views/products/ProductList.vue'
import KnowledgeList from '@/views/knowledge/KnowledgeList.vue'
import StatsDashboard from '@/views/statistics/StatsDashboard.vue'
import ApiSettings from '@/views/settings/ApiSettings.vue'
import QuickReplies from '@/views/settings/QuickReplies.vue'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: Login,
    meta: { guest: true }
  },
  {
    path: '/',
    component: AppLayout,
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        redirect: '/dashboard'
      },
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: Dashboard,
        meta: { title: '仪表盘' }
      },
      {
        path: 'shops',
        name: 'ShopList',
        component: ShopList,
        meta: { title: '店铺管理' }
      },
      {
        path: 'shops/:id',
        name: 'ShopDetail',
        component: ShopDetail,
        meta: { title: '店铺详情' }
      },
      {
        path: 'chat',
        name: 'ChatList',
        component: ChatList,
        meta: { title: '客服会话' }
      },
      {
        path: 'chat/:sessionId',
        name: 'ChatWindow',
        component: ChatWindow,
        meta: { title: '聊天窗口' }
      },
      {
        path: 'products',
        name: 'ProductList',
        component: ProductList,
        meta: { title: '商品管理' }
      },
      {
        path: 'knowledge',
        name: 'KnowledgeList',
        component: KnowledgeList,
        meta: { title: '知识库' }
      },
      {
        path: 'statistics',
        name: 'StatsDashboard',
        component: StatsDashboard,
        meta: { title: '数据统计' }
      },
      {
        path: 'settings/api',
        name: 'ApiSettings',
        component: ApiSettings,
        meta: { title: 'API设置' }
      },
      {
        path: 'settings/quick-replies',
        name: 'QuickReplies',
        component: QuickReplies,
        meta: { title: '快捷回复' }
      }
    ]
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/dashboard'
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// Navigation guard
router.beforeEach((to, from, next) => {
  const authStore = useAuthStore()
  
  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    next({ name: 'Login', query: { redirect: to.fullPath } })
  } else if (to.meta.guest && authStore.isAuthenticated) {
    next({ name: 'Dashboard' })
  } else {
    next()
  }
})

export default router
