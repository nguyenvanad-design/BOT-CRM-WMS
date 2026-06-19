/**
 * Tokinarc frontend — src/pages/ceo/Debt.tsx
 * Công nợ toàn công ty + phân tích tuổi nợ — THẬT từ /analytics/debt-aging/.
 */
import { useQuery } from '@tanstack/react-query'
import { Wallet } from 'lucide-react'
import { getDebtAging } from '@/lib/analytics'
import { apiError } from '@/lib/api'
import { compactVnd, formatVnd } from '@/lib/crm'
import type { DebtBucket } from '@/lib/types'
import type { TagTone } from '@/lib/crm'
import { Card, SectionTitle, StatCard, PageHeader, Tag, TableCard, Th, Td, RowMsg } from '@/components/ui'

const BUCKET_LABEL: Record<DebtBucket, string> = {
  current: 'Trong hạn', d1_30: 'Quá 1-30 ngày', d31_60: 'Quá 31-60 ngày', d60p: 'Quá >60 ngày',
}
// debt-aging trả bucket dạng 'current' | '1-30' | '31-60' | '60+'
const RAW_TO_BUCKET: Record<string, DebtBucket> = {
  current: 'current', '1-30': 'd1_30', '31-60': 'd31_60', '60+': 'd60p',
}
const BUCKET_TONE: Record<DebtBucket, TagTone> = {
  current: 'ok', d1_30: 'warn', d31_60: 'flame', d60p: 'danger',
}

export function CeoDebtPage() {
  const debt = useQuery({ queryKey: ['ceo', 'debt'], queryFn: getDebtAging })

  const rows = (debt.data?.results ?? []).map((d) => ({
    ...d, b: RAW_TO_BUCKET[d.bucket as string] ?? 'current',
  }))
  const total = rows.reduce((s, r) => s + r.amount_due, 0)
  const sumBucket = (b: DebtBucket) => rows.filter((r) => r.b === b).reduce((s, r) => s + r.amount_due, 0)
  const sorted = [...rows].sort((a, b) => b.days_overdue - a.days_overdue)

  return (
    <div className="max-w-5xl">
      <PageHeader icon={<Wallet size={20} className="text-flame" />} title="Công nợ phải thu"
        subtitle={debt.data ? `${debt.data.count} đơn còn nợ` : undefined} />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <StatCard label="Tổng phải thu" tone="flame" value={debt.isLoading ? '…' : compactVnd(total)} />
        <StatCard label="Trong hạn" tone="ok" value={debt.isLoading ? '…' : compactVnd(sumBucket('current'))} />
        <StatCard label="Quá 1-60 ngày" tone="warn" value={debt.isLoading ? '…' : compactVnd(sumBucket('d1_30') + sumBucket('d31_60'))} />
        <StatCard label="Quá >60 ngày" tone="danger" value={debt.isLoading ? '…' : compactVnd(sumBucket('d60p'))} />
      </div>

      <Card>
        <SectionTitle>Chi tiết công nợ</SectionTitle>
        <TableCard>
          <thead><tr className="border-b border-line">
            <Th>Mã đơn</Th><Th>Khách hàng</Th><Th className="text-right">Số nợ</Th>
            <Th className="text-right">Quá hạn</Th><Th>Nhóm</Th>
          </tr></thead>
          <tbody>
            {debt.isLoading && <RowMsg colSpan={5}>Đang tải…</RowMsg>}
            {debt.isError && <RowMsg colSpan={5} danger>Lỗi: {apiError(debt.error)} (cần quyền quản lý)</RowMsg>}
            {debt.data && sorted.length === 0 && <RowMsg colSpan={5}>Không có công nợ. 🎉</RowMsg>}
            {sorted.map((d) => (
              <tr key={d.code} className="border-b border-line/50 last:border-0 hover:bg-ink-3/40">
                <Td className="font-mono text-flame">{d.code}</Td>
                <Td className="font-medium">{d.customer}</Td>
                <Td className="text-right tabular-nums">{formatVnd(d.amount_due)}</Td>
                <Td className="text-right tabular-nums">
                  {d.days_overdue > 0 ? <span className="text-danger">{d.days_overdue} ngày</span> : <span className="text-txt-2">—</span>}
                </Td>
                <Td><Tag tone={BUCKET_TONE[d.b]}>{BUCKET_LABEL[d.b]}</Tag></Td>
              </tr>
            ))}
          </tbody>
        </TableCard>
      </Card>
    </div>
  )
}
