/**
 * Tokinarc frontend — src/pages/crm/forms/VisitForm.tsx
 * Tạo báo cáo viếng thăm. POST /crm/visits/ (owner do backend gán).
 */
import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { MapPin } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { useCustomerOptions, useOpportunityOptions } from '@/lib/useCustomerOptions'
import { Modal } from '@/components/Modal'
import { Button } from '@/components/ui'
import { FieldRow, TextInput, TextArea, SelectInput } from '@/components/form'

interface Form {
  customer: string; opportunity: string; visit_date: string; purpose: string
  summary: string; next_action: string
}
const today = () => new Date().toISOString().slice(0, 10)
const EMPTY = (): Form => ({ customer: '', opportunity: '', visit_date: today(), purpose: '', summary: '', next_action: '' })

export function VisitForm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const { options: customers, isLoading } = useCustomerOptions()
  const { opps } = useOpportunityOptions()
  const { register, handleSubmit, reset, watch, formState: { errors } } = useForm<Form>({ defaultValues: EMPTY() })
  const selectedCust = watch('customer')
  const oppOptions = opps.filter((o) => o.customer === selectedCust).map((o) => ({ value: o.id, label: o.title }))

  useEffect(() => { if (open) reset(EMPTY()) }, [open, reset])

  const save = useMutation({
    mutationFn: (d: Form) => api.post('/crm/visits/', { ...d, opportunity: d.opportunity || null }),
    onSuccess: () => {
      toast.success('Đã ghi nhận visit')
      qc.invalidateQueries({ queryKey: ['visits'] })
      onClose()
    },
    onError: (e) => toast.error(apiError(e)),
  })

  return (
    <Modal open={open} onClose={onClose} title="Lên lịch / ghi visit"
      icon={<MapPin size={18} className="text-flame" />}
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
          <SelectInput label="Khách hàng *" error={errors.customer?.message}
            placeholder={isLoading ? 'Đang tải…' : '— Chọn KH —'} options={customers}
            {...register('customer', { required: 'Chọn khách hàng' })} />
          <TextInput label="Ngày thăm *" type="date" error={errors.visit_date?.message}
            {...register('visit_date', { required: 'Bắt buộc' })} />
        </FieldRow>
        {selectedCust && oppOptions.length > 0 && (
          <SelectInput label="Gắn cơ hội (tùy chọn)" full placeholder="— Không gắn —"
            options={oppOptions} {...register('opportunity')} />
        )}
        <TextInput label="Mục đích *" full error={errors.purpose?.message}
          placeholder="Demo sản phẩm / Khảo sát / Bảo trì…"
          {...register('purpose', { required: 'Bắt buộc' })} />
        <TextArea label="Tóm tắt" {...register('summary')} />
        <TextInput label="Hành động tiếp theo" full {...register('next_action')} />
      </form>
    </Modal>
  )
}
