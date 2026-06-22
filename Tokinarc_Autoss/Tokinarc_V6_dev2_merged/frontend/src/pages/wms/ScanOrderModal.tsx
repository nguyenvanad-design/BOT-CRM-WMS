/**
 * Tokinarc frontend — src/pages/wms/ScanOrderModal.tsx
 * Quét theo phiếu Nhập/Xuất trên điện thoại:
 *  - inbound : quét mã + SL → POST /wms/inbound/{id}/scan-receive/ (cộng qty_received)
 *  - outbound: quét mã + ô + SL → POST /wms/outbound/{id}/scan-pick/ (trừ tồn)
 * Hiện tiến độ từng dòng; xong thì Xác nhận nhận (confirm) / Giao (ship).
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ScanLine, Check, Truck } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { Modal } from '@/components/Modal'
import { Button, Tag } from '@/components/ui'

interface Line { id: string; part: string | null; torch: string | null; qty_expected?: number; qty_received?: number; qty_ordered?: number; qty_picked?: number }
interface Order { id: string; code: string; status: string; lines: Line[] }

export function ScanOrderModal({ open, onClose, kind, orderId }: {
  open: boolean; onClose: () => void; kind: 'inbound' | 'outbound'; orderId: string | null
}) {
  const qc = useQueryClient()
  const [code, setCode] = useState(''); const [bin, setBin] = useState(''); const [qty, setQty] = useState('1')

  const order = useQuery({
    queryKey: ['wms-order', kind, orderId],
    queryFn: async () => (await api.get<Order>(`/wms/${kind}/${orderId}/`)).data,
    enabled: open && !!orderId,
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['wms-order', kind, orderId] })
    qc.invalidateQueries({ queryKey: [`wms-${kind}-list`] })
    qc.invalidateQueries({ queryKey: ['wms-inventory'] })
  }

  const scan = useMutation({
    mutationFn: () => api.post(`/wms/${kind}/${orderId}/scan-${kind === 'inbound' ? 'receive' : 'pick'}/`,
      kind === 'inbound'
        ? { code: code.trim(), qty: Number(qty) }
        : { code: code.trim(), bin_code: bin.trim(), qty: Number(qty) }),
    onSuccess: (r) => { toast.success(r.data.detail); setCode(''); setQty('1'); invalidate() },
    onError: (e) => toast.error(apiError(e)),
  })
  const finalize = useMutation({
    mutationFn: () => api.post(`/wms/${kind}/${orderId}/${kind === 'inbound' ? 'confirm' : 'ship'}/`),
    onSuccess: () => { toast.success(kind === 'inbound' ? 'Đã nhận hàng — cộng tồn' : 'Đã giao hàng'); invalidate(); onClose() },
    onError: (e) => toast.error(apiError(e)),
  })

  const o = order.data
  const done = (l: Line) => kind === 'inbound'
    ? (l.qty_received ?? 0) >= (l.qty_expected ?? 0)
    : (l.qty_picked ?? 0) >= (l.qty_ordered ?? 0)
  const allDone = !!o && o.lines.length > 0 && o.lines.every(done)

  return (
    <Modal open={open} onClose={onClose}
      title={`Quét ${kind === 'inbound' ? 'nhận' : 'soạn'} — ${o?.code ?? ''}`}
      icon={<ScanLine size={18} className="text-flame" />}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Đóng</Button>
          {kind === 'inbound'
            ? <Button variant="success" disabled={!allDone || finalize.isPending} onClick={() => finalize.mutate()}>
                <Check size={14} /> Xác nhận nhận</Button>
            : <Button variant="success" disabled={!allDone || finalize.isPending} onClick={() => finalize.mutate()}>
                <Truck size={14} /> Giao hàng</Button>}
        </>
      }>
      <div className="space-y-3">
        <div className={`grid ${kind === 'outbound' ? 'grid-cols-3' : 'grid-cols-2'} gap-2`}>
          <Inp label="Mã hàng" v={code} set={setCode} ph="Quét/nhập mã" />
          {kind === 'outbound' && <Inp label="Mã ô" v={bin} set={setBin} ph="HCM-A-R01-B01" />}
          <div className="flex gap-2 items-end">
            <Inp label="SL" v={qty} set={setQty} ph="1" type="number" />
            <Button onClick={() => scan.mutate()} disabled={scan.isPending}><ScanLine size={14} /></Button>
          </div>
        </div>

        <div className="border border-line rounded-md divide-y divide-line/50">
          {order.isLoading && <p className="text-xs text-txt-2 py-4 text-center">Đang tải…</p>}
          {o?.lines.map((l) => {
            const cur = kind === 'inbound' ? (l.qty_received ?? 0) : (l.qty_picked ?? 0)
            const tot = kind === 'inbound' ? (l.qty_expected ?? 0) : (l.qty_ordered ?? 0)
            return (
              <div key={l.id} className="flex items-center gap-2 px-3 py-2 text-sm">
                <span className="font-mono text-flame flex-1">{l.part || l.torch}</span>
                <span className="tabular-nums">{cur}/{tot}</span>
                {done(l) ? <Tag tone="ok">Đủ</Tag> : <Tag tone="warn">Còn {tot - cur}</Tag>}
              </div>
            )
          })}
        </div>
        <p className="text-[11px] text-txt-2">
          {kind === 'inbound'
            ? 'Quét đủ số lượng rồi bấm "Xác nhận nhận" để cộng tồn.'
            : 'Quét mã + ô để trừ tồn; đủ rồi bấm "Giao hàng".'}
        </p>
      </div>
    </Modal>
  )
}

function Inp({ label, v, set, ph, type = 'text' }: { label: string; v: string; set: (s: string) => void; ph?: string; type?: string }) {
  return (
    <div className="flex-1">
      <label className="block text-[11px] uppercase tracking-wide text-txt-2 font-semibold mb-1">{label}</label>
      <input value={v} onChange={(e) => set(e.target.value)} placeholder={ph} type={type}
        className="w-full bg-ink-3 border border-line rounded-md px-3 py-2 text-sm focus:border-flame focus:outline-none" />
    </div>
  )
}
