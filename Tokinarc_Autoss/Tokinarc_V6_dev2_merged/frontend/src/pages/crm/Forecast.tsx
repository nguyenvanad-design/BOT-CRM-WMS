/**
 * Tokinarc frontend — src/pages/crm/Forecast.tsx
 * Forecast pipeline cho CRM (sale xem được) — tính client-side từ
 * /crm/opportunities/ (weighted = giá trị × xác suất). Khác CEO Forecast
 * (manager-only, từ analytics).
 */
import { useQuery } from '@tanstack/react-query'
import { TrendingUp } from 'lucide-react'
import { fetchAll } from '@/lib/list'
import { apiError } from '@/lib/api'
import { compactVnd, formatVnd, OPP_STAGE_LABEL, OPP_STAGE_TONE, OPP_STAGE_ORDER } from '@/lib/crm'
import type { Opportunity, OppStage } from '@/lib/types'
import { Card, SectionTitle, StatCard, PageHeader, Tag, TableCard, Th, Td, RowMsg } from '@/components/ui'
import { MoneyBarChart } from '@/components/charts'

const OPEN = new Set<OppStage>(['prospect', 'qualify', 'proposal', 'negotiate'])

export function CrmForecastPage() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['crm-forecast'],
    queryFn: () => fetchAll<Opportunity>('/crm/opportunities/'),
  })
  const items = data?.items ?? []

  const byStage = OPP_STAGE_ORDER.map((stage) => {
    const rows = items.filter((o) => o.stage === stage)
    const value = rows.reduce((s, o) => s + Number(o.est_value_vnd || 0), 0)
    const weighted = rows.reduce((s, o) => s + (Number(o.est_value_vnd || 0) * (o.probability || 0)) / 100, 0)
    return { stage, count: rows.length, value, weighted }
  }).filter((r) => r.count > 0)

  const openRows = byStage.filter((r) => OPEN.has(r.stage))
  const totalWeighted = openRows.reduce((s, r) => s + r.weighted, 0)
  const totalValue = openRows.reduce((s, r) => s + r.value, 0)
  const chart = openRows.map((r) => ({ label: OPP_STAGE_LABEL[r.stage], value: r.weighted }))

  return (
    <div className="max-w-5xl">
      <PageHeader icon={<TrendingUp size={20} className="text-flame" />} title="Forecast" />

      <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 mb-4">
        <StatCard label="Pipeline mở" tone="blue" value={isLoading ? '…' : compactVnd(totalValue)} />
        <StatCard label="Forecast (weighted)" tone="flame" value={isLoading ? '…' : compactVnd(totalWeighted)} />
        <StatCard label="Số cơ hội mở" tone="txt" value={isLoading ? '…' : openRows.reduce((s, r) => s + r.count, 0)} />
      </div>

      <Card className="mb-4">
        <SectionTitle>Dự báo theo giai đoạn (weighted)</SectionTitle>
        {isLoading ? <p className="text-txt-2 text-sm text-center py-10">Đang tải…</p>
          : isError ? <p className="text-danger text-sm">Lỗi: {apiError(error)}</p>
          : <MoneyBarChart data={chart} multicolor height={260} />}
      </Card>

      <Card>
        <SectionTitle>Chi tiết theo giai đoạn</SectionTitle>
        <TableCard>
          <thead><tr className="border-b border-line">
            <Th>Giai đoạn</Th><Th className="text-right">Số deal</Th>
            <Th className="text-right">Tổng giá trị</Th><Th className="text-right">Weighted</Th>
          </tr></thead>
          <tbody>
            {isLoading && <RowMsg colSpan={4}>Đang tải…</RowMsg>}
            {data && byStage.length === 0 && <RowMsg colSpan={4}>Chưa có cơ hội nào.</RowMsg>}
            {byStage.map((r) => (
              <tr key={r.stage} className="border-b border-line/50 last:border-0">
                <Td><Tag tone={OPP_STAGE_TONE[r.stage]}>{OPP_STAGE_LABEL[r.stage]}</Tag></Td>
                <Td className="text-right tabular-nums">{r.count}</Td>
                <Td className="text-right tabular-nums text-txt-2">{compactVnd(r.value)}</Td>
                <Td className="text-right tabular-nums text-flame">{formatVnd(Math.round(r.weighted))}</Td>
              </tr>
            ))}
          </tbody>
        </TableCard>
      </Card>
    </div>
  )
}
