/**
 * Tokinarc frontend — src/pages/admin/UserForm.tsx
 * Tạo / sửa người dùng (admin). POST/PATCH /accounts/users/.
 * Tạo: cần username + mật khẩu. Sửa: để trống mật khẩu = giữ nguyên.
 */
import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { UserCog } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import type { User, Role } from '@/lib/types'
import { Modal } from '@/components/Modal'
import { Button } from '@/components/ui'
import { FieldRow, TextInput, SelectInput } from '@/components/form'
import { ROLE_OPTIONS } from '@/pages/admin/Users'

interface Form {
  username: string
  display_name: string
  email: string
  phone: string
  role: Role
  is_active: string   // 'true' | 'false' (select trả string)
  password: string
}

export function UserForm({ open, onClose, editing }: {
  open: boolean; onClose: () => void; editing: User | null
}) {
  const qc = useQueryClient()
  const { register, handleSubmit, reset, formState: { errors } } = useForm<Form>({
    defaultValues: {
      username: '', display_name: '', email: '', phone: '',
      role: 'sales', is_active: 'true', password: '',
    },
  })

  useEffect(() => {
    if (!open) return
    reset(editing
      ? {
          username: editing.username, display_name: editing.display_name ?? '',
          email: editing.email ?? '', phone: editing.phone ?? '',
          role: editing.role, is_active: editing.is_active ? 'true' : 'false', password: '',
        }
      : {
          username: '', display_name: '', email: '', phone: '',
          role: 'sales', is_active: 'true', password: '',
        })
  }, [open, editing, reset])

  const save = useMutation({
    mutationFn: (d: Form) => {
      const body: Record<string, unknown> = {
        username: d.username.trim(), display_name: d.display_name.trim(),
        email: d.email.trim(), phone: d.phone.trim(),
        role: d.role, is_active: d.is_active === 'true',
      }
      if (d.password.trim()) body.password = d.password.trim()
      return editing
        ? api.patch(`/accounts/users/${editing.id}/`, body)
        : api.post('/accounts/users/', body)
    },
    onSuccess: () => {
      toast.success(editing ? 'Đã cập nhật người dùng' : 'Đã tạo người dùng')
      qc.invalidateQueries({ queryKey: ['admin-users'] })
      onClose()
    },
    onError: (e) => toast.error(apiError(e)),
  })

  return (
    <Modal open={open} onClose={onClose}
      title={editing ? 'Sửa người dùng' : 'Tạo người dùng'}
      icon={<UserCog size={18} className="text-flame" />}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Hủy</Button>
          <Button onClick={handleSubmit((d) => save.mutate(d))} disabled={save.isPending}>
            {save.isPending ? 'Đang lưu…' : 'Lưu'}
          </Button>
        </>
      }>
      <form onSubmit={handleSubmit((d) => save.mutate(d))}>
        <FieldRow>
          <TextInput label="Tên đăng nhập *" error={errors.username?.message}
            {...register('username', { required: 'Bắt buộc' })} />
          <TextInput label="Họ tên hiển thị" {...register('display_name')} />
        </FieldRow>
        <FieldRow>
          <TextInput label="Email" type="email" {...register('email')} />
          <TextInput label="Điện thoại" {...register('phone')} />
        </FieldRow>
        <FieldRow>
          <SelectInput label="Vai trò" options={ROLE_OPTIONS} {...register('role')} />
          <SelectInput label="Trạng thái"
            options={[{ value: 'true', label: 'Hoạt động' }, { value: 'false', label: 'Đã khóa' }]}
            {...register('is_active')} />
        </FieldRow>
        <TextInput
          label={editing ? 'Mật khẩu mới (để trống = giữ nguyên)' : 'Mật khẩu *'}
          type="password" full error={errors.password?.message}
          {...register('password', editing ? {} : { required: 'Bắt buộc khi tạo mới' })} />
      </form>
    </Modal>
  )
}
