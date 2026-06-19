/**
 * Tokinarc frontend — src/pages/wms/Serials.tsx
 * Serial súng hàn THẬT (GET /wms/serials/). Search theo serial + lọc trạng thái.
 */
import { useState } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { Barcode } from 'lucide-react'
import { apiError } from '@/lib/api'
import { fetchPage, PAGE_SIZE } from '@/lib/list'
import { useDebounced } from '@/lib/useDebounced'
import { formatDate } from '@/lib/crm'
import { SERIAL_STATUS_LABEL, SERIAL_STATUS_TONE } from '@/lib/wms'
import type { SerialNumber, SerialStatus } from '@/lib/types'
import {
  PageHeader, SearchInput, Tag, TableCard, Th, Td, RowMsg, Pagination,
} from '@/components/ui'

const STATUSES: (SerialStatus | '')[] = ['', 'in_stock', 'reserved', 'sold', 'shipped', 'returned', 'scrapped']

export function SerialsPage() {
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<SerialStatus | ''>('')
  const [page, setPage] = useState(1)
  const debounced = useDebounced(search, 350, () => setPage(1))

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ['wms-serials', debounced, status, page],
    queryFn: () => fetchPage<SerialNumber>('/wms/serials/', {
      search: debounced || undefined, status: status || undefined, page,
    }),
    placeholderData: keepPreviousData,
  })

  const totalPages = data ? Math.max(1, Math.ceil(data.count / PAGE_SIZE)) : 1

  return (
    <div className="max-w-5xl">
      <PageHeader
        icon={<Barcode size={20} className="text-flame" />}
        title="Serial"
        subtitle={data ? `${data.count} serial` : undefined}
        actions={
          <>
            <select value={status} onChange={(e) => { setStatus(e.target.value as SerialStatus | ''); setPage(1) }}
              className="bg-ink-2 border border-line rounded-md px-2.5 py-2 text-sm focus:border-flame">
              {STATUSES.map((s) => <option key={s} value={s}>{s ? SERIAL_STATUS_LABEL[s] : 'Tất cả trạng thái'}</option>)}
            </select>
            <SearchInput value={search} onChange={setSearch} placeholder="Tìm serial…" />
          </>
        }
      />

      <TableCard>
        <thead>
          <tr className="border-b border-line">
            <Th>Serial</Th><Th>Model</Th><Th>Vị trí</Th><Th>Trạng thái</Th><Th>Bảo hành đến</Th>
          </tr>
        </thead>
        <tbody>
          {isLoading && <RowMsg colSpan={5}>Đang tải…</RowMsg>}
          {isError && <RowMsg colSpan={5} danger>Lỗi: {apiError(error)}</RowMsg>}
          {data?.results.length === 0 && <RowMsg colSpan={5}>Không có serial nào.</RowMsg>}
          {data?.results.map((s) => (
            <tr key={s.id} className="border-b border-line/50 last:border-0 hover:bg-ink-3/40">
              <Td className="font-mono text-flame">{s.serial}</Td>
              <Td className="font-medium">{s.torch}</Td>
              <Td className="font-mono text-txt-2">{s.bin || '—'}</Td>
              <Td><Tag tone={SERIAL_STATUS_TONE[s.status]}>{SERIAL_STATUS_LABEL[s.status]}</Tag></Td>
              <Td className="text-txt-2">{formatDate(s.warranty_until)}</Td>
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
