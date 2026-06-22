/**
 * Tokinarc frontend — src/pages/wms/Outbound.tsx
 * Đơn xuất kho THẬT (GET /wms/outbound/) + xem pick-list (GET .../pick-list/)
 * + giao hàng (POST .../ship/ → trừ tồn, ghi movement).
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { PackageCheck, Truck, ClipboardList, Plus, ScanLine } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { fetchAll } from '@/lib/list'
import { OUTBOUND_STATUS_LABEL, OUTBOUND_STATUS_TONE, RULE_LABEL } from '@/lib/wms'
import type { OutboundOrder } from '@/lib/types'
import {
  PageHeader, Tag, Button, TableCard, Th, Td, RowMsg,
} from '@/components/ui'
import { Modal } from '@/components/Modal'
import { OutboundForm } from '@/pages/wms/forms/OutboundForm'
import { ScanOrderModal } from '@/pages/wms/ScanOrderModal'

interface Pick { id: string; bin_code: string; qty: number; is_picked: boolean; serial: string | null }

export function OutboundPage() {
  const qc = useQueryClient()
  const [formOpen, setFormOpen] = useState(false)
  const [pickFor, setPickFor] = useState<OutboundOrder | null>(null)
  const [picks, setPicks] = useState<Pick[] | null>(null)
  const [scanId, setScanId] = useState<string | null>(null)

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['wms-outbound-list'],
    queryFn: () => fetchAll<OutboundOrder>('/wms/outbound/'),
  })

  const ship = useMutation({
    mutationFn: (id: string) => api.post(`/wms/outbound/${id}/ship/`),
    onSuccess: () => {
      toast.success('Đã giao hàng — trừ tồn kho')
      qc.invalidateQueries({ queryKey: ['wms-outbound-list'] })
      qc.invalidateQueries({ queryKey: ['wms'] })
    },
    onError: (e) => toast.error(apiError(e)),
  })

  const reject = useMutation({
    mutationFn: (v: { id: string; reason: string }) =>
      api.post(`/wms/outbound/${v.id}/reject/`, { reason: v.reason }),
    onSuccess: () => {
      toast.success('Đã từ chối phiếu — đơn trả về sale xử lý')
      qc.invalidateQueries({ queryKey: ['wms-outbound-list'] })
      qc.invalidateQueries({ queryKey: ['wms'] })
    },
    onError: (e) => toast.error(apiError(e)),
  })

  const viewPicks = useMutation({
    mutationFn: (o: OutboundOrder) => api.get<Pick[]>(`/wms/outbound/${o.id}/pick-list/`),
    onSuccess: (res, o) => { setPickFor(o); setPicks(res.data) },
    onError: (e) => toast.error(apiError(e)),
  })

  const items = data?.items ?? []

  return (
    <div className="max-w-5xl">
      <PageHeader icon={<PackageCheck size={20} className="text-flame" />} title="Xuất kho"
        subtitle={data ? `${data.count} đơn xuất` : undefined}
        actions={<Button onClick={() => setFormOpen(true)}><Plus size={14} /> Tạo đơn xuất</Button>} />

      <TableCard>
        <thead>
          <tr className="border-b border-line">
            <Th>Mã đơn</Th><Th>Đơn bán</Th><Th>Rule</Th><Th className="text-right">Số dòng</Th>
            <Th>Trạng thái</Th><Th className="text-right">Hành động</Th>
          </tr>
        </thead>
        <tbody>
          {isLoading && <RowMsg colSpan={6}>Đang tải…</RowMsg>}
          {isError && <RowMsg colSpan={6} danger>Lỗi: {apiError(error)}</RowMsg>}
          {data && items.length === 0 && <RowMsg colSpan={6}>Chưa có đơn xuất.</RowMsg>}
          {items.map((o) => (
            <tr key={o.id} className="border-b border-line/50 last:border-0 hover:bg-ink-3/40">
              <Td className="font-mono text-flame">{o.code}</Td>
              <Td className="text-txt-2 font-mono text-[11px]">{o.sales_order_code || '—'}</Td>
              <Td className="text-txt-2">{o.rule}</Td>
              <Td className="text-right tabular-nums">{o.lines?.length ?? 0}</Td>
              <Td><Tag tone={OUTBOUND_STATUS_TONE[o.status]}>{OUTBOUND_STATUS_LABEL[o.status]}</Tag></Td>
              <Td className="text-right whitespace-nowrap">
                <Button variant="ghost" size="sm" className="mr-1.5"
                  disabled={viewPicks.isPending} onClick={() => viewPicks.mutate(o)}>
                  <ClipboardList size={13} /> Pick-list
                </Button>
                {o.status !== 'shipped' && o.status !== 'cancelled' && (
                  <Button variant="ghost" size="sm" className="mr-1.5" onClick={() => setScanId(o.id)}>
                    <ScanLine size={13} /> Quét
                  </Button>
                )}
                {o.status !== 'shipped' && o.status !== 'cancelled' && (
                  <Button variant="ghost" size="sm" className="mr-1.5"
                    onClick={() => {
                      const reason = window.prompt('Lý do từ chối phiếu xuất (hết hàng, hàng lỗi…):')
                      if (reason !== null) reject.mutate({ id: o.id, reason })
                    }}>
                    Từ chối
                  </Button>
                )}
                {(o.status === 'picking' || o.status === 'picked' || o.status === 'partial') && (
                  <Button size="sm" disabled={ship.isPending && ship.variables === o.id}
                    onClick={() => ship.mutate(o.id)}>
                    <Truck size={13} /> {o.status === 'partial' ? 'Giao tiếp' : 'Giao'}
                  </Button>
                )}
              </Td>
            </tr>
          ))}
        </tbody>
      </TableCard>

      <OutboundForm open={formOpen} onClose={() => setFormOpen(false)} />
      <ScanOrderModal open={!!scanId} onClose={() => setScanId(null)} kind="outbound" orderId={scanId} />

      <Modal open={!!pickFor} onClose={() => setPickFor(null)}
        title={`Pick-list — ${pickFor?.code ?? ''}`}
        icon={<ClipboardList size={18} className="text-flame" />}>
        <p className="text-xs text-txt-2 mb-3">Rule: {pickFor && RULE_LABEL[pickFor.rule]}</p>
        {picks && picks.length === 0 && <p className="text-sm text-txt-2">Không phân được bin (có thể thiếu tồn).</p>}
        {picks && picks.length > 0 && (
          <div className="space-y-2">
            {picks.map((p) => (
              <div key={p.id} className="flex items-center gap-3 border border-line rounded-md px-3 py-2 text-sm">
                <span className="font-mono text-flame">{p.bin_code}</span>
                <span className="flex-1">{p.serial ? `Serial ${p.serial}` : `SL ${p.qty}`}</span>
                {p.is_picked ? <Tag tone="ok">đã soạn</Tag> : <Tag tone="warn">chờ soạn</Tag>}
              </div>
            ))}
          </div>
        )}
      </Modal>
    </div>
  )
}
