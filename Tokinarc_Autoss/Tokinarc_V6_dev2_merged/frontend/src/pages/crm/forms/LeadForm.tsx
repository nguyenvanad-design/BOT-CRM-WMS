/**
 * Tokinarc frontend — src/pages/crm/forms/LeadForm.tsx
 * Modal tạo/sửa Lead. POST /crm/leads/ hoặc PATCH /crm/leads/{id}/.
 */
import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Radar } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { LEAD_STATUS_LABEL, LEAD_SOURCE_LABEL } from '@/lib/crm'
import { optionsFromLabels } from '@/lib/useCustomerOptions'
import type { Lead } from '@/lib/types'
import { Modal } from '@/components/Modal'
import { Button } from '@/components/ui'
import { FieldRow, TextInput, TextArea, SelectInput } from '@/components/form'

interface Form {
  name: string; company: string; phone: string; email: string
  source: string; campaign: string; referred_by: string
  status: string; score: number
  interest_part: string; interest_qty: number; notes: string
}

const EMPTY: Form = {
  name: '', company: '', phone: '', email: '',
  source: '', campaign: '', referred_by: '', status: 'new', score: 0,
  interest_part: '', interest_qty: 0, notes: '',
}

export function LeadForm({ open, onClose, editing }: {
  open: boolean; onClose: () => void; editing?: Lead | null
}) {
  const qc = useQueryClient()
  const { register, handleSubmit, reset, watch, formState: { errors } } =
    useForm<Form>({ defaultValues: EMPTY })

  useEffect(() => {
    if (!open) return
    reset(editing ? {
      name: editing.name, company: editing.company, phone: editing.phone,
      email: editing.email, source: editing.source, campaign: editing.campaign ?? '',
      referred_by: editing.referred_by ?? '',
      status: editing.status, score: editing.score,
      interest_part: editing.interest_part ?? '', interest_qty: editing.interest_qty ?? 0,
      notes: editing.notes,
    } : EMPTY)
  }, [open, editing, reset])

  // Tự tính giá trị dự kiến = giá bán × số lượng (đổ về Opportunity khi "+ Cơ hội").
  const partCode = watch('interest_part')
  const qty = Number(watch('interest_qty')) || 0
  const partQ = useQuery({
    queryKey: ['part-price', partCode],
    queryFn: async () => (await api.get(`/catalog/parts/${encodeURIComponent(partCode)}/`)).data,
    enabled: open && !!partCode && partCode.length >= 2,
    retry: false,
  })
  const unitPrice = Number(partQ.data?.effective_price_vnd || 0)

  const save = useMutation({
    mutationFn: (data: Form) => {
      const payload = { ...data, interest_part: data.interest_part || null, interest_qty: data.interest_qty || 0 }
      return editing
        ? api.patch(`/crm/leads/${editing.id}/`, payload)
        : api.post('/crm/leads/', payload)
    },
    onSuccess: () => {
      toast.success(editing ? 'Đã cập nhật lead' : 'Đã tạo lead')
      qc.invalidateQueries({ queryKey: ['leads'] })
      qc.invalidateQueries({ queryKey: ['dash'] })
      onClose()
    },
    onError: (e) => toast.error(apiError(e)),
  })

  return (
    <Modal
      open={open} onClose={onClose}
      title={editing ? `Sửa lead — ${editing.name}` : 'Tạo Lead'}
      icon={<Radar size={18} className="text-flame" />}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Hủy</Button>
          <Button onClick={handleSubmit((d) => save.mutate(d))} disabled={save.isPending}>
            {save.isPending ? 'Đang lưu…' : editing ? 'Lưu' : 'Tạo'}
          </Button>
        </>
      }
    >
      <form onSubmit={handleSubmit((d) => save.mutate(d))}>
        <FieldRow>
          <TextInput label="Tên *" error={errors.name?.message}
            {...register('name', { required: 'Bắt buộc' })} />
          <TextInput label="Công ty" {...register('company')} />
        </FieldRow>
        <FieldRow>
          <TextInput label="Điện thoại" {...register('phone')} />
          <TextInput label="Email" type="email" {...register('email')} />
        </FieldRow>
        <FieldRow>
          <SelectInput label="Nguồn" options={optionsFromLabels(LEAD_SOURCE_LABEL)}
            {...register('source')} />
          <SelectInput label="Trạng thái" options={optionsFromLabels(LEAD_STATUS_LABEL)}
            {...register('status')} />
        </FieldRow>
        <FieldRow>
          <TextInput label="Chiến dịch" placeholder="VD: METALEX 2026, FB-Tet…"
            {...register('campaign')} />
          <TextInput label="Người giới thiệu" placeholder="VD: Anh Tuấn - Cty ABC"
            {...register('referred_by')} />
        </FieldRow>
        <FieldRow>
          <TextInput label="Điểm (0-100)" type="number" min={0} max={100}
            {...register('score', { valueAsNumber: true })} />
          <div />
        </FieldRow>
        <FieldRow>
          <TextInput label="Sản phẩm quan tâm (mã)" placeholder="VD: 001002"
            {...register('interest_part')} />
          <TextInput label="Số lượng" type="number" min={0}
            {...register('interest_qty', { valueAsNumber: true })} />
        </FieldRow>
        {partCode && (
          <p className="text-[11px] text-txt-2 -mt-1 mb-2">
            {unitPrice
              ? `Giá bán ${unitPrice.toLocaleString('vi-VN')}₫ × ${qty} → Giá trị dự kiến ${(unitPrice * qty).toLocaleString('vi-VN')}₫ (đổ về Cơ hội)`
              : 'Không tìm thấy giá của mã này.'}
          </p>
        )}
        <TextArea label="Nội dung làm việc với khách hàng"
          placeholder="Ghi lại nội dung gọi điện/trao đổi: nhu cầu, sản phẩm quan tâm, hẹn gặp…"
          {...register('notes')} />
      </form>
    </Modal>
  )
}
