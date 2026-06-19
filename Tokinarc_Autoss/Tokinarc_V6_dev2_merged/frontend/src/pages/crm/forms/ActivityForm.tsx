/**
 * Tokinarc frontend — src/pages/crm/forms/ActivityForm.tsx
 * Ghi nhận hoạt động chăm sóc KH. POST /crm/activities/.
 */
import { useEffect } from 'react'
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

interface Form { customer: string; opportunity: string; activity_type: string; content: string }
const EMPTY: Form = { customer: '', opportunity: '', activity_type: 'call', content: '' }

export function ActivityForm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const { options: customers, isLoading } = useCustomerOptions()
  const { opps } = useOpportunityOptions()
  const { register, handleSubmit, reset, watch, formState: { errors } } = useForm<Form>({ defaultValues: EMPTY })
  const selectedCust = watch('customer')
  const oppOptions = opps.filter((o) => o.customer === selectedCust).map((o) => ({ value: o.id, label: o.title }))

  useEffect(() => { if (open) reset(EMPTY) }, [open, reset])

  const save = useMutation({
    mutationFn: (d: Form) => api.post('/crm/activities/', { ...d, opportunity: d.opportunity || null }),
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
      </form>
    </Modal>
  )
}
