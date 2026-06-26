/**
 * Tokinarc frontend — src/pages/purchasing/PurchaseOrders.tsx
 * Đơn mua: tạo → đặt (confirm) → nhận (receive, cộng tồn) → trả NCC (payment).
 * + thẻ Công nợ phải trả (AP). /purchasing/orders/, /payments/.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ShoppingCart, Plus, Check, PackageCheck, Wallet, Trash2, Eye, ShieldCheck, X, Download, Truck } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { downloadFile } from '@/lib/download'
import { compactVnd, formatVnd } from '@/lib/crm'
import { isManager, isCeo, useAuth } from '@/lib/auth/store'
import { Modal } from '@/components/Modal'
import { PageHeader, Button, StatCard, Tag, TableCard, Th, Td, RowMsg } from '@/components/ui'
import { PODetailModal, type PODetail } from '@/pages/purchasing/PODetailModal'

interface POLine { id?: string; part: string; part_name?: string; description?: string; qty: number; unit_cost: number; qty_received?: number }
interface PO {
  id: string; code: string; supplier_name: string; warehouse_code: string
  status: string; status_display: string; total_vnd: string; paid_vnd: string; debt_vnd: number
  requires_l2?: boolean; owner_username?: string; notes?: string; lines: POLine[]
}
interface IncomingRow {
  id: string; code: string; supplier_name: string; status: string; status_display: string
  expected_date: string | null; carrier?: string; tracking_no?: string
  total_vnd: number; days_late: number; is_overdue: boolean
}
interface IncomingResp { count: number; overdue: number; results: IncomingRow[] }
const TONE: Record<string, 'gray' | 'blue' | 'warn' | 'ok' | 'danger' | 'purple'> = {
  draft: 'gray', pending_ceo: 'warn', approved: 'blue', rejected: 'danger',
  ordered: 'purple', partial: 'warn', received: 'ok', cancelled: 'danger',
}

export function PurchaseOrdersPage() {
  const qc = useQueryClient()
  const role = useAuth((s) => s.user?.role)
  const canManage = isManager(role)
  const canApproveL2 = isCeo(role)
  // QL kho lập đơn mua + trả NCC (Mua hàng nằm trong tab WMS); duyệt vẫn là manager/CEO.
  const canPurchase = canManage || role === 'wh_manager'
  const [open, setOpen] = useState(false)
  const [detail, setDetail] = useState<PODetail | null>(null)
  const [payFor, setPayFor] = useState<PO | null>(null)
  const [supplier, setSupplier] = useState(''); const [warehouse, setWarehouse] = useState('')
  const [expectedDate, setExpectedDate] = useState(''); const [paymentTerms, setPaymentTerms] = useState('')
  const [carrier, setCarrier] = useState(''); const [trackingNo, setTrackingNo] = useState('')
  const [lines, setLines] = useState<POLine[]>([{ part: '', qty: 1, unit_cost: 0 }])
  const [payAmt, setPayAmt] = useState('')

  const [view, setView] = useState<'all' | 'incoming'>('all')
  const orders = useQuery({ queryKey: ['po'], queryFn: async () => (await api.get<{ results: PO[] }>('/purchasing/orders/')).data.results ?? [] })
  const ap = useQuery({ queryKey: ['po-ap'], queryFn: async () => (await api.get('/purchasing/orders/ap-summary/')).data })
  const incoming = useQuery({ queryKey: ['po-incoming'], queryFn: async () => (await api.get<IncomingResp>('/purchasing/orders/incoming/')).data })
  const suppliers = useQuery({ queryKey: ['suppliers'], queryFn: async () => (await api.get<{ results: { id: string; name: string }[] }>('/purchasing/suppliers/')).data.results ?? [] })
  const whs = useQuery({ queryKey: ['wh-list'], queryFn: async () => (await api.get<{ results: { id: string; code: string }[] }>('/wms/warehouses/')).data.results ?? [] })

  const invalidate = () => { qc.invalidateQueries({ queryKey: ['po'] }); qc.invalidateQueries({ queryKey: ['po-ap'] }) }
  const create = useMutation({
    mutationFn: () => api.post('/purchasing/orders/', {
      supplier, warehouse,
      expected_date: expectedDate || null, payment_terms_note: paymentTerms,
      carrier, tracking_no: trackingNo,
      lines: lines.filter((l) => l.part).map((l) => ({ part: l.part.trim(), qty: Number(l.qty), unit_cost: Number(l.unit_cost) })),
    }),
    onSuccess: (r) => { toast.success(`Đã tạo ${r.data.code}`); invalidate(); setOpen(false); setLines([{ part: '', qty: 1, unit_cost: 0 }]); setSupplier(''); setExpectedDate(''); setPaymentTerms(''); setCarrier(''); setTrackingNo('') },
    onError: (e) => toast.error(apiError(e)),
  })
  const ACT_MSG: Record<string, string> = {
    confirm: 'Đã đặt hàng', receive: 'Đã nhận → cộng tồn',
    approve: 'Đã duyệt đơn mua', 'approve-l2': 'CEO đã duyệt cấp 2',
  }
  const act = useMutation({
    mutationFn: (v: { id: string; what: 'confirm' | 'receive' | 'approve' | 'approve-l2' }) =>
      api.post(`/purchasing/orders/${v.id}/${v.what}/`),
    onSuccess: (r, v) => {
      const msg = v.what === 'approve' && r.data?.status === 'pending_ceo'
        ? 'Đã duyệt cấp 1 — chuyển CEO duyệt cấp 2' : (ACT_MSG[v.what] ?? 'Đã cập nhật')
      toast.success(msg); invalidate()
    },
    onError: (e) => toast.error(apiError(e)),
  })
  const reject = useMutation({
    mutationFn: (v: { id: string; reason: string }) =>
      api.post(`/purchasing/orders/${v.id}/reject/`, { reason: v.reason }),
    onSuccess: () => { toast.success('Đã từ chối đơn mua'); invalidate() },
    onError: (e) => toast.error(apiError(e)),
  })
  const onReject = (id: string) => {
    const reason = window.prompt('Lý do từ chối đơn mua?') ?? ''
    if (reason !== null) reject.mutate({ id, reason })
  }
  const pay = useMutation({
    mutationFn: () => api.post('/purchasing/payments/', { po: payFor!.id, amount_vnd: Number(payAmt), paid_at: new Date().toISOString().slice(0, 10) }),
    onSuccess: () => { toast.success('Đã ghi thanh toán'); invalidate(); setPayFor(null); setPayAmt('') },
    onError: (e) => toast.error(apiError(e)),
  })

  return (
    <div className="max-w-6xl">
      <PageHeader icon={<ShoppingCart size={20} className="text-flame" />} title="Đơn mua hàng"
        subtitle={orders.data ? `${orders.data.length} đơn` : undefined}
        actions={
          <>
            {canPurchase && (
              <Button variant="ghost" onClick={async () => {
                try {
                  const res = await api.get('/purchasing/payments/export-misa/', { responseType: 'blob' })
                  const url = URL.createObjectURL(res.data as Blob)
                  const a = document.createElement('a'); a.href = url; a.download = 'phieuchi_misa.xlsx'; a.click()
                  URL.revokeObjectURL(url)
                } catch (e) { toast.error(apiError(e)) }
              }}><Wallet size={14} /> Xuất phiếu chi (MISA)</Button>
            )}
            {canPurchase && <Button onClick={() => setOpen(true)}><Plus size={14} /> Tạo PO</Button>}
          </>
        } />

      <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 mb-4">
        <StatCard label="Công nợ phải trả" tone="danger" value={ap.data ? compactVnd(ap.data.total_payable) : '…'} />
        <StatCard label="Hàng đang về" tone="warn" value={incoming.data ? `${incoming.data.count} đơn` : '…'} />
        <StatCard label="Đơn TRỄ hẹn" tone={incoming.data?.overdue ? 'danger' : 'ok'} value={incoming.data ? `${incoming.data.overdue}` : '…'} />
      </div>

      <div className="flex gap-1.5 mb-3">
        <button onClick={() => setView('all')}
          className={`text-xs rounded-md px-3 py-1.5 border transition-colors ${view === 'all' ? 'border-flame text-flame bg-flame/10' : 'border-line text-txt-2 hover:text-txt'}`}>
          Tất cả đơn
        </button>
        <button onClick={() => setView('incoming')}
          className={`text-xs rounded-md px-3 py-1.5 border transition-colors flex items-center gap-1.5 ${view === 'incoming' ? 'border-flame text-flame bg-flame/10' : 'border-line text-txt-2 hover:text-txt'}`}>
          <Truck size={13} /> Hàng đang về{incoming.data ? ` (${incoming.data.count})` : ''}
          {incoming.data?.overdue ? <span className="text-danger font-medium">· {incoming.data.overdue} trễ</span> : null}
        </button>
      </div>

      {view === 'all' ? (
      <TableCard>
        <thead><tr className="border-b border-line">
          <Th>Mã PO</Th><Th>Nhà cung cấp</Th><Th>Kho</Th><Th className="text-right">Giá trị</Th>
          <Th className="text-right">Còn nợ</Th><Th>Trạng thái</Th><Th className="text-right">Hành động</Th>
        </tr></thead>
        <tbody>
          {orders.isLoading && <RowMsg colSpan={7}>Đang tải…</RowMsg>}
          {orders.data?.length === 0 && <RowMsg colSpan={7}>Chưa có đơn mua.</RowMsg>}
          {orders.data?.map((o) => (
            <tr key={o.id} className="border-b border-line/50 last:border-0 hover:bg-ink-3/40">
              <Td className="font-mono text-flame">{o.code}</Td>
              <Td className="font-medium">{o.supplier_name}</Td>
              <Td className="text-txt-2">{o.warehouse_code}</Td>
              <Td className="text-right tabular-nums">{compactVnd(o.total_vnd)}</Td>
              <Td className="text-right tabular-nums">{o.debt_vnd > 0 ? <span className="text-warn">{formatVnd(o.debt_vnd)}</span> : <span className="text-ok">Đã trả</span>}</Td>
              <Td><Tag tone={TONE[o.status] ?? 'gray'}>{o.status_display}</Tag></Td>
              <Td className="text-right whitespace-nowrap">
                <Button size="sm" variant="ghost" className="mr-1" onClick={() => setDetail(o as PODetail)}>
                  <Eye size={13} /> Xem
                </Button>
                <Button size="sm" variant="ghost" className="mr-1"
                  onClick={() => downloadFile(`/purchasing/orders/${o.id}/export-xlsx/`, `don_mua_${o.code}.xlsx`)}>
                  <Download size={13} /> Excel
                </Button>
                {/* Duyệt cấp 1 (manager+) cho đơn nháp */}
                {o.status === 'draft' && canManage && (
                  <>
                    <Button size="sm" variant="success" className="mr-1" onClick={() => act.mutate({ id: o.id, what: 'approve' })}>
                      <Check size={13} /> Duyệt{o.requires_l2 ? ' (cấp 1)' : ''}
                    </Button>
                    <Button size="sm" variant="ghost" className="mr-1" onClick={() => onReject(o.id)}><X size={13} /> Từ chối</Button>
                  </>
                )}
                {/* Duyệt cấp 2 (CEO) cho đơn vượt ngưỡng */}
                {o.status === 'pending_ceo' && canApproveL2 && (
                  <Button size="sm" variant="success" className="mr-1" onClick={() => act.mutate({ id: o.id, what: 'approve-l2' })}>
                    <ShieldCheck size={13} /> Duyệt cấp 2 (CEO)
                  </Button>
                )}
                {o.status === 'pending_ceo' && !canApproveL2 && (
                  <span className="text-[11px] text-txt-2 mr-1">Chờ CEO duyệt</span>
                )}
                {/* Đặt hàng sau khi đã duyệt */}
                {o.status === 'approved' && canPurchase && (
                  <Button size="sm" className="mr-1" onClick={() => act.mutate({ id: o.id, what: 'confirm' })}><Check size={13} /> Đặt</Button>
                )}
                {(o.status === 'ordered' || o.status === 'partial') && (
                  <Button size="sm" variant="success" className="mr-1" onClick={() => act.mutate({ id: o.id, what: 'receive' })}><PackageCheck size={13} /> Nhận</Button>
                )}
                {o.debt_vnd > 0 && canPurchase && (
                  <Button size="sm" variant="ghost" onClick={() => setPayFor(o)}><Wallet size={13} /> Trả</Button>
                )}
              </Td>
            </tr>
          ))}
        </tbody>
      </TableCard>
      ) : (
      <TableCard>
        <thead><tr className="border-b border-line">
          <Th>Mã PO</Th><Th>Nhà cung cấp</Th><Th>Dự kiến về</Th><Th>Tình trạng</Th>
          <Th>Vận chuyển</Th><Th className="text-right">Giá trị</Th><Th>Trạng thái</Th>
        </tr></thead>
        <tbody>
          {incoming.isLoading && <RowMsg colSpan={7}>Đang tải…</RowMsg>}
          {incoming.data?.results.length === 0 && <RowMsg colSpan={7}>Không có đơn nào đang về.</RowMsg>}
          {incoming.data?.results.map((o) => (
            <tr key={o.id} className={`border-b border-line/50 last:border-0 hover:bg-ink-3/40 ${o.is_overdue ? 'bg-danger/5' : ''}`}>
              <Td className="font-mono text-flame">{o.code}</Td>
              <Td className="font-medium">{o.supplier_name}</Td>
              <Td className="text-txt-2 whitespace-nowrap">{o.expected_date ?? '—'}</Td>
              <Td>{o.is_overdue ? <Tag tone="danger">Trễ {o.days_late} ngày</Tag> : <Tag tone="ok">Đúng hẹn</Tag>}</Td>
              <Td className="text-txt-2">{[o.carrier, o.tracking_no].filter(Boolean).join(' · ') || '—'}</Td>
              <Td className="text-right tabular-nums">{compactVnd(o.total_vnd)}</Td>
              <Td><Tag tone={TONE[o.status] ?? 'gray'}>{o.status_display}</Tag></Td>
            </tr>
          ))}
        </tbody>
      </TableCard>
      )}

      {/* Tạo PO */}
      <Modal open={open} onClose={() => setOpen(false)} title="Tạo đơn mua"
        icon={<ShoppingCart size={18} className="text-flame" />}
        footer={<><Button variant="ghost" onClick={() => setOpen(false)}>Hủy</Button>
          <Button onClick={() => create.mutate()} disabled={create.isPending || !supplier || !warehouse}>Tạo</Button></>}>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <Sel label="Nhà cung cấp *" value={supplier} onChange={setSupplier}
              opts={(suppliers.data ?? []).map((s) => ({ v: s.id, l: s.name }))} />
            <Sel label="Kho nhận *" value={warehouse} onChange={setWarehouse}
              opts={(whs.data ?? []).map((w) => ({ v: w.id, l: w.code }))} />
          </div>
          <div className="grid grid-cols-3 gap-2">
            <div>
              <label className="block text-[11px] uppercase tracking-wide text-txt-2 font-semibold mb-1">Dự kiến về</label>
              <input type="date" value={expectedDate} onChange={(e) => setExpectedDate(e.target.value)}
                className="w-full bg-ink-3 border border-line rounded-md px-2 py-1.5 text-sm" />
            </div>
            <div>
              <label className="block text-[11px] uppercase tracking-wide text-txt-2 font-semibold mb-1">Hãng VC</label>
              <input value={carrier} onChange={(e) => setCarrier(e.target.value)} placeholder="GHN, Viettel…"
                className="w-full bg-ink-3 border border-line rounded-md px-2 py-1.5 text-sm" />
            </div>
            <div>
              <label className="block text-[11px] uppercase tracking-wide text-txt-2 font-semibold mb-1">Số vận đơn</label>
              <input value={trackingNo} onChange={(e) => setTrackingNo(e.target.value)} placeholder="Tracking"
                className="w-full bg-ink-3 border border-line rounded-md px-2 py-1.5 text-sm" />
            </div>
          </div>
          <div>
            <label className="block text-[11px] uppercase tracking-wide text-txt-2 font-semibold mb-1">Điều kiện thanh toán (NCC)</label>
            <textarea value={paymentTerms} onChange={(e) => setPaymentTerms(e.target.value)} rows={2}
              placeholder="VD: Trả trước 30%, còn lại sau 30 ngày / 100% khi nhận hàng…"
              className="w-full bg-ink-3 border border-line rounded-md px-2 py-1.5 text-sm" />
          </div>
          <div className="text-xs text-txt-2">Dòng hàng (mã part + SL + đơn giá):</div>
          {lines.map((l, i) => (
            <div key={i} className="flex gap-2 items-center">
              <input placeholder="Mã part" value={l.part} onChange={(e) => setLines((a) => a.map((x, j) => j === i ? { ...x, part: e.target.value } : x))}
                className="flex-1 bg-ink-3 border border-line rounded-md px-2 py-1.5 text-sm" />
              <input placeholder="SL" type="number" value={l.qty} onChange={(e) => setLines((a) => a.map((x, j) => j === i ? { ...x, qty: Number(e.target.value) } : x))}
                className="w-20 bg-ink-3 border border-line rounded-md px-2 py-1.5 text-sm" />
              <input placeholder="Đơn giá" type="number" value={l.unit_cost} onChange={(e) => setLines((a) => a.map((x, j) => j === i ? { ...x, unit_cost: Number(e.target.value) } : x))}
                className="w-28 bg-ink-3 border border-line rounded-md px-2 py-1.5 text-sm" />
              <button onClick={() => setLines((a) => a.filter((_, j) => j !== i))} className="text-txt-2 hover:text-danger"><Trash2 size={14} /></button>
            </div>
          ))}
          <Button variant="ghost" size="sm" onClick={() => setLines((a) => [...a, { part: '', qty: 1, unit_cost: 0 }])}><Plus size={13} /> Thêm dòng</Button>
        </div>
      </Modal>

      {/* Trả NCC */}
      <Modal open={!!payFor} onClose={() => setPayFor(null)} title={`Thanh toán ${payFor?.code ?? ''}`}
        icon={<Wallet size={18} className="text-flame" />}
        footer={<><Button variant="ghost" onClick={() => setPayFor(null)}>Hủy</Button>
          <Button onClick={() => pay.mutate()} disabled={pay.isPending || !payAmt}>Ghi thanh toán</Button></>}>
        <p className="text-sm text-txt-2 mb-2">Còn nợ: <b className="text-warn">{payFor ? formatVnd(payFor.debt_vnd) : ''}</b></p>
        <input placeholder="Số tiền trả" type="number" value={payAmt} onChange={(e) => setPayAmt(e.target.value)}
          className="w-full bg-ink-3 border border-line rounded-md px-3 py-2 text-sm" />
      </Modal>

      <PODetailModal po={detail} open={!!detail} onClose={() => setDetail(null)} />
    </div>
  )
}

function Sel({ label, value, onChange, opts }: { label: string; value: string; onChange: (v: string) => void; opts: { v: string; l: string }[] }) {
  return (
    <div>
      <label className="block text-[11px] uppercase tracking-wide text-txt-2 font-semibold mb-1">{label}</label>
      <select value={value} onChange={(e) => onChange(e.target.value)}
        className="w-full bg-ink-3 border border-line rounded-md px-3 py-2 text-sm">
        <option value="">— Chọn —</option>
        {opts.map((o) => <option key={o.v} value={o.v}>{o.l}</option>)}
      </select>
    </div>
  )
}
