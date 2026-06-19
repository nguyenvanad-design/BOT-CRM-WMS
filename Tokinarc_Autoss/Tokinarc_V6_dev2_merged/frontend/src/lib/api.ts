/**
 * Tokinarc frontend — src/lib/api.ts
 * Axios client: gắn JWT vào mọi request, tự refresh khi 401, logout khi refresh fail.
 */
import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'

const BASE = import.meta.env.VITE_API_BASE ?? '/api/v1'

export const TOKEN_KEY = 'tokinarc_access'
export const REFRESH_KEY = 'tokinarc_refresh'

export const tokens = {
  access: () => localStorage.getItem(TOKEN_KEY),
  refresh: () => localStorage.getItem(REFRESH_KEY),
  set: (access: string, refresh?: string) => {
    localStorage.setItem(TOKEN_KEY, access)
    if (refresh) localStorage.setItem(REFRESH_KEY, refresh)
  },
  clear: () => {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(REFRESH_KEY)
  },
}

export const api = axios.create({ baseURL: BASE })

api.interceptors.request.use((cfg: InternalAxiosRequestConfig) => {
  const t = tokens.access()
  if (t) cfg.headers.Authorization = `Bearer ${t}`
  return cfg
})

// Auto-refresh: gặp 401 một lần → thử refresh → retry; fail → clear + về login.
let refreshing: Promise<string | null> | null = null

async function doRefresh(): Promise<string | null> {
  const r = tokens.refresh()
  if (!r) return null
  try {
    const res = await axios.post(`${BASE}/auth/refresh/`, { refresh: r })
    const access = res.data.access as string
    tokens.set(access, res.data.refresh)
    return access
  } catch {
    return null
  }
}

api.interceptors.response.use(
  (res) => res,
  async (err: AxiosError) => {
    const cfg = err.config as InternalAxiosRequestConfig & { _retry?: boolean }
    if (err.response?.status === 401 && cfg && !cfg._retry) {
      cfg._retry = true
      refreshing = refreshing ?? doRefresh()
      const newAccess = await refreshing
      refreshing = null
      if (newAccess) {
        cfg.headers.Authorization = `Bearer ${newAccess}`
        return api(cfg)
      }
      tokens.clear()
      if (location.pathname !== '/login') location.assign('/login')
    }
    return Promise.reject(err)
  },
)

/** Lấy message lỗi từ response Django (DRF detail / non_field_errors). */
export function apiError(e: unknown): string {
  const ax = e as AxiosError<any>
  const d = ax.response?.data
  if (typeof d === 'string') return d
  if (d?.detail) return d.detail
  if (d?.non_field_errors?.length) return d.non_field_errors[0]
  if (ax.message) return ax.message
  return 'Đã có lỗi xảy ra.'
}
