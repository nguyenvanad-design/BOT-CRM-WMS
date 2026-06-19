/**
 * Tokinarc frontend — src/pages/wms/forms/OutboundForm.tsx
 * Tạo đơn xuất kho kèm dòng hàng. POST /wms/outbound/.
 */
import { useEffect } from 'react'
import { useForm, useFieldArray } from 'react-hook-form'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { PackageCheck, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { useWarehouseOptions, useItemOptions, splitItem } from '@/lib/useWmsOptions'
import { useCustomerOptions } from '@/lib/useCustomerOptions'
import { RULE_LABEL } from '@/lib/wms'
import { Modal } from '@/components/Modal'
import { Button } from '@/components/ui'
import { FieldRow, TextInput, SelectInput } from '@/components/form'

interface LineForm { item: string; qty_ordered: number }
interface Form {
  code: string; warehouse: string; customer: string
  sales_order_code: string; rule: string; lines: LineForm[]
}
const EMPTY_LINE: LineForm = { item: '', qty_ordered: 1 }
const EMPTY: Form = { code: '', warehouse: '', customer: '', sales_order_code: '', rule: 'FIFO', lines: [{ ...EMPTY_LINE }] }

export function OutboundForm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const { options: whs } = useWarehouseOptions()
  const { options: items, isLoading: itemsLoading } = useItemOptions()
  const { options: customers } = useCustomerOptions()
  const { register, handleSubmit, reset, control, formState: { errors } } = useForm<Form>({ defaultValues: EMPTY })
  const { fields, append, remove } = useFieldArray({ control, name: 'lines' })

  useEffect(() => { if (open) reset(EMPTY) }, [open, reset])

  const save = useMutation({
    mutationFn: (d: Form) => api.post('/wms/outbound/', {
      code: d.code,
      warehouse: d.warehouse,
      customer: d.customer || null,
      sales_order_code: d.sales_order_code,
      rule: d.rule,
      lines: d.lines.map((l) => ({ ...splitItem(l.item), qty_ordered: Number(l.qty_ordered) || 0 })),
    }),
    onSuccess: () => {
      toast.success('Đã tạo đơn xuất')
      qc.invalidateQueries({ queryKey: ['wms-outbound-list'] })
      qc.invalidateQueries({ queryKey: ['wms'] })
      onClose()
    },
    onError: (e) => toast.error(apiError(e)),
  })

  return (
    <Modal open={open} onClose={onClose} wide title="Tạo đơn xuất kho"
      icon={<PackageCheck size={18} className="text-flame" />}
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
          <TextInput label="Mã đơn *" placeholder="OUT-2026-001" error={errors.code?.message}
            {...register('code', { required: 'Bắt buộc' })} />
          <SelectInput label="Kho *" error={errors.warehouse?.message}
            placeholder="— Chọn kho —" options={whs}
            {...register('warehouse', { required: 'Chọn kho' })} />
        </FieldRow>
        <FieldRow>
          <SelectInput label="Khách hàng" placeholder="— (tùy chọn) —" options={customers} {...register('customer')} />
          <SelectInput label="Rule soạn hàng"
            options={(Object.keys(RULE_LABEL) as (keyof typeof RULE_LABEL)[]).map((k) => ({ value: k, label: RULE_LABEL[k] }))}
            {...register('rule')} />
        </FieldRow>

        <div className="mb-1.5 flex items-center justify-between">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-txt-2">Dòng hàng</span>
          <Button type="button" variant="ghost" size="sm" onClick={() => append({ ...EMPTY_LINE })}>
            <Plus size={13} /> Thêm dòng
          </Button>
        </div>
        <div className="space-y-2 mb-3 overflow-x-auto">
          {fields.map((f, i) => (
            <div key={f.id} className="grid grid-cols-[1fr_0.5fr_auto] gap-2 items-start min-w-[420px]">
              <select {...register(`lines.${i}.item` as const, { required: true })}
                className="bg-ink-3 border border-line rounded-md px-2 py-1.5 text-sm focus:border-flame focus:outline-none">
                <option value="">{itemsLoading ? 'Đang tải…' : '— Chọn mặt hàng —'}</option>
                {items.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              <input type="number" min={1} placeholder="SL"
                {...register(`lines.${i}.qty_ordered` as const, { valueAsNumber: true })}
                className="bg-ink-3 border border-line rounded-md px-2 py-1.5 text-sm focus:border-flame focus:outline-none" />
              <button type="button" onClick={() => fields.length > 1 && remove(i)}
                className="text-txt-2 hover:text-danger p-1.5 disabled:opacity-30" disabled={fields.length <= 1} aria-label="Xóa">
                <Trash2 size={15} />
              </button>
            </div>
          ))}
        </div>
      </form>
    </Modal>
  )
}
