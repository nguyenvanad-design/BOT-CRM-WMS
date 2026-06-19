/**
 * Tokinarc frontend — src/pages/ceo/Forecast.tsx
 * Dự báo pipeline (weighted) theo giai đoạn — THẬT từ /analytics/forecast/pipeline/.
 */
import { useQuery } from '@tanstack/react-query'
import { Sparkles } from 'lucide-react'
import { getForecast } from '@/lib/analytics'
import { apiError } from '@/lib/api'
import { compactVnd, formatVnd, OPP_STAGE_LABEL, OPP_STAGE_TONE } from '@/lib/crm'
import type { OppStage } from '@/lib/types'
import { Card, SectionTitle, StatCard, PageHeader, Tag, TableCard, Th, Td, RowMsg } from '@/components/ui'
import { MoneyBarChart } from '@/components/charts'

export function CeoForecastPage() {
  const fc = useQuery({ queryKey: ['ceo', 'fc'], queryFn: getForecast })

  const rows = fc.data ?? []
  const totalWeighted = rows.reduce((s, r) => s + r.weighted_vnd, 0)
  const totalDeals = rows.reduce((s, r) => s + r.count, 0)
  const chartData = rows.map((f) => ({ label: OPP_STAGE_LABEL[f.stage as OppStage] ?? f.stage, value: f.weighted_vnd }))

  return (
    <div className="max-w-5xl">
      <PageHeader icon={<Sparkles size={20} className="text-flame" />} title="Forecast" />

      <div className="grid grid-cols-2 gap-3 mb-4">
        <StatCard label="Forecast weighted" tone="flame" value={fc.isLoading ? '…' : compactVnd(totalWeighted)} />
        <StatCard label="Số cơ hội" tone="txt" value={fc.isLoading ? '…' : totalDeals} />
      </div>

      <Card className="mb-4">
        <SectionTitle>Dự báo theo giai đoạn (đã nhân xác suất)</SectionTitle>
        {fc.isLoading ? <p className="text-txt-2 text-sm text-center py-10">Đang tải…</p>
          : fc.isError ? <p className="text-danger text-sm">Lỗi: {apiError(fc.error)}</p>
          : <MoneyBarChart data={chartData} multicolor height={260} />}
      </Card>

      <Card>
        <SectionTitle>Chi tiết</SectionTitle>
        <TableCard>
          <thead><tr className="border-b border-line">
            <Th>Giai đoạn</Th><Th className="text-right">Số deal</Th><Th className="text-right">Forecast (weighted)</Th>
          </tr></thead>
          <tbody>
            {fc.isLoading && <RowMsg colSpan={3}>Đang tải…</RowMsg>}
            {fc.data && rows.length === 0 && <RowMsg colSpan={3}>Chưa có cơ hội nào.</RowMsg>}
            {rows.map((r) => (
              <tr key={r.stage} className="border-b border-line/50 last:border-0">
                <Td><Tag tone={OPP_STAGE_TONE[r.stage as OppStage] ?? 'gray'}>{OPP_STAGE_LABEL[r.stage as OppStage] ?? r.stage}</Tag></Td>
                <Td className="text-right tabular-nums">{r.count}</Td>
                <Td className="text-right text-flame tabular-nums">{formatVnd(r.weighted_vnd)}</Td>
              </tr>
            ))}
          </tbody>
        </TableCard>
      </Card>
    </div>
  )
}
