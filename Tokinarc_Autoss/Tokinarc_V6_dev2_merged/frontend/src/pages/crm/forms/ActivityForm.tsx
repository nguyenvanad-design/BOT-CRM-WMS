/**
 * Tokinarc frontend — src/pages/crm/forms/ActivityForm.tsx
 * Ghi nhận hoạt động chăm sóc KH. POST /crm/activities/.
 */
import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Phone } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { ACTIVITY_TYPE_LABEL } from '@/lib/crm'
import { useCustomerOptions, useOpportunityOptions, optionsFromLabels } from '@/lib/useCustomerOptions'
import { Modal } from '@/components/Modal'
import { Button } from '@/components/ui'
import { TextArea, SelectInput, FieldRow } from '@/components/form'
import { FileUploadField } from '@/components/FileUploadField'
import type { UploadedFile } from '@/lib/upload'

interface Form { customer: string; opportunity: string; activity_type: string; content: string; recap_text: string }
const EMPTY: Form = { customer: '', opportunity: '', activity_type: 'call', content: '', recap_text: '' }

export function ActivityForm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const { options: customers, isLoading } = useCustomerOptions()
  const { opps } = useOpportunityOptions()
  const { register, handleSubmit, reset, watch, formState: { errors } } = useForm<Form>({ defaultValues: EMPTY })
  const [recording, setRecording] = useState<UploadedFile | null>(null)
  const [recapFile, setRecapFile] = useState<UploadedFile | null>(null)
  const selectedCust = watch('customer')
  const oppOptions = opps.filter((o) => o.customer === selectedCust).map((o) => ({ value: o.id, label: o.title }))

  useEffect(() => { if (open) { reset(EMPTY); setRecording(null); setRecapFile(null) } }, [open, reset])

  const save = useMutation({
    mutationFn: (d: Form) => api.post('/crm/activities/', {
      ...d, opportunity: d.opportunity || null,
      recording: recording?.id ?? null, recap_file: recapFile?.id ?? null,
    }),
    onSuccess: () => {
      toast.success('Đã ghi hoạt động')
      qc.invalidateQueries({ queryKey: ['activities'] })
      onClose()
    },
    onError: (e) => toast.error(apiError(e)),
  })

  return (
    <Modal open={open} onClose={onClose} title="Ghi hoạt động"
      icon={<Phone size={18} className="text-flame" />}
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
          <SelectInput label="Loại" options={optionsFromLabels(ACTIVITY_TYPE_LABEL)} {...register('activity_type')} />
        </FieldRow>
        {selectedCust && oppOptions.length > 0 && (
          <SelectInput label="Gắn cơ hội (tùy chọn)" full placeholder="— Không gắn —"
            options={oppOptions} {...register('opportunity')} />
        )}
        <TextArea label="Nội dung" {...register('content')} />

        {/* Ghi âm cuộc gọi/tiếp xúc + recap */}
        <FieldRow>
          <FileUploadField label="File ghi âm" kind="activity_recording" accept="audio/*"
            value={recording} onChange={setRecording} />
          <FileUploadField label="File recap (Word/PDF)" kind="activity_recap"
            accept=".doc,.docx,.pdf,.txt" value={recapFile} onChange={setRecapFile} />
        </FieldRow>
        <TextArea label="Recap (văn bản)" {...register('recap_text')} />
      </form>
    </Modal>
  )
}
