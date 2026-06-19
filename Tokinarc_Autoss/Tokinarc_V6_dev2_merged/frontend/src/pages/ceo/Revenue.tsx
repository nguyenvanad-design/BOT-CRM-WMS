/**
 * Tokinarc frontend — src/pages/ceo/Revenue.tsx
 * Doanh thu: biểu đồ theo tháng + bảng theo phân khúc (THẬT từ /analytics).
 */
import { useQuery } from '@tanstack/react-query'
import { TrendingUp } from 'lucide-react'
import { getRevenueMonthly, getRevenueBySegment } from '@/lib/analytics'
import { apiError } from '@/lib/api'
import { compactVnd, formatVnd, SEGMENT_LABEL } from '@/lib/crm'
import { Card, SectionTitle, PageHeader, TableCard, Th, Td, RowMsg } from '@/components/ui'
import { MoneyBarChart } from '@/components/charts'

export function CeoRevenuePage() {
  const rev = useQuery({ queryKey: ['ceo', 'rev'], queryFn: getRevenueMonthly })
  const seg = useQuery({ queryKey: ['ceo', 'seg'], queryFn: getRevenueBySegment })

  const revData = (rev.data ?? []).map((r) => ({ label: r.month, value: r.revenue_vnd }))
  const totalRev = (seg.data ?? []).reduce((s, r) => s + r.revenue_vnd, 0)

  return (
    <div className="max-w-5xl">
      <PageHeader icon={<TrendingUp size={20} className="text-flame" />} title="Doanh thu" />

      <Card className="mb-4">
        <SectionTitle>Doanh thu theo tháng <span className="text-xs text-txt-2 font-normal">(đơn active/shipping/completed)</span></SectionTitle>
        {rev.isLoading ? <p className="text-txt-2 text-sm text-center py-10">Đang tải…</p>
          : rev.isError ? <p className="text-danger text-sm">Lỗi: {apiError(rev.error)}</p>
          : <MoneyBarChart data={revData} height={280} />}
      </Card>

      <Card>
        <SectionTitle>Doanh thu theo phân khúc khách hàng</SectionTitle>
        <TableCard>
          <thead><tr className="border-b border-line">
            <Th>Phân khúc</Th><Th className="text-right">Doanh thu</Th><Th className="text-right">Tỷ trọng</Th><Th className="text-right">Số đơn</Th>
          </tr></thead>
          <tbody>
            {seg.isLoading && <RowMsg colSpan={4}>Đang tải…</RowMsg>}
            {seg.data && seg.data.length === 0 && <RowMsg colSpan={4}>Chưa có doanh thu.</RowMsg>}
            {seg.data?.map((r) => (
              <tr key={r.segment} className="border-b border-line/50 last:border-0">
                <Td className="font-medium">{SEGMENT_LABEL[r.segment] ?? r.segment}</Td>
                <Td className="text-right text-flame tabular-nums">{formatVnd(r.revenue_vnd)}</Td>
                <Td className="text-right text-txt-2 tabular-nums">{totalRev ? Math.round((r.revenue_vnd / totalRev) * 100) : 0}%</Td>
                <Td className="text-right text-txt-2 tabular-nums">{r.orders}</Td>
              </tr>
            ))}
          </tbody>
        </TableCard>
        {seg.data && seg.data.length > 0 && (
          <div className="text-right text-sm mt-3 text-txt-2">Tổng: <span className="text-flame font-semibold">{compactVnd(totalRev)}</span></div>
        )}
      </Card>
    </div>
  )
}
