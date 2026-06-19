/**
 * Tokinarc frontend — src/pages/wms/forms/ASNForm.tsx
 * Tạo ASN (báo trước hàng về). POST /wms/asn/.
 */
import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Inbox } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { useWarehouseOptions } from '@/lib/useWmsOptions'
import { Modal } from '@/components/Modal'
import { Button } from '@/components/ui'
import { FieldRow, TextInput, TextArea, SelectInput } from '@/components/form'

interface Form { code: string; warehouse: string; supplier: string; eta: string; notes: string }
const EMPTY: Form = { code: '', warehouse: '', supplier: '', eta: '', notes: '' }

export function ASNForm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const { options: whs, isLoading } = useWarehouseOptions()
  const { register, handleSubmit, reset, formState: { errors } } = useForm<Form>({ defaultValues: EMPTY })

  useEffect(() => { if (open) reset(EMPTY) }, [open, reset])

  const save = useMutation({
    mutationFn: (d: Form) => api.post('/wms/asn/', { ...d, eta: d.eta || null }),
    onSuccess: () => {
      toast.success('Đã tạo ASN')
      qc.invalidateQueries({ queryKey: ['wms-asn-list'] })
      onClose()
    },
    onError: (e) => toast.error(apiError(e)),
  })

  return (
    <Modal open={open} onClose={onClose} title="Tạo ASN" icon={<Inbox size={18} className="text-flame" />}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Hủy</Button>
          <Button onClick={handleSubmit((d) => save.mutate(d))} disabled={save.isPending}>
            {save.isPending ? 'Đang lưu…' : 'Tạo'}
          </Button>
        </>
      }>
      <form onSubmit={handleSubmit((d) => save.mutate(d))}>
        <FieldRow>
          <TextInput label="Mã ASN *" placeholder="ASN-2026-001" error={errors.code?.message}
            {...register('code', { required: 'Bắt buộc' })} />
          <SelectInput label="Kho *" error={errors.warehouse?.message}
            placeholder={isLoading ? 'Đang tải…' : '— Chọn kho —'} options={whs}
            {...register('warehouse', { required: 'Chọn kho' })} />
        </FieldRow>
        <FieldRow>
          <TextInput label="Nhà cung cấp" {...register('supplier')} />
          <TextInput label="ETA (dự kiến về)" type="date" {...register('eta')} />
        </FieldRow>
        <TextArea label="Ghi chú" {...register('notes')} />
      </form>
    </Modal>
  )
}
