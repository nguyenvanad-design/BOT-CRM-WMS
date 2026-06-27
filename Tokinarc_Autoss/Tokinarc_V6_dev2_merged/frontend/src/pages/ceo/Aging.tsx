/**
 * Tokinarc frontend — src/pages/ceo/Aging.tsx
 * Tuổi tồn & Hàng chậm/chết (manager+). Cho thấy VỐN ĐANG CHÔN ở hàng để lâu.
 *  - Aging: bucket theo ngày nhập (received_at) + giá trị theo giá vốn.
 *  - Dead stock: còn tồn nhưng >90 ngày không xuất, xếp theo vốn chôn giảm dần.
 */
import { useQuery } from '@tanstack/react-query'
import { Hourglass, PackageX } from 'lucide-react'
import { api, apiError } from '@/lib/api'
import { compactVnd, formatVnd } from '@/lib/crm'
import {
  PageHeader, Card, SectionTitle, StatCard, TableCard, Th, Td, RowMsg, Tag,
} from '@/components/ui'

interface AgingBucket { bucket: string; lines: number; qty: number; value_vnd: number }
interface AgingResp { buckets: AgingBucket[]; total_value_vnd: number }
interface DeadItem { part_no: string; name: string; qty: number; value_vnd: number; last_out: string | null; days_idle: number | null }
interface DeadResp { days: number; count: number; tied_value_vnd: number; results: DeadItem[] }

const B_LABEL: Record<string, string> = {
  '0-30': '0–30 ngày', '31-90': '31–90 ngày', '91-180': '91–180 ngày',
  '180+': '> 180 ngày', 'unknown': 'Chưa rõ ngày nhập',
}
const B_TONE: Record<string, 'ok' | 'warn' | 'danger' | 'gray'> = {
  '0-30': 'ok', '31-90': 'warn', '91-180': 'danger', '180+': 'danger', 'unknown': 'gray',
}

export function CeoAgingPage() {
  const aging = useQuery({ queryKey: ['ceo', 'aging'], queryFn: async () => (await api.get<AgingResp>('/analytics/inventory/aging/')).data })
  const dead = useQuery({ queryKey: ['ceo', 'dead'], queryFn: async () => (await api.get<DeadResp>('/analytics/inventory/dead-stock/')).data })

  const buckets = aging.data?.buckets ?? []
  const totalVal = aging.data?.total_value_vnd ?? 0
  // Vốn ở hàng "để lâu" (>90 ngày) — tiền chôn đáng lo.
  const oldVal = buckets.filter((b) => b.bucket === '91-180' || b.bucket === '180+').reduce((s, b) => s + b.value_vnd, 0)

  return (
    <div className="max-w-5xl">
      <PageHeader icon={<Hourglass size={20} className="text-flame" />} title="Tuổi tồn & Hàng chậm"
        subtitle="Vốn đang chôn ở hàng để lâu — theo giá vốn" />

      <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 mb-4">
        <StatCard label="Tổng giá trị tồn (giá vốn)" tone="txt" value={aging.isLoading ? '…' : compactVnd(totalVal)} />
        <StatCard label="Vốn ở hàng > 90 ngày" tone="danger" value={aging.isLoading ? '…' : compactVnd(oldVal)} />
        <StatCard label="Vốn chôn hàng chậm (>90n không xuất)" tone="warn"
          value={dead.isLoading ? '…' : compactVnd(dead.data?.tied_value_vnd ?? 0)} />
      </div>

      {/* AGING — bucket theo ngày nhập */}
      <Card className="mb-4">
        <SectionTitle>Tuổi tồn theo ngày nhập</SectionTitle>
        <TableCard>
          <thead><tr className="border-b border-line">
            <Th>Nhóm tuổi</Th><Th className="text-right">Số dòng tồn</Th>
            <Th className="text-right">Số lượng</Th><Th className="text-right">Giá trị (giá vốn)</Th>
          </tr></thead>
          <tbody>
            {aging.isLoading && <RowMsg colSpan={4}>Đang tải…</RowMsg>}
            {aging.isError && <RowMsg colSpan={4} danger>Lỗi: {apiError(aging.error)}</RowMsg>}
            {buckets.map((b) => (
              <tr key={b.bucket} className="border-b border-line/50 last:border-0">
                <Td><Tag tone={B_TONE[b.bucket]}>{B_LABEL[b.bucket] ?? b.bucket}</Tag></Td>
                <Td className="text-right tabular-nums">{b.lines}</Td>
                <Td className="text-right tabular-nums">{b.qty.toLocaleString('vi-VN')}</Td>
                <Td className="text-right tabular-nums">{formatVnd(b.value_vnd)}</Td>
              </tr>
            ))}
          </tbody>
        </TableCard>
        <p className="text-[11px] text-txt-2 mt-2">Tuổi tính theo lần nhập đầu (FIFO). "Chưa rõ" = hàng seed/cũ chưa ghi ngày nhập.</p>
      </Card>

      {/* DEAD STOCK — lâu không xuất */}
      <Card>
        <SectionTitle>
          <span className="flex items-center gap-1.5"><PackageX size={15} className="text-danger" /> Hàng chậm / chết (&gt; 90 ngày không xuất)</span>
        </SectionTitle>
        <TableCard>
          <thead><tr className="border-b border-line">
            <Th>Mã</Th><Th>Tên</Th><Th className="text-right">Tồn</Th>
            <Th className="text-right">Vốn chôn</Th><Th>Lần xuất cuối</Th>
          </tr></thead>
          <tbody>
            {dead.isLoading && <RowMsg colSpan={5}>Đang tải…</RowMsg>}
            {dead.isError && <RowMsg colSpan={5} danger>Lỗi: {apiError(dead.error)}</RowMsg>}
            {dead.data && dead.data.results.length === 0 && <RowMsg colSpan={5}>Không có hàng chậm. 🎉</RowMsg>}
            {(dead.data?.results ?? []).map((r) => (
              <tr key={r.part_no} className="border-b border-line/50 last:border-0">
                <Td className="font-mono text-flame">{r.part_no}</Td>
                <Td>{r.name}</Td>
                <Td className="text-right tabular-nums">{r.qty.toLocaleString('vi-VN')}</Td>
                <Td className="text-right tabular-nums text-danger">{formatVnd(r.value_vnd)}</Td>
                <Td className="text-txt-2 text-xs">{r.last_out ?? <span className="text-danger">Chưa từng xuất</span>}{r.days_idle != null && ` · ${r.days_idle}n`}</Td>
              </tr>
            ))}
          </tbody>
        </TableCard>
      </Card>
    </div>
  )
}
