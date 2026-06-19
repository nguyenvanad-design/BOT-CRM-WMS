/**
 * Tokinarc frontend — src/pages/crm/Visits.tsx
 * Danh sách báo cáo viếng thăm THẬT (GET /crm/visits/). Phân trang.
 */
import { useState } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { MapPin, CheckCircle2, Plus } from 'lucide-react'
import { apiError } from '@/lib/api'
import { fetchPage, PAGE_SIZE } from '@/lib/list'
import { formatDate } from '@/lib/crm'
import type { Visit } from '@/lib/types'
import { PageHeader, Button, TableCard, Th, Td, RowMsg, Pagination } from '@/components/ui'
import { VisitForm } from '@/pages/crm/forms/VisitForm'

export function VisitsPage() {
  const [page, setPage] = useState(1)
  const [formOpen, setFormOpen] = useState(false)

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ['visits', page],
    queryFn: () => fetchPage<Visit>('/crm/visits/', { page }),
    placeholderData: keepPreviousData,
  })

  const totalPages = data ? Math.max(1, Math.ceil(data.count / PAGE_SIZE)) : 1
  const hasGps = (v: Visit) => v.gps && Object.keys(v.gps).length > 0

  return (
    <div className="max-w-5xl">
      <PageHeader
        icon={<MapPin size={20} className="text-flame" />}
        title="Visit Report"
        subtitle={data ? `${data.count} lượt thăm` : undefined}
        actions={<Button onClick={() => setFormOpen(true)}><Plus size={14} /> Lên lịch visit</Button>}
      />

      <TableCard>
        <thead>
          <tr className="border-b border-line">
            <Th>Ngày</Th><Th>Khách hàng</Th><Th>Mục đích</Th>
            <Th>Hành động tiếp theo</Th><Th>Sale</Th><Th>GPS</Th>
          </tr>
        </thead>
        <tbody>
          {isLoading && <RowMsg colSpan={6}>Đang tải…</RowMsg>}
          {isError && <RowMsg colSpan={6} danger>Lỗi: {apiError(error)}</RowMsg>}
          {data?.results.length === 0 && <RowMsg colSpan={6}>Chưa có visit nào.</RowMsg>}
          {data?.results.map((v) => (
            <tr key={v.id} className="border-b border-line/50 last:border-0 hover:bg-ink-3/40">
              <Td className="text-txt-2 whitespace-nowrap">{formatDate(v.visit_date)}</Td>
              <Td className="font-medium">{v.customer_name}</Td>
              <Td>{v.purpose}</Td>
              <Td className="text-txt-2">{v.next_action || '—'}</Td>
              <Td className="text-txt-2">{v.owner_username}</Td>
              <Td>
                {hasGps(v)
                  ? <span className="inline-flex items-center gap-1 text-ok text-xs"><CheckCircle2 size={13} /> Check-in</span>
                  : <span className="text-txt-2 text-xs">—</span>}
              </Td>
            </tr>
          ))}
        </tbody>
      </TableCard>

      {data && data.count > PAGE_SIZE && (
        <Pagination
          page={page} totalPages={totalPages} fetching={isFetching}
          onPrev={() => setPage((p) => p - 1)} onNext={() => setPage((p) => p + 1)}
        />
      )}

      <VisitForm open={formOpen} onClose={() => setFormOpen(false)} />
    </div>
  )
}
