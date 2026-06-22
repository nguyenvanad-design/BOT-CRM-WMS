/**
 * Tokinarc frontend — src/pages/crm/LeadSources.tsx
 * Báo cáo Lead theo nguồn + chiến dịch. GET /crm/lead-sources/?days=
 * Sale → của mình; Manager → toàn bộ.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { PieChart } from 'lucide-react'
import { api, apiError } from '@/lib/api'
import { PageHeader, StatCard, TableCard, Th, Td, RowMsg } from '@/components/ui'

interface Row { source?: string; source_label: string; campaign?: string; referred_by?: string; total: number; converted: number; conversion_pct: number }
interface Report {
  days: number
  summary: { total: number; converted: number; conversion_pct: number }
  by_source: Row[]
  by_campaign: Row[]
  by_referrer: Row[]
}

export function LeadSourcesPage() {
  const [days, setDays] = useState(90)
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['lead-sources', days],
    queryFn: async () => (await api.get<Report>(`/crm/lead-sources/?days=${days}`)).data,
  })
  const maxTotal = Math.max(1, ...(data?.by_source ?? []).map((r) => r.total))

  return (
    <div className="max-w-4xl">
      <PageHeader icon={<PieChart size={20} className="text-flame" />} title="Nguồn lead"
        subtitle={data ? `${data.summary.total} lead · ${days} ngày` : undefined}
        actions={
          <div className="flex gap-1">
            {[30, 90, 365].map((d) => (
              <button key={d} onClick={() => setDays(d)}
                className={`text-xs rounded-md px-2.5 py-1.5 border transition-colors ${
                  days === d ? 'border-flame text-flame bg-flame/10' : 'border-line text-txt-2 hover:text-txt'}`}>
                {d === 365 ? '1 năm' : `${d} ngày`}
              </button>
            ))}
          </div>
        } />

      {isLoading && <div className="text-txt-2 text-sm">Đang tải…</div>}
      {isError && <div className="text-danger text-sm">Lỗi: {apiError(error)}</div>}

      {data && (
        <>
          <div className="grid grid-cols-3 gap-3 mb-4">
            <StatCard label="Tổng lead" tone="flame" value={String(data.summary.total)} />
            <StatCard label="Đã thành KH" tone="ok" value={String(data.summary.converted)} />
            <StatCard label="Tỉ lệ chuyển" tone="blue" value={`${data.summary.conversion_pct}%`} />
          </div>

          <div className="bg-ink-2 border border-line rounded-lg p-4 mb-4">
            <div className="text-sm font-semibold mb-3">Lead theo nguồn</div>
            {data.by_source.length === 0 && <div className="text-txt-2 text-sm">Chưa có lead.</div>}
            <div className="space-y-2.5">
              {data.by_source.map((r) => (
                <div key={r.source} className="flex items-center gap-3">
                  <span className="w-36 text-xs shrink-0 truncate">{r.source_label}</span>
                  <div className="flex-1 h-5 bg-ink-3 rounded overflow-hidden relative">
                    <div className="h-full bg-flame/70 rounded" style={{ width: `${(r.total / maxTotal) * 100}%` }} />
                    <span className="absolute inset-y-0 left-2 flex items-center text-[11px] text-txt">
                      {r.total} lead · {r.converted} KH ({r.conversion_pct}%)
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="text-sm font-semibold mb-2">Theo chiến dịch</div>
          <TableCard>
            <thead><tr className="border-b border-line">
              <Th>Chiến dịch</Th><Th>Nguồn</Th><Th className="text-right">Lead</Th>
              <Th className="text-right">Thành KH</Th><Th className="text-right">Tỉ lệ</Th>
            </tr></thead>
            <tbody>
              {data.by_campaign.length === 0 && <RowMsg colSpan={5}>Chưa gắn chiến dịch nào.</RowMsg>}
              {data.by_campaign.map((r, i) => (
                <tr key={i} className="border-b border-line/50 last:border-0">
                  <Td className="font-medium">{r.campaign}</Td>
                  <Td className="text-txt-2">{r.source_label}</Td>
                  <Td className="text-right tabular-nums">{r.total}</Td>
                  <Td className="text-right tabular-nums text-ok">{r.converted}</Td>
                  <Td className="text-right tabular-nums">{r.conversion_pct}%</Td>
                </tr>
              ))}
            </tbody>
          </TableCard>

          <div className="text-sm font-semibold mb-2 mt-5">🤝 Top người giới thiệu</div>
          <TableCard>
            <thead><tr className="border-b border-line">
              <Th>Người giới thiệu</Th><Th className="text-right">Lead</Th>
              <Th className="text-right">Thành KH</Th><Th className="text-right">Tỉ lệ</Th>
            </tr></thead>
            <tbody>
              {data.by_referrer.length === 0 && <RowMsg colSpan={4}>Chưa có lead từ giới thiệu.</RowMsg>}
              {data.by_referrer.map((r, i) => (
                <tr key={i} className="border-b border-line/50 last:border-0">
                  <Td className="font-medium">{r.referred_by}</Td>
                  <Td className="text-right tabular-nums">{r.total}</Td>
                  <Td className="text-right tabular-nums text-ok">{r.converted}</Td>
                  <Td className="text-right tabular-nums">{r.conversion_pct}%</Td>
                </tr>
              ))}
            </tbody>
          </TableCard>
        </>
      )}
    </div>
  )
}
