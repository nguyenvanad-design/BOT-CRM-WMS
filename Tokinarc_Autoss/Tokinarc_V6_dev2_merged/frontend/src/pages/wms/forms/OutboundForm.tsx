/**
 * Tokinarc frontend — src/pages/wms/forms/OutboundForm.tsx
 * Tạo đơn xuất kho kèm dòng hàng. POST /wms/outbound/.
 */
import { useEffect, useState } from 'react'
import { useForm, useFieldArray, useWatch } from 'react-hook-form'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Camera, PackageCheck, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { resolveScanToItem } from '@/lib/scanResolve'
import { useWarehouseOptions, useItemOptions, splitItem } from '@/lib/useWmsOptions'
import { useCustomerOptions } from '@/lib/useCustomerOptions'
import { RULE_LABEL } from '@/lib/wms'
import { CameraScanner } from '@/components/CameraScanner'
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
  const { register, handleSubmit, reset, control, setValue, formState: { errors } } = useForm<Form>({ defaultValues: EMPTY })
  const { fields, append, remove } = useFieldArray({ control, name: 'lines' })
  const watched = (useWatch({ control, name: 'lines' }) as LineForm[] | undefined) ?? []
  const itemLabel = (v: string) => items.find((o) => o.value === v)?.label ?? v
  const filled = watched.filter((l) => l?.item)
  const totalQty = filled.reduce((s, l) => s + (Number(l.qty_ordered) || 0), 0)
  const [showCam, setShowCam] = useState(false)

  // Quét camera NGAY KHI TẠO PHIẾU XUẤT: quét mã → tự thêm dòng; cùng mã → +1 SL.
  const onScan = async (raw: string) => {
    const val = await resolveScanToItem(raw, items)
    if (!val) { toast.error(`Không tìm thấy mặt hàng cho mã "${raw}"`); return }
    const idx = watched.findIndex((l) => l?.item === val)
    if (idx >= 0) {
      setValue(`lines.${idx}.qty_ordered`, (Number(watched[idx].qty_ordered) || 0) + 1)
    } else {
      const empty = watched.findIndex((l) => !l?.item)
      if (empty >= 0) setValue(`lines.${empty}.item`, val)
      else append({ ...EMPTY_LINE, item: val })
    }
    toast.success(`✓ ${itemLabel(val)}`)
  }

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
          <span className="inline-flex gap-1.5">
            <Button type="button" variant="ghost" size="sm" onClick={() => setShowCam((v) => !v)}>
              <Camera size={13} /> {showCam ? 'Tắt quét' : 'Quét mã'}
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => append({ ...EMPTY_LINE })}>
              <Plus size={13} /> Thêm dòng
            </Button>
          </span>
        </div>
        {showCam && (
          <div className="mb-2">
            <CameraScanner onScan={onScan} />
            <p className="text-[11px] text-txt-2 mt-1">Quét tem hàng → tự thêm dòng; quét lại cùng mã → +1 SL.</p>
          </div>
        )}
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

        {/* Xem trước nội dung sắp tạo */}
        {filled.length > 0 && (
          <div className="border-t border-line pt-2 mt-1">
            <div className="text-[11px] uppercase tracking-wide text-txt-2 mb-1">Xem trước</div>
            <ul className="text-sm space-y-0.5">
              {filled.map((l, i) => (
                <li key={i} className="flex justify-between">
                  <span className="truncate">{itemLabel(l.item)}</span>
                  <span className="tabular-nums text-txt-2 ml-3">× {Number(l.qty_ordered) || 0}</span>
                </li>
              ))}
            </ul>
            <div className="text-xs text-txt-2 mt-1">{filled.length} mặt hàng · tổng SL xuất <b className="text-txt">{totalQty}</b></div>
          </div>
        )}
      </form>
    </Modal>
  )
}
