/**
 * Tokinarc frontend — src/pages/admin/Users.tsx
 * Quản trị người dùng (chỉ admin/superuser). Dùng API có sẵn:
 *   GET    /accounts/users/                list
 *   POST   /accounts/users/                tạo
 *   PATCH  /accounts/users/{id}/           sửa / khóa (is_active)
 *   POST   /accounts/users/{id}/set-role/  đổi role (ghi AuditLog)
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { UserCog, Plus, Lock, Unlock, Pencil } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { fetchAll } from '@/lib/list'
import { useAuth } from '@/lib/auth/store'
import type { User, Role } from '@/lib/types'
import {
  PageHeader, Button, Tag, TableCard, Th, Td, RowMsg,
} from '@/components/ui'
import { UserForm } from '@/pages/admin/UserForm'

export const ROLE_OPTIONS: { value: Role; label: string }[] = [
  { value: 'customer', label: 'Khách hàng' },
  { value: 'sales', label: 'Sales' },
  { value: 'warehouse', label: 'Nhân viên kho' },
  { value: 'wh_manager', label: 'Quản lý kho' },
  { value: 'service', label: 'Kỹ sư dịch vụ' },
  { value: 'manager', label: 'Quản lý' },
  { value: 'ceo', label: 'CEO' },
  { value: 'admin', label: 'Admin' },
]
const ROLE_LABEL = Object.fromEntries(ROLE_OPTIONS.map((o) => [o.value, o.label]))

export function AdminUsersPage() {
  const qc = useQueryClient()
  const meId = useAuth((s) => s.user?.id)
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<User | null>(null)

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['admin-users'],
    queryFn: () => fetchAll<User>('/accounts/users/'),
  })

  const invalidate = () => qc.invalidateQueries({ queryKey: ['admin-users'] })

  const setRole = useMutation({
    mutationFn: (v: { id: string; role: Role }) =>
      api.post(`/accounts/users/${v.id}/set-role/`, { role: v.role }),
    onSuccess: () => { toast.success('Đã đổi vai trò'); invalidate() },
    onError: (e) => toast.error(apiError(e)),
  })
  const toggleActive = useMutation({
    mutationFn: (v: { id: string; is_active: boolean }) =>
      api.patch(`/accounts/users/${v.id}/`, { is_active: v.is_active }),
    onSuccess: (_r, v) => { toast.success(v.is_active ? 'Đã mở khóa' : 'Đã khóa'); invalidate() },
    onError: (e) => toast.error(apiError(e)),
  })

  const openCreate = () => { setEditing(null); setFormOpen(true) }
  const openEdit = (u: User) => { setEditing(u); setFormOpen(true) }

  const users = data?.items ?? []

  return (
    <div className="max-w-5xl">
      <PageHeader
        icon={<UserCog size={20} className="text-flame" />}
        title="Người dùng & quyền"
        subtitle={data ? `${data.count} tài khoản` : 'Quản trị tài khoản và phân quyền'}
        actions={<Button onClick={openCreate}><Plus size={14} /> Tạo người dùng</Button>}
      />

      <TableCard>
        <thead>
          <tr className="border-b border-line">
            <Th>Tài khoản</Th><Th>Họ tên</Th><Th>Email</Th>
            <Th>Vai trò</Th><Th>Trạng thái</Th><Th className="text-right">Hành động</Th>
          </tr>
        </thead>
        <tbody>
          {isLoading && <RowMsg colSpan={6}>Đang tải…</RowMsg>}
          {isError && <RowMsg colSpan={6} danger>Lỗi: {apiError(error)}</RowMsg>}
          {users.length === 0 && !isLoading && <RowMsg colSpan={6}>Chưa có tài khoản nào.</RowMsg>}
          {users.map((u) => {
            const isSelf = u.id === meId
            return (
              <tr key={u.id} className="border-b border-line/50 last:border-0 hover:bg-ink-3/40">
                <Td className="font-mono">{u.username}{isSelf && <span className="text-txt-2"> (bạn)</span>}</Td>
                <Td className="font-medium">{u.full_name || u.display_name || '—'}</Td>
                <Td className="text-txt-2">{u.email || '—'}</Td>
                <Td>
                  <select
                    value={u.role}
                    disabled={isSelf || setRole.isPending}
                    onChange={(e) => setRole.mutate({ id: u.id, role: e.target.value as Role })}
                    className="bg-ink-3 border border-line rounded-md px-2 py-1 text-xs focus:outline-none focus:border-flame disabled:opacity-60"
                    title={isSelf ? 'Không thể tự đổi vai trò của mình' : 'Đổi vai trò'}
                  >
                    {ROLE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                </Td>
                <Td>
                  {u.is_active
                    ? <Tag tone="ok">Hoạt động</Tag>
                    : <Tag tone="danger">Đã khóa</Tag>}
                </Td>
                <Td className="text-right">
                  <span className="inline-flex gap-1.5 justify-end">
                    <Button variant="ghost" size="sm" onClick={() => openEdit(u)}>
                      <Pencil size={13} /> Sửa
                    </Button>
                    {u.is_active
                      ? <Button variant="ghost" size="sm" disabled={isSelf || toggleActive.isPending}
                          title={isSelf ? 'Không thể tự khóa mình' : 'Khóa tài khoản'}
                          onClick={() => toggleActive.mutate({ id: u.id, is_active: false })}>
                          <Lock size={13} /> Khóa
                        </Button>
                      : <Button variant="ghost" size="sm" disabled={toggleActive.isPending}
                          onClick={() => toggleActive.mutate({ id: u.id, is_active: true })}>
                          <Unlock size={13} /> Mở
                        </Button>}
                  </span>
                </Td>
              </tr>
            )
          })}
        </tbody>
      </TableCard>

      <UserForm open={formOpen} onClose={() => setFormOpen(false)} editing={editing} />
    </div>
  )
}

export { ROLE_LABEL }
