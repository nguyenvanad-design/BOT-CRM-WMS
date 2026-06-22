/**
 * Tokinarc frontend — src/pages/crm/forms/LeadForm.tsx
 * Modal tạo/sửa Lead. POST /crm/leads/ hoặc PATCH /crm/leads/{id}/.
 */
import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { useMutation, useQueryClient } from '@tanstack/react-query'
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
  status: string; score: number; notes: string
}

const EMPTY: Form = {
  name: '', company: '', phone: '', email: '',
  source: '', campaign: '', referred_by: '', status: 'new', score: 0, notes: '',
}

export function LeadForm({ open, onClose, editing }: {
  open: boolean; onClose: () => void; editing?: Lead | null
}) {
  const qc = useQueryClient()
  const { register, handleSubmit, reset, formState: { errors } } = useForm<Form>({ defaultValues: EMPTY })

  useEffect(() => {
    if (!open) return
    reset(editing ? {
      name: editing.name, company: editing.company, phone: editing.phone,
      email: editing.email, source: editing.source, campaign: editing.campaign ?? '',
      referred_by: editing.referred_by ?? '',
      status: editing.status, score: editing.score, notes: editing.notes,
    } : EMPTY)
  }, [open, editing, reset])

  const save = useMutation({
    mutationFn: (data: Form) => editing
      ? api.patch(`/crm/leads/${editing.id}/`, data)
      : api.post('/crm/leads/', data),
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
        <TextArea label="Ghi chú" {...register('notes')} />
      </form>
    </Modal>
  )
}
