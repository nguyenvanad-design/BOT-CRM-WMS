/**
 * Tokinarc frontend — src/pages/crm/forms/QuoteForm.tsx
 * Modal tạo/sửa báo giá kèm dòng hàng (line items). total_vnd do server tính lại.
 * POST /crm/quotes/ hoặc PATCH /crm/quotes/{id}/ (gửi kèm mảng lines).
 */
import { useEffect, useState } from 'react'
import { useForm, useFieldArray, useWatch, type Control } from 'react-hook-form'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { FileText, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { compactVnd } from '@/lib/crm'
import { useCustomerOptions } from '@/lib/useCustomerOptions'
import type { Quote } from '@/lib/types'
import { Modal } from '@/components/Modal'
import { Button } from '@/components/ui'
import { FieldRow, TextInput, TextArea, SelectInput } from '@/components/form'

interface LineForm { part_no: string; part_name: string; qty: number; unit_price_vnd: number }
interface Form {
  customer: string; due_date: string; valid_until: string; discount_pct: number
  payment_terms_note: string; notes: string; lines: LineForm[]
}

const EMPTY_LINE: LineForm = { part_no: '', part_name: '', qty: 1, unit_price_vnd: 0 }
const EMPTY: Form = { customer: '', due_date: '', valid_until: '', discount_pct: 0, payment_terms_note: '', notes: '', lines: [{ ...EMPTY_LINE }] }

interface PInfo { name: string; available: number; discount: number; list: number; suggested: number; segment: string; contact: boolean }

/** Dòng thông tin dưới mỗi line: tồn khả dụng (cảnh báo nếu SL > tồn) + giá theo phân khúc. */
function LineInfo({ control, index, info }: { control: Control<Form>; index: number; info: PInfo }) {
  const qty = Number(useWatch({ control, name: `lines.${index}.qty` })) || 0
  const short = qty > info.available
  return (
    <div className="text-[11px] mt-0.5 ml-1 flex flex-wrap gap-x-3 gap-y-0.5">
      <span className={short ? 'text-danger font-semibold' : 'text-txt-2'}>
        Tồn khả dụng: {info.available.toLocaleString('vi-VN')}{short && ` ⚠ thiếu ${qty - info.available}`}
      </span>
      {info.contact
        ? <span className="text-warn">Giá liên hệ — tự nhập</span>
        : info.discount > 0
          ? <span className="text-ok">Giá {info.segment}: −{info.discount}% → {info.suggested.toLocaleString('vi-VN')}₫ (niêm yết {info.list.toLocaleString('vi-VN')})</span>
          : <span className="text-txt-2">Giá niêm yết: {info.list.toLocaleString('vi-VN')}₫</span>}
    </div>
  )
}

/** Tạm tính / chiết khấu / tổng phía client (server tính lại chính thức). */
function LiveTotal({ control }: { control: Control<Form> }) {
  const lines = useWatch({ control, name: 'lines' })
  const disc = Number(useWatch({ control, name: 'discount_pct' })) || 0
  const sub = (lines ?? []).reduce(
    (s, l) => s + (Number(l?.qty) || 0) * (Number(l?.unit_price_vnd) || 0), 0,
  )
  const total = Math.round(sub * (1 - disc / 100))
  return (
    <span className="tabular-nums">
      Tạm tính {compactVnd(sub)}
      {disc > 0 && <> · CK {disc}%</>}
      {' · '}<span className="text-flame font-semibold">Tổng {compactVnd(total)}</span>
    </span>
  )
}

export function QuoteForm({ open, onClose, editing }: {
  open: boolean; onClose: () => void; editing?: Quote | null
}) {
  const qc = useQueryClient()
  const { options: customers, isLoading: custLoading } = useCustomerOptions()
  const { register, handleSubmit, reset, control, setValue, getValues, formState: { errors } } =
    useForm<Form>({ defaultValues: EMPTY })
  const { fields, append, remove } = useFieldArray({ control, name: 'lines' })

  // Thông tin SP theo dòng: tồn khả dụng + giá theo phân khúc KH (gợi ý).
  const [lineInfo, setLineInfo] = useState<Record<number, PInfo>>({})

  // Nhập/đổi mã part → tra tên + giá đề xuất (theo KH) + tồn khả dụng.
  const fetchInfo = async (i: number, partNo: string) => {
    const code = partNo.trim()
    if (!code) { setLineInfo((m) => { const n = { ...m }; delete n[i]; return n }); return }
    try {
      const customer = getValues('customer')
      const { data } = await api.get(`/crm/part-quote-info/`, { params: { part_no: code, customer } })
      if (!data.found) { setLineInfo((m) => { const n = { ...m }; delete n[i]; return n }); return }
      const info: PInfo = {
        name: data.part_name, available: data.available_qty, discount: data.discount_pct,
        list: data.list_price_vnd, suggested: data.suggested_price_vnd,
        segment: data.segment, contact: data.is_contact_price,
      }
      setLineInfo((m) => ({ ...m, [i]: info }))
      // Tự điền tên nếu trống; tự điền GIÁ ĐỀ XUẤT nếu chưa nhập (giữ giá sale đã sửa).
      if (!getValues(`lines.${i}.part_name`)) setValue(`lines.${i}.part_name`, info.name)
      if (!Number(getValues(`lines.${i}.unit_price_vnd`))) setValue(`lines.${i}.unit_price_vnd`, info.suggested)
    } catch { /* lặng lẽ — không chặn nhập tay */ }
  }

  useEffect(() => {
    if (!open) return
    reset(editing ? {
      customer: editing.customer,
      due_date: editing.due_date ?? '',
      valid_until: editing.valid_until ?? '',
      discount_pct: Number(editing.discount_pct || 0),
      payment_terms_note: editing.payment_terms_note ?? '',
      notes: editing.notes,
      lines: editing.lines.length
        ? editing.lines.map((l) => ({
            part_no: l.part_no, part_name: l.part_name,
            qty: l.qty, unit_price_vnd: Number(l.unit_price_vnd || 0),
          }))
        : [{ ...EMPTY_LINE }],
    } : EMPTY)
  }, [open, editing, reset])

  const save = useMutation({
    mutationFn: (data: Form) => {
      const payload = {
        customer: data.customer,
        due_date: data.due_date || null,
        valid_until: data.valid_until || null,
        discount_pct: Number(data.discount_pct) || 0,
        payment_terms_note: data.payment_terms_note,
        notes: data.notes,
        lines: data.lines.map((l) => ({
          part_no: l.part_no, part_name: l.part_name,
          qty: Number(l.qty) || 0, unit_price_vnd: Number(l.unit_price_vnd) || 0,
        })),
      }
      return editing
        ? api.patch(`/crm/quotes/${editing.id}/`, payload)
        : api.post('/crm/quotes/', payload)
    },
    onSuccess: () => {
      toast.success(editing ? 'Đã cập nhật báo giá' : 'Đã tạo báo giá')
      qc.invalidateQueries({ queryKey: ['quotes'] })
      qc.invalidateQueries({ queryKey: ['dash'] })
      onClose()
    },
    onError: (e) => toast.error(apiError(e)),
  })

  return (
    <Modal
      open={open} onClose={onClose} wide
      title={editing ? `Sửa báo giá — ${editing.code}` : 'Tạo Báo giá'}
      icon={<FileText size={18} className="text-flame" />}
      footer={
        <>
          <div className="mr-auto text-xs text-txt-2">Tạm tính: <LiveTotal control={control} /></div>
          <Button variant="ghost" onClick={onClose}>Hủy</Button>
          <Button onClick={handleSubmit((d) => save.mutate(d))} disabled={save.isPending}>
            {save.isPending ? 'Đang lưu…' : editing ? 'Lưu' : 'Tạo'}
          </Button>
        </>
      }
    >
      <form onSubmit={handleSubmit((d) => save.mutate(d))}>
        <FieldRow>
          <SelectInput
            label="Khách hàng *" error={errors.customer?.message}
            placeholder={custLoading ? 'Đang tải KH…' : '— Chọn khách hàng —'}
            options={customers}
            {...register('customer', { required: 'Chọn khách hàng' })}
          />
          <TextInput label="Ngày dự kiến chốt" type="date" {...register('due_date')} />
        </FieldRow>
        <FieldRow>
          <TextInput label="Hạn hiệu lực giá" type="date" {...register('valid_until')} />
          <TextInput label="Chiết khấu (%)" type="number" step="0.01" min={0} max={100}
            {...register('discount_pct', { valueAsNumber: true })} />
        </FieldRow>

        {/* Line items */}
        <div className="mb-1.5 flex items-center justify-between">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-txt-2">Dòng hàng</span>
          <Button type="button" variant="ghost" size="sm" onClick={() => append({ ...EMPTY_LINE })}>
            <Plus size={13} /> Thêm dòng
          </Button>
        </div>
        <div className="space-y-2 mb-3 overflow-x-auto">
          {fields.map((f, i) => (
            <div key={f.id}>
              <div className="grid grid-cols-[1.2fr_1.6fr_0.6fr_1fr_auto] gap-2 items-start min-w-[460px]">
                <input placeholder="Mã part" {...register(`lines.${i}.part_no` as const, { required: true })}
                  onBlur={(e) => fetchInfo(i, e.target.value)}
                  className="bg-ink-3 border border-line rounded-md px-2 py-1.5 text-sm focus:border-flame focus:outline-none" />
                <input placeholder="Tên part" {...register(`lines.${i}.part_name` as const)}
                  className="bg-ink-3 border border-line rounded-md px-2 py-1.5 text-sm focus:border-flame focus:outline-none" />
                <input placeholder="SL" type="number" min={1}
                  {...register(`lines.${i}.qty` as const, { valueAsNumber: true })}
                  className="bg-ink-3 border border-line rounded-md px-2 py-1.5 text-sm focus:border-flame focus:outline-none" />
                <input placeholder="Đơn giá ₫" type="number" min={0}
                  {...register(`lines.${i}.unit_price_vnd` as const, { valueAsNumber: true })}
                  className="bg-ink-3 border border-line rounded-md px-2 py-1.5 text-sm focus:border-flame focus:outline-none" />
                <button type="button" onClick={() => fields.length > 1 && remove(i)}
                  className="text-txt-2 hover:text-danger p-1.5 disabled:opacity-30"
                  disabled={fields.length <= 1} aria-label="Xóa dòng">
                  <Trash2 size={15} />
                </button>
              </div>
              {lineInfo[i] && <LineInfo control={control} index={i} info={lineInfo[i]} />}
            </div>
          ))}
        </div>

        <TextArea label="Điều khoản thanh toán"
          placeholder="Sale thỏa thuận với khách, VD: 30% khi giao, 70% sau 30 ngày / 50% khi nhận, còn lại sau 45 ngày…"
          {...register('payment_terms_note')} />
        <TextArea label="Ghi chú" {...register('notes')} />
      </form>
    </Modal>
  )
}
