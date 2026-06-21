/**
 * Tokinarc frontend — src/pages/crm/forms/VisitForm.tsx
 * Tạo báo cáo viếng thăm. POST /crm/visits/ (owner do backend gán).
 */
import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { MapPin } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { useCustomerOptions, useOpportunityOptions } from '@/lib/useCustomerOptions'
import { Modal } from '@/components/Modal'
import { Button } from '@/components/ui'
import { FieldRow, TextInput, TextArea, SelectInput } from '@/components/form'
import { FileUploadField } from '@/components/FileUploadField'
import type { UploadedFile } from '@/lib/upload'

interface Form {
  customer: string; opportunity: string; visit_date: string; purpose: string
  summary: string; next_action: string; recap_text: string
}
const today = () => new Date().toISOString().slice(0, 10)
const EMPTY = (): Form => ({ customer: '', opportunity: '', visit_date: today(), purpose: '', summary: '', next_action: '', recap_text: '' })

export function VisitForm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const { options: customers, isLoading } = useCustomerOptions()
  const { opps } = useOpportunityOptions()
  const { register, handleSubmit, reset, watch, formState: { errors } } = useForm<Form>({ defaultValues: EMPTY() })
  const [recording, setRecording] = useState<UploadedFile | null>(null)
  const [recapFile, setRecapFile] = useState<UploadedFile | null>(null)
  const selectedCust = watch('customer')
  const oppOptions = opps.filter((o) => o.customer === selectedCust).map((o) => ({ value: o.id, label: o.title }))

  useEffect(() => { if (open) { reset(EMPTY()); setRecording(null); setRecapFile(null) } }, [open, reset])

  const save = useMutation({
    mutationFn: (d: Form) => api.post('/crm/visits/', {
      ...d, opportunity: d.opportunity || null,
      recording: recording?.id ?? null, recap_file: recapFile?.id ?? null,
    }),
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

        {/* Ghi âm buổi gặp + recap (sau khi đi họp về) */}
        <FieldRow>
          <FileUploadField label="File ghi âm" kind="visit_recording" accept="audio/*"
            value={recording} onChange={setRecording} />
          <FileUploadField label="File recap (Word/PDF)" kind="visit_recap"
            accept=".doc,.docx,.pdf,.txt" value={recapFile} onChange={setRecapFile} />
        </FieldRow>
        <TextArea label="Recap (văn bản)" {...register('recap_text')} />
      </form>
    </Modal>
  )
}
