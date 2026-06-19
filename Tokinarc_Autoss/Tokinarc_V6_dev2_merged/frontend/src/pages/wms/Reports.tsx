/**
 * Tokinarc frontend — src/pages/wms/Reports.tsx
 * Báo cáo kho: tổng hợp từ /wms (movements, inventory, inbound, outbound).
 * Không dùng analytics (manager-only) → role kho cũng xem được.
 */
import { useQuery } from '@tanstack/react-query'
import { FileBarChart } from 'lucide-react'
import { fetchAll } from '@/lib/list'
import { apiError } from '@/lib/api'
import { MOVE_REASON_LABEL, MOVE_REASON_TONE, INBOUND_STATUS_LABEL, OUTBOUND_STATUS_LABEL } from '@/lib/wms'
import type { StockMovement, InventoryItem, InboundOrder, OutboundOrder, MovementReason } from '@/lib/types'
import { Card, SectionTitle, StatCard, PageHeader, Tag, TableCard, Th, Td, RowMsg } from '@/components/ui'

const REASONS: MovementReason[] = ['inbound', 'outbound', 'adjust', 'transfer', 'return']

export function WmsReportsPage() {
  const moves = useQuery({ queryKey: ['wms-rep-moves'], queryFn: () => fetchAll<StockMovement>('/wms/stock-movements/') })
  const inv = useQuery({ queryKey: ['wms-rep-inv'], queryFn: () => fetchAll<InventoryItem>('/wms/inventory/') })
  const inb = useQuery({ queryKey: ['wms-rep-inb'], queryFn: () => fetchAll<InboundOrder>('/wms/inbound/') })
  const outb = useQuery({ queryKey: ['wms-rep-out'], queryFn: () => fetchAll<OutboundOrder>('/wms/outbound/') })

  const mv = moves.data?.items ?? []
  const totalQty = (inv.data?.items ?? []).reduce((s, i) => s + i.qty_on_hand, 0)
  const byReason = REASONS.map((r) => {
    const rows = mv.filter((m) => m.reason === r)
    return { reason: r, count: rows.length, delta: rows.reduce((s, m) => s + m.delta, 0) }
  }).filter((r) => r.count > 0)
  const maxCount = Math.max(1, ...byReason.map((r) => r.count))

  const countByStatus = <T extends { status: string }>(items: T[]) => {
    const map: Record<string, number> = {}
    items.forEach((o) => { map[o.status] = (map[o.status] || 0) + 1 })
    return map
  }
  const inbByStatus = countByStatus(inb.data?.items ?? [])
  const outByStatus = countByStatus(outb.data?.items ?? [])

  return (
    <div className="max-w-5xl">
      <PageHeader icon={<FileBarChart size={20} className="text-flame" />} title="Báo cáo kho" />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <StatCard label="Tổng biến động" tone="txt" value={moves.isLoading ? '…' : mv.length} />
        <StatCard label="Tổng SL tồn" tone="blue" value={inv.isLoading ? '…' : totalQty.toLocaleString('vi-VN')} />
        <StatCard label="Đơn nhập" tone="ok" value={inb.isLoading ? '…' : (inb.data?.count ?? 0)} />
        <StatCard label="Đơn xuất" tone="flame" value={outb.isLoading ? '…' : (outb.data?.count ?? 0)} />
      </div>

      <Card className="mb-4">
        <SectionTitle>Biến động kho theo loại</SectionTitle>
        {moves.isError && <p className="text-danger text-sm">Lỗi: {apiError(moves.error)}</p>}
        <div className="space-y-2">
          {byReason.map((r) => (
            <div key={r.reason} className="flex items-center gap-3">
              <span className="w-28 shrink-0"><Tag tone={MOVE_REASON_TONE[r.reason]}>{MOVE_REASON_LABEL[r.reason]}</Tag></span>
              <div className="flex-1 h-2.5 bg-ink-3 rounded-full overflow-hidden">
                <div className="h-full rounded-full bg-flame" style={{ width: `${(r.count / maxCount) * 100}%` }} />
              </div>
              <span className="w-28 text-right text-xs tabular-nums text-txt-2">
                {r.count} lần · <span className={r.delta >= 0 ? 'text-ok' : 'text-danger'}>{r.delta > 0 ? `+${r.delta}` : r.delta}</span>
              </span>
            </div>
          ))}
          {!moves.isLoading && byReason.length === 0 && <p className="text-txt-2 text-sm">Chưa có biến động.</p>}
        </div>
      </Card>

      <div className="grid lg:grid-cols-2 gap-4">
        <Card>
          <SectionTitle>Đơn nhập theo trạng thái</SectionTitle>
          <TableCard>
            <thead><tr className="border-b border-line"><Th>Trạng thái</Th><Th className="text-right">Số đơn</Th></tr></thead>
            <tbody>
              {Object.keys(inbByStatus).length === 0 && <RowMsg colSpan={2}>Chưa có.</RowMsg>}
              {Object.entries(inbByStatus).map(([s, n]) => (
                <tr key={s} className="border-b border-line/50 last:border-0">
                  <Td>{INBOUND_STATUS_LABEL[s as keyof typeof INBOUND_STATUS_LABEL] ?? s}</Td>
                  <Td className="text-right tabular-nums">{n}</Td>
                </tr>
              ))}
            </tbody>
          </TableCard>
        </Card>
        <Card>
          <SectionTitle>Đơn xuất theo trạng thái</SectionTitle>
          <TableCard>
            <thead><tr className="border-b border-line"><Th>Trạng thái</Th><Th className="text-right">Số đơn</Th></tr></thead>
            <tbody>
              {Object.keys(outByStatus).length === 0 && <RowMsg colSpan={2}>Chưa có.</RowMsg>}
              {Object.entries(outByStatus).map(([s, n]) => (
                <tr key={s} className="border-b border-line/50 last:border-0">
                  <Td>{OUTBOUND_STATUS_LABEL[s as keyof typeof OUTBOUND_STATUS_LABEL] ?? s}</Td>
                  <Td className="text-right tabular-nums">{n}</Td>
                </tr>
              ))}
            </tbody>
          </TableCard>
        </Card>
      </div>
    </div>
  )
}
