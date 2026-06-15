import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  { path: '/login', name: 'login', component: () => import('../views/LoginView.vue'), meta: { public: true } },
  { path: '/', redirect: '/chat' },
  { path: '/chat', name: 'chat', component: () => import('../views/MainShell.vue'), meta: { permission: 'chat:view' } },
  { path: '/knowledge', name: 'knowledge', component: () => import('../views/MainShell.vue'), meta: { permission: 'kb:view' } },
  { path: '/multimodal', name: 'multimodal', component: () => import('../views/MainShell.vue'), meta: { permission: 'kb:view' } },
  { path: '/structured', name: 'structured', component: () => import('../views/MainShell.vue'), meta: { permission: 'kb:view' } },
  { path: '/sessions', name: 'sessions', component: () => import('../views/MainShell.vue'), meta: { permission: 'session:view' } },
  { path: '/profile', name: 'profile', component: () => import('../views/MainShell.vue'), meta: { permission: 'profile:view' } },
  { path: '/profile/feedback', name: 'profile-feedback', component: () => import('../views/MainShell.vue'), meta: { permission: 'profile:feedback:view' } },
  { path: '/admin/logs/operation', name: 'log-operation', component: () => import('../views/MainShell.vue'), meta: { permission: 'system:log:operation' } },
  { path: '/admin/logs/error', name: 'log-error', component: () => import('../views/MainShell.vue'), meta: { permission: 'system:log:error' } },
  { path: '/admin/logs/api-call', name: 'log-api', component: () => import('../views/MainShell.vue'), meta: { permission: 'system:log:api' } },
  { path: '/admin/logs/schedule', name: 'log-schedule', component: () => import('../views/MainShell.vue'), meta: { permission: 'system:log:schedule' } },
  { path: '/admin/eval', name: 'admin-eval', component: () => import('../views/MainShell.vue'), meta: { permission: 'system:eval:view' } },
  { path: '/admin/agent-config', name: 'admin-agent-config', component: () => import('../views/MainShell.vue'), meta: { permission: 'system:agent:config' } },
  { path: '/admin/agent-gateway', name: 'admin-agent-gateway', component: () => import('../views/MainShell.vue'), meta: { permission: 'system:agent:gateway' } },
  { path: '/admin/gateway-security', name: 'admin-gateway-security', component: () => import('../views/MainShell.vue'), meta: { permission: 'system:agent:security' } },
  { path: '/admin/gateway-cache', name: 'admin-gateway-cache', component: () => import('../views/MainShell.vue'), meta: { permission: 'system:agent:cache' } },
  { path: '/admin/gateway-circuit', name: 'admin-gateway-circuit', component: () => import('../views/MainShell.vue'), meta: { permission: 'system:agent:circuit' } },
  { path: '/admin/rbac', name: 'admin-rbac', component: () => import('../views/MainShell.vue'), meta: { permission: 'system:rbac:users' } },
  { path: '/admin/feedback', name: 'admin-feedback', component: () => import('../views/MainShell.vue'), meta: { permission: 'system:feedback:view' } },
  { path: '/admin/users', name: 'admin-users', component: () => import('../views/MainShell.vue'), meta: { permission: 'system:rbac:users' } },
  { path: '/403', name: 'forbidden', component: () => import('../views/ForbiddenView.vue'), meta: { public: true } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

function getToken(): string {
  return localStorage.getItem('hc_access_token') || ''
}

function getUser(): { permissions?: string[]; roles?: string[] } | null {
  const raw = localStorage.getItem('hc_user')
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

router.beforeEach((to) => {
  if (to.meta.public) return true
  if (!getToken()) return { path: '/login', query: { redirect: to.fullPath } }
  const perm = to.meta.permission as string | undefined
  if (!perm) return true
  const user = getUser()
  const perms = user?.permissions || []
  const roles = user?.roles || []
  if (roles.includes('admin') || perms.includes(perm)) return true
  return { path: '/403' }
})

export default router
