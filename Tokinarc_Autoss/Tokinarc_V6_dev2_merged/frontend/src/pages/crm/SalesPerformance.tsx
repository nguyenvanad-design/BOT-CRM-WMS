/**
 * Tokinarc frontend — src/pages/crm/SalesPerformance.tsx
 * Hiệu suất theo từng SALE (manager+): bảng xếp hạng KH/lead/cơ hội/pipeline/
 * won/đơn/doanh thu/đã thu. Dữ liệu /analytics/sales-performance/.
 */
import { useQuery } from '@tanstack/react-query'
import { Trophy } from 'lucide-react'
import { api, apiError } from '@/lib/api'
import { compactVnd } from '@/lib/crm'
import { PageHeader, Card, TableCard, Th, Td, RowMsg, StatCard } from '@/components/ui'

interface Row {
  id: string; username: string; name: string
  customers: number; leads: number; open_opps: number
  pipeline_vnd: number; weighted_vnd: number; won_opps: number
  orders: number; revenue_vnd: number; collected_vnd: number
}

export function SalesPerformancePage() {
  const q = useQuery({
    queryKey: ['sales-performance'],
    queryFn: async () => (await api.get<Row[]>('/analytics/sales-performance/')).data,
  })
  const rows = q.data ?? []
  const sum = (k: keyof Row) => rows.reduce((s, r) => s + Number(r[k] || 0), 0)

  return (
    <div className="max-w-6xl">
      <PageHeader icon={<Trophy size={20} className="text-flame" />} title="Hiệu suất Sale"
        subtitle="Thống kê theo từng nhân viên — xếp hạng theo doanh thu" />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <StatCard label="Tổng doanh thu" tone="flame" value={q.isLoading ? '…' : compactVnd(sum('revenue_vnd'))} />
        <StatCard label="Đã thu" tone="ok" value={q.isLoading ? '…' : compactVnd(sum('collected_vnd'))} />
        <StatCard label="Pipeline mở" tone="blue" value={q.isLoading ? '…' : compactVnd(sum('pipeline_vnd'))} />
        <StatCard label="Số nhân viên" tone="txt" value={q.isLoading ? '…' : rows.length} />
      </div>

      <Card>
        <TableCard>
          <thead>
            <tr className="border-b border-line">
              <Th>#</Th><Th>Nhân viên</Th>
              <Th className="text-right">KH</Th><Th className="text-right">Lead</Th>
              <Th className="text-right">Cơ hội mở</Th><Th className="text-right">Pipeline</Th>
              <Th className="text-right">Weighted</Th><Th className="text-right">Won</Th>
              <Th className="text-right">Đơn</Th><Th className="text-right">Doanh thu</Th>
              <Th className="text-right">Đã thu</Th>
            </tr>
          </thead>
          <tbody>
            {q.isLoading && <RowMsg colSpan={11}>Đang tải…</RowMsg>}
            {q.isError && <RowMsg colSpan={11} danger>Lỗi: {apiError(q.error)}</RowMsg>}
            {q.data && rows.length === 0 && <RowMsg colSpan={11}>Chưa có dữ liệu.</RowMsg>}
            {rows.map((r, i) => (
              <tr key={r.id} className="border-b border-line/50 last:border-0 hover:bg-ink-3/40">
                <Td className="text-txt-2">{i === 0 ? '🏆' : i + 1}</Td>
                <Td className="font-medium">{r.name} <span className="text-txt-2 text-xs font-mono">@{r.username}</span></Td>
                <Td className="text-right tabular-nums">{r.customers}</Td>
                <Td className="text-right tabular-nums">{r.leads}</Td>
                <Td className="text-right tabular-nums">{r.open_opps}</Td>
                <Td className="text-right tabular-nums text-blue-300">{compactVnd(r.pipeline_vnd)}</Td>
                <Td className="text-right tabular-nums text-txt-2">{compactVnd(r.weighted_vnd)}</Td>
                <Td className="text-right tabular-nums">{r.won_opps}</Td>
                <Td className="text-right tabular-nums">{r.orders}</Td>
                <Td className="text-right tabular-nums text-flame font-semibold">{compactVnd(r.revenue_vnd)}</Td>
                <Td className="text-right tabular-nums text-ok">{compactVnd(r.collected_vnd)}</Td>
              </tr>
            ))}
          </tbody>
        </TableCard>
      </Card>
    </div>
  )
}
