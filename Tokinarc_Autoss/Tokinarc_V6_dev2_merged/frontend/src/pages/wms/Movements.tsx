/**
 * Tokinarc frontend — src/pages/wms/Movements.tsx
 * Lịch sử biến động kho THẬT (GET /wms/stock-movements/). Lọc theo loại.
 */
import { useState } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { History } from 'lucide-react'
import { apiError } from '@/lib/api'
import { fetchPage, PAGE_SIZE } from '@/lib/list'
import { formatDate } from '@/lib/crm'
import { MOVE_REASON_LABEL, MOVE_REASON_TONE } from '@/lib/wms'
import type { StockMovement, MovementReason } from '@/lib/types'
import {
  PageHeader, Tag, TableCard, Th, Td, RowMsg, Pagination,
} from '@/components/ui'

const REASONS: (MovementReason | '')[] = ['', 'inbound', 'outbound', 'adjust', 'transfer', 'return']

export function MovementsPage() {
  const [reason, setReason] = useState<MovementReason | ''>('')
  const [page, setPage] = useState(1)

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ['wms-moves', reason, page],
    queryFn: () => fetchPage<StockMovement>('/wms/stock-movements/', {
      reason: reason || undefined, page,
    }),
    placeholderData: keepPreviousData,
  })

  const totalPages = data ? Math.max(1, Math.ceil(data.count / PAGE_SIZE)) : 1

  return (
    <div className="max-w-5xl">
      <PageHeader
        icon={<History size={20} className="text-flame" />}
        title="Lịch sử kho"
        subtitle={data ? `${data.count} biến động` : undefined}
        actions={
          <select value={reason} onChange={(e) => { setReason(e.target.value as MovementReason | ''); setPage(1) }}
            className="bg-ink-2 border border-line rounded-md px-2.5 py-2 text-sm focus:border-flame">
            {REASONS.map((r) => <option key={r} value={r}>{r ? MOVE_REASON_LABEL[r] : 'Tất cả loại'}</option>)}
          </select>
        }
      />

      <TableCard>
        <thead>
          <tr className="border-b border-line">
            <Th>Thời gian</Th><Th>Mặt hàng</Th><Th>Vị trí</Th>
            <Th className="text-right">Thay đổi</Th><Th>Loại</Th><Th>Tham chiếu</Th><Th>Người</Th>
          </tr>
        </thead>
        <tbody>
          {isLoading && <RowMsg colSpan={7}>Đang tải…</RowMsg>}
          {isError && <RowMsg colSpan={7} danger>Lỗi: {apiError(error)}</RowMsg>}
          {data?.results.length === 0 && <RowMsg colSpan={7}>Chưa có biến động.</RowMsg>}
          {data?.results.map((m) => (
            <tr key={m.id} className="border-b border-line/50 last:border-0 hover:bg-ink-3/40">
              <Td className="text-txt-2 whitespace-nowrap">{formatDate(m.ts)}</Td>
              <Td className="font-medium">{m.part || m.torch || '—'}</Td>
              <Td className="font-mono text-txt-2">{m.bin}</Td>
              <Td className={`text-right tabular-nums ${m.delta >= 0 ? 'text-ok' : 'text-danger'}`}>{m.delta > 0 ? `+${m.delta}` : m.delta}</Td>
              <Td><Tag tone={MOVE_REASON_TONE[m.reason]}>{MOVE_REASON_LABEL[m.reason]}</Tag></Td>
              <Td className="text-txt-2 font-mono text-[11px]">{m.ref_id || '—'}</Td>
              <Td className="text-txt-2">{m.by_username || '—'}</Td>
            </tr>
          ))}
        </tbody>
      </TableCard>

      {data && data.count > PAGE_SIZE && (
        <Pagination page={page} totalPages={totalPages} fetching={isFetching}
          onPrev={() => setPage((p) => p - 1)} onNext={() => setPage((p) => p + 1)} />
      )}
    </div>
  )
}
