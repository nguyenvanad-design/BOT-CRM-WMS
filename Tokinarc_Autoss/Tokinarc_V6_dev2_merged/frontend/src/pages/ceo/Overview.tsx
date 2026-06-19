/**
 * Tokinarc frontend — src/pages/ceo/Overview.tsx
 * Bảng điều hành CEO: KPI + biểu đồ doanh thu/phân khúc/forecast + công nợ.
 * Toàn bộ số liệu THẬT từ /analytics (manager/admin).
 */
import { useQuery } from '@tanstack/react-query'
import { Crown } from 'lucide-react'
import {
  getKpi, getRevenueMonthly, getRevenueBySegment, getForecast,
  getInventoryValue, getDebtAging,
} from '@/lib/analytics'
import { apiError } from '@/lib/api'
import { compactVnd, formatVnd, SEGMENT_LABEL, OPP_STAGE_LABEL } from '@/lib/crm'
import type { OppStage } from '@/lib/types'
import { Card, SectionTitle, StatCard, PageHeader, RowMsg, TableCard, Th, Td } from '@/components/ui'
import { MoneyBarChart } from '@/components/charts'

export function CeoOverviewPage() {
  const kpi = useQuery({ queryKey: ['ceo', 'kpi'], queryFn: getKpi })
  const rev = useQuery({ queryKey: ['ceo', 'rev'], queryFn: getRevenueMonthly })
  const seg = useQuery({ queryKey: ['ceo', 'seg'], queryFn: getRevenueBySegment })
  const fc = useQuery({ queryKey: ['ceo', 'fc'], queryFn: getForecast })
  const invv = useQuery({ queryKey: ['ceo', 'invv'], queryFn: () => getInventoryValue() })
  const debt = useQuery({ queryKey: ['ceo', 'debt'], queryFn: getDebtAging })

  if (kpi.isError) {
    return (
      <div className="max-w-3xl">
        <PageHeader icon={<Crown size={20} className="text-flame" />} title="Bảng điều hành" />
        <p className="text-danger text-sm">Lỗi: {apiError(kpi.error)} (cần quyền quản lý/admin)</p>
      </div>
    )
  }

  const k = kpi.data
  const revData = (rev.data ?? []).map((r) => ({ label: r.month, value: r.revenue_vnd }))
  const segData = (seg.data ?? []).map((s) => ({ label: SEGMENT_LABEL[s.segment] ?? s.segment, value: s.revenue_vnd }))
  const fcData = (fc.data ?? []).map((f) => ({ label: OPP_STAGE_LABEL[f.stage as OppStage] ?? f.stage, value: f.weighted_vnd }))
  const topDebt = [...(debt.data?.results ?? [])].sort((a, b) => b.days_overdue - a.days_overdue).slice(0, 6)

  return (
    <div className="max-w-6xl">
      <PageHeader icon={<Crown size={20} className="text-flame" />} title="Bảng điều hành"
        subtitle="Tổng quan điều hành — số liệu trực tiếp toàn công ty" />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-3">
        <StatCard label="Doanh thu (ghi nhận)" tone="flame" value={kpi.isLoading ? '…' : compactVnd(k?.revenue_vnd)} />
        <StatCard label="Đã thu" tone="ok" value={kpi.isLoading ? '…' : compactVnd(k?.collected_vnd)} />
        <StatCard label="Công nợ phải thu" tone="danger" value={kpi.isLoading ? '…' : compactVnd(k?.debt_vnd)} />
        <StatCard label="Giá trị tồn kho" tone="blue" value={invv.isLoading ? '…' : compactVnd(invv.data?.inventory_value_vnd)} />
      </div>
      <div className="grid grid-cols-3 gap-3 mb-4">
        <StatCard label="Số đơn hàng" tone="txt" value={kpi.isLoading ? '…' : (k?.order_count ?? 0)} />
        <StatCard label="Khách hàng" tone="txt" value={kpi.isLoading ? '…' : (k?.customer_count ?? 0)} />
        <StatCard label="Lead đang theo" tone="warn" value={kpi.isLoading ? '…' : (k?.open_leads ?? 0)} />
      </div>

      <div className="grid lg:grid-cols-2 gap-4 mb-4">
        <Card>
          <SectionTitle>Doanh thu theo tháng</SectionTitle>
          {rev.isLoading ? <Loading /> : <MoneyBarChart data={revData} />}
        </Card>
        <Card>
          <SectionTitle>Doanh thu theo phân khúc</SectionTitle>
          {seg.isLoading ? <Loading /> : <MoneyBarChart data={segData} multicolor />}
        </Card>
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <Card>
          <SectionTitle>Dự báo pipeline (weighted)</SectionTitle>
          {fc.isLoading ? <Loading /> : <MoneyBarChart data={fcData} multicolor />}
        </Card>
        <Card>
          <SectionTitle>Công nợ cần thu</SectionTitle>
          <TableCard>
            <thead><tr className="border-b border-line">
              <Th>Khách hàng</Th><Th className="text-right">Số nợ</Th><Th className="text-right">Quá hạn</Th>
            </tr></thead>
            <tbody>
              {debt.isLoading && <RowMsg colSpan={3}>Đang tải…</RowMsg>}
              {debt.data && topDebt.length === 0 && <RowMsg colSpan={3}>Không có công nợ. 🎉</RowMsg>}
              {topDebt.map((d) => (
                <tr key={d.code} className="border-b border-line/50 last:border-0">
                  <Td className="font-medium">{d.customer}</Td>
                  <Td className="text-right tabular-nums">{formatVnd(d.amount_due)}</Td>
                  <Td className="text-right tabular-nums">
                    {d.days_overdue > 0 ? <span className="text-danger">{d.days_overdue} ngày</span> : <span className="text-txt-2">trong hạn</span>}
                  </Td>
                </tr>
              ))}
            </tbody>
          </TableCard>
        </Card>
      </div>
    </div>
  )
}

function Loading() {
  return <div className="text-txt-2 text-sm text-center py-10">Đang tải…</div>
}
