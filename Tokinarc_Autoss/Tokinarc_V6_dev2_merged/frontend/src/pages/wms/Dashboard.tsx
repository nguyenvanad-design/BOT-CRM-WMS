/**
 * Tokinarc frontend — src/pages/wms/Dashboard.tsx
 * Dashboard WMS: KPI tổng hợp thật từ inventory/serials/inbound/outbound.
 */
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { LayoutDashboard } from 'lucide-react'
import { fetchAll } from '@/lib/list'
import { apiError } from '@/lib/api'
import { MOVE_REASON_LABEL, MOVE_REASON_TONE } from '@/lib/wms'
import { formatDate } from '@/lib/crm'
import type { InventoryItem, SerialNumber, InboundOrder, OutboundOrder, StockMovement } from '@/lib/types'
import { Card, SectionTitle, StatCard, PageHeader, Tag, TableCard, Th, Td, RowMsg } from '@/components/ui'

export function WmsDashboardPage() {
  const nav = useNavigate()
  const inv = useQuery({ queryKey: ['wms', 'inv'], queryFn: () => fetchAll<InventoryItem>('/wms/inventory/') })
  const serials = useQuery({ queryKey: ['wms', 'serials'], queryFn: () => fetchAll<SerialNumber>('/wms/serials/') })
  const inbound = useQuery({ queryKey: ['wms', 'inbound'], queryFn: () => fetchAll<InboundOrder>('/wms/inbound/') })
  const outbound = useQuery({ queryKey: ['wms', 'outbound'], queryFn: () => fetchAll<OutboundOrder>('/wms/outbound/') })
  const moves = useQuery({ queryKey: ['wms', 'moves'], queryFn: () => fetchAll<StockMovement>('/wms/stock-movements/') })

  const items = inv.data?.items ?? []
  const lowStock = items.filter((i) => i.qty_on_hand <= i.min_level)
  const totalQty = items.reduce((s, i) => s + i.qty_on_hand, 0)
  const serialInStock = (serials.data?.items ?? []).filter((s) => s.status === 'in_stock').length
  const inboundPending = (inbound.data?.items ?? []).filter((o) => o.status === 'draft' || o.status === 'confirmed').length
  const outboundPending = (outbound.data?.items ?? []).filter((o) => o.status === 'picking' || o.status === 'picked').length

  return (
    <div className="max-w-6xl">
      <PageHeader icon={<LayoutDashboard size={20} className="text-flame" />} title="Dashboard kho"
        subtitle="Tổng quan tồn kho & vận hành — số liệu trực tiếp" />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <StatCard label="Dòng tồn (SKU×bin)" tone="txt" value={inv.isLoading ? '…' : items.length} onClick={() => nav('/wms/inventory')} />
        <StatCard label="Tổng số lượng" tone="blue" value={inv.isLoading ? '…' : totalQty.toLocaleString('vi-VN')} />
        <StatCard label="Sắp hết hàng" tone="danger" value={inv.isLoading ? '…' : lowStock.length} onClick={() => nav('/wms/low-stock')} />
        <StatCard label="Serial trong kho" tone="ok" value={serials.isLoading ? '…' : serialInStock} onClick={() => nav('/wms/serials')} />
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <StatCard label="Đơn nhập chờ" tone="warn" value={inbound.isLoading ? '…' : inboundPending} onClick={() => nav('/wms/inbound')} />
        <StatCard label="Đơn xuất chờ" tone="flame" value={outbound.isLoading ? '…' : outboundPending} onClick={() => nav('/wms/outbound')} />
      </div>

      <Card className="mb-4">
        <SectionTitle action={<button className="text-xs text-flame hover:underline" onClick={() => nav('/wms/low-stock')}>Xem tất cả</button>}>
          Sắp hết hàng
        </SectionTitle>
        <TableCard>
          <thead><tr className="border-b border-line">
            <Th>Mặt hàng</Th><Th>Vị trí</Th><Th className="text-right">Tồn</Th><Th className="text-right">Tối thiểu</Th>
          </tr></thead>
          <tbody>
            {inv.isLoading && <RowMsg colSpan={4}>Đang tải…</RowMsg>}
            {inv.isError && <RowMsg colSpan={4} danger>Lỗi: {apiError(inv.error)}</RowMsg>}
            {inv.data && lowStock.length === 0 && <RowMsg colSpan={4}>Không có mặt hàng sắp hết. 🎉</RowMsg>}
            {lowStock.slice(0, 8).map((i) => (
              <tr key={i.id} className="border-b border-line/50 last:border-0">
                <Td className="font-medium">{i.item_name}</Td>
                <Td className="font-mono text-txt-2">{i.bin_code}</Td>
                <Td className="text-right text-danger tabular-nums">{i.qty_on_hand}</Td>
                <Td className="text-right text-txt-2 tabular-nums">{i.min_level}</Td>
              </tr>
            ))}
          </tbody>
        </TableCard>
      </Card>

      <Card>
        <SectionTitle action={<button className="text-xs text-flame hover:underline" onClick={() => nav('/wms/movements')}>Xem tất cả</button>}>
          Biến động gần đây
        </SectionTitle>
        <TableCard>
          <thead><tr className="border-b border-line">
            <Th>Thời gian</Th><Th>Mặt hàng</Th><Th>Vị trí</Th><Th className="text-right">Thay đổi</Th><Th>Loại</Th>
          </tr></thead>
          <tbody>
            {moves.isLoading && <RowMsg colSpan={5}>Đang tải…</RowMsg>}
            {moves.data && moves.data.items.length === 0 && <RowMsg colSpan={5}>Chưa có biến động.</RowMsg>}
            {(moves.data?.items ?? []).slice(0, 8).map((m) => (
              <tr key={m.id} className="border-b border-line/50 last:border-0">
                <Td className="text-txt-2 whitespace-nowrap">{formatDate(m.ts)}</Td>
                <Td className="font-medium">{m.part || m.torch || '—'}</Td>
                <Td className="font-mono text-txt-2">{m.bin}</Td>
                <Td className={`text-right tabular-nums ${m.delta >= 0 ? 'text-ok' : 'text-danger'}`}>{m.delta > 0 ? `+${m.delta}` : m.delta}</Td>
                <Td><Tag tone={MOVE_REASON_TONE[m.reason]}>{MOVE_REASON_LABEL[m.reason]}</Tag></Td>
              </tr>
            ))}
          </tbody>
        </TableCard>
      </Card>
    </div>
  )
}
