/**
 * Tokinarc frontend — src/pages/crm/Returns.tsx
 * Trả hàng (RMA): tạo phiếu → kho nhận lại (+tồn). Hoàn tiền do MISA.
 * /sales/returns/ + action receive.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Undo2, Plus, PackageCheck, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { compactVnd } from '@/lib/crm'
import { isManager, isWmsControl, useAuth } from '@/lib/auth/store'
import { useCustomerOptions } from '@/lib/useCustomerOptions'
import { Modal } from '@/components/Modal'
import { PageHeader, Button, Tag, TableCard, Th, Td, RowMsg } from '@/components/ui'

interface RLine { part: string; qty: number; unit_price: number }
interface RO { id: string; code: string; customer_name: string; warehouse_code: string; status: string; status_display: string; total_vnd: string; reason: string; created_at: string }
const TONE: Record<string, 'gray' | 'ok' | 'danger'> = { draft: 'gray', received: 'ok', cancelled: 'danger' }

export function ReturnsPage() {
  const qc = useQueryClient()
  const role = useAuth((s) => s.user?.role)
  const canCreate = isManager(role) || role === 'sales'
  const canReceive = isWmsControl(role) || role === 'warehouse'
  const [open, setOpen] = useState(false)
  const [customer, setCustomer] = useState(''); const [warehouse, setWarehouse] = useState('')
  const [reason, setReason] = useState(''); const [lines, setLines] = useState<RLine[]>([{ part: '', qty: 1, unit_price: 0 }])

  const { options: customers } = useCustomerOptions()
  const whs = useQuery({ queryKey: ['wh-list'], queryFn: async () => (await api.get<{ results: { id: string; code: string }[] }>('/wms/warehouses/')).data.results ?? [] })
  const { data, isLoading } = useQuery({ queryKey: ['returns'], queryFn: async () => (await api.get<{ results: RO[] }>('/sales/returns/')).data.results ?? [] })

  const inval = () => { qc.invalidateQueries({ queryKey: ['returns'] }); qc.invalidateQueries({ queryKey: ['wms-inventory'] }) }
  const create = useMutation({
    mutationFn: () => api.post('/sales/returns/', {
      customer, warehouse, reason,
      lines: lines.filter((l) => l.part).map((l) => ({ part: l.part.trim(), qty: Number(l.qty), unit_price: Number(l.unit_price) })),
    }),
    onSuccess: (r) => { toast.success(`Đã tạo ${r.data.code}`); inval(); setOpen(false); setLines([{ part: '', qty: 1, unit_price: 0 }]); setCustomer(''); setReason('') },
    onError: (e) => toast.error(apiError(e)),
  })
  const receive = useMutation({
    mutationFn: (id: string) => api.post(`/sales/returns/${id}/receive/`),
    onSuccess: () => { toast.success('Đã nhận lại kho (+tồn)'); inval() },
    onError: (e) => toast.error(apiError(e)),
  })

  return (
    <div className="max-w-5xl">
      <PageHeader icon={<Undo2 size={20} className="text-flame" />} title="Trả hàng (RMA)"
        subtitle={data ? `${data.length} phiếu trả` : undefined}
        actions={canCreate && <Button onClick={() => setOpen(true)}><Plus size={14} /> Tạo phiếu trả</Button>} />
      <TableCard>
        <thead><tr className="border-b border-line">
          <Th>Mã</Th><Th>Khách hàng</Th><Th>Kho</Th><Th>Lý do</Th><Th className="text-right">Giá trị</Th>
          <Th>Trạng thái</Th><Th className="text-right">Hành động</Th>
        </tr></thead>
        <tbody>
          {isLoading && <RowMsg colSpan={7}>Đang tải…</RowMsg>}
          {data?.length === 0 && <RowMsg colSpan={7}>Chưa có phiếu trả hàng.</RowMsg>}
          {data?.map((o) => (
            <tr key={o.id} className="border-b border-line/50 last:border-0 hover:bg-ink-3/40">
              <Td className="font-mono text-flame">{o.code}</Td>
              <Td className="font-medium">{o.customer_name}</Td>
              <Td className="text-txt-2">{o.warehouse_code}</Td>
              <Td className="text-txt-2 text-xs">{o.reason || '—'}</Td>
              <Td className="text-right tabular-nums">{compactVnd(o.total_vnd)}</Td>
              <Td><Tag tone={TONE[o.status] ?? 'gray'}>{o.status_display}</Tag></Td>
              <Td className="text-right">
                {o.status === 'draft' && canReceive && (
                  <Button size="sm" variant="success" onClick={() => receive.mutate(o.id)}><PackageCheck size={13} /> Nhận lại</Button>
                )}
              </Td>
            </tr>
          ))}
        </tbody>
      </TableCard>

      <Modal open={open} onClose={() => setOpen(false)} title="Tạo phiếu trả hàng"
        icon={<Undo2 size={18} className="text-flame" />}
        footer={<><Button variant="ghost" onClick={() => setOpen(false)}>Hủy</Button>
          <Button onClick={() => create.mutate()} disabled={create.isPending || !customer || !warehouse}>Tạo</Button></>}>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <Sel label="Khách hàng *" value={customer} onChange={setCustomer} opts={customers.map((c) => ({ v: c.value, l: c.label }))} />
            <Sel label="Kho nhận *" value={warehouse} onChange={setWarehouse} opts={(whs.data ?? []).map((w) => ({ v: w.id, l: w.code }))} />
          </div>
          <input placeholder="Lý do trả" value={reason} onChange={(e) => setReason(e.target.value)}
            className="w-full bg-ink-3 border border-line rounded-md px-3 py-2 text-sm" />
          <div className="text-xs text-txt-2">Dòng hàng trả:</div>
          {lines.map((l, i) => (
            <div key={i} className="flex gap-2 items-center">
              <input placeholder="Mã part" value={l.part} onChange={(e) => setLines((a) => a.map((x, j) => j === i ? { ...x, part: e.target.value } : x))}
                className="flex-1 bg-ink-3 border border-line rounded-md px-2 py-1.5 text-sm" />
              <input placeholder="SL" type="number" value={l.qty} onChange={(e) => setLines((a) => a.map((x, j) => j === i ? { ...x, qty: Number(e.target.value) } : x))}
                className="w-20 bg-ink-3 border border-line rounded-md px-2 py-1.5 text-sm" />
              <input placeholder="Đơn giá" type="number" value={l.unit_price} onChange={(e) => setLines((a) => a.map((x, j) => j === i ? { ...x, unit_price: Number(e.target.value) } : x))}
                className="w-28 bg-ink-3 border border-line rounded-md px-2 py-1.5 text-sm" />
              <button onClick={() => setLines((a) => a.filter((_, j) => j !== i))} className="text-txt-2 hover:text-danger"><Trash2 size={14} /></button>
            </div>
          ))}
          <Button variant="ghost" size="sm" onClick={() => setLines((a) => [...a, { part: '', qty: 1, unit_price: 0 }])}><Plus size={13} /> Thêm dòng</Button>
        </div>
      </Modal>
    </div>
  )
}

function Sel({ label, value, onChange, opts }: { label: string; value: string; onChange: (v: string) => void; opts: { v: string; l: string }[] }) {
  return (
    <div>
      <label className="block text-[11px] uppercase tracking-wide text-txt-2 font-semibold mb-1">{label}</label>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="w-full bg-ink-3 border border-line rounded-md px-3 py-2 text-sm">
        <option value="">— Chọn —</option>
        {opts.map((o) => <option key={o.v} value={o.v}>{o.l}</option>)}
      </select>
    </div>
  )
}
