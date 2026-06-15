import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import { setupFetchInterceptor } from './api/client'
import { isAuthenticated, isPublicPage, loadAuthFromStorage, redirectToLogin } from './api/auth'
import './styles/main.css'

// 全局 fetch 拦截：无 token 不发受保护 API；401 强制登录
setupFetchInterceptor()

// 启动时同步校验，防止残留用户信息造成假登录态
loadAuthFromStorage()
if (!isPublicPage() && !isAuthenticated()) {
  redirectToLogin()
}

createApp(App).use(router).mount('#app')
