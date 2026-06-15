import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import { setupFetchInterceptor } from './api/client'
import './styles/main.css'

// 全局fetch拦截：自动加Token + 401跳转登录
setupFetchInterceptor()

createApp(App).use(router).mount('#app')
