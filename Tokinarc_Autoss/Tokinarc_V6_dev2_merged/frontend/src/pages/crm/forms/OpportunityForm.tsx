/**
 * Tokinarc frontend — src/pages/crm/forms/OpportunityForm.tsx
 * Modal tạo/sửa cơ hội. POST /crm/opportunities/ hoặc PATCH .../{id}/.
 */
import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Target } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { OPP_STAGE_LABEL } from '@/lib/crm'
import { useCustomerOptions, optionsFromLabels } from '@/lib/useCustomerOptions'
import type { Opportunity } from '@/lib/types'
import { Modal } from '@/components/Modal'
import { Button } from '@/components/ui'
import { FieldRow, TextInput, TextArea, SelectInput } from '@/components/form'

interface Form {
  customer: string; title: string; stage: string
  interest_part: string; interest_qty: number
  est_value_vnd: number; probability: number
  expected_close: string; notes: string
}

const EMPTY: Form = {
  customer: '', title: '', stage: 'prospect',
  interest_part: '', interest_qty: 0,
  est_value_vnd: 0, probability: 0, expected_close: '', notes: '',
}

export function OpportunityForm({ open, onClose, editing, preset, onSaved }: {
  open: boolean; onClose: () => void; editing?: Opportunity | null
  /** Điền sẵn khi tạo mới (vd từ Lead/Customer 360: khách + nhu cầu SP×SL → giá trị). */
  preset?: { customer?: string; title?: string; notes?: string
             interest_part?: string; interest_qty?: number; est_value_vnd?: number }
  /** Gọi sau khi tạo/sửa thành công — để trang cha refetch query riêng của mình. */
  onSaved?: () => void
}) {
  const qc = useQueryClient()
  const { options: customers, isLoading: custLoading } = useCustomerOptions()
  const { register, handleSubmit, reset, watch, setValue, formState: { errors } } =
    useForm<Form>({ defaultValues: EMPTY })

  useEffect(() => {
    if (!open) return
    reset(editing ? {
      customer: editing.customer, title: editing.title, stage: editing.stage,
      interest_part: '', interest_qty: 0,
      est_value_vnd: Number(editing.est_value_vnd || 0), probability: editing.probability,
      expected_close: editing.expected_close ?? '', notes: editing.notes,
    } : { ...EMPTY, ...(preset ?? {}) })
  }, [open, editing, preset, reset])

  // Tự tính Giá trị = giá bán × số lượng khi chọn sản phẩm quan tâm.
  const partCode = watch('interest_part')
  const qty = Number(watch('interest_qty')) || 0
  const partQ = useQuery({
    queryKey: ['part-price', partCode],
    queryFn: async () => (await api.get(`/catalog/parts/${encodeURIComponent(partCode)}/`)).data,
    enabled: open && !!partCode && partCode.length >= 2,
    retry: false,
  })
  const unitPrice = Number(partQ.data?.effective_price_vnd || 0)
  useEffect(() => {
    if (unitPrice && qty) setValue('est_value_vnd', unitPrice * qty)
  }, [unitPrice, qty, setValue])

  const save = useMutation({
    mutationFn: (data: Form) => {
      const payload = { ...data, expected_close: data.expected_close || null }
      return editing
        ? api.patch(`/crm/opportunities/${editing.id}/`, payload)
        : api.post('/crm/opportunities/', payload)
    },
    onSuccess: () => {
      toast.success(editing ? 'Đã cập nhật cơ hội' : 'Đã tạo cơ hội')
      qc.invalidateQueries({ queryKey: ['opportunities'] })
      qc.invalidateQueries({ queryKey: ['pipeline'] })
      qc.invalidateQueries({ queryKey: ['dash'] })
      onSaved?.()
      onClose()
    },
    onError: (e) => toast.error(apiError(e)),
  })

  return (
    <Modal
      open={open} onClose={onClose}
      title={editing ? `Sửa cơ hội` : 'Tạo Opportunity'}
      icon={<Target size={18} className="text-flame" />}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Hủy</Button>
          <Button onClick={handleSubmit((d) => save.mutate(d))} disabled={save.isPending}>
            {save.isPending ? 'Đang lưu…' : editing ? 'Lưu' : 'Tạo'}
          </Button>
        </>
      }
    >
      <form onSubmit={handleSubmit((d) => save.mutate(d))}>
        <SelectInput
          label="Khách hàng *" full error={errors.customer?.message}
          placeholder={custLoading ? 'Đang tải KH…' : '— Chọn khách hàng —'}
          options={customers}
          {...register('customer', { required: 'Chọn khách hàng' })}
        />
        <TextInput label="Tên cơ hội *" full error={errors.title?.message}
          {...register('title', { required: 'Bắt buộc' })} />
        <FieldRow>
          <SelectInput label="Giai đoạn" options={optionsFromLabels(OPP_STAGE_LABEL)} {...register('stage')} />
          <TextInput label="Xác suất (%)" type="number" min={0} max={100}
            {...register('probability', { valueAsNumber: true })} />
        </FieldRow>
        <FieldRow>
          <TextInput label="Sản phẩm quan tâm (mã)" placeholder="VD: 001002"
            {...register('interest_part')} />
          <TextInput label="Số lượng" type="number" min={0}
            {...register('interest_qty', { valueAsNumber: true })} />
        </FieldRow>
        {partCode && (
          <p className="text-[11px] text-txt-2 -mt-1 mb-2">
            {unitPrice
              ? `Giá bán ${unitPrice.toLocaleString('vi-VN')}₫ × ${qty} → tự điền Giá trị ${(unitPrice * qty).toLocaleString('vi-VN')}₫`
              : 'Không tìm thấy giá của mã này — nhập Giá trị tay bên dưới.'}
          </p>
        )}
        <FieldRow>
          <TextInput label="Giá trị ước tính (₫)" type="number" min={0}
            {...register('est_value_vnd', { valueAsNumber: true })} />
          <TextInput label="Dự kiến chốt" type="date" {...register('expected_close')} />
        </FieldRow>
        <TextArea label="Ghi chú" {...register('notes')} />
      </form>
    </Modal>
  )
}
