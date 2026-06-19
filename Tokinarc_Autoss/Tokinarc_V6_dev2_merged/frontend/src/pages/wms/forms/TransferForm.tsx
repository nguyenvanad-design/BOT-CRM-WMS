/**
 * Tokinarc frontend — src/pages/wms/forms/TransferForm.tsx
 * Chuyển kho 1 dòng tồn sang bin khác (POST /wms/inventory/transfer/).
 */
import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeftRight } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import type { InventoryItem } from '@/lib/types'
import type { Option } from '@/components/form'
import { Modal } from '@/components/Modal'
import { Button } from '@/components/ui'
import { FieldRow, TextInput, SelectInput } from '@/components/form'

interface Form { to_bin: string; qty: number }

export function TransferForm({ open, onClose, item, binOptions }: {
  open: boolean; onClose: () => void; item: InventoryItem | null; binOptions: Option[]
}) {
  const qc = useQueryClient()
  const { register, handleSubmit, reset, formState: { errors } } = useForm<Form>({
    defaultValues: { to_bin: '', qty: 1 },
  })

  useEffect(() => {
    if (open) reset({ to_bin: '', qty: 1 })
  }, [open, item, reset])

  // Loại bin hiện tại khỏi danh sách đích
  const targets = binOptions.filter((b) => b.value !== item?.bin)

  const save = useMutation({
    mutationFn: (data: Form) => api.post('/wms/inventory/transfer/', {
      from_bin: item!.bin,
      to_bin: data.to_bin,
      part: item!.part ?? undefined,
      torch: item!.torch ?? undefined,
      qty: data.qty,
    }),
    onSuccess: () => {
      toast.success('Đã chuyển kho')
      qc.invalidateQueries({ queryKey: ['wms-inventory'] })
      qc.invalidateQueries({ queryKey: ['wms'] })
      qc.invalidateQueries({ queryKey: ['wms-moves'] })
      onClose()
    },
    onError: (e) => toast.error(apiError(e)),
  })

  return (
    <Modal open={open} onClose={onClose} title="Chuyển kho"
      icon={<ArrowLeftRight size={18} className="text-flame" />}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Hủy</Button>
          <Button onClick={handleSubmit((d) => save.mutate(d))} disabled={save.isPending}>
            {save.isPending ? 'Đang chuyển…' : 'Chuyển'}
          </Button>
        </>
      }>
      {item && (
        <>
          <div className="bg-ink-3 rounded-md px-3 py-2 mb-3 text-sm">
            <div className="font-medium">{item.item_name}</div>
            <div className="text-xs text-txt-2 mt-0.5">
              Từ <span className="font-mono">{item.bin_code}</span> · Khả dụng: {item.qty_available}
            </div>
          </div>
          <form onSubmit={handleSubmit((d) => save.mutate(d))}>
            <SelectInput label="Bin đích *" full error={errors.to_bin?.message}
              placeholder="— Chọn vị trí đích —" options={targets}
              {...register('to_bin', { required: 'Chọn bin đích' })} />
            <FieldRow>
              <TextInput label="Số lượng *" type="number" min={1} max={item.qty_available}
                error={errors.qty?.message}
                {...register('qty', {
                  valueAsNumber: true, required: 'Bắt buộc',
                  min: { value: 1, message: '≥ 1' },
                  max: { value: item.qty_available, message: `Tối đa ${item.qty_available}` },
                })} />
              <div />
            </FieldRow>
          </form>
        </>
      )}
    </Modal>
  )
}
