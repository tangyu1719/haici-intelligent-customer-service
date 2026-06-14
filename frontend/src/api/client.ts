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

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const { authHeaders, getRefreshToken, refreshAccessToken, clearAuth } = await import('./auth')
  let res = await fetch(path, { ...init, headers: { ...authHeaders(), ...(init.headers as Record<string, string> | undefined) } })
  if (res.status === 401 && getRefreshToken()) {
    const ok = await refreshAccessToken()
    if (ok) {
      res = await fetch(path, { ...init, headers: { ...authHeaders(), ...(init.headers as Record<string, string> | undefined) } })
    } else {
      clearAuth()
    }
  }
  return res
}
