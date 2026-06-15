export {
  authHeaders,
  clearAuth,
  currentUser,
  getAccessToken,
  getRefreshToken,
  hasPerm,
  loadAuthFromStorage,
  refreshAccessToken,
  setAuth,
} from './auth'

export function getToken(): string {
  return localStorage.getItem('hc_access_token') || ''
}

export function setToken(token: string): void {
  localStorage.setItem('hc_access_token', token)
}

/** 带401拦截的API请求 — 未登录自动跳转登录页 */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const { authHeaders, getRefreshToken, refreshAccessToken, clearAuth } = await import('./auth')
  const headers = { ...authHeaders(), ...(init.headers as Record<string, string> | undefined) }
  let res = await fetch(path, { ...init, headers })

  // 401 → 尝试刷新token
  if (res.status === 401 && getRefreshToken()) {
    const ok = await refreshAccessToken()
    if (ok) {
      res = await fetch(path, { ...init, headers: { ...authHeaders(), ...(init.headers as Record<string, string> | undefined) } })
    } else {
      clearAuth()
      // 跳转登录页
      const currentPath = window.location.pathname
      if (currentPath !== '/login') {
        window.location.href = '/login?redirect=' + encodeURIComponent(currentPath)
      }
    }
  }

  // 二次401 → 强制登录
  if (res.status === 401) {
    clearAuth()
    const cp = window.location.pathname
    if (cp !== '/login') {
      window.location.href = '/login?redirect=' + encodeURIComponent(cp)
    }
  }

  return res
}

/** 全局fetch拦截器：自动给所有API请求加token，未登录跳转 */
export function setupFetchInterceptor(): void {
  const originalFetch = window.fetch
  window.fetch = async function (...args: Parameters<typeof fetch>) {
    const [input, init] = args
    const url = typeof input === 'string' ? input : input.url

    // 只拦截API请求
    if (!url.includes('/api/')) {
      return originalFetch(...args)
    }

    const token = getToken()
    const headers = new Headers(init?.headers)
    if (token && !headers.has('Authorization')) {
      headers.set('Authorization', `Bearer ${token}`)
    }
    if (!headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json')
    }

    const res = await originalFetch(input, { ...init, headers })

    // 401 → 尝试刷新
    if (res.status === 401) {
      const rt = localStorage.getItem('hc_refresh_token')
      if (rt) {
        const { refreshAccessToken, clearAuth } = await import('./auth')
        const ok = await refreshAccessToken()
        if (ok) {
          const newHeaders = new Headers(init?.headers)
          newHeaders.set('Authorization', `Bearer ${getToken()}`)
          return originalFetch(input, { ...init, headers: newHeaders })
        }
        clearAuth()
      }
      // 跳登录
      const cp = window.location.pathname
      if (cp !== '/login') {
        window.location.href = '/login?redirect=' + encodeURIComponent(cp)
      }
    }

    return res
  }
}
