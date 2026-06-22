/**
 * Tokinarc frontend — src/pages/purchasing/Suppliers.tsx
 * Nhà cung cấp: danh sách + thêm mới. GET/POST /purchasing/suppliers/.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Building, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { Modal } from '@/components/Modal'
import { PageHeader, Button, TableCard, Th, Td, RowMsg } from '@/components/ui'
import { FieldRow, TextInput } from '@/components/form'
import { useForm } from 'react-hook-form'

interface Supplier { id: string; code: string; name: string; tax_code: string; phone: string; email: string }
interface Form { code: string; name: string; tax_code: string; phone: string; email: string; address: string }

export function SuppliersPage() {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const { register, handleSubmit, reset } = useForm<Form>()
  const { data, isLoading } = useQuery({
    queryKey: ['suppliers'],
    queryFn: async () => (await api.get<{ results: Supplier[] }>('/purchasing/suppliers/')).data.results ?? [],
  })
  const save = useMutation({
    mutationFn: (d: Form) => api.post('/purchasing/suppliers/', d),
    onSuccess: () => { toast.success('Đã thêm NCC'); qc.invalidateQueries({ queryKey: ['suppliers'] }); setOpen(false); reset() },
    onError: (e) => toast.error(apiError(e)),
  })

  return (
    <div className="max-w-4xl">
      <PageHeader icon={<Building size={20} className="text-flame" />} title="Nhà cung cấp"
        subtitle={data ? `${data.length} NCC` : undefined}
        actions={<Button onClick={() => setOpen(true)}><Plus size={14} /> Thêm NCC</Button>} />
      <TableCard>
        <thead><tr className="border-b border-line"><Th>Mã</Th><Th>Tên</Th><Th>MST</Th><Th>Điện thoại</Th></tr></thead>
        <tbody>
          {isLoading && <RowMsg colSpan={4}>Đang tải…</RowMsg>}
          {data?.length === 0 && <RowMsg colSpan={4}>Chưa có NCC.</RowMsg>}
          {data?.map((s) => (
            <tr key={s.id} className="border-b border-line/50 last:border-0">
              <Td className="font-mono text-flame">{s.code}</Td><Td className="font-medium">{s.name}</Td>
              <Td className="text-txt-2">{s.tax_code || '—'}</Td><Td className="text-txt-2">{s.phone || '—'}</Td>
            </tr>
          ))}
        </tbody>
      </TableCard>

      <Modal open={open} onClose={() => setOpen(false)} title="Thêm nhà cung cấp"
        icon={<Building size={18} className="text-flame" />}
        footer={<><Button variant="ghost" onClick={() => setOpen(false)}>Hủy</Button>
          <Button onClick={handleSubmit((d) => save.mutate(d))} disabled={save.isPending}>Lưu</Button></>}>
        <form>
          <FieldRow>
            <TextInput label="Mã NCC *" placeholder="NCC-0001" {...register('code', { required: true })} />
            <TextInput label="Tên *" {...register('name', { required: true })} />
          </FieldRow>
          <FieldRow>
            <TextInput label="Mã số thuế" {...register('tax_code')} />
            <TextInput label="Điện thoại" {...register('phone')} />
          </FieldRow>
          <TextInput label="Email" full {...register('email')} />
          <TextInput label="Địa chỉ" full {...register('address')} />
        </form>
      </Modal>
    </div>
  )
}
