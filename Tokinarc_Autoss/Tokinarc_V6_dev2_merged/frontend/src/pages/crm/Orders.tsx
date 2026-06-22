/**
 * Tokinarc frontend — src/pages/crm/Orders.tsx
 * Đơn bán: Ký → Giao (tự sinh phiếu xuất WMS) → Xuất hóa đơn (→MISA) → Thu tiền.
 * /sales/orders/ + actions sign/ship/create-invoice; /sales/payments/.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ShoppingBag, PenLine, Truck, FileText, Wallet } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { compactVnd, formatVnd, formatDate } from '@/lib/crm'
import { isManager, useAuth } from '@/lib/auth/store'
import { Modal } from '@/components/Modal'
import { PageHeader, Button, Tag, TableCard, Th, Td, RowMsg } from '@/components/ui'

interface Order {
  id: string; code: string; customer_name: string; issued_date: string
  total_vnd: string; paid_vnd: string; debt_vnd: string; status: string
}
const LABEL: Record<string, string> = {
  draft: 'Nháp', pending: 'Chờ ký', active: 'Hiệu lực', shipping: 'Đang giao',
  completed: 'Hoàn tất', cancelled: 'Hủy',
}
const TONE: Record<string, 'gray' | 'blue' | 'warn' | 'ok' | 'danger' | 'purple'> = {
  draft: 'gray', pending: 'warn', active: 'blue', shipping: 'purple', completed: 'ok', cancelled: 'danger',
}

export function OrdersPage() {
  const qc = useQueryClient()
  const canMng = isManager(useAuth((s) => s.user?.role))
  const [payFor, setPayFor] = useState<Order | null>(null)
  const [amt, setAmt] = useState('')

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['orders'],
    queryFn: async () => (await api.get<{ results: Order[] }>('/sales/orders/')).data.results ?? [],
  })
  const inval = () => { qc.invalidateQueries({ queryKey: ['orders'] }); qc.invalidateQueries({ queryKey: ['invoices'] }) }

  const act = useMutation({
    mutationFn: (v: { id: string; what: string }) => api.post(`/sales/orders/${v.id}/${v.what}/`),
    onSuccess: (r, v) => {
      const msg = v.what === 'sign' ? 'Đã ký đơn' : v.what === 'ship' ? 'Đã giao (sinh phiếu xuất)' : 'Đã xuất hóa đơn'
      toast.success(v.what === 'create-invoice' && r.data?.code ? `Đã tạo HĐ ${r.data.code}` : msg)
      inval()
    },
    onError: (e) => toast.error(apiError(e)),
  })
  const pay = useMutation({
    mutationFn: () => api.post('/sales/payments/', { order: payFor!.id, amount_vnd: Number(amt), paid_at: new Date().toISOString().slice(0, 10), method: 'transfer' }),
    onSuccess: () => { toast.success('Đã thu tiền'); inval(); setPayFor(null); setAmt('') },
    onError: (e) => toast.error(apiError(e)),
  })

  return (
    <div className="max-w-6xl">
      <PageHeader icon={<ShoppingBag size={20} className="text-flame" />} title="Đơn bán"
        subtitle={data ? `${data.length} đơn` : undefined} />
      <TableCard>
        <thead><tr className="border-b border-line">
          <Th>Mã đơn</Th><Th>Khách hàng</Th><Th>Ngày</Th><Th className="text-right">Tổng</Th>
          <Th className="text-right">Còn nợ</Th><Th>Trạng thái</Th><Th className="text-right">Hành động</Th>
        </tr></thead>
        <tbody>
          {isLoading && <RowMsg colSpan={7}>Đang tải…</RowMsg>}
          {isError && <RowMsg colSpan={7} danger>Lỗi: {apiError(error)}</RowMsg>}
          {data?.length === 0 && <RowMsg colSpan={7}>Chưa có đơn bán. Tạo từ Báo giá đã duyệt (“Tạo đơn”).</RowMsg>}
          {data?.map((o) => (
            <tr key={o.id} className="border-b border-line/50 last:border-0 hover:bg-ink-3/40">
              <Td className="font-mono text-flame">{o.code}</Td>
              <Td className="font-medium">{o.customer_name}</Td>
              <Td className="text-txt-2">{formatDate(o.issued_date)}</Td>
              <Td className="text-right tabular-nums">{compactVnd(o.total_vnd)}</Td>
              <Td className="text-right tabular-nums">{Number(o.debt_vnd) > 0 ? <span className="text-warn">{formatVnd(o.debt_vnd)}</span> : <span className="text-ok">Đã thu</span>}</Td>
              <Td><Tag tone={TONE[o.status] ?? 'gray'}>{LABEL[o.status] ?? o.status}</Tag></Td>
              <Td className="text-right whitespace-nowrap">
                {(o.status === 'draft' || o.status === 'pending') && canMng && (
                  <Button size="sm" className="mr-1" onClick={() => act.mutate({ id: o.id, what: 'sign' })}><PenLine size={13} /> Ký</Button>
                )}
                {o.status === 'active' && (
                  <Button size="sm" variant="success" className="mr-1" onClick={() => act.mutate({ id: o.id, what: 'ship' })}><Truck size={13} /> Giao</Button>
                )}
                {['active', 'shipping', 'completed'].includes(o.status) && canMng && (
                  <Button size="sm" variant="ghost" className="mr-1" onClick={() => act.mutate({ id: o.id, what: 'create-invoice' })}><FileText size={13} /> Hóa đơn</Button>
                )}
                {Number(o.debt_vnd) > 0 && canMng && (
                  <Button size="sm" variant="ghost" onClick={() => setPayFor(o)}><Wallet size={13} /> Thu</Button>
                )}
              </Td>
            </tr>
          ))}
        </tbody>
      </TableCard>

      <Modal open={!!payFor} onClose={() => setPayFor(null)} title={`Thu tiền ${payFor?.code ?? ''}`}
        icon={<Wallet size={18} className="text-flame" />}
        footer={<><Button variant="ghost" onClick={() => setPayFor(null)}>Hủy</Button>
          <Button onClick={() => pay.mutate()} disabled={pay.isPending || !amt}>Ghi thu</Button></>}>
        <p className="text-sm text-txt-2 mb-2">Còn nợ: <b className="text-warn">{payFor ? formatVnd(payFor.debt_vnd) : ''}</b></p>
        <input placeholder="Số tiền thu" type="number" value={amt} onChange={(e) => setAmt(e.target.value)}
          className="w-full bg-ink-3 border border-line rounded-md px-3 py-2 text-sm" />
      </Modal>
    </div>
  )
}
