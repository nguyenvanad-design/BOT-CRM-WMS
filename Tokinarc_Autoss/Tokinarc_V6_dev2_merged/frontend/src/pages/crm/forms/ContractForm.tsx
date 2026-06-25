/**
 * Tokinarc frontend — src/pages/crm/forms/ContractForm.tsx
 * Tạo/sửa hợp đồng. POST/PATCH /crm/contracts/ (code sinh tự động ở server).
 */
import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ScrollText } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { CONTRACT_STATUS_LABEL } from '@/lib/crm'
import { useCustomerOptions, optionsFromLabels } from '@/lib/useCustomerOptions'
import type { Contract } from '@/lib/types'
import { Modal } from '@/components/Modal'
import { Button } from '@/components/ui'
import { FieldRow, TextInput, TextArea, SelectInput } from '@/components/form'

interface Form {
  customer: string; title: string; discount_pct: number; value_vnd: number; paid_vnd: number
  status: string; start_date: string; end_date: string; notes: string
}
const EMPTY: Form = {
  customer: '', title: '', discount_pct: 0, value_vnd: 0, paid_vnd: 0,
  status: 'draft', start_date: '', end_date: '', notes: '',
}

export function ContractForm({ open, onClose, editing }: {
  open: boolean; onClose: () => void; editing?: Contract | null
}) {
  const qc = useQueryClient()
  const { options: customers, isLoading } = useCustomerOptions()
  const { register, handleSubmit, reset, formState: { errors } } = useForm<Form>({ defaultValues: EMPTY })

  useEffect(() => {
    if (!open) return
    reset(editing ? {
      customer: editing.customer, title: editing.title,
      discount_pct: Number(editing.discount_pct || 0),
      value_vnd: Number(editing.value_vnd || 0), paid_vnd: Number(editing.paid_vnd || 0),
      status: editing.status, start_date: editing.start_date ?? '', end_date: editing.end_date ?? '',
      notes: editing.notes,
    } : EMPTY)
  }, [open, editing, reset])

  const save = useMutation({
    mutationFn: (d: Form) => {
      const payload = { ...d, start_date: d.start_date || null, end_date: d.end_date || null }
      return editing ? api.patch(`/crm/contracts/${editing.id}/`, payload)
                     : api.post('/crm/contracts/', payload)
    },
    onSuccess: () => {
      toast.success(editing ? 'Đã cập nhật hợp đồng' : 'Đã tạo hợp đồng')
      qc.invalidateQueries({ queryKey: ['contracts'] })
      onClose()
    },
    onError: (e) => toast.error(apiError(e)),
  })

  return (
    <Modal open={open} onClose={onClose}
      title={editing ? `Sửa HĐ — ${editing.code}` : 'Tạo hợp đồng'}
      icon={<ScrollText size={18} className="text-flame" />}
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
        <TextInput label="Tiêu đề" full {...register('title')} />
        <FieldRow>
          <TextInput label="Giá trị (₫)" type="number" min={0} {...register('value_vnd', { valueAsNumber: true })} />
          <TextInput label="Đã thanh toán (₫)" type="number" min={0} {...register('paid_vnd', { valueAsNumber: true })} />
        </FieldRow>
        <FieldRow>
          <SelectInput label="Trạng thái" options={optionsFromLabels(CONTRACT_STATUS_LABEL)} {...register('status')} />
          <TextInput label="Chiết khấu (%)" type="number" step="0.01" min={0} max={100}
            {...register('discount_pct', { valueAsNumber: true })} />
        </FieldRow>
        <FieldRow>
          <TextInput label="Hiệu lực từ" type="date" {...register('start_date')} />
          <TextInput label="Đến" type="date" {...register('end_date')} />
        </FieldRow>
        <TextArea label="Ghi chú" {...register('notes')} />
      </form>
    </Modal>
  )
}
