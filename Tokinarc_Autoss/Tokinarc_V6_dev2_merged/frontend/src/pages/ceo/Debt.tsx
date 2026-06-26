/**
 * Tokinarc frontend — src/pages/ceo/Debt.tsx
 * Công nợ toàn công ty + phân tích tuổi nợ — THẬT từ /analytics/debt-aging/.
 */
import { useQuery } from '@tanstack/react-query'
import { Wallet } from 'lucide-react'
import { getDebtAging } from '@/lib/analytics'
import { api, apiError } from '@/lib/api'
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

interface PayableResp { total_payable: number; by_supplier: { supplier: string; debt: number }[] }

export function CeoDebtPage() {
  const debt = useQuery({ queryKey: ['ceo', 'debt'], queryFn: getDebtAging })
  const payable = useQuery({
    queryKey: ['ceo', 'payable'],
    queryFn: async () => (await api.get<PayableResp>('/analytics/payable/')).data,
  })

  const rows = (debt.data?.results ?? []).map((d) => ({
    ...d, b: RAW_TO_BUCKET[d.bucket as string] ?? 'current',
  }))
  const total = rows.reduce((s, r) => s + r.amount_due, 0)
  const totalPayable = payable.data?.total_payable ?? 0
  const net = total - totalPayable
  const sumBucket = (b: DebtBucket) => rows.filter((r) => r.b === b).reduce((s, r) => s + r.amount_due, 0)
  const sorted = [...rows].sort((a, b) => b.days_overdue - a.days_overdue)

  return (
    <div className="max-w-5xl">
      <PageHeader icon={<Wallet size={20} className="text-flame" />} title="Công nợ (Phải thu / Phải trả)"
        subtitle="Phải thu khách + phải trả nhà cung cấp — dòng tiền ròng" />

      {/* Tổng quan 2 chiều: thu − trả = ròng */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        <StatCard label="Phải thu (KH nợ mình)" tone="ok" value={debt.isLoading ? '…' : compactVnd(total)} />
        <StatCard label="Phải trả NCC (mình nợ)" tone="danger" value={payable.isLoading ? '…' : compactVnd(totalPayable)} />
        <StatCard label="Ròng (thu − trả)" tone={net >= 0 ? 'ok' : 'danger'}
          value={(debt.isLoading || payable.isLoading) ? '…' : compactVnd(net)} />
      </div>

      <SectionTitle>Phải thu — phân tích tuổi nợ</SectionTitle>
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

      <Card className="mt-4">
        <SectionTitle>Phải trả nhà cung cấp</SectionTitle>
        <TableCard>
          <thead><tr className="border-b border-line">
            <Th>Nhà cung cấp</Th><Th className="text-right">Còn nợ NCC</Th>
          </tr></thead>
          <tbody>
            {payable.isLoading && <RowMsg colSpan={2}>Đang tải…</RowMsg>}
            {payable.isError && <RowMsg colSpan={2} danger>Lỗi: {apiError(payable.error)}</RowMsg>}
            {payable.data && payable.data.by_supplier.length === 0 && <RowMsg colSpan={2}>Không nợ NCC. 🎉</RowMsg>}
            {(payable.data?.by_supplier ?? []).map((r, i) => (
              <tr key={i} className="border-b border-line/50 last:border-0 hover:bg-ink-3/40">
                <Td className="font-medium">{r.supplier}</Td>
                <Td className="text-right tabular-nums text-danger">{formatVnd(r.debt)}</Td>
              </tr>
            ))}
          </tbody>
        </TableCard>
      </Card>
    </div>
  )
}
