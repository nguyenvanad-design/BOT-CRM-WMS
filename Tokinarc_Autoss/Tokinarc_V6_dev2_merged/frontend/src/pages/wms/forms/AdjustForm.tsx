/**
 * Tokinarc frontend — src/pages/wms/forms/AdjustForm.tsx
 * Điều chỉnh tồn cho 1 dòng tồn (POST /wms/inventory/adjust/). Bin & mặt hàng
 * cố định theo dòng đã chọn; chỉ nhập số lượng mới + lý do.
 */
import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { SlidersHorizontal } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import type { InventoryItem } from '@/lib/types'
import { Modal } from '@/components/Modal'
import { Button } from '@/components/ui'
import { FieldRow, TextInput, TextArea, SelectInput } from '@/components/form'

interface Form { new_qty: number; reason: string; note: string }

export function AdjustForm({ open, onClose, item }: {
  open: boolean; onClose: () => void; item: InventoryItem | null
}) {
  const qc = useQueryClient()
  const { register, handleSubmit, reset, formState: { errors } } = useForm<Form>({
    defaultValues: { new_qty: 0, reason: 'adjust', note: '' },
  })

  useEffect(() => {
    if (open && item) reset({ new_qty: item.qty_on_hand, reason: 'adjust', note: '' })
  }, [open, item, reset])

  const save = useMutation({
    mutationFn: (data: Form) => api.post('/wms/inventory/adjust/', {
      bin: item!.bin,
      part: item!.part ?? undefined,
      torch: item!.torch ?? undefined,
      new_qty: data.new_qty,
      reason: data.reason,
      note: data.note,
    }),
    onSuccess: () => {
      toast.success('Đã điều chỉnh tồn')
      qc.invalidateQueries({ queryKey: ['wms-inventory'] })
      qc.invalidateQueries({ queryKey: ['wms'] })
      qc.invalidateQueries({ queryKey: ['wms-moves'] })
      onClose()
    },
    onError: (e) => toast.error(apiError(e)),
  })

  return (
    <Modal open={open} onClose={onClose} title="Điều chỉnh tồn"
      icon={<SlidersHorizontal size={18} className="text-flame" />}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Hủy</Button>
          <Button onClick={handleSubmit((d) => save.mutate(d))} disabled={save.isPending}>
            {save.isPending ? 'Đang lưu…' : 'Lưu'}
          </Button>
        </>
      }>
      {item && (
        <>
          <div className="bg-ink-3 rounded-md px-3 py-2 mb-3 text-sm">
            <div className="font-medium">{item.item_name}</div>
            <div className="text-xs text-txt-2 mt-0.5">
              Vị trí <span className="font-mono">{item.bin_code}</span> · Tồn hiện tại: {item.qty_on_hand}
            </div>
          </div>
          <form onSubmit={handleSubmit((d) => save.mutate(d))}>
            <FieldRow>
              <TextInput label="Số lượng mới *" type="number" min={0} error={errors.new_qty?.message}
                {...register('new_qty', { valueAsNumber: true, required: 'Bắt buộc', min: { value: 0, message: '≥ 0' } })} />
              <SelectInput label="Lý do"
                options={[{ value: 'adjust', label: 'Điều chỉnh' }, { value: 'return', label: 'Trả hàng' }]}
                {...register('reason')} />
            </FieldRow>
            <TextArea label="Ghi chú" {...register('note')} />
          </form>
        </>
      )}
    </Modal>
  )
}
