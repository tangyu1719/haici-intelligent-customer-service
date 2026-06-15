export {
  authHeaders,
  clearAuth,
  currentUser,
  getAccessToken,
  getRefreshToken,
  hasPerm,
  isAuthenticated,
  isPublicPage,
  loadAuthFromStorage,
  redirectToLogin,
  refreshAccessToken,
  setAuth,
} from './auth'

export function getToken(): string {
  return localStorage.getItem('hc_access_token') || ''
}

const PUBLIC_API_PATHS = new Set([
  '/api/v1/auth/login',
  '/api/v1/auth/register',
  '/api/v1/auth/send-code',
  '/api/v1/auth/refresh',
])

let redirecting = false

function apiPath(url: string): string {
  try {
    if (url.startsWith('http')) return new URL(url).pathname
    return url.split('?')[0]
  } catch {
    return url.split('?')[0]
  }
}

function isPublicApi(url: string): boolean {
  return PUBLIC_API_PATHS.has(apiPath(url))
}

function isFormDataBody(init?: RequestInit): boolean {
  return init?.body instanceof FormData
}

function forceLoginRedirect(): void {
  if (redirecting) return
  redirecting = true
  import('./auth').then(({ redirectToLogin }) => redirectToLogin())
}

/** 带401拦截的API请求 — 未登录自动跳转登录页 */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const { authHeaders, getRefreshToken, refreshAccessToken, clearAuth, redirectToLogin } = await import('./auth')
  const headers = { ...authHeaders(), ...(init.headers as Record<string, string> | undefined) }
  let res = await fetch(path, { ...init, headers })

  if (res.status === 401 && getRefreshToken()) {
    const ok = await refreshAccessToken()
    if (ok) {
      res = await fetch(path, { ...init, headers: { ...authHeaders(), ...(init.headers as Record<string, string> | undefined) } })
      if (res.status !== 401) return res
    }
    clearAuth()
  }

  if (res.status === 401) {
    clearAuth()
    redirectToLogin()
  }

  return res
}

/** 全局fetch拦截器：无 token 不发受保护请求；401 强制登录 */
export function setupFetchInterceptor(): void {
  const originalFetch = window.fetch
  window.fetch = async function (...args: Parameters<typeof fetch>) {
    const [input, init] = args
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url

    if (!url.includes('/api/')) {
      return originalFetch(...args)
    }

    const path = apiPath(url)
    const publicApi = isPublicApi(path)
    const token = getToken().trim()

    if (!publicApi && !token) {
      forceLoginRedirect()
      return new Response(JSON.stringify({ detail: '未登录，请先登录' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      })
    }

    const headers = new Headers(init?.headers)
    if (token && !headers.has('Authorization')) {
      headers.set('Authorization', `Bearer ${token}`)
    }
    const method = (init?.method || 'GET').toUpperCase()
    if (
      !publicApi &&
      !isFormDataBody(init) &&
      !headers.has('Content-Type') &&
      method !== 'GET' &&
      method !== 'HEAD'
    ) {
      headers.set('Content-Type', 'application/json')
    }

    let res = await originalFetch(input, { ...init, headers })

    if (res.status === 401 && !publicApi) {
      const rt = localStorage.getItem('hc_refresh_token')
      if (rt && path !== '/api/v1/auth/refresh') {
        const { refreshAccessToken, clearAuth } = await import('./auth')
        const ok = await refreshAccessToken()
        if (ok) {
          const retryHeaders = new Headers(init?.headers)
          retryHeaders.set('Authorization', `Bearer ${getToken()}`)
          res = await originalFetch(input, { ...init, headers: retryHeaders })
          if (res.status !== 401) return res
        }
        clearAuth()
      } else if (!rt) {
        const { clearAuth } = await import('./auth')
        clearAuth()
      }
      forceLoginRedirect()
    }

    return res
  }
}
