/**
 * Tokinarc frontend — src/lib/auth/store.ts
 * Trạng thái đăng nhập (zustand). User persist qua localStorage để reload không mất.
 */
import { create } from 'zustand'
import { api, tokens } from '@/lib/api'
import type { User, Role } from '@/lib/types'

const USER_KEY = 'tokinarc_user'

function loadUser(): User | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as User) : null
  } catch {
    return null
  }
}

interface AuthState {
  user: User | null
  isAuthed: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  hasRole: (...roles: Role[]) => boolean
}

export const useAuth = create<AuthState>((set, get) => ({
  user: loadUser(),
  isAuthed: !!tokens.access() && !!loadUser(),

  login: async (username, password) => {
    const res = await api.post('/auth/login/', { username, password })
    const { access, refresh, user } = res.data as {
      access: string; refresh: string; user: User
    }
    tokens.set(access, refresh)
    localStorage.setItem(USER_KEY, JSON.stringify(user))
    set({ user, isAuthed: true })
  },

  logout: async () => {
    try {
      const r = tokens.refresh()
      if (r) await api.post('/auth/logout/', { refresh: r })
    } catch {
      /* logout vẫn tiếp tục dù API lỗi */
    }
    tokens.clear()
    localStorage.removeItem(USER_KEY)
    set({ user: null, isAuthed: false })
  },

  hasRole: (...roles) => {
    const r = get().user?.role
    return !!r && roles.includes(r)
  },
}))

/** Mức quản lý+ = manager, ceo hoặc admin (khớp MANAGER_ROLES backend). */
export const isManager = (role?: Role) =>
  role === 'manager' || role === 'ceo' || role === 'admin'

/** Duyệt cấp 2 báo giá = ceo hoặc admin (khớp CEO_ROLES backend). */
export const isCeo = (role?: Role) => role === 'ceo' || role === 'admin'
