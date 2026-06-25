/**
 * Tokinarc frontend — src/pages/wms/forms/InboundForm.tsx
 * Tạo đơn nhập kho kèm dòng hàng (item + SL dự kiến + bin đích). POST /wms/inbound/.
 */
import { useEffect } from 'react'
import { useForm, useFieldArray, useWatch } from 'react-hook-form'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { PackageCheck, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { fetchAll } from '@/lib/list'
import { useWarehouseOptions, useItemOptions, splitItem } from '@/lib/useWmsOptions'
import { Modal } from '@/components/Modal'
import { Button } from '@/components/ui'
import { FieldRow, TextInput, SelectInput } from '@/components/form'

interface BinLite { id: string; full_code: string }
interface LineForm { item: string; qty_expected: number; target_bin: string }
interface Form { code: string; warehouse: string; lines: LineForm[] }
const EMPTY_LINE: LineForm = { item: '', qty_expected: 1, target_bin: '' }
const EMPTY: Form = { code: '', warehouse: '', lines: [{ ...EMPTY_LINE }] }

export function InboundForm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const { options: whs } = useWarehouseOptions()
  const { options: items, isLoading: itemsLoading } = useItemOptions()
  const bins = useQuery({ queryKey: ['wms-bins-opt'], queryFn: () => fetchAll<BinLite>('/wms/bins/') })
  const binItems = bins.data?.items ?? []
  const { register, handleSubmit, reset, control, formState: { errors } } = useForm<Form>({ defaultValues: EMPTY })
  const { fields, append, remove } = useFieldArray({ control, name: 'lines' })
  const watched = (useWatch({ control, name: 'lines' }) as LineForm[] | undefined) ?? []
  const itemLabel = (v: string) => items.find((o) => o.value === v)?.label ?? v
  const filled = watched.filter((l) => l?.item)
  const totalQty = filled.reduce((s, l) => s + (Number(l.qty_expected) || 0), 0)

  useEffect(() => { if (open) reset(EMPTY) }, [open, reset])

  const save = useMutation({
    mutationFn: (d: Form) => api.post('/wms/inbound/', {
      code: d.code,
      warehouse: d.warehouse,
      lines: d.lines.map((l) => ({
        ...splitItem(l.item),
        qty_expected: Number(l.qty_expected) || 0,
        target_bin: l.target_bin || null,
      })),
    }),
    onSuccess: () => {
      toast.success('Đã tạo đơn nhập')
      qc.invalidateQueries({ queryKey: ['wms-inbound-list'] })
      qc.invalidateQueries({ queryKey: ['wms'] })
      onClose()
    },
    onError: (e) => toast.error(apiError(e)),
  })

  return (
    <Modal open={open} onClose={onClose} wide title="Tạo đơn nhập kho"
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
          <TextInput label="Mã đơn *" placeholder="IN-2026-001" error={errors.code?.message}
            {...register('code', { required: 'Bắt buộc' })} />
          <SelectInput label="Kho *" error={errors.warehouse?.message}
            placeholder="— Chọn kho —" options={whs}
            {...register('warehouse', { required: 'Chọn kho' })} />
        </FieldRow>

        <div className="mb-1.5 flex items-center justify-between">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-txt-2">Dòng hàng</span>
          <Button type="button" variant="ghost" size="sm" onClick={() => append({ ...EMPTY_LINE })}>
            <Plus size={13} /> Thêm dòng
          </Button>
        </div>
        <div className="space-y-2 mb-3 overflow-x-auto">
          {fields.map((f, i) => (
            <div key={f.id} className="grid grid-cols-[1.2fr_0.5fr_1fr_auto] gap-2 items-start min-w-[480px]">
              <select {...register(`lines.${i}.item` as const, { required: true })}
                className="bg-ink-3 border border-line rounded-md px-2 py-1.5 text-sm focus:border-flame focus:outline-none">
                <option value="">{itemsLoading ? 'Đang tải…' : '— Mặt hàng —'}</option>
                {items.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              <input type="number" min={1} placeholder="SL"
                {...register(`lines.${i}.qty_expected` as const, { valueAsNumber: true })}
                className="bg-ink-3 border border-line rounded-md px-2 py-1.5 text-sm focus:border-flame focus:outline-none" />
              <select {...register(`lines.${i}.target_bin` as const)}
                className="bg-ink-3 border border-line rounded-md px-2 py-1.5 text-sm focus:border-flame focus:outline-none">
                <option value="">— Bin đích —</option>
                {binItems.map((b) => <option key={b.id} value={b.id}>{b.full_code}</option>)}
              </select>
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
                  <span className="tabular-nums text-txt-2 ml-3">× {Number(l.qty_expected) || 0}</span>
                </li>
              ))}
            </ul>
            <div className="text-xs text-txt-2 mt-1">{filled.length} mặt hàng · tổng SL dự kiến <b className="text-txt">{totalQty}</b></div>
          </div>
        )}
      </form>
    </Modal>
  )
}
