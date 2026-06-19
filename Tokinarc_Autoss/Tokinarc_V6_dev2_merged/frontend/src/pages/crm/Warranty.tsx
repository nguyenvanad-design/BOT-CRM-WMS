/**
 * Tokinarc frontend — src/pages/crm/Warranty.tsx
 * Bảo hành: dựa trên serial súng hàn (WMS) có warranty_until. Tính trạng thái
 * còn hạn / sắp hết / hết hạn từ ngày bảo hành.
 */
import { useState } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { ShieldCheck } from 'lucide-react'
import { apiError } from '@/lib/api'
import { fetchPage, PAGE_SIZE } from '@/lib/list'
import { useDebounced } from '@/lib/useDebounced'
import { formatDate } from '@/lib/crm'
import { SERIAL_STATUS_LABEL, SERIAL_STATUS_TONE } from '@/lib/wms'
import type { SerialNumber } from '@/lib/types'
import type { TagTone } from '@/lib/crm'
import { PageHeader, SearchInput, Tag, TableCard, Th, Td, RowMsg, Pagination } from '@/components/ui'

function warrantyState(until: string | null): { label: string; tone: TagTone } {
  if (!until) return { label: 'Không có', tone: 'gray' }
  const d = new Date(until).getTime()
  const now = Date.now()
  if (d < now) return { label: 'Hết hạn', tone: 'danger' }
  if (d < now + 60 * 86400_000) return { label: 'Sắp hết', tone: 'warn' }
  return { label: 'Còn hạn', tone: 'ok' }
}

export function WarrantyPage() {
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const debounced = useDebounced(search, 350, () => setPage(1))

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ['warranty', debounced, page],
    queryFn: () => fetchPage<SerialNumber>('/wms/serials/', { search: debounced || undefined, page }),
    placeholderData: keepPreviousData,
  })
  const totalPages = data ? Math.max(1, Math.ceil(data.count / PAGE_SIZE)) : 1

  return (
    <div className="max-w-5xl">
      <PageHeader icon={<ShieldCheck size={20} className="text-flame" />} title="Bảo hành"
        subtitle={data ? `${data.count} serial` : undefined}
        actions={<SearchInput value={search} onChange={setSearch} placeholder="Tìm serial…" />} />

      <TableCard>
        <thead><tr className="border-b border-line">
          <Th>Serial</Th><Th>Model</Th><Th>Trạng thái máy</Th><Th>BH đến</Th><Th>Bảo hành</Th>
        </tr></thead>
        <tbody>
          {isLoading && <RowMsg colSpan={5}>Đang tải…</RowMsg>}
          {isError && <RowMsg colSpan={5} danger>Lỗi: {apiError(error)}</RowMsg>}
          {data?.results.length === 0 && <RowMsg colSpan={5}>Không có serial nào.</RowMsg>}
          {data?.results.map((s) => {
            const w = warrantyState(s.warranty_until)
            return (
              <tr key={s.id} className="border-b border-line/50 last:border-0 hover:bg-ink-3/40">
                <Td className="font-mono text-flame">{s.serial}</Td>
                <Td className="font-medium">{s.torch}</Td>
                <Td><Tag tone={SERIAL_STATUS_TONE[s.status]}>{SERIAL_STATUS_LABEL[s.status]}</Tag></Td>
                <Td className="text-txt-2">{formatDate(s.warranty_until)}</Td>
                <Td><Tag tone={w.tone}>{w.label}</Tag></Td>
              </tr>
            )
          })}
        </tbody>
      </TableCard>

      {data && data.count > PAGE_SIZE && (
        <Pagination page={page} totalPages={totalPages} fetching={isFetching}
          onPrev={() => setPage((p) => p - 1)} onNext={() => setPage((p) => p + 1)} />
      )}
    </div>
  )
}
