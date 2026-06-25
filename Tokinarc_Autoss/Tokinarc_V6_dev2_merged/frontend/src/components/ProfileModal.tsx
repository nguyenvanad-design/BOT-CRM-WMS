/**
 * Tokinarc frontend — src/components/ProfileModal.tsx
 * "Tài khoản của tôi" — mọi vai trò tự sửa hồ sơ + đổi mật khẩu của CHÍNH MÌNH.
 * PATCH /auth/me/. KHÔNG đổi được role/quyền (việc của admin).
 */
import { useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { UserCircle } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { useAuth } from '@/lib/auth/store'
import type { User } from '@/lib/types'
import { Modal } from '@/components/Modal'
import { Button } from '@/components/ui'
import { FieldRow, TextInput } from '@/components/form'

export function ProfileModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const user = useAuth((s) => s.user)
  const updateUser = useAuth((s) => s.updateUser)
  const [display, setDisplay] = useState('')
  const [phone, setPhone] = useState('')
  const [email, setEmail] = useState('')
  const [pw, setPw] = useState('')

  useEffect(() => {
    if (open && user) {
      setDisplay(user.display_name ?? ''); setPhone(user.phone ?? '')
      setEmail(user.email ?? ''); setPw('')
    }
  }, [open, user])

  const save = useMutation({
    mutationFn: async () => {
      const body: Record<string, unknown> = {
        display_name: display.trim(), phone: phone.trim(), email: email.trim(),
      }
      if (pw.trim()) body.password = pw.trim()
      return (await api.patch<User>('/auth/me/', body)).data
    },
    onSuccess: (u) => {
      updateUser(u)
      toast.success(pw.trim() ? 'Đã lưu hồ sơ + đổi mật khẩu' : 'Đã lưu hồ sơ')
      onClose()
    },
    onError: (e) => toast.error(apiError(e)),
  })

  return (
    <Modal open={open} onClose={onClose} title="Tài khoản của tôi"
      icon={<UserCircle size={18} className="text-flame" />}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Đóng</Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? 'Đang lưu…' : 'Lưu'}
          </Button>
        </>
      }>
      <div className="bg-ink-3 rounded-md px-3 py-2 mb-3 text-sm">
        <span className="text-txt-2">Tài khoản: </span><span className="font-mono">{user?.username}</span>
        <span className="text-txt-2"> · Vai trò: </span><span>{user?.role}</span>
      </div>
      <FieldRow>
        <TextInput label="Họ tên hiển thị" value={display} onChange={(e) => setDisplay(e.target.value)} />
        <TextInput label="Điện thoại" value={phone} onChange={(e) => setPhone(e.target.value)} />
      </FieldRow>
      <TextInput label="Email" type="email" full value={email} onChange={(e) => setEmail(e.target.value)} />
      <TextInput label="Mật khẩu mới (để trống = giữ nguyên)" type="password" full
        value={pw} onChange={(e) => setPw(e.target.value)} />
    </Modal>
  )
}
