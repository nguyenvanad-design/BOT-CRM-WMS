/**
 * Tokinarc frontend — src/pages/crm/forms/ContactForm.tsx
 * Tạo/sửa người liên hệ. POST/PATCH /crm/contacts/.
 */
import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Contact as ContactIcon } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { useCustomerOptions, optionsFromLabels } from '@/lib/useCustomerOptions'
import type { CrmContact } from '@/lib/types'
import { Modal } from '@/components/Modal'
import { Button } from '@/components/ui'
import { FieldRow, TextInput, TextArea, SelectInput } from '@/components/form'

const CHANNELS = { zalo: 'Zalo', phone: 'Điện thoại', email: 'Email', other: 'Khác' }

interface Form {
  customer: string; full_name: string; title: string
  phone: string; email: string; preferred_channel: string; is_primary: boolean; notes: string
}
const EMPTY: Form = {
  customer: '', full_name: '', title: '', phone: '', email: '',
  preferred_channel: 'zalo', is_primary: false, notes: '',
}

export function ContactForm({ open, onClose, editing }: {
  open: boolean; onClose: () => void; editing?: CrmContact | null
}) {
  const qc = useQueryClient()
  const { options: customers, isLoading } = useCustomerOptions()
  const { register, handleSubmit, reset, formState: { errors } } = useForm<Form>({ defaultValues: EMPTY })

  useEffect(() => {
    if (!open) return
    reset(editing ? {
      customer: editing.customer, full_name: editing.full_name, title: editing.title,
      phone: editing.phone, email: editing.email, preferred_channel: editing.preferred_channel,
      is_primary: editing.is_primary, notes: editing.notes,
    } : EMPTY)
  }, [open, editing, reset])

  const save = useMutation({
    mutationFn: (d: Form) => editing
      ? api.patch(`/crm/contacts/${editing.id}/`, d)
      : api.post('/crm/contacts/', d),
    onSuccess: () => {
      toast.success(editing ? 'Đã cập nhật liên hệ' : 'Đã thêm liên hệ')
      qc.invalidateQueries({ queryKey: ['contacts'] })
      qc.invalidateQueries({ queryKey: ['customer-360'] })
      onClose()
    },
    onError: (e) => toast.error(apiError(e)),
  })

  return (
    <Modal open={open} onClose={onClose}
      title={editing ? `Sửa liên hệ — ${editing.full_name}` : 'Thêm người liên hệ'}
      icon={<ContactIcon size={18} className="text-flame" />}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Hủy</Button>
          <Button onClick={handleSubmit((d) => save.mutate(d))} disabled={save.isPending}>
            {save.isPending ? 'Đang lưu…' : editing ? 'Lưu' : 'Tạo'}
          </Button>
        </>
      }>
      <form onSubmit={handleSubmit((d) => save.mutate(d))}>
        <SelectInput label="Khách hàng *" full error={errors.customer?.message}
          placeholder={isLoading ? 'Đang tải…' : '— Chọn KH —'} options={customers}
          {...register('customer', { required: 'Chọn khách hàng' })} />
        <FieldRow>
          <TextInput label="Họ tên *" error={errors.full_name?.message}
            {...register('full_name', { required: 'Bắt buộc' })} />
          <TextInput label="Chức vụ" {...register('title')} />
        </FieldRow>
        <FieldRow>
          <TextInput label="Điện thoại" {...register('phone')} />
          <TextInput label="Email" type="email" {...register('email')} />
        </FieldRow>
        <FieldRow>
          <SelectInput label="Kênh ưu tiên" options={optionsFromLabels(CHANNELS)} {...register('preferred_channel')} />
          <label className="flex items-center gap-2 text-sm mt-6">
            <input type="checkbox" {...register('is_primary')} className="accent-flame" /> Liên hệ chính
          </label>
        </FieldRow>
        <TextArea label="Ghi chú" {...register('notes')} />
      </form>
    </Modal>
  )
}
