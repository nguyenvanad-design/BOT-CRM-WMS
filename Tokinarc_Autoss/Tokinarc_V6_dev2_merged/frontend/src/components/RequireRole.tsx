/**
 * Tokinarc frontend — src/components/RequireRole.tsx
 * Chặn truy cập theo vai trò ở FE (backend vẫn là tầng chặn thật). Nếu không đủ
 * quyền → hiện thông báo lịch sự thay vì để API trả 403 thô.
 */
import type { ReactNode } from 'react'
import { ShieldAlert } from 'lucide-react'
import { useAuth } from '@/lib/auth/store'
import type { Role } from '@/lib/types'

export function RequireRole({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const user = useAuth((s) => s.user)
  const role = user?.role
  // superuser (is_admin) luôn vào được mục dành cho 'admin' dù role gốc khác.
  const ok = (role && roles.includes(role)) || (roles.includes('admin') && !!user?.is_admin)
  if (ok) return <>{children}</>
  return (
    <div className="max-w-md mx-auto mt-20 text-center">
      <ShieldAlert size={36} className="text-danger mx-auto mb-3" />
      <h1 className="text-lg font-semibold">Không có quyền truy cập</h1>
      <p className="text-sm text-txt-2 mt-1.5">
        Mục này chỉ dành cho {roles.map((r) => ROLE_VI[r] ?? r).join(' / ')}.
      </p>
    </div>
  )
}

const ROLE_VI: Record<string, string> = {
  admin: 'Admin', manager: 'Quản lý', sales: 'Sale',
  warehouse: 'Kho', service: 'Dịch vụ', customer: 'Khách',
}
