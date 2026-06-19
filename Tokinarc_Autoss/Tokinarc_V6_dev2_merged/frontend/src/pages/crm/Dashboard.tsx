/**
 * Tokinarc frontend — src/pages/crm/Dashboard.tsx
 * Dashboard CRM: KPI tổng hợp THẬT từ các list endpoint (/crm/...).
 * - Pipeline mở = tổng est_value_vnd của opportunity chưa won/lost.
 * - Số KH / lead / ticket mở lấy từ count phân trang.
 */
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { LayoutDashboard } from 'lucide-react'
import { fetchAll, fetchCount } from '@/lib/list'
import { apiError } from '@/lib/api'
import {
  compactVnd, formatDate, OPP_STAGE_LABEL, OPP_STAGE_TONE,
  TICKET_STATUS_TONE, TICKET_PRIORITY_LABEL, TICKET_PRIORITY_TONE,
} from '@/lib/crm'
import type { Opportunity, Ticket } from '@/lib/types'
import {
  Card, SectionTitle, StatCard, PageHeader, Tag, Gauge,
  TableCard, Th, Td, RowMsg,
} from '@/components/ui'

const OPEN_STAGES = new Set(['prospect', 'qualify', 'proposal', 'negotiate'])

export function DashboardPage() {
  const nav = useNavigate()

  const opps = useQuery({
    queryKey: ['dash', 'opportunities'],
    queryFn: () => fetchAll<Opportunity>('/crm/opportunities/'),
  })
  const tickets = useQuery({
    queryKey: ['dash', 'tickets'],
    queryFn: () => fetchAll<Ticket>('/crm/tickets/'),
  })
  const customerCount = useQuery({
    queryKey: ['dash', 'customers', 'count'],
    queryFn: () => fetchCount('/crm/customers/'),
  })
  const leadCount = useQuery({
    queryKey: ['dash', 'leads', 'count'],
    queryFn: () => fetchCount('/crm/leads/'),
  })

  const openOpps = (opps.data?.items ?? []).filter((o) => OPEN_STAGES.has(o.stage))
  const pipelineValue = openOpps.reduce((s, o) => s + Number(o.est_value_vnd || 0), 0)
  const weighted = openOpps.reduce(
    (s, o) => s + (Number(o.est_value_vnd || 0) * (o.probability || 0)) / 100, 0,
  )
  const openTickets = (tickets.data?.items ?? []).filter(
    (t) => t.status === 'open' || t.status === 'in_progress',
  )

  // Cơ hội sắp chốt: còn mở, sắp xếp theo ngày dự kiến gần nhất.
  const closing = [...openOpps]
    .sort((a, b) => (a.expected_close ?? '9999').localeCompare(b.expected_close ?? '9999'))
    .slice(0, 6)

  return (
    <div className="max-w-6xl">
      <PageHeader
        icon={<LayoutDashboard size={20} className="text-flame" />}
        title="Dashboard"
        subtitle="Tổng quan kinh doanh — số liệu trực tiếp từ hệ thống"
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <StatCard
          label="Khách hàng" tone="txt"
          value={customerCount.isLoading ? '…' : (customerCount.data ?? '—')}
          onClick={() => nav('/customers')}
        />
        <StatCard
          label="Pipeline mở" tone="blue"
          value={opps.isLoading ? '…' : compactVnd(pipelineValue)}
          delta={<span className="text-warn">{openOpps.length} cơ hội</span>}
          onClick={() => nav('/opportunities')}
        />
        <StatCard
          label="Forecast (weighted)" tone="flame"
          value={opps.isLoading ? '…' : compactVnd(weighted)}
          delta={<span className="text-txt-2">theo xác suất chốt</span>}
          onClick={() => nav('/pipeline')}
        />
        <StatCard
          label="Ticket mở" tone="danger"
          value={tickets.isLoading ? '…' : openTickets.length}
          delta={<span className="text-txt-2">{leadCount.data ?? 0} lead đang theo</span>}
          onClick={() => nav('/tickets')}
        />
      </div>

      <Card className="mb-4">
        <SectionTitle action={<button className="text-xs text-flame hover:underline" onClick={() => nav('/opportunities')}>Xem tất cả</button>}>
          Cơ hội sắp chốt
        </SectionTitle>
        <TableCard>
          <thead>
            <tr className="border-b border-line">
              <Th>Cơ hội</Th><Th>Khách hàng</Th><Th className="text-right">Giá trị</Th>
              <Th className="w-40">Xác suất</Th><Th>Dự kiến</Th><Th>Giai đoạn</Th>
            </tr>
          </thead>
          <tbody>
            {opps.isLoading && <RowMsg colSpan={6}>Đang tải…</RowMsg>}
            {opps.isError && <RowMsg colSpan={6} danger>Lỗi: {apiError(opps.error)}</RowMsg>}
            {opps.data && closing.length === 0 && <RowMsg colSpan={6}>Chưa có cơ hội đang mở.</RowMsg>}
            {closing.map((o) => (
              <tr key={o.id} className="border-b border-line/50 last:border-0 hover:bg-ink-3/40">
                <Td className="font-medium">{o.title}</Td>
                <Td className="text-txt-2">{o.customer_name}</Td>
                <Td className="text-right text-flame tabular-nums">{compactVnd(o.est_value_vnd)}</Td>
                <Td><Gauge pct={o.probability} tone={o.probability >= 70 ? 'ok' : 'warn'} /></Td>
                <Td className="text-txt-2">{formatDate(o.expected_close)}</Td>
                <Td><Tag tone={OPP_STAGE_TONE[o.stage]}>{OPP_STAGE_LABEL[o.stage]}</Tag></Td>
              </tr>
            ))}
          </tbody>
        </TableCard>
      </Card>

      <Card>
        <SectionTitle action={<button className="text-xs text-flame hover:underline" onClick={() => nav('/tickets')}>Xem tất cả</button>}>
          Ticket cần chú ý
        </SectionTitle>
        <TableCard>
          <thead>
            <tr className="border-b border-line">
              <Th>Mã</Th><Th>Khách hàng</Th><Th>Tiêu đề</Th><Th>Ưu tiên</Th><Th>Trạng thái</Th>
            </tr>
          </thead>
          <tbody>
            {tickets.isLoading && <RowMsg colSpan={5}>Đang tải…</RowMsg>}
            {tickets.isError && <RowMsg colSpan={5} danger>Lỗi: {apiError(tickets.error)}</RowMsg>}
            {tickets.data && openTickets.length === 0 && <RowMsg colSpan={5}>Không có ticket đang mở.</RowMsg>}
            {openTickets.slice(0, 6).map((t) => (
              <tr key={t.id} className="border-b border-line/50 last:border-0 hover:bg-ink-3/40">
                <Td className="font-mono text-flame">{t.code}</Td>
                <Td className="text-txt-2">{t.customer_name}</Td>
                <Td className="font-medium">{t.title}</Td>
                <Td><Tag tone={TICKET_PRIORITY_TONE[t.priority]}>{TICKET_PRIORITY_LABEL[t.priority]}</Tag></Td>
                <Td><Tag tone={TICKET_STATUS_TONE[t.status]}>{t.status_display}</Tag></Td>
              </tr>
            ))}
          </tbody>
        </TableCard>
      </Card>
    </div>
  )
}
