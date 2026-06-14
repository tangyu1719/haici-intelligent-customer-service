import { ref } from 'vue'

export interface AuthUser {
  id: number
  user_no: string
  email?: string
  phone?: string
  nickname?: string
  roles: string[]
  permissions: string[]
}

const ACCESS_KEY = 'hc_access_token'
const REFRESH_KEY = 'hc_refresh_token'
const USER_KEY = 'hc_user'

export const currentUser = ref<AuthUser | null>(null)

export function getAccessToken(): string {
  return localStorage.getItem(ACCESS_KEY) || ''
}

export function getRefreshToken(): string {
  return localStorage.getItem(REFRESH_KEY) || ''
}

export function setAuth(access: string, refresh: string, user: AuthUser): void {
  localStorage.setItem(ACCESS_KEY, access)
  localStorage.setItem(REFRESH_KEY, refresh)
  localStorage.setItem(USER_KEY, JSON.stringify(user))
  currentUser.value = user
}

export function clearAuth(): void {
  localStorage.removeItem(ACCESS_KEY)
  localStorage.removeItem(REFRESH_KEY)
  localStorage.removeItem(USER_KEY)
  currentUser.value = null
}

export function loadAuthFromStorage(): void {
  const raw = localStorage.getItem(USER_KEY)
  if (raw) {
    try {
      currentUser.value = JSON.parse(raw)
    } catch {
      clearAuth()
    }
  }
}

export function hasPerm(code: string): boolean {
  const u = currentUser.value
  if (!u) return false
  if (u.roles?.includes('admin')) return true
  return u.permissions?.includes(code) ?? false
}

export async function refreshAccessToken(): Promise<boolean> {
  const rt = getRefreshToken()
  if (!rt) return false
  const res = await fetch('/api/v1/auth/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: rt }),
  })
  if (!res.ok) return false
  const data = await res.json()
  setAuth(data.access_token, data.refresh_token, data.user)
  return true
}

export function authHeaders(): Record<string, string> {
  const t = getAccessToken()
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  if (t) h.Authorization = `Bearer ${t}`
  return h
}
