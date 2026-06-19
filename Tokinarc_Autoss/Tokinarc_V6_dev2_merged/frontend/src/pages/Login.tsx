/**
 * Tokinarc frontend — src/pages/Login.tsx
 * Đăng nhập gọi POST /auth/login/ thật. Hiển thị lỗi từ backend (sai mật khẩu, khóa).
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { Flame } from 'lucide-react'
import { useAuth } from '@/lib/auth/store'
import { apiError } from '@/lib/api'

interface Form { username: string; password: string }

export function LoginPage() {
  const login = useAuth((s) => s.login)
  const nav = useNavigate()
  const [busy, setBusy] = useState(false)
  const { register, handleSubmit, formState: { errors } } = useForm<Form>()

  const onSubmit = async (data: Form) => {
    setBusy(true)
    try {
      await login(data.username, data.password)
      nav('/customers', { replace: true })
    } catch (e) {
      toast.error(apiError(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen grid place-items-center px-4">
      <div className="w-full max-w-sm">
        <div className="flex items-center gap-2 mb-1">
          <Flame className="text-flame" size={26} />
          <span className="text-xl font-bold tracking-tight">Tokinarc</span>
        </div>
        <p className="text-txt-2 text-sm mb-8">Hệ thống nội bộ — đăng nhập để tiếp tục</p>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-txt-2 mb-1.5">Tên đăng nhập</label>
            <input
              {...register('username', { required: 'Nhập tên đăng nhập' })}
              autoFocus autoComplete="username"
              className="w-full bg-ink-2 border border-line rounded-md px-3 py-2.5 text-sm
                         focus:border-flame transition-colors"
            />
            {errors.username && <p className="text-danger text-xs mt-1">{errors.username.message}</p>}
          </div>

          <div>
            <label className="block text-xs font-medium text-txt-2 mb-1.5">Mật khẩu</label>
            <input
              type="password" autoComplete="current-password"
              {...register('password', { required: 'Nhập mật khẩu' })}
              className="w-full bg-ink-2 border border-line rounded-md px-3 py-2.5 text-sm
                         focus:border-flame transition-colors"
            />
            {errors.password && <p className="text-danger text-xs mt-1">{errors.password.message}</p>}
          </div>

          <button
            type="submit" disabled={busy}
            className="w-full bg-flame hover:bg-flame-hi disabled:opacity-50 disabled:cursor-not-allowed
                       text-white font-semibold rounded-md py-2.5 text-sm transition-colors"
          >
            {busy ? 'Đang đăng nhập…' : 'Đăng nhập'}
          </button>
        </form>
      </div>
    </div>
  )
}
